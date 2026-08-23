"""Registry of in-flight pipeline runs.

The pipeline is a detached asyncio task: a client's connection must never be
what keeps a run alive, and a run must never die because a socket dropped.
Keeping the tasks here (rather than inside a route module) gives every surface
the same three operations — launch, ask whether a query is running, cancel —
and keeps a strong reference so the task is not garbage-collected mid-run.

Admission lives here too, because a run slot and the task that consumes it have
exactly the same lifetime: `admission()` reserves one of the global slots before
a caller writes anything, and `launch()` hands it to the background task.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from app.services.limits import RunSlot, run_gate
from app.services.pipeline import run_pipeline_safe

logger = logging.getLogger(__name__)

_tasks: dict[UUID, asyncio.Task] = {}


def launch(
    query_id: UUID,
    raw_query: str,
    *,
    slot: RunSlot | None = None,
    uploaded_paper_ids: list[str] | None = None,
) -> asyncio.Task:
    """Start the pipeline for a query in the background, taking over `slot`.

    `uploaded_paper_ids` runs the question over the reader's own papers instead
    of retrieving any — the pipeline branches on it, nothing here does.

    Ownership of the slot moves here unconditionally: it is released from the
    task's done callback, which fires on success, on failure and on cancellation
    alike, so a crashed or cancelled run can never strand capacity.
    """
    existing = _tasks.get(query_id)
    if existing and not existing.done():
        # Already running, so this submission adds no load — hand the slot back
        # instead of holding it against a task that will not release it.
        if slot is not None:
            slot.release()
        return existing

    if slot is not None:
        # Named now rather than at acquisition: the slot is reserved before the
        # query row exists, and the phase lookup needs the id.
        slot.attach(query_id)

    task = asyncio.create_task(
        run_pipeline_safe(query_id, raw_query, uploaded_paper_ids=uploaded_paper_ids),
        name=f"pipeline:{query_id}",
    )
    _tasks[query_id] = task

    def _finished(_task: asyncio.Task, qid: UUID = query_id) -> None:
        _tasks.pop(qid, None)
        if slot is not None:
            slot.release()

    task.add_done_callback(_finished)
    return task


class Admission:
    """A reserved run slot, held from before the query row is written.

    Reserving first is what keeps a refusal clean: committing the row and then
    rejecting the submission strands a `pending` query that nothing will ever
    run. `launch()` transfers the slot to the background task — every other exit
    from the `admission()` block, including an inline run and any exception,
    releases it.
    """

    __slots__ = ("_slot", "_launched")

    def __init__(self, slot: RunSlot) -> None:
        self._slot = slot
        self._launched = False

    def launch(
        self,
        query_id: UUID,
        raw_query: str,
        *,
        uploaded_paper_ids: list[str] | None = None,
    ) -> asyncio.Task:
        self._launched = True
        return launch(query_id, raw_query, slot=self._slot, uploaded_paper_ids=uploaded_paper_ids)

    def release_if_unused(self) -> None:
        if not self._launched:
            self._slot.release()


@contextlib.asynccontextmanager
async def admission() -> AsyncIterator[Admission]:
    """Reserve one of the global run slots, or raise `TooManyRequests`.

    An inline (`wait=true`) run holds the slot for as long as the block is open,
    which is the whole pipeline — so inline and background runs are counted the
    same way.
    """
    reserved = Admission(run_gate.acquire())
    try:
        yield reserved
    finally:
        reserved.release_if_unused()


def is_running(query_id: UUID) -> bool:
    task = _tasks.get(query_id)
    return bool(task and not task.done())


def running_ids() -> list[UUID]:
    return [qid for qid, task in _tasks.items() if not task.done()]


def cancel(query_id: UUID) -> bool:
    """Request cancellation. Returns False when nothing was running.

    The pipeline records the terminal status itself when the CancelledError
    propagates, so callers do not have to.
    """
    task = _tasks.get(query_id)
    if not task or task.done():
        return False
    task.cancel()
    logger.info("Cancellation requested for query %s", query_id)
    return True


async def cancel_all() -> None:
    """Cancel every in-flight pipeline — used on application shutdown."""
    tasks = [task for task in _tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
