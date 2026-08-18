"""v1's progress socket still works after the v2 hub changes.

v1 forwards hub messages verbatim, so the added `seq`/`phase` fields ride along
without breaking existing clients, and the stream still closes on a terminal
status (v2 keeps the socket open instead).
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.events import hub
from app.main import app


def test_v1_stream_replays_history_and_closes_on_terminal_status():
    query_id = uuid4()
    hub.publish(query_id, "pipeline_started", raw_query="hallucinations in LLMs")
    hub.publish(query_id, "papers_retrieved", count=20)

    try:
        with (
            TestClient(app) as client,
            client.websocket_connect(f"/api/v1/queries/{query_id}/stream") as socket,
        ):
            first = socket.receive_json()
            second = socket.receive_json()
            assert [first["event"], second["event"]] == ["pipeline_started", "papers_retrieved"]
            # New fields are additive — old clients ignore them.
            assert first["seq"] == 1 and first["phase"] == "queued"

            hub.publish(query_id, "status", status="completed")
            assert socket.receive_json()["status"] == "completed"
    finally:
        hub.clear(query_id)
