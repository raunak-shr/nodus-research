"""Run-slot lifetime: a slot must come back on every exit path.

A leaked slot is worse than a missing limit — the gate silently shrinks until
the app refuses all work — so success, failure, cancellation, shutdown and the
already-running short circuit each get their own test.

`run_pipeline_safe` is patched out throughout: these tests are about the slot,
not the pipeline.
"""

import asyncio

import pytest

from app.core.config import settings
from app.services import runner
from app.services.errors import TooManyRequests
from app.services.limits import run_gate


@pytest.fixture(autouse=True)
def _clean_runner():
    """The task registry and the gate are process-global."""
    runner._tasks.clear()
    run_gate.reset()
    yield
    runner._tasks.clear()
    run_gate.reset()


def _active() -> int:
    return run_gate.snapshot()["active"]


# ------------------------------------------------------- the admission block


async def test_admission_releases_when_no_run_is_launched():
    """A caller that validates, then bails, must not strand the slot."""
    async with runner.admission():
        assert _active() == 1
    assert _active() == 0


async def test_admission_releases_when_the_block_raises():
    with pytest.raises(RuntimeError):
        async with runner.admission():
            assert _active() == 1
            raise RuntimeError("row insert failed")
    assert _active() == 0


async def test_admission_holds_the_slot_for_an_inline_run_then_releases():
    """`wait=true` runs inside the block, so the slot spans the whole run."""
    started = asyncio.Event()

    async def fake_run(query_id, raw_query):
        started.set()
        assert _active() == 1

    async with runner.admission():
        await fake_run("q", "raw")
        assert started.is_set()
        assert _active() == 1

    assert _active() == 0


async def test_admission_refuses_past_the_configured_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_active_queries", 2)

    first = await runner.admission().__aenter__()
    second = await runner.admission().__aenter__()
    assert _active() == 2

    with pytest.raises(TooManyRequests) as refused:
        async with runner.admission():
            pass

    assert refused.value.detail["scope"] == "active_queries"
    assert _active() == 2

    first.release_if_unused()
    second.release_if_unused()
    assert _active() == 0


async def test_a_refused_admission_never_reaches_the_block(monkeypatch):
    """The gate must reject before a caller writes anything."""
    monkeypatch.setattr(settings, "max_active_queries", 1)
    reserved = await runner.admission().__aenter__()

    entered = False
    with pytest.raises(TooManyRequests):
        async with runner.admission():
            entered = True

    assert entered is False
    reserved.release_if_unused()


# --------------------------------------------------------- launched run slots


async def test_slot_is_released_when_a_launched_run_succeeds(monkeypatch):
    finished = asyncio.Event()

    async def fake_run(query_id, raw_query):
        assert _active() == 1
        finished.set()

    monkeypatch.setattr(runner, "run_pipeline_safe", fake_run)

    async with runner.admission() as reserved:
        task = reserved.launch("query-1", "raw")

    await task
    await finished.wait()
    # The done callback runs on the next loop pass.
    await asyncio.sleep(0)
    assert _active() == 0
    assert runner._tasks == {}


async def test_slot_is_released_when_a_launched_run_raises(monkeypatch):
    """`run_pipeline_safe` should swallow failures, but a slot must survive one
    that escapes anyway."""

    async def fake_run(query_id, raw_query):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(runner, "run_pipeline_safe", fake_run)

    async with runner.admission() as reserved:
        task = reserved.launch("query-1", "raw")

    with pytest.raises(RuntimeError):
        await task
    await asyncio.sleep(0)
    assert _active() == 0
    assert runner._tasks == {}


async def test_slot_is_released_when_a_launched_run_is_cancelled(monkeypatch):
    running = asyncio.Event()

    async def fake_run(query_id, raw_query):
        running.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(runner, "run_pipeline_safe", fake_run)

    async with runner.admission() as reserved:
        reserved.launch("query-1", "raw")

    await running.wait()
    assert _active() == 1

    assert runner.cancel("query-1") is True
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert _active() == 0
    assert runner._tasks == {}


async def test_shutdown_cancellation_releases_every_slot(monkeypatch):
    monkeypatch.setattr(settings, "max_active_queries", 3)

    async def fake_run(query_id, raw_query):
        await asyncio.sleep(3600)

    monkeypatch.setattr(runner, "run_pipeline_safe", fake_run)

    for index in range(3):
        async with runner.admission() as reserved:
            reserved.launch(f"query-{index}", "raw")

    await asyncio.sleep(0)
    assert _active() == 3

    await runner.cancel_all()
    await asyncio.sleep(0)
    assert _active() == 0


async def test_relaunching_a_running_query_hands_the_slot_back(monkeypatch):
    """A duplicate submission adds no load, so it must not hold capacity."""

    async def fake_run(query_id, raw_query):
        await asyncio.sleep(3600)

    monkeypatch.setattr(runner, "run_pipeline_safe", fake_run)

    async with runner.admission() as first:
        task = first.launch("query-1", "raw")
    assert _active() == 1

    async with runner.admission() as second:
        again = second.launch("query-1", "raw")

    assert again is task
    # Two slots were taken, one was returned by `launch`.
    assert _active() == 1

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)
    assert _active() == 0


async def test_daily_ceiling_blocks_submission(monkeypatch):
    monkeypatch.setattr(settings, "max_active_queries", 5)
    monkeypatch.setattr(settings, "max_daily_runs", 2)

    for _ in range(2):
        async with runner.admission():
            pass

    with pytest.raises(TooManyRequests) as refused:
        async with runner.admission():
            pass

    assert refused.value.detail["scope"] == "daily_runs"
    # Concurrency is free; it is the day's budget that ran out.
    assert _active() == 0
