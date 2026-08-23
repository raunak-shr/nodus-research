"""The pipeline's second entry: a run over papers the reader supplied.

One branch, taken after the question is structured. Everything downstream is
the ordinary pipeline, which is the point — these tests are about the branch
being taken, the corpus being linked in the reader's own order, and the run
being recognisable as an upload run before any paper has arrived.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.events import _PHASE_BY_EVENT, hub
from app.models.paper import Paper
from app.services import pipeline, uploads
from app.services.errors import BadRequest


def _record(sink):
    """Capture what the hub was asked to publish, in order."""
    return lambda query_id, event, **payload: sink.append((event, payload))


def test_a_run_with_no_uploads_still_retrieves():
    assert pipeline.route_after_structure({"uploaded_paper_ids": []}) == "retrieve"
    assert pipeline.route_after_structure({}) == "retrieve"


def test_a_run_with_uploads_skips_retrieval_and_ranking():
    assert pipeline.route_after_structure({"uploaded_paper_ids": ["a", "b"]}) == "uploads"


def test_the_graph_compiles_with_both_entries():
    """A conditional edge naming a node that does not exist fails here, not on
    the first upload run in production."""
    assert pipeline.build_graph() is not None


def test_the_upload_event_has_a_phase():
    """An event the hub cannot place inherits whatever phase came before it,
    which on the first one of a run is `queued`."""
    assert _PHASE_BY_EVENT["papers_uploaded"] == "storing"


async def test_the_corpus_is_linked_in_the_order_the_reader_gave_it():
    """Rank is the reader's ordering and `ranking_score` is null.

    Nothing was scored — writing a score would claim a ranking that never
    happened, and the papers screen would sort by it.
    """
    query_id = uuid4()
    papers = [
        Paper(id=uuid4(), semantic_scholar_id=uploads.fingerprint(b"a"), title="First"),
        Paper(id=uuid4(), semantic_scholar_id=uploads.fingerprint(b"b"), title="Second"),
    ]
    written: list[dict] = []

    class _Db:
        async def execute(self, statement, *args, **kwargs):
            written.append(dict(statement.compile().params))
            return SimpleNamespace()

        async def get(self, *args, **kwargs):
            return SimpleNamespace(paper_count=0)

        async def commit(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    published: list[tuple[str, dict]] = []

    with (
        patch.object(pipeline, "AsyncSessionLocal", _Db),
        patch.object(pipeline, "_set_status", AsyncMock()),
        patch.object(uploads, "resolve_for_run", AsyncMock(return_value=papers)),
        patch.object(hub, "publish", _record(published)),
    ):
        result = await pipeline.store_uploads_node(
            {
                "query_id": str(query_id),
                "uploaded_paper_ids": [str(papers[0].id), str(papers[1].id)],
            }
        )

    assert result["paper_ids"] == [str(papers[0].id), str(papers[1].id)]
    assert [row["rank"] for row in written] == [1, 2]
    assert all(row["ranking_score"] is None for row in written)

    events = dict(published)
    # `papers_stored` as well as `papers_uploaded`: every client already reads
    # the first one, and an upload run must not need a new event to be visible.
    assert set(events) == {"papers_uploaded", "papers_stored"}
    assert events["papers_stored"]["count"] == 2


async def test_a_bad_corpus_fails_the_node_rather_than_running_on_nothing():
    query_id = uuid4()

    class _Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    with (
        patch.object(pipeline, "AsyncSessionLocal", _Db),
        patch.object(pipeline, "_set_status", AsyncMock()),
        patch.object(uploads, "resolve_for_run", AsyncMock(side_effect=BadRequest("too few"))),
    ):
        with pytest.raises(BadRequest):
            await pipeline.store_uploads_node(
                {"query_id": str(query_id), "uploaded_paper_ids": ["one"]}
            )


async def test_the_run_says_which_shape_it_is_before_any_paper_arrives():
    """The run screen has to drop the ranking step from the ladder immediately.

    A phase that stays pending for the whole run reads as a run that stalled,
    and the papers are minutes away.
    """
    published: list[tuple[str, dict]] = []
    invoked = AsyncMock()

    with (
        patch.object(hub, "publish", _record(published)),
        patch.object(pipeline, "get_graph", lambda: SimpleNamespace(ainvoke=invoked)),
    ):
        await pipeline.run_pipeline(uuid4(), "A question", uploaded_paper_ids=["a", "b"])

    event, payload = published[0]
    assert event == "pipeline_started"
    assert payload["source"] == "upload"
    assert payload["uploaded_papers"] == 2
    assert invoked.await_args.args[0]["uploaded_paper_ids"] == ["a", "b"]


async def test_an_ordinary_run_still_says_it_is_a_search():
    published: list[tuple[str, dict]] = []

    with (
        patch.object(hub, "publish", _record(published)),
        patch.object(pipeline, "get_graph", lambda: SimpleNamespace(ainvoke=AsyncMock())),
    ):
        await pipeline.run_pipeline(uuid4(), "A question")

    assert published[0][1]["source"] == "search"
