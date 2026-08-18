"""Progress hub backing the WebSocket stream."""

import asyncio
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.events import ProgressHub


def test_publish_records_history():
    hub = ProgressHub()
    query_id = uuid4()

    hub.publish(query_id, "status", status="retrieving")
    hub.publish(query_id, "papers_retrieved", count=20)

    events = hub.history(query_id)
    assert [e["event"] for e in events] == ["status", "papers_retrieved"]
    assert events[0]["status"] == "retrieving"
    assert events[1]["count"] == 20
    assert all(e["query_id"] == str(query_id) for e in events)
    assert all("timestamp" in e for e in events)


@pytest.mark.asyncio
async def test_subscriber_receives_published_events():
    hub = ProgressHub()
    query_id = uuid4()
    queue = hub.subscribe(query_id)

    hub.publish(query_id, "paper_processed", completed=1, total=5)
    event = await asyncio.wait_for(queue.get(), timeout=1)

    assert event["event"] == "paper_processed"
    assert event["completed"] == 1


@pytest.mark.asyncio
async def test_events_are_scoped_per_query():
    hub = ProgressHub()
    mine, theirs = uuid4(), uuid4()
    queue = hub.subscribe(mine)

    hub.publish(theirs, "status", status="failed")
    assert queue.empty()

    hub.publish(mine, "status", status="completed")
    assert (await asyncio.wait_for(queue.get(), timeout=1))["status"] == "completed"


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive():
    hub = ProgressHub()
    query_id = uuid4()
    first, second = hub.subscribe(query_id), hub.subscribe(query_id)

    hub.publish(query_id, "status", status="clustering")

    assert (await first.get())["status"] == "clustering"
    assert (await second.get())["status"] == "clustering"


def test_unsubscribe_stops_delivery():
    hub = ProgressHub()
    query_id = uuid4()
    queue = hub.subscribe(query_id)
    hub.unsubscribe(query_id, queue)

    hub.publish(query_id, "status", status="completed")
    assert queue.empty()


def test_history_replays_for_late_subscribers():
    """A client that connects mid-run still sees the whole run."""
    hub = ProgressHub()
    query_id = uuid4()
    hub.publish(query_id, "pipeline_started")
    hub.publish(query_id, "status", status="processing")

    hub.subscribe(query_id)
    assert len(hub.history(query_id)) == 2


def test_history_is_bounded():
    hub = ProgressHub()
    query_id = uuid4()
    published = settings.event_replay_max + 150
    for index in range(published):
        hub.publish(query_id, "tick", index=index)

    history = hub.history(query_id)
    assert len(history) == settings.event_replay_max
    assert history[-1]["index"] == published - 1


def test_slow_subscriber_does_not_block_publishing():
    hub = ProgressHub()
    query_id = uuid4()
    queue = hub.subscribe(query_id)

    for index in range(settings.event_queue_maxsize + 200):
        hub.publish(query_id, "tick", index=index)

    # Publishing never blocks: the queue fills and further events are dropped
    # for this subscriber, which the seq gap makes visible to the client.
    assert queue.full()
    assert len(hub.history(query_id)) == settings.event_replay_max


def test_clear_removes_history_and_subscribers():
    hub = ProgressHub()
    query_id = uuid4()
    hub.subscribe(query_id)
    hub.publish(query_id, "status", status="completed")

    hub.clear(query_id)
    assert hub.history(query_id) == []
