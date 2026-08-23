"""`graph.get` — one run as a field of nodes, over the socket.

Hermetic: `app/services/graph.py` has its own tests for what the payload says.
What is checked here is that the action is reachable, that it is one request,
and that it inherits the query's ownership rule rather than having its own.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.v2 import actions as v2_actions
from app.main import app
from app.schemas.graph import GraphRead
from app.services import graph as graph_service
from tests.conftest import StubSession, owns_queries


def _ready(socket) -> dict:
    frame = socket.receive_json()
    assert frame["type"] == "ready"
    return frame


def test_the_graph_action_is_advertised():
    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        assert "graph.get" in _ready(socket)["actions"]


def test_the_graph_is_one_request_for_all_four_views():
    payload = GraphRead(
        query_id=uuid4(),
        question="Does aerobic exercise reduce depression severity?",
        status="completed",
        uploaded_corpus=False,
        papers=[],
        clusters=[],
        lineage=[],
        lineage_basis="chronological+stance",
        claims_unclustered=4,
    )

    with (
        TestClient(app) as client,
        owns_queries(),
        patch.object(graph_service, "build_graph", AsyncMock(return_value=payload)),
        patch.object(v2_actions, "AsyncSessionLocal", StubSession),
        client.websocket_connect("/api/v2/ws") as socket,
    ):
        _ready(socket)
        socket.send_json({"id": "g", "action": "graph.get", "params": {"query_id": str(uuid4())}})
        frame = socket.receive_json()

    assert frame["type"] == "result", frame
    assert frame["data"]["claims_unclustered"] == 4
    assert frame["data"]["lineage_basis"] == "chronological+stance"


def test_the_graph_of_someone_elses_run_is_not_found():
    """Ownership is checked on the query, so the graph inherits it — and the
    answer has to be `not_found`, because `forbidden` confirms the id exists."""
    from app.services import ownership
    from app.services.errors import NotFound

    with (
        TestClient(app) as client,
        patch.object(
            ownership, "require_query", AsyncMock(side_effect=NotFound("Query not found"))
        ),
        patch.object(v2_actions, "AsyncSessionLocal", StubSession),
        client.websocket_connect("/api/v2/ws") as socket,
    ):
        _ready(socket)
        socket.send_json({"id": "g", "action": "graph.get", "params": {"query_id": str(uuid4())}})
        frame = socket.receive_json()

    assert frame["error"]["code"] == "not_found"
