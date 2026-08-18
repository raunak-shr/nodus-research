"""The hardening surface: 429s, the admin-only inline path, and reads staying open.

Hermetic, and deliberately so. Most cases here are refused *before* the handler
touches anything, so they need no stubbing at all: the setup drains a bucket or
fills the gate and then asserts what the transport does about it. The few cases
that must reach a handler use `stub_pipeline`, which replaces the session and the
pipeline entry points — a test that reached the real database would open an
asyncpg connection and run for minutes.
"""

import json
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.api.v1.routes import queries as query_routes
from app.api.v2.routes.ws import _is_admin
from app.core.config import settings
from app.db.session import get_session
from app.main import app
from app.services import limits, runner
from app.services.limits import run_gate

# Both transports report a fixed peer, which is the key the limiters see.
HTTP_CLIENT_KEY = "127.0.0.1"
WS_CLIENT_KEY = "testclient"

A_QUERY = {"query": "does caffeine improve reaction time"}
MISSING_ID = "00000000-0000-0000-0000-000000000000"


def _drain(limiter, key: str) -> None:
    """Spend the whole bucket, so the next call is the one under test."""
    while limiter.allow(key) is None:
        pass


class _StubSession:
    """Just enough AsyncSession for a create handler, with no Postgres behind it."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass

    async def refresh(self, obj: object, *args, **kwargs) -> None:
        # Stand in for the column defaults that normally come from the database.
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        if getattr(obj, "paper_count", None) is None:
            obj.paper_count = 0
        now = datetime.now(UTC)
        obj.created_at = getattr(obj, "created_at", None) or now
        obj.updated_at = getattr(obj, "updated_at", None) or now

    async def execute(self, *args, **kwargs):
        raise AssertionError("this test must not query the database")


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Let a handler run to completion without a database or an LLM.

    `launch` still releases the slot it is handed, so slot accounting stays
    honest — that is the part these tests are watching.
    """
    launched: list[tuple] = []

    def fake_launch(query_id, raw_query, *, slot=None):
        launched.append((query_id, raw_query))
        if slot is not None:
            slot.release()
        return None

    async def fake_run(query_id, raw_query):
        launched.append((query_id, raw_query))

    monkeypatch.setattr(runner, "launch", fake_launch)
    monkeypatch.setattr(query_routes, "run_pipeline_safe", fake_run)
    app.dependency_overrides[get_session] = lambda: _StubSession()
    yield launched
    app.dependency_overrides.pop(get_session, None)


# ------------------------------------------------------- global backpressure


@pytest.mark.asyncio
async def test_query_creation_is_refused_when_the_gate_is_full(client: AsyncClient):
    with patch.object(settings, "max_active_queries", 2):
        held = [run_gate.acquire(), run_gate.acquire()]
        try:
            response = await client.post("/api/v1/queries/", json=A_QUERY)
        finally:
            for slot in held:
                slot.release()

    assert response.status_code == 429
    context = response.json()["context"]
    assert context["scope"] == "active_queries"
    assert context["limit"] == 2
    # A 429 without this tells clients to guess, and they guess "immediately".
    assert int(response.headers["retry-after"]) >= 1


@pytest.mark.asyncio
async def test_a_refused_submission_leaves_no_query_behind(client: AsyncClient):
    """The slot is taken before the row is written, so nothing is persisted.

    Were the order reversed, a refusal would strand a `pending` query no pipeline
    will ever pick up — hence asserting the model was never even constructed.
    """
    with patch.object(settings, "max_active_queries", 1):
        slot = run_gate.acquire()
        try:
            with patch.object(query_routes, "Query") as model:
                response = await client.post("/api/v1/queries/", json=A_QUERY)
        finally:
            slot.release()

    assert response.status_code == 429
    model.assert_not_called()


@pytest.mark.asyncio
async def test_requests_are_refused_immediately_rather_than_queued(client: AsyncClient):
    """Backpressure, not a queue: the caller is told now, not parked."""
    with patch.object(settings, "max_active_queries", 1):
        slot = run_gate.acquire()
        try:
            responses = [await client.post("/api/v1/queries/", json=A_QUERY) for _ in range(3)]
        finally:
            slot.release()

    assert [r.status_code for r in responses] == [429, 429, 429]


@pytest.mark.asyncio
async def test_capacity_returns_after_a_slot_is_released(client: AsyncClient, stub_pipeline):
    with patch.object(settings, "max_active_queries", 1):
        slot = run_gate.acquire()
        refused = await client.post("/api/v1/queries/", json=A_QUERY)
        assert refused.status_code == 429

        slot.release()
        allowed = await client.post("/api/v1/queries/", json=A_QUERY)

    assert allowed.status_code == 201
    assert len(stub_pipeline) == 1
    # And the slot that run took came back too.
    assert run_gate.snapshot()["active"] == 0


@pytest.mark.asyncio
async def test_the_daily_ceiling_refuses_with_its_own_scope(client: AsyncClient):
    with (
        patch.object(settings, "max_active_queries", 5),
        patch.object(settings, "max_daily_runs", 3),
    ):
        for _ in range(3):
            run_gate.acquire().release()

        response = await client.post("/api/v1/queries/", json=A_QUERY)

    assert response.status_code == 429
    context = response.json()["context"]
    assert context["scope"] == "daily_runs"
    assert context["limit"] == 3


@pytest.mark.asyncio
async def test_the_daily_ceiling_is_off_by_default(client: AsyncClient, stub_pipeline):
    assert settings.max_daily_runs == 0
    for _ in range(6):
        run_gate.acquire().release()

    response = await client.post("/api/v1/queries/", json=A_QUERY)
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_followups_go_through_the_same_gate(client: AsyncClient):
    """A follow-up costs a full run, so it must not be a way around the cap."""
    with patch.object(settings, "max_active_queries", 1):
        slot = run_gate.acquire()
        try:
            response = await client.post(
                f"/api/v1/queries/{MISSING_ID}/followup",
                json={"query": "narrow it to adolescents"},
            )
        finally:
            slot.release()

    # Refused for capacity before the parent is even looked up.
    assert response.status_code == 429
    assert response.json()["context"]["scope"] == "active_queries"


# ---------------------------------------------------- the admin-only inline path


@pytest.mark.asyncio
async def test_wait_is_refused_without_the_admin_key(client: AsyncClient):
    with patch.object(settings, "admin_api_key", "admin-secret"):
        response = await client.post("/api/v1/queries/?wait=true", json=A_QUERY)

    assert response.status_code == 403
    assert "admin-only" in response.json()["detail"]
    # The gate is untouched: the flag is rejected before a slot is reserved.
    assert run_gate.snapshot()["active"] == 0


@pytest.mark.asyncio
async def test_wait_is_refused_when_no_admin_key_is_configured(client: AsyncClient):
    """Unset means nobody is an admin — the path must not open by default."""
    with patch.object(settings, "admin_api_key", ""):
        response = await client.post("/api/v1/queries/?wait=true", json=A_QUERY)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_wait_is_refused_with_the_wrong_admin_key(client: AsyncClient):
    with patch.object(settings, "admin_api_key", "admin-secret"):
        response = await client.post(
            "/api/v1/queries/?wait=true",
            json=A_QUERY,
            headers={"X-Admin-Key": "guess"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_the_admin_key_unlocks_the_inline_run(client: AsyncClient, stub_pipeline):
    with patch.object(settings, "admin_api_key", "admin-secret"):
        response = await client.post(
            "/api/v1/queries/?wait=true",
            json=A_QUERY,
            headers={"X-Admin-Key": "admin-secret"},
        )

    assert response.status_code == 201
    assert len(stub_pipeline) == 1
    # An inline run holds the slot for its duration, then gives it back.
    assert run_gate.snapshot()["active"] == 0


@pytest.mark.asyncio
async def test_the_normal_background_path_needs_no_admin_key(client: AsyncClient, stub_pipeline):
    response = await client.post("/api/v1/queries/", json=A_QUERY)
    assert response.status_code == 201
    assert run_gate.snapshot()["active"] == 0


@pytest.mark.asyncio
async def test_followup_wait_is_admin_only_too(client: AsyncClient):
    with patch.object(settings, "admin_api_key", "admin-secret"):
        response = await client.post(
            f"/api/v1/queries/{MISSING_ID}/followup?wait=true",
            json={"query": "narrow it to adolescents"},
        )
    assert response.status_code == 403


def test_socket_admin_resolution():
    """The handshake resolves the admin key once, by constant-time comparison."""

    class FakeSocket:
        def __init__(self, headers=None, params=None):
            self.headers = headers or {}
            self.query_params = params or {}

    with patch.object(settings, "admin_api_key", ""):
        assert _is_admin(FakeSocket(headers={"x-admin-key": "anything"})) is False

    with patch.object(settings, "admin_api_key", "admin-secret"):
        assert _is_admin(FakeSocket()) is False
        assert _is_admin(FakeSocket(headers={"x-admin-key": "guess"})) is False
        assert _is_admin(FakeSocket(headers={"x-admin-key": "admin-secret"})) is True
        assert _is_admin(FakeSocket(params={"admin_key": "admin-secret"})) is True


# ------------------------------------------------------- per-IP rate limiting


@pytest.mark.asyncio
async def test_run_submissions_are_rate_limited(client: AsyncClient):
    _drain(limits.runs_limiter, HTTP_CLIENT_KEY)

    response = await client.post("/api/v1/queries/", json=A_QUERY)

    assert response.status_code == 429
    assert response.json()["context"]["scope"] == "runs"
    assert int(response.headers["retry-after"]) >= 1


@pytest.mark.asyncio
async def test_the_run_burst_is_spendable_before_the_limit_bites(
    client: AsyncClient, stub_pipeline
):
    with (
        patch.object(settings, "rate_limit_runs_burst", 2),
        patch.object(settings, "max_active_queries", 5),
    ):
        statuses = [
            (await client.post("/api/v1/queries/", json=A_QUERY)).status_code for _ in range(3)
        ]

    assert statuses == [201, 201, 429]


@pytest.mark.asyncio
async def test_report_regeneration_uses_the_run_bucket(client: AsyncClient):
    """Up to one LLM call per cluster, repeatable against one existing query."""
    _drain(limits.runs_limiter, HTTP_CLIENT_KEY)

    response = await client.post(f"/api/v1/queries/{MISSING_ID}/report")

    assert response.status_code == 429
    assert response.json()["context"]["scope"] == "runs"


@pytest.mark.asyncio
async def test_cluster_edits_use_the_edit_bucket(client: AsyncClient):
    _drain(limits.edits_limiter, HTTP_CLIENT_KEY)

    response = await client.patch(
        f"/api/v1/claims/clusters/{MISSING_ID}", json={"theme": "renamed"}
    )

    assert response.status_code == 429
    assert response.json()["context"]["scope"] == "edits"


@pytest.mark.asyncio
async def test_report_edits_use_the_edit_bucket(client: AsyncClient):
    _drain(limits.edits_limiter, HTTP_CLIENT_KEY)

    response = await client.patch(f"/api/v1/queries/{MISSING_ID}/report", json={"title": "renamed"})

    assert response.status_code == 429
    assert response.json()["context"]["scope"] == "edits"


@pytest.mark.asyncio
async def test_the_two_buckets_are_independent(client: AsyncClient, stub_pipeline):
    """Editing all afternoon must not cost the ability to start a run."""
    _drain(limits.edits_limiter, HTTP_CLIENT_KEY)

    edit = await client.patch(f"/api/v1/claims/clusters/{MISSING_ID}", json={"theme": "renamed"})
    assert edit.status_code == 429

    run = await client.post("/api/v1/queries/", json=A_QUERY)
    assert run.status_code == 201


@pytest.mark.asyncio
async def test_rate_limiting_can_be_switched_off(client: AsyncClient, stub_pipeline):
    _drain(limits.runs_limiter, HTTP_CLIENT_KEY)

    with patch.object(settings, "rate_limit_enabled", False):
        response = await client.post("/api/v1/queries/", json=A_QUERY)

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_auth_is_checked_before_the_rate_limit(client: AsyncClient):
    """An unauthenticated flood must not spend a legitimate caller's budget."""
    with patch.object(settings, "api_key", "secret-key"):
        for _ in range(10):
            rejected = await client.post("/api/v1/queries/", json=A_QUERY)
            assert rejected.status_code == 401

    assert limits.runs_limiter.tracked_keys() == 0


def test_only_expensive_writes_carry_a_rate_limiter():
    """Reads must stay cheap to serve — a limiter on one is a bug, not a policy."""
    limited: dict[str, set[str]] = {"runs": set(), "edits": set()}
    for route in app.routes:
        for dependency in getattr(route, "dependencies", []):
            name = getattr(dependency.dependency, "__name__", "")
            if name == "rate_limit_runs":
                limited["runs"] |= {f"{m} {route.path}" for m in route.methods if m != "HEAD"}
            elif name == "rate_limit_edits":
                limited["edits"] |= {f"{m} {route.path}" for m in route.methods if m != "HEAD"}

    assert limited["runs"] == {
        "POST /api/v1/queries/",
        "POST /api/v1/queries/{query_id}/followup",
        "POST /api/v1/queries/{query_id}/report",
    }
    assert limited["edits"] == {
        "DELETE /api/v1/queries/{query_id}",
        "PATCH /api/v1/queries/{query_id}/report",
        "PATCH /api/v1/queries/{query_id}/report/sections/{cluster_id}",
        "PATCH /api/v1/claims/clusters/{cluster_id}",
        "PATCH /api/v1/claims/clusters/{cluster_id}/claims/{claim_id}",
        "POST /api/v1/claims/clusters/{cluster_id}/claims",
        "DELETE /api/v1/claims/clusters/{cluster_id}/claims/{claim_id}",
    }
    # No GET anywhere in either set.
    assert not any(entry.startswith("GET ") for group in limited.values() for entry in group)


# -------------------------------------------------------- the v2 socket surface


def test_socket_run_actions_are_rate_limited():
    """The socket reaches the same services, so it cannot be a way around limits."""
    _drain(limits.runs_limiter, WS_CLIENT_KEY)

    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        assert socket.receive_json()["type"] == "ready"
        socket.send_json({"id": "1", "action": "queries.create", "params": A_QUERY})
        frame = socket.receive_json()

    assert frame["type"] == "error"
    assert frame["error"]["code"] == "too_many_requests"
    assert frame["error"]["detail"]["scope"] == "runs"


def test_socket_edit_actions_are_rate_limited():
    _drain(limits.edits_limiter, WS_CLIENT_KEY)

    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        assert socket.receive_json()["type"] == "ready"
        socket.send_json(
            {
                "id": "1",
                "action": "clusters.update",
                "params": {"cluster_id": MISSING_ID, "patch": {"theme": "renamed"}},
            }
        )
        frame = socket.receive_json()

    assert frame["error"]["code"] == "too_many_requests"
    assert frame["error"]["detail"]["scope"] == "edits"


def test_socket_reads_survive_an_empty_bucket():
    _drain(limits.runs_limiter, WS_CLIENT_KEY)
    _drain(limits.edits_limiter, WS_CLIENT_KEY)

    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        assert socket.receive_json()["type"] == "ready"
        socket.send_json({"id": "1", "action": "meta.health"})
        frame = socket.receive_json()

    assert frame["type"] == "result"


def test_socket_wait_is_admin_only():
    with patch.object(settings, "admin_api_key", "admin-secret"):
        with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
            assert socket.receive_json()["type"] == "ready"
            socket.send_json(
                {
                    "id": "1",
                    "action": "queries.create",
                    "params": {**A_QUERY, "wait": True, "subscribe": False},
                }
            )
            frame = socket.receive_json()

    assert frame["type"] == "error"
    assert frame["error"]["code"] == "forbidden"
    # Refused before a slot was reserved.
    assert run_gate.snapshot()["active"] == 0


def test_socket_gate_refusal_is_an_error_frame():
    with patch.object(settings, "max_active_queries", 1):
        slot = run_gate.acquire()
        try:
            with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
                assert socket.receive_json()["type"] == "ready"
                socket.send_json({"id": "1", "action": "queries.create", "params": A_QUERY})
                frame = socket.receive_json()
        finally:
            slot.release()

    assert frame["error"]["code"] == "too_many_requests"
    assert frame["error"]["detail"]["scope"] == "active_queries"


def test_describe_publishes_each_action_cost():
    """The frontend needs to know which calls are throttled before it makes them."""
    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        socket.receive_json()
        socket.send_json({"id": "1", "action": "meta.describe"})
        actions = {item["name"]: item["cost"] for item in socket.receive_json()["data"]["actions"]}

    assert actions["queries.create"] == "run"
    assert actions["queries.followup"] == "run"
    assert actions["report.regenerate"] == "run"
    assert actions["clusters.update"] == "edit"
    assert actions["report.section.update"] == "edit"
    assert actions["queries.get"] == "read"
    assert actions["meta.describe"] == "read"


def test_config_reports_admission_state_without_leaking_keys():
    with patch.object(settings, "admin_api_key", "admin-secret"):
        with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
            socket.receive_json()
            socket.send_json({"id": "1", "action": "meta.config"})
            frame = socket.receive_json()

    config = frame["data"]
    assert config["admin_enabled"] is True
    assert config["rate_limit_enabled"] is True
    assert set(config["runs"]) == {"active", "limit", "runs_today", "daily_limit"}
    assert "admin-secret" not in str(frame)


# ------------------------------------------------------- reporting the budget


@pytest.mark.asyncio
async def test_health_limits_reports_the_gate_and_the_callers_budget(client: AsyncClient):
    with (
        patch.object(settings, "max_active_queries", 2),
        patch.object(settings, "max_daily_runs", 40),
        patch.object(settings, "rate_limit_runs_burst", 10),
        patch.object(settings, "rate_limit_runs_per_hour", 60),
    ):
        for _ in range(3):
            limits.runs_limiter.allow(HTTP_CLIENT_KEY)
        held = run_gate.acquire()
        try:
            response = await client.get("/health/limits")
        finally:
            held.release()

    assert response.status_code == 200
    body = response.json()
    # The shared gate and the caller's own allowance are separate facts.
    assert body["runs"] == {"active": 1, "limit": 2, "runs_today": 1, "daily_limit": 40}
    assert body["budgets"]["runs"]["remaining"] == 7
    assert body["budgets"]["runs"]["capacity"] == 10
    assert body["budgets"]["runs"]["refill_seconds"] == pytest.approx(60.0)
    assert "edits" in body["budgets"]


@pytest.mark.asyncio
async def test_reading_the_budget_does_not_spend_it(client: AsyncClient):
    """A UI that polls this must not throttle the caller by displaying it."""
    for _ in range(4):
        await client.get("/health/limits")

    body = (await client.get("/health/limits")).json()
    assert body["budgets"]["runs"]["remaining"] == body["budgets"]["runs"]["capacity"]
    assert limits.runs_limiter.tracked_keys() == 0


@pytest.mark.asyncio
async def test_the_budget_falls_as_submissions_are_spent(client: AsyncClient):
    with (
        patch.object(settings, "rate_limit_runs_burst", 3),
        patch.object(settings, "max_active_queries", 5),
    ):
        before = (await client.get("/health/limits")).json()["budgets"]["runs"]["remaining"]
        _drain(limits.runs_limiter, HTTP_CLIENT_KEY)
        after = (await client.get("/health/limits")).json()["budgets"]["runs"]["remaining"]

    assert before == 3
    assert after == 0


@pytest.mark.asyncio
async def test_health_limits_leaks_no_keys(client: AsyncClient):
    with patch.object(settings, "admin_api_key", "admin-secret"):
        response = await client.get("/health/limits")
    body = response.text.lower()
    assert "secret" not in body and "api_key" not in body


def test_socket_reports_the_budget_for_its_own_connection():
    _drain(limits.edits_limiter, WS_CLIENT_KEY)

    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        assert socket.receive_json()["type"] == "ready"
        socket.send_json({"id": "1", "action": "meta.limits"})
        frame = socket.receive_json()

    data = frame["data"]
    # The action must read the same key the limiter charges, not a fresh one.
    assert data["budgets"]["edits"]["remaining"] == 0
    assert data["budgets"]["runs"]["remaining"] > 0
    assert set(data) == {"runs", "active_runs", "rate_limit_enabled", "budgets"}


def test_meta_limits_is_a_read_so_it_cannot_throttle_itself():
    from app.api.v2.actions import REGISTRY

    assert REGISTRY["meta.limits"].cost == "read"


# --------------------------------------------------- describing a busy queue


@pytest.mark.asyncio
async def test_active_runs_describes_each_slot_without_naming_it(client: AsyncClient):
    """The whole point: explain the wait, reveal nobody's research question."""
    from uuid import uuid4

    from app.core.events import hub

    query_id = uuid4()
    hub.publish(query_id, "pipeline_started", raw_query="a private question")
    hub.publish(query_id, "paper_processed", completed=9, total=18, progress=0.5)

    with patch.object(settings, "max_active_queries", 2):
        held = run_gate.acquire()
        held.attach(query_id)
        try:
            body = (await client.get("/health/limits")).json()
        finally:
            held.release()
            hub.clear(query_id)

    assert body["runs"]["active"] == 1
    run = body["active_runs"][0]
    assert run["phase"] == "processing"
    assert (run["completed"], run["total"]) == (9, 18)
    assert run["elapsed_seconds"] >= 0

    # No identifier of any kind, and nothing resembling the question.
    serialised = json.dumps(body)
    assert str(query_id) not in serialised
    assert "private question" not in serialised
    assert not any("id" in key for key in run)


@pytest.mark.asyncio
async def test_active_runs_is_empty_when_nothing_is_running(client: AsyncClient):
    body = (await client.get("/health/limits")).json()
    assert body["active_runs"] == []
    assert body["runs"]["active"] == 0


@pytest.mark.asyncio
async def test_an_unnamed_slot_still_occupies_the_queue(client: AsyncClient):
    """An inline admin run holds capacity even though nothing attached an id."""
    with patch.object(settings, "max_active_queries", 2):
        held = run_gate.acquire()
        try:
            body = (await client.get("/health/limits")).json()
        finally:
            held.release()

    assert len(body["active_runs"]) == 1
    run = body["active_runs"][0]
    assert run["phase"] is None
    assert run["total"] is None
    assert run["elapsed_seconds"] >= 0


@pytest.mark.asyncio
async def test_active_runs_reports_slots_oldest_first(client: AsyncClient):
    with patch.object(settings, "max_active_queries", 3):
        first, second = run_gate.acquire(), run_gate.acquire()
        try:
            body = (await client.get("/health/limits")).json()
        finally:
            first.release()
            second.release()

    elapsed = [run["elapsed_seconds"] for run in body["active_runs"]]
    assert len(elapsed) == 2
    assert elapsed == sorted(elapsed, reverse=True)


@pytest.mark.asyncio
async def test_no_run_advertises_a_finish_time(client: AsyncClient):
    """Elapsed is measured; anything remaining would be invented."""
    with patch.object(settings, "max_active_queries", 2):
        held = run_gate.acquire()
        try:
            body = (await client.get("/health/limits")).json()
        finally:
            held.release()

    run = body["active_runs"][0]
    assert set(run) == {"phase", "elapsed_seconds", "completed", "total"}


def test_socket_reports_active_runs_too():
    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        assert socket.receive_json()["type"] == "ready"
        socket.send_json({"id": "1", "action": "meta.limits"})
        data = socket.receive_json()["data"]

    assert data["active_runs"] == []
