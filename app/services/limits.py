"""In-process admission control: a global run gate and per-caller rate limits.

Deliberately not distributed. The progress hub is already in-process (see
`app/core/events.py`), so the API runs with a single worker — which makes a dict
and an integer counter a complete implementation here rather than a placeholder
for Redis. Nothing in this module awaits, so the event loop cannot interleave a
check with its own increment and no lock is needed.

Two different questions get two different answers:

* `RunGate` — *how much* expensive work may exist at once, and how much may be
  started per day. One pipeline run is tens of LLM calls and holds database
  sessions for minutes, so this bounds both the bill and the connection pool.
* `RateLimiter` — *how fast* one caller may ask for expensive work, keyed by
  client address, so a script in a loop is throttled without affecting anyone
  else.

Both refuse immediately rather than queueing. A caller told to come back can
retry cheaply; a caller parked in a queue holds a connection open and learns
nothing. Limits are read from `settings` on every call, so tests (and a running
process being reconfigured) see changes without rebuilding the limiter.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.events import hub
from app.services.errors import TooManyRequests

# A pipeline run takes minutes, so there is no useful precision to offer a
# caller that arrives while the gate is full — just a sane "not immediately".
_CONCURRENCY_RETRY_AFTER = 30.0

# Ceiling on any advertised Retry-After. A limit configured down to zero would
# otherwise produce an infinite wait, which is not a useful thing to send.
_MAX_RETRY_AFTER = 3600.0


# --------------------------------------------------------------- rate limiting


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass(frozen=True)
class Budget:
    """What one caller has left in a bucket, without spending any of it.

    `remaining` is floored: nine tenths of a token buys nothing, so reporting it
    as 1 would promise a request that is about to be refused.
    """

    name: str
    enabled: bool
    remaining: int
    capacity: int
    #: Seconds to regain one token, or None when limiting is off or the bucket is
    #: closed. This is the sustained rate, which `capacity` (a burst) is not.
    refill_seconds: float | None


class RateLimiter:
    """Token bucket per key.

    `capacity` is the burst one caller may spend at once; tokens refill at
    `rate_per_second`. A caller staying under the sustained rate never notices
    the limiter at all. A rate of zero closes the bucket entirely — use
    `enabled` to turn limiting off, not a zero rate.

    Limits are supplied as callables because the module-level instances are
    built at import time while the values they read live in `settings`.
    """

    def __init__(
        self,
        name: str,
        *,
        rate_per_second: Callable[[], float],
        capacity: Callable[[], int],
        enabled: Callable[[], bool] = lambda: True,
        max_keys: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self._rate_per_second = rate_per_second
        self._capacity = capacity
        self._enabled = enabled
        self._max_keys = max_keys
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def allow(self, key: str) -> float | None:
        """Spend one token. Returns None when allowed, else seconds to wait."""
        if not self._enabled():
            return None

        capacity = float(max(1, self._capacity()))
        rate = max(0.0, self._rate_per_second())
        now = self._clock()

        bucket = self._buckets.get(key)
        if bucket is None:
            # Prune before inserting, so the dict cannot grow past the cap.
            self._prune(now)
            bucket = _Bucket(tokens=capacity, updated=now)
            self._buckets[key] = bucket
        else:
            elapsed = max(0.0, now - bucket.updated)
            bucket.tokens = min(capacity, bucket.tokens + elapsed * rate)
            bucket.updated = now

        if bucket.tokens < 1.0:
            if rate <= 0:
                return _MAX_RETRY_AFTER
            return min(_MAX_RETRY_AFTER, (1.0 - bucket.tokens) / rate)

        bucket.tokens -= 1.0
        return None

    def check(self, key: str) -> None:
        """`allow`, but raising the transport-neutral error on refusal."""
        retry_after = self.allow(key)
        if retry_after is None:
            return
        raise TooManyRequests(
            "Rate limit exceeded — slow down and retry",
            retry_after=retry_after,
            scope=self.name,
        )

    def peek(self, key: str) -> Budget:
        """What `key` has left right now, spending nothing.

        Non-mutating and non-inserting on purpose: answering a question about a
        caller must not create a bucket for them, or polling this would fill the
        dict with keys that never spent a token — the same unbounded growth
        `_prune` exists to prevent.
        """
        capacity = max(1, self._capacity())
        rate = max(0.0, self._rate_per_second())

        if not self._enabled():
            return Budget(
                name=self.name,
                enabled=False,
                remaining=capacity,
                capacity=capacity,
                refill_seconds=None,
            )

        bucket = self._buckets.get(key)
        if bucket is None:
            tokens = float(capacity)
        else:
            elapsed = max(0.0, self._clock() - bucket.updated)
            tokens = min(float(capacity), bucket.tokens + elapsed * rate)

        return Budget(
            name=self.name,
            enabled=True,
            remaining=int(tokens),
            capacity=capacity,
            refill_seconds=(1.0 / rate) if rate > 0 else None,
        )

    def _prune(self, now: float) -> None:
        """Drop idle buckets.

        Without this, a caller rotating addresses grows the dict forever, which
        turns the rate limiter itself into a memory exhaustion vector.
        """
        if len(self._buckets) < self._max_keys:
            return

        rate = max(0.0, self._rate_per_second())
        capacity = float(max(1, self._capacity()))
        # Once a bucket has refilled to capacity it carries no state worth
        # keeping: recreating it yields exactly the same thing.
        full_after = (capacity / rate) if rate > 0 else float("inf")
        for key in [k for k, b in self._buckets.items() if now - b.updated >= full_after]:
            del self._buckets[key]

        if len(self._buckets) >= self._max_keys:
            # Every bucket is still live. Evict the least recently seen quarter
            # rather than refusing to track anything new.
            oldest = sorted(self._buckets.items(), key=lambda item: item[1].updated)
            for key, _ in oldest[: max(1, len(self._buckets) // 4)]:
                del self._buckets[key]

    def reset(self) -> None:
        self._buckets.clear()

    def tracked_keys(self) -> int:
        return len(self._buckets)


# -------------------------------------------------------------- the run gate


class RunSlot:
    """A held pipeline slot.

    Releasing twice is a no-op so ownership can move from the request that
    reserved the slot to the background task that consumes it, without either
    side having to know whether the other already let go.

    The slot also carries when the run began and, once `attach` is called, which
    query it is running — the two facts needed to describe a busy queue to
    somebody who has just been refused.
    """

    __slots__ = ("_gate", "_released", "started_at", "query_id")

    def __init__(self, gate: RunGate, *, started_at: float) -> None:
        self._gate = gate
        self._released = False
        self.started_at = started_at
        self.query_id: UUID | None = None

    @property
    def released(self) -> bool:
        return self._released

    def attach(self, query_id: UUID) -> None:
        """Name the run holding this slot, so its phase can be looked up.

        A slot is reserved before the query row exists, so this cannot happen at
        acquisition. An unattached slot is still reported — an inline admin run
        occupies capacity whether or not anything named it.
        """
        self.query_id = query_id

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._gate.release_one(self)


class RunGate:
    """Non-blocking global cap on concurrent pipeline runs, plus a daily ceiling.

    A counter rather than an `asyncio.Semaphore` because the requirement is to
    refuse immediately and never queue: `Semaphore.acquire()` waits, and testing
    `locked()` before awaiting it reintroduces the very race the semaphore was
    supposed to remove. Since `acquire` never awaits, its check and increment
    are atomic with respect to the event loop.

    The daily counter is charged on admission, not on completion — otherwise a
    run that fails fast would be free and abuse would cost nothing.
    """

    def __init__(
        self,
        *,
        limit: Callable[[], int],
        daily_limit: Callable[[], int],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._daily_limit = daily_limit
        self._now = now
        self._monotonic = monotonic
        # The live slots *are* the count. Keeping a separate integer alongside
        # them would let the number reported drift from the runs actually held.
        # Ordered by acquisition, so the oldest run is always first.
        self._live: list[RunSlot] = []
        self._day: date | None = None
        self._runs_today = 0

    @property
    def _active(self) -> int:
        return len(self._live)

    def acquire(self) -> RunSlot:
        """Reserve a slot, or raise `TooManyRequests` without side effects."""
        limit = max(1, self._limit())
        daily_limit = self._daily_limit()
        self._roll_day()

        if daily_limit > 0 and self._runs_today >= daily_limit:
            raise TooManyRequests(
                "Daily analysis limit reached — try again tomorrow",
                retry_after=self._seconds_until_utc_midnight(),
                scope="daily_runs",
                limit=daily_limit,
            )

        if self._active >= limit:
            raise TooManyRequests(
                "Too many analyses already running — retry shortly",
                retry_after=_CONCURRENCY_RETRY_AFTER,
                scope="active_queries",
                limit=limit,
                active=self._active,
            )

        self._runs_today += 1
        slot = RunSlot(self, started_at=self._monotonic())
        self._live.append(slot)
        return slot

    def release_one(self, slot: RunSlot) -> None:
        """Give a slot back. Paired with `RunSlot.release`, which is idempotent."""
        try:
            self._live.remove(slot)
        except ValueError:
            # Already gone. Releasing twice is allowed by design, so this is not
            # an error worth raising at a caller that did nothing wrong.
            pass

    def live_slots(self) -> list[RunSlot]:
        """The slots currently held, oldest first."""
        return list(self._live)

    def snapshot(self) -> dict[str, int]:
        self._roll_day()
        return {
            "active": self._active,
            "limit": max(1, self._limit()),
            "runs_today": self._runs_today,
            "daily_limit": self._daily_limit(),
        }

    def reset(self) -> None:
        self._live.clear()
        self._runs_today = 0
        self._day = None

    def _roll_day(self) -> None:
        today = self._now().date()
        if self._day != today:
            self._day = today
            self._runs_today = 0

    def _seconds_until_utc_midnight(self) -> float:
        now = self._now()
        midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
        return max(1.0, (midnight - now).total_seconds())


# ------------------------------------------------------------------ instances


run_gate = RunGate(
    limit=lambda: settings.max_active_queries,
    daily_limit=lambda: settings.max_daily_runs,
)

#: Pipeline submissions, follow-ups and report regeneration — the LLM-heavy
#: writes, measured per hour because one of them costs minutes of work.
runs_limiter = RateLimiter(
    "runs",
    rate_per_second=lambda: max(0, settings.rate_limit_runs_per_hour) / 3600.0,
    capacity=lambda: settings.rate_limit_runs_burst,
    enabled=lambda: settings.rate_limit_enabled,
)

#: Cluster and report edits — individually cheap database writes, but a loop
#: over them still costs the pool and the disk.
edits_limiter = RateLimiter(
    "edits",
    rate_per_second=lambda: max(0, settings.rate_limit_edits_per_minute) / 60.0,
    capacity=lambda: settings.rate_limit_edits_burst,
    enabled=lambda: settings.rate_limit_enabled,
)

#: Interpreting a draft question — two LLM calls, no run slot and no write. It
#: is the one LLM path a visitor can reach without submitting anything, so it
#: gets its own bucket rather than borrowing the runs budget it does not spend.
interprets_limiter = RateLimiter(
    "interprets",
    rate_per_second=lambda: max(0, settings.rate_limit_interprets_per_minute) / 60.0,
    capacity=lambda: settings.rate_limit_interprets_burst,
    enabled=lambda: settings.rate_limit_enabled,
)

#: Asking a finished report a question — one LLM call over material already in
#: the database. Its own bucket because a chat is used in bursts: borrowing the
#: interpret budget would mean four questions locked the Interpret button, and
#: borrowing the runs budget would price a question like a pipeline run.
chat_limiter = RateLimiter(
    "chat",
    rate_per_second=lambda: max(0, settings.rate_limit_chat_per_minute) / 60.0,
    capacity=lambda: settings.rate_limit_chat_burst,
    enabled=lambda: settings.rate_limit_enabled,
)

#: Handing over a paper — one call per file, and a corpus arrives as a burst of
#: them from a single drop. Its own bucket for that reason alone: the edits
#: budget is sized for one deliberate change at a time, and twenty files would
#: exhaust it before the reader had finished choosing them.
uploads_limiter = RateLimiter(
    "uploads",
    rate_per_second=lambda: max(0, settings.rate_limit_uploads_per_minute) / 60.0,
    capacity=lambda: settings.rate_limit_uploads_burst,
    enabled=lambda: settings.rate_limit_enabled,
)

#: Cost classes used by the v2 action registry, mapped to the bucket that
#: governs them. Anything absent (i.e. a read) is not rate limited.
_LIMITER_BY_COST = {
    "run": runs_limiter,
    "edit": edits_limiter,
    "interpret": interprets_limiter,
    "chat": chat_limiter,
    "upload": uploads_limiter,
}


def limiter_for_cost(cost: str) -> RateLimiter | None:
    return _LIMITER_BY_COST.get(cost)


def budgets_for(key: str) -> dict[str, dict[str, object]]:
    """Every rate-limited bucket's remaining allowance for one caller.

    Reads never consume, so a client may poll this to show a caller what they
    have left without that display itself costing them a request.
    """
    return {
        limiter.name: {
            "remaining": budget.remaining,
            "capacity": budget.capacity,
            "refill_seconds": budget.refill_seconds,
        }
        for limiter in (
            runs_limiter,
            edits_limiter,
            interprets_limiter,
            chat_limiter,
            uploads_limiter,
        )
        for budget in (limiter.peek(key),)
    }


def _last_progress(query_id: UUID) -> tuple[int | None, int | None]:
    """The most recent completed/total a run published, if it published any.

    Read back off the hub's history rather than tracked separately: the events
    already carry it, and a second copy would be one more thing to keep in step.
    """
    for event in reversed(hub.history(query_id)):
        total = event.get("total")
        if total:
            return int(event.get("completed") or 0), int(total)
    return None, None


def active_runs() -> list[dict[str, Any]]:
    """One anonymous entry per in-flight run, oldest first.

    Deliberately carries no query id. Someone refused for capacity is a stranger,
    and an id is a key to `queries.get`, which returns the question itself —
    handing ids out to explain a busy queue would leak exactly what reporting
    only the phase was meant to protect. Nothing here predicts a finish time
    either; elapsed is measured, remaining would be invented.
    """
    runs: list[dict[str, Any]] = []
    for slot in run_gate.live_slots():
        elapsed = max(0.0, time.monotonic() - slot.started_at)
        phase: str | None = None
        completed: int | None = None
        total: int | None = None
        if slot.query_id is not None:
            phase = hub.snapshot(slot.query_id).get("phase") or None
            completed, total = _last_progress(slot.query_id)
        runs.append(
            {
                "phase": phase,
                "elapsed_seconds": round(elapsed, 1),
                "completed": completed,
                "total": total,
            }
        )
    return runs


def snapshot_for(key: str) -> dict[str, object]:
    """The whole admission picture for one caller: global gate plus own budgets.

    Two different limits, kept apart on purpose. The gate is shared by everyone
    and says whether the machine is busy; the budgets are the caller's own and say
    how fast they may ask. A UI that merged them would explain neither.
    """
    return {
        "runs": run_gate.snapshot(),
        "active_runs": active_runs(),
        "rate_limit_enabled": settings.rate_limit_enabled,
        "budgets": budgets_for(key),
    }


def client_key(*, client_host: str | None, forwarded_for: str | None) -> str:
    """The identity a rate limit is keyed on.

    `X-Forwarded-For` is only consulted when TRUST_FORWARDED_FOR is on: the
    header is caller-supplied, so honouring it with no proxy in front lets
    anyone mint a fresh identity per request and bypass limiting entirely. When
    it is trusted, the client-most entry is used — the one a well-behaved proxy
    puts first.
    """
    if settings.trust_forwarded_for and forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return client_host or "unknown"


def reset_all() -> None:
    """Clear every limiter and the gate — for tests, which share a process."""
    run_gate.reset()
    runs_limiter.reset()
    edits_limiter.reset()
