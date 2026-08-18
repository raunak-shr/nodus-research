"""Registry of in-flight pipeline runs.

The pipeline is a detached asyncio task: a client's connection must never be
what keeps a run alive, and a run must never die because a socket dropped.
Keeping the tasks here (rather than inside a route module) gives every surface
the same three operations — launch, ask whether a query is running, cancel —
and keeps a strong reference so the task is not garbage-collected mid-run.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.services.pipeline import run_pipeline_safe

logger = logging.getLogger(__name__)

_tasks: dict[UUID, asyncio.Task] = {}


def launch(query_id: UUID, raw_query: str) -> asyncio.Task:
    """Start the pipeline for a query in the background."""
    existing = _tasks.get(query_id)
    if existing and not existing.done():
        return existing

    task = asyncio.create_task(run_pipeline_safe(query_id, raw_query), name=f"pipeline:{query_id}")
    _tasks[query_id] = task
    task.add_done_callback(lambda t, qid=query_id: _tasks.pop(qid, None))
    return task


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
