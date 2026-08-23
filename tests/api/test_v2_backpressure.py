"""What a connection says when it has no room for another request.

The ceiling itself is not the interesting part — it is fixed and small on
purpose, so that one slow call (a PDF render, an inline run) cannot stall the
event stream. What matters is that being turned away for it is *distinguishable*
from being turned away on the merits, because a client can act on one and not
the other.

This was a `bad_request` for one revision, and the upload queue rendered it as
a rejected file: fourteen papers dropped at once, six of them reported as
refused with a reason that said nothing about the paper.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.api.v2.session import _INFLIGHT_RETRY_AFTER, _MAX_INFLIGHT_REQUESTS, Connection


class _Socket:
    """A websocket that only records what was sent to it."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.client = SimpleNamespace(host="198.51.100.7")
        self.headers: dict[str, str] = {}

    async def send_text(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


async def _saturated() -> tuple[Connection, _Socket]:
    """A connection already holding its maximum number of in-flight requests."""
    socket = _Socket()
    connection = Connection(socket)

    async def never() -> None:
        await asyncio.sleep(3600)

    for _ in range(_MAX_INFLIGHT_REQUESTS):
        connection._requests.add(asyncio.create_task(never()))
    return connection, socket


async def _drain(connection: Connection) -> None:
    for task in list(connection._requests):
        task.cancel()
    await asyncio.gather(*connection._requests, return_exceptions=True)


async def test_a_request_refused_for_room_is_retryable_not_a_bad_request():
    """`too_many_requests` plus a `retry_after`, because it is backpressure.

    As a `bad_request` it was indistinguishable from a refusal the caller had
    earned, which left no way to tell "send this again in a moment" from "this
    will never work".
    """
    connection, socket = await _saturated()
    try:
        await connection.handle_text(json.dumps({"id": "9", "action": "meta.health"}))
    finally:
        await _drain(connection)

    frame = socket.sent[-1]
    assert frame["type"] == "error"
    assert frame["error"]["code"] == "too_many_requests"
    assert frame["id"] == "9"
    assert frame["action"] == "meta.health"
    # The wait, and the ceiling that caused it, both named — a client that
    # backs off needs the first and a person reading a log wants the second.
    assert float(frame["error"]["detail"]["retry_after"]) == pytest.approx(
        _INFLIGHT_RETRY_AFTER, abs=0.1
    )
    assert int(frame["error"]["detail"]["limit"]) == _MAX_INFLIGHT_REQUESTS


async def test_the_wait_is_short_because_nothing_is_being_rationed():
    """The ceiling counts replies being composed, not a budget being spent.

    Whatever is in flight is milliseconds from finishing unless it is a render,
    so a long backoff would be the client punishing itself.
    """
    assert 0 < _INFLIGHT_RETRY_AFTER <= 2


async def test_room_below_the_ceiling_is_not_refused():
    """The guard must not fire early — one under the limit still goes through."""
    socket = _Socket()
    connection = Connection(socket)

    async def never() -> None:
        await asyncio.sleep(3600)

    for _ in range(_MAX_INFLIGHT_REQUESTS - 1):
        connection._requests.add(asyncio.create_task(never()))

    try:
        await connection.handle_text(json.dumps({"id": "8", "action": "meta.health"}))
        # Let the dispatched action run to completion.
        await asyncio.sleep(0.05)
    finally:
        await _drain(connection)

    assert [frame for frame in socket.sent if frame.get("type") == "result"], socket.sent
    assert not [frame for frame in socket.sent if frame.get("type") == "error"]
