"""Admission control: the token buckets and the global run gate.

Both are pure in-process mechanisms with injectable clocks, so everything here
is exact rather than timing-dependent — no sleeps, no tolerances.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import settings
from app.services.errors import TooManyRequests
from app.services.limits import RateLimiter, RunGate, client_key


class FakeClock:
    """A monotonic clock that only moves when a test says so."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _limiter(clock, *, per_second=1.0, capacity=3, enabled=True, max_keys=4096) -> RateLimiter:
    return RateLimiter(
        "test",
        rate_per_second=lambda: per_second,
        capacity=lambda: capacity,
        enabled=lambda: enabled,
        max_keys=max_keys,
        clock=clock,
    )


# ------------------------------------------------------------- rate limiting


def test_burst_is_allowed_then_refused():
    clock = FakeClock()
    limiter = _limiter(clock, per_second=1.0, capacity=3)

    assert [limiter.allow("1.2.3.4") for _ in range(3)] == [None, None, None]

    retry_after = limiter.allow("1.2.3.4")
    assert retry_after is not None
    # One token refills per second, and the bucket is empty.
    assert retry_after == pytest.approx(1.0)


def test_tokens_refill_over_time():
    clock = FakeClock()
    limiter = _limiter(clock, per_second=1.0, capacity=3)
    for _ in range(3):
        limiter.allow("ip")
    assert limiter.allow("ip") is not None

    clock.advance(1.0)
    assert limiter.allow("ip") is None
    # Spent again immediately, so it is empty again.
    assert limiter.allow("ip") is not None


def test_refill_is_capped_at_capacity():
    clock = FakeClock()
    limiter = _limiter(clock, per_second=1.0, capacity=3)
    limiter.allow("ip")

    clock.advance(3600.0)
    assert [limiter.allow("ip") for _ in range(3)] == [None, None, None]
    # Capacity, not one hour's worth of tokens.
    assert limiter.allow("ip") is not None


def test_keys_are_independent():
    clock = FakeClock()
    limiter = _limiter(clock, per_second=1.0, capacity=1)

    assert limiter.allow("a") is None
    assert limiter.allow("a") is not None
    # A throttled caller must not spend anyone else's budget.
    assert limiter.allow("b") is None


def test_disabled_limiter_never_refuses():
    clock = FakeClock()
    limiter = _limiter(clock, per_second=1.0, capacity=1, enabled=False)
    assert all(limiter.allow("ip") is None for _ in range(50))
    assert limiter.tracked_keys() == 0


def test_check_raises_with_a_retry_hint():
    clock = FakeClock()
    limiter = _limiter(clock, per_second=1.0, capacity=1)
    limiter.check("ip")

    with pytest.raises(TooManyRequests) as refused:
        limiter.check("ip")

    assert refused.value.status_code == 429
    assert refused.value.retry_after == pytest.approx(1.0)
    assert refused.value.detail["scope"] == "test"
    # The hint reaches a socket client through `detail`, not just the header.
    assert refused.value.detail["retry_after"] == pytest.approx(1.0)


def test_zero_rate_closes_the_bucket_without_an_infinite_wait():
    clock = FakeClock()
    limiter = _limiter(clock, per_second=0.0, capacity=1)
    assert limiter.allow("ip") is None

    retry_after = limiter.allow("ip")
    clock.advance(10_000)
    assert retry_after == 3600.0
    assert limiter.allow("ip") == 3600.0


def test_idle_buckets_are_pruned_so_key_rotation_cannot_exhaust_memory():
    clock = FakeClock()
    limiter = _limiter(clock, per_second=1.0, capacity=1, max_keys=16)

    for index in range(16):
        limiter.allow(f"ip-{index}")
    assert limiter.tracked_keys() == 16

    # Every bucket has now refilled, so none of them carries state worth keeping.
    clock.advance(60.0)
    limiter.allow("ip-fresh")
    assert limiter.tracked_keys() == 1


def test_pruning_evicts_when_every_bucket_is_still_live():
    clock = FakeClock()
    limiter = _limiter(clock, per_second=0.001, capacity=1, max_keys=8)

    for index in range(8):
        limiter.allow(f"ip-{index}")
    assert limiter.tracked_keys() == 8

    # Nothing has refilled, so the limiter must evict rather than grow.
    limiter.allow("ip-new")
    assert limiter.tracked_keys() <= 8


# ------------------------------------------------------------- the run gate


class FakeDate:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


def _gate(*, limit=2, daily_limit=0, now=None) -> RunGate:
    clock = now or FakeDate(datetime(2026, 8, 18, 12, 0, tzinfo=UTC))
    return RunGate(limit=lambda: limit, daily_limit=lambda: daily_limit, now=clock)


def test_gate_admits_up_to_the_limit_then_refuses():
    gate = _gate(limit=2)
    first, second = gate.acquire(), gate.acquire()

    with pytest.raises(TooManyRequests) as refused:
        gate.acquire()

    assert refused.value.status_code == 429
    assert refused.value.detail["scope"] == "active_queries"
    assert refused.value.detail["limit"] == 2
    assert gate.snapshot()["active"] == 2
    assert not first.released and not second.released


def test_releasing_a_slot_frees_capacity():
    gate = _gate(limit=1)
    slot = gate.acquire()
    with pytest.raises(TooManyRequests):
        gate.acquire()

    slot.release()
    assert gate.snapshot()["active"] == 0
    # Capacity is genuinely back, not just the counter.
    assert gate.acquire() is not None


def test_releasing_twice_does_not_hand_back_capacity_it_never_had():
    """Ownership moves from the request to the task, so both may call release."""
    gate = _gate(limit=2)
    slot = gate.acquire()
    gate.acquire()

    slot.release()
    slot.release()
    slot.release()

    assert gate.snapshot()["active"] == 1


def test_daily_ceiling_refuses_once_spent():
    gate = _gate(limit=5, daily_limit=2)
    gate.acquire().release()
    gate.acquire().release()

    with pytest.raises(TooManyRequests) as refused:
        gate.acquire()

    assert refused.value.detail["scope"] == "daily_runs"
    assert refused.value.detail["limit"] == 2
    # Slots are free — it is the day's budget that is gone.
    assert gate.snapshot()["active"] == 0
    assert gate.snapshot()["runs_today"] == 2


def test_daily_ceiling_is_charged_on_admission_not_completion():
    """A run that fails instantly must still cost a day's budget."""
    gate = _gate(limit=5, daily_limit=1)
    gate.acquire().release()

    with pytest.raises(TooManyRequests):
        gate.acquire()


def test_a_concurrency_refusal_does_not_spend_daily_budget():
    gate = _gate(limit=1, daily_limit=5)
    gate.acquire()

    with pytest.raises(TooManyRequests):
        gate.acquire()

    assert gate.snapshot()["runs_today"] == 1


def test_daily_counter_resets_on_the_next_utc_day():
    clock = FakeDate(datetime(2026, 8, 18, 23, 59, tzinfo=UTC))
    gate = _gate(limit=5, daily_limit=1, now=clock)
    gate.acquire().release()
    with pytest.raises(TooManyRequests):
        gate.acquire()

    clock.moment += timedelta(minutes=2)
    assert gate.acquire() is not None
    assert gate.snapshot()["runs_today"] == 1


def test_daily_refusal_advertises_the_wait_until_midnight():
    clock = FakeDate(datetime(2026, 8, 18, 23, 0, tzinfo=UTC))
    gate = _gate(limit=5, daily_limit=1, now=clock)
    gate.acquire()

    with pytest.raises(TooManyRequests) as refused:
        gate.acquire()

    assert refused.value.retry_after == pytest.approx(3600.0)


def test_zero_daily_limit_means_unlimited():
    gate = _gate(limit=50, daily_limit=0)
    for _ in range(20):
        gate.acquire().release()
    assert gate.snapshot()["runs_today"] == 20


def test_snapshot_exposes_the_configured_ceilings():
    gate = _gate(limit=3, daily_limit=7)
    gate.acquire()
    assert gate.snapshot() == {
        "active": 1,
        "limit": 3,
        "runs_today": 1,
        "daily_limit": 7,
    }


# ----------------------------------------------------------------- client key


def test_forwarded_for_is_ignored_unless_it_is_trusted():
    """Untrusted, the header is a free identity generator — it must not be used."""
    assert settings.trust_forwarded_for is False
    assert client_key(client_host="10.0.0.1", forwarded_for="1.1.1.1") == "10.0.0.1"


def test_forwarded_for_is_used_when_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trust_forwarded_for", True)
    # The client-most entry is the one a well-behaved proxy puts first.
    assert client_key(client_host="10.0.0.1", forwarded_for="1.1.1.1, 10.0.0.1") == "1.1.1.1"


def test_forwarded_for_falls_back_when_blank(monkeypatch):
    monkeypatch.setattr(settings, "trust_forwarded_for", True)
    assert client_key(client_host="10.0.0.1", forwarded_for="  ") == "10.0.0.1"


def test_missing_peer_still_yields_a_key():
    assert client_key(client_host=None, forwarded_for=None) == "unknown"


# ---------------------------------------------------------------- peek/budget


def test_peek_reports_what_is_left_without_spending_it():
    clock = FakeClock()
    limiter = _limiter(clock, per_second=1.0, capacity=10)
    for _ in range(3):
        limiter.allow("ip")

    first = limiter.peek("ip")
    second = limiter.peek("ip")

    assert (first.remaining, first.capacity) == (7, 10)
    # Peeking twice must not cost a token; a status display cannot be a charge.
    assert second.remaining == 7
    assert limiter.allow("ip") is None
    assert limiter.peek("ip").remaining == 6


def test_peek_does_not_create_a_bucket():
    """Polling must not populate the dict, or it becomes the growth vector."""
    clock = FakeClock()
    limiter = _limiter(clock, per_second=1.0, capacity=5)

    budget = limiter.peek("never-seen")

    assert budget.remaining == 5
    assert limiter.tracked_keys() == 0


def test_peek_accounts_for_refill_since_the_last_spend():
    clock = FakeClock()
    limiter = _limiter(clock, per_second=1.0, capacity=10)
    for _ in range(10):
        limiter.allow("ip")
    assert limiter.peek("ip").remaining == 0

    clock.advance(4.0)
    assert limiter.peek("ip").remaining == 4


def test_peek_floors_partial_tokens():
    """Nine tenths of a token buys nothing, so it must not read as one."""
    clock = FakeClock()
    limiter = _limiter(clock, per_second=1.0, capacity=5)
    for _ in range(5):
        limiter.allow("ip")

    clock.advance(0.9)
    assert limiter.peek("ip").remaining == 0
    clock.advance(0.1)
    assert limiter.peek("ip").remaining == 1


def test_peek_reports_the_sustained_rate_not_the_burst():
    """`capacity` is a burst; `refill_seconds` is the rate. Conflating them lies."""
    clock = FakeClock()
    limiter = _limiter(clock, per_second=1 / 60, capacity=10)

    budget = limiter.peek("ip")

    assert budget.capacity == 10
    assert budget.refill_seconds == pytest.approx(60.0)


def test_peek_says_so_when_limiting_is_off():
    clock = FakeClock()
    limiter = _limiter(clock, per_second=1.0, capacity=4, enabled=False)

    budget = limiter.peek("ip")

    assert budget.enabled is False
    assert budget.remaining == budget.capacity == 4
    assert budget.refill_seconds is None


def test_peek_on_a_closed_bucket_has_no_refill():
    clock = FakeClock()
    limiter = _limiter(clock, per_second=0.0, capacity=1)
    assert limiter.peek("ip").refill_seconds is None


# ------------------------------------------------------------- live slot state


class FakeMono:
    def __init__(self, now: float = 500.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _timed_gate(*, limit=3, mono=None) -> RunGate:
    return RunGate(
        limit=lambda: limit,
        daily_limit=lambda: 0,
        now=FakeDate(datetime(2026, 8, 18, 12, 0, tzinfo=UTC)),
        monotonic=mono or FakeMono(),
    )


def test_active_count_is_derived_from_the_live_slots():
    """One source of truth: the reported count cannot drift from what is held."""
    gate = _timed_gate(limit=3)
    first, second = gate.acquire(), gate.acquire()

    assert gate.snapshot()["active"] == 2
    assert len(gate.live_slots()) == 2

    first.release()
    assert gate.snapshot()["active"] == 1
    assert gate.live_slots() == [second]


def test_live_slots_are_ordered_oldest_first():
    """So "slot 1" stays "slot 1" between polls rather than reshuffling."""
    mono = FakeMono()
    gate = _timed_gate(limit=3, mono=mono)

    first = gate.acquire()
    mono.advance(10.0)
    second = gate.acquire()

    assert [slot.started_at for slot in gate.live_slots()] == [
        first.started_at,
        second.started_at,
    ]
    assert first.started_at < second.started_at


def test_a_slot_records_when_its_run_began():
    mono = FakeMono(1000.0)
    gate = _timed_gate(mono=mono)
    slot = gate.acquire()

    mono.advance(362.0)

    assert mono() - slot.started_at == 362.0


def test_releasing_twice_removes_one_slot_only():
    gate = _timed_gate(limit=3)
    slot = gate.acquire()
    gate.acquire()

    slot.release()
    slot.release()

    assert gate.snapshot()["active"] == 1


def test_a_slot_is_anonymous_until_a_run_claims_it():
    """Reserved before the query row exists, so it cannot be named at acquire."""
    gate = _timed_gate()
    slot = gate.acquire()
    assert slot.query_id is None

    query_id = uuid4()
    slot.attach(query_id)
    assert gate.live_slots()[0].query_id == query_id


def test_reset_drops_live_slots():
    gate = _timed_gate()
    gate.acquire()
    gate.reset()
    assert gate.snapshot()["active"] == 0
    assert gate.live_slots() == []
