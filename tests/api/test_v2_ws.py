"""The v2 socket: handshake, dispatch, error frames and subscription replay.

Hermetic — only actions that touch neither the database nor an LLM are exercised
here (`meta.*`, subscription management). The data-path actions are thin wrappers
over services covered by their own tests and by scripts/run_query.py end to end.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.core.events import hub
from app.main import app
from app.schemas.stream import PROTOCOL_VERSION


def _ready(socket) -> dict:
    frame = socket.receive_json()
    assert frame["type"] == "ready"
    return frame


def test_ready_frame_advertises_the_protocol():
    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        frame = _ready(socket)

        assert frame["protocol"] == PROTOCOL_VERSION
        assert frame["heartbeat_seconds"] == settings.ws_heartbeat_seconds
        assert "queries.create" in frame["actions"]
        assert "report.pdf" in frame["actions"]


def test_describe_returns_a_schema_for_every_action():
    """The socket has no OpenAPI document, so this is the frontend's contract."""
    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        ready = _ready(socket)
        socket.send_json({"id": "1", "action": "meta.describe"})
        frame = socket.receive_json()

        assert frame == {
            "type": "result",
            "id": "1",
            "action": "meta.describe",
            "data": frame["data"],
        }
        described = {item["name"] for item in frame["data"]["actions"]}
        assert described == set(ready["actions"])
        assert all(item["params"]["type"] == "object" for item in frame["data"]["actions"])
        assert "clustering" in frame["data"]["phases"]


def test_health_and_config_are_available_over_the_socket():
    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        _ready(socket)

        socket.send_json({"id": "h", "action": "meta.health"})
        assert socket.receive_json()["data"]["status"] == "ok"

        socket.send_json({"id": "c", "action": "meta.config"})
        config = socket.receive_json()["data"]
        assert config["embedding_dim"] == 768
        assert "pdf_enabled" in config
        # Secrets must never cross the wire.
        assert not any("secret" in key for key in config)


def test_unknown_action_returns_an_error_frame_with_the_request_id():
    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        _ready(socket)
        socket.send_json({"id": "42", "action": "queries.explode"})
        frame = socket.receive_json()

        assert frame["type"] == "error"
        assert frame["id"] == "42"
        assert frame["error"]["code"] == "bad_request"
        assert "queries.explode" in frame["error"]["message"]


def test_invalid_params_are_rejected_before_the_handler_runs():
    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        _ready(socket)
        socket.send_json({"id": "7", "action": "queries.get", "params": {"query_id": "nope"}})
        frame = socket.receive_json()

        assert frame["type"] == "error"
        assert frame["error"]["code"] == "bad_request"
        assert frame["error"]["message"] == "Invalid params"


def test_malformed_frame_does_not_close_the_socket():
    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        _ready(socket)
        socket.send_text("not json at all")
        assert socket.receive_json()["error"]["code"] == "bad_request"

        # Still usable afterwards.
        socket.send_json({"id": "after", "action": "meta.health"})
        assert socket.receive_json()["id"] == "after"


def test_subscribe_replays_buffered_events_then_streams_live_ones():
    query_id = uuid4()
    hub.publish(query_id, "pipeline_started", raw_query="hallucinations in LLMs")
    hub.publish(query_id, "papers_retrieved", count=20)

    try:
        with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
            _ready(socket)
            socket.send_json(
                {"id": "s", "action": "queries.subscribe", "params": {"query_id": str(query_id)}}
            )

            replayed = [socket.receive_json(), socket.receive_json()]
            assert [frame["event"] for frame in replayed] == [
                "pipeline_started",
                "papers_retrieved",
            ]
            assert all(frame["type"] == "event" for frame in replayed)
            assert all(frame["topic"] == f"query:{query_id}" for frame in replayed)

            result = socket.receive_json()
            assert result["action"] == "queries.subscribe"
            assert result["data"] == {
                "subscribed": True,
                "query_id": str(query_id),
                "replayed": 2,
                "since": 0,
                "last_seq": 2,
                "phase": "retrieving",
                "buffered": 2,
                "oldest_seq": 1,
            }

            # A live event reaches the same socket without another request.
            hub.publish(query_id, "clustering_complete", clusters=23)
            live = socket.receive_json()
            assert (live["event"], live["clusters"], live["seq"]) == ("clustering_complete", 23, 3)
    finally:
        hub.clear(query_id)


def test_subscribe_since_skips_events_the_client_already_has():
    query_id = uuid4()
    for index in range(4):
        hub.publish(query_id, "tick", index=index)

    try:
        with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
            _ready(socket)
            socket.send_json(
                {
                    "id": "s",
                    "action": "queries.subscribe",
                    "params": {"query_id": str(query_id), "since": 3},
                }
            )
            assert socket.receive_json()["seq"] == 4
            assert socket.receive_json()["data"]["replayed"] == 1
    finally:
        hub.clear(query_id)


def test_preattached_socket_subscribes_on_connect():
    query_id = uuid4()
    hub.publish(query_id, "report_ready", sections=23)

    try:
        with (
            TestClient(app) as client,
            client.websocket_connect(f"/api/v2/ws/{query_id}") as socket,
        ):
            event = socket.receive_json()
            assert event["type"] == "event"
            assert event["event"] == "report_ready"

            ready = _ready(socket)
            assert ready["resumed_subscriptions"] == [str(query_id)]
    finally:
        hub.clear(query_id)


def test_unsubscribe_stops_delivery():
    query_id = uuid4()
    try:
        with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
            _ready(socket)
            socket.send_json(
                {"id": "1", "action": "queries.subscribe", "params": {"query_id": str(query_id)}}
            )
            assert socket.receive_json()["data"]["subscribed"] is True

            socket.send_json(
                {"id": "2", "action": "queries.unsubscribe", "params": {"query_id": str(query_id)}}
            )
            assert socket.receive_json()["data"] == {
                "subscribed": False,
                "was_subscribed": True,
                "query_id": str(query_id),
            }

            hub.publish(query_id, "clustering_complete", clusters=1)
            socket.send_json({"id": "3", "action": "meta.health"})
            # The next frame is the reply, not the event we just published.
            assert socket.receive_json()["id"] == "3"
    finally:
        hub.clear(query_id)


def test_socket_requires_the_api_key_when_one_is_configured():
    with patch.object(settings, "api_key", "secret-key"), TestClient(app) as client:
        # The handshake is refused with a policy close code, before accept().
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect("/api/v2/ws"):
                pass
        assert rejected.value.code == 4401

        with client.websocket_connect("/api/v2/ws?api_key=secret-key") as socket:
            assert _ready(socket)["protocol"] == PROTOCOL_VERSION

        with client.websocket_connect("/api/v2/ws", headers={"X-API-Key": "secret-key"}) as socket:
            assert _ready(socket)["protocol"] == PROTOCOL_VERSION
