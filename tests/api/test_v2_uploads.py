"""`papers.upload`, and a run started over what it accepted.

Hermetic: `app/services/uploads.py` has its own tests, so what is checked here
is the socket contract — the params a client must send, the errors it gets back,
and the fact that an upload run reaches the pipeline carrying its corpus.
"""

import base64
import io
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.v2 import actions as v2_actions
from app.core.config import settings
from app.main import app
from app.services import runner, uploads
from app.services.errors import BadRequest
from tests.conftest import StubSession, owns_queries


def _ready(socket) -> dict:
    frame = socket.receive_json()
    assert frame["type"] == "ready"
    return frame


def _pdf(pages: int = 2) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# -- papers.upload ----------------------------------------------------------


def test_upload_is_advertised_and_described():
    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        ready = _ready(socket)
        assert "papers.upload" in ready["actions"]

        socket.send_json({"id": "1", "action": "meta.describe"})
        described = {item["name"]: item for item in socket.receive_json()["data"]["actions"]}
        assert set(described["papers.upload"]["params"]["properties"]) == {
            "filename",
            "content_base64",
        }


def test_the_upload_ceilings_are_published_so_a_client_need_not_guess_them():
    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        _ready(socket)
        socket.send_json({"id": "c", "action": "meta.config"})
        config = socket.receive_json()["data"]

        assert config["upload_max_papers"] == settings.upload_max_papers
        assert config["upload_max_pages"] == settings.upload_max_pages
        assert config["max_pages_read"] == settings.pdf_max_pages
        assert config["upload_max_bytes"] == settings.upload_max_bytes


def test_a_body_that_is_not_base64_is_a_bad_request_not_a_dead_socket():
    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        _ready(socket)
        socket.send_json(
            {
                "id": "u",
                "action": "papers.upload",
                "params": {"filename": "a.pdf", "content_base64": "not base64!!!"},
            }
        )
        frame = socket.receive_json()

        assert frame["type"] == "error"
        assert frame["error"]["code"] == "bad_request"
        # The socket is still usable afterwards.
        socket.send_json({"id": "h", "action": "meta.health"})
        assert socket.receive_json()["data"]["status"] == "ok"


def test_an_accepted_file_comes_back_as_a_paper_id_to_run_with():
    accepted = uploads.UploadedPaper(
        paper_id=str(uuid4()),
        fingerprint="upload:abc",
        filename="blumenthal_2007.pdf",
        title="Exercise and Pharmacotherapy",
        authors=["J Blumenthal"],
        year=2007,
        pages=8,
        pages_read=8,
        characters=24_000,
        reused=False,
    )

    with (
        TestClient(app) as client,
        patch.object(v2_actions.uploads, "accept_upload", AsyncMock(return_value=accepted)),
        client.websocket_connect("/api/v2/ws") as socket,
    ):
        _ready(socket)
        socket.send_json(
            {
                "id": "u",
                "action": "papers.upload",
                "params": {
                    "filename": "blumenthal_2007.pdf",
                    "content_base64": base64.b64encode(_pdf()).decode(),
                },
            }
        )
        data = socket.receive_json()["data"]

    assert data["paper_id"] == accepted.paper_id
    assert data["pages"] == 8
    assert data["reused"] is False


def test_a_refused_file_says_why():
    """The reader is standing in front of the drop zone; "rejected" alone is
    what makes them try the same file again."""
    refusal = BadRequest(
        "310 pages — this is longer than a paper (the limit is 80).",
        filename="a-whole-book.pdf",
        pages=310,
    )

    with (
        TestClient(app) as client,
        patch.object(v2_actions.uploads, "accept_upload", AsyncMock(side_effect=refusal)),
        client.websocket_connect("/api/v2/ws") as socket,
    ):
        _ready(socket)
        socket.send_json(
            {
                "id": "u",
                "action": "papers.upload",
                "params": {
                    "filename": "a-whole-book.pdf",
                    "content_base64": base64.b64encode(_pdf()).decode(),
                },
            }
        )
        frame = socket.receive_json()

    assert frame["error"]["code"] == "bad_request"
    assert "longer than a paper" in frame["error"]["message"]
    # Every detail value crosses the wire as a string — see app/api/v2/session.py.
    assert frame["error"]["detail"]["pages"] == "310"


# -- queries.create over an uploaded corpus ---------------------------------


def test_an_upload_run_carries_its_corpus_into_the_pipeline():
    launched: dict = {}

    def _launch(query_id, raw_query, *, slot=None, uploaded_paper_ids=None):
        launched["ids"] = uploaded_paper_ids
        launched["query"] = raw_query
        if slot is not None:
            slot.release()
        return AsyncMock()

    ids = [str(uuid4()), str(uuid4())]

    with (
        TestClient(app) as client,
        owns_queries(),
        patch.object(v2_actions.uploads, "resolve_for_run", AsyncMock(return_value=[])),
        patch.object(runner, "launch", _launch),
        patch.object(v2_actions, "AsyncSessionLocal", StubSession),
        client.websocket_connect("/api/v2/ws") as socket,
    ):
        _ready(socket)
        socket.send_json(
            {
                "id": "q",
                "action": "queries.create",
                "params": {
                    "query": "Does aerobic exercise reduce depression severity?",
                    "paper_ids": ids,
                    "subscribe": False,
                },
            }
        )
        frame = socket.receive_json()

    assert frame["type"] == "result", frame
    assert frame["data"]["uploaded_corpus"] is True
    assert launched["ids"] == ids


def test_a_corpus_that_is_refused_never_reserves_a_run_slot():
    """Reserved first, written second — so a refusal here must come before the
    slot is taken, or a bad corpus costs the deployment a pipeline slot."""
    with (
        TestClient(app) as client,
        patch.object(
            v2_actions.uploads,
            "resolve_for_run",
            AsyncMock(side_effect=BadRequest("A run over uploaded papers needs at least 2")),
        ),
        patch.object(runner, "launch", AsyncMock()) as launched,
        client.websocket_connect("/api/v2/ws") as socket,
    ):
        _ready(socket)
        socket.send_json(
            {
                "id": "q",
                "action": "queries.create",
                "params": {"query": "A question", "paper_ids": [str(uuid4())], "subscribe": False},
            }
        )
        frame = socket.receive_json()

    assert frame["error"]["code"] == "bad_request"
    launched.assert_not_called()
