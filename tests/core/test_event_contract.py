"""The v2 stream contract: seq, phase, progress and gap-recovery replay.

A frontend drives its stepper off `phase` and detects dropped events with
`seq`, so these are the fields worth pinning down.
"""

from uuid import uuid4

from app.core.events import PHASE_ORDER, ProgressHub


def test_every_event_carries_seq_and_phase():
    hub = ProgressHub()
    query_id = uuid4()

    first = hub.publish(query_id, "pipeline_started", raw_query="x")
    second = hub.publish(query_id, "papers_retrieved", count=20)

    assert (first["seq"], second["seq"]) == (1, 2)
    assert first["phase"] == "queued"
    assert second["phase"] == "retrieving"
    assert all(event["phase"] in PHASE_ORDER for event in (first, second))


def test_seq_is_per_query():
    hub = ProgressHub()
    one, two = uuid4(), uuid4()

    assert hub.publish(one, "pipeline_started")["seq"] == 1
    assert hub.publish(two, "pipeline_started")["seq"] == 1
    assert hub.publish(one, "papers_retrieved", count=1)["seq"] == 2


def test_status_events_map_to_phases():
    hub = ProgressHub()
    query_id = uuid4()

    assert hub.publish(query_id, "status", status="retrieving")["phase"] == "retrieving"
    assert hub.publish(query_id, "status", status="completed")["phase"] == "completed"
    assert hub.publish(query_id, "status", status="failed")["phase"] == "failed"


def test_report_skipped_belongs_to_synthesis():
    """A run that writes no report still ends inside the synthesizing phase."""
    hub = ProgressHub()
    query_id = uuid4()

    event = hub.publish(query_id, "report_skipped", reason="No clusters were formed.")
    assert event["phase"] == "synthesizing"
    assert event["reason"] == "No clusters were formed."


def test_unknown_events_inherit_the_current_phase():
    """An event the table does not know must not reset the UI to 'queued'."""
    hub = ProgressHub()
    query_id = uuid4()

    hub.publish(query_id, "status", status="clustering")
    assert hub.publish(query_id, "something_new")["phase"] == "clustering"


def test_explicit_phase_wins():
    hub = ProgressHub()
    query_id = uuid4()

    event = hub.publish(query_id, "synthesis_started", phase="synthesizing")
    assert event["phase"] == "synthesizing"


def test_progress_is_clamped_and_omitted_when_absent():
    hub = ProgressHub()
    query_id = uuid4()

    assert "progress" not in hub.publish(query_id, "papers_retrieved", count=3)
    assert hub.publish(query_id, "paper_processed", progress=0.5)["progress"] == 0.5
    assert hub.publish(query_id, "paper_processed", progress=1.9)["progress"] == 1.0
    assert hub.publish(query_id, "paper_processed", progress=-2)["progress"] == 0.0


def test_history_since_returns_only_the_gap():
    hub = ProgressHub()
    query_id = uuid4()
    for index in range(5):
        hub.publish(query_id, "tick", index=index)

    missed = hub.history(query_id, since=3)
    assert [event["seq"] for event in missed] == [4, 5]


def test_snapshot_reports_where_the_run_is():
    hub = ProgressHub()
    query_id = uuid4()
    hub.publish(query_id, "status", status="processing")
    hub.publish(query_id, "paper_processed", completed=1, total=2)

    snapshot = hub.snapshot(query_id)
    assert snapshot["last_seq"] == 2
    assert snapshot["phase"] == "processing"
    assert snapshot["oldest_seq"] == 1


def test_callback_for_binds_one_query():
    """Services take a callback so they never import the hub."""
    hub = ProgressHub()
    query_id = uuid4()
    emit = hub.callback_for(query_id)

    emit("cluster_analyzed", theme="t", completed=1, total=3, progress=1 / 3)

    event = hub.history(query_id)[-1]
    assert event["event"] == "cluster_analyzed"
    assert event["phase"] == "clustering"
    assert event["progress"] == 0.3333
    assert event["query_id"] == str(query_id)


def test_clear_resets_the_sequence():
    hub = ProgressHub()
    query_id = uuid4()
    hub.publish(query_id, "tick")
    hub.clear(query_id)

    assert hub.snapshot(query_id) == {
        "last_seq": 0,
        "phase": None,
        "buffered": 0,
        "oldest_seq": 0,
    }
