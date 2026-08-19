"""asyncpg rejects multi-statement SQL, so migrations split before executing."""

from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.session import (
    build_connect_args,
    build_engine_kwargs,
    is_transaction_pooled,
    resolve_pool_limits,
)
from app.db.sql_split import split_statements


def test_splits_simple_statements():
    statements = split_statements("CREATE TABLE a (id INT); CREATE TABLE b (id INT);")
    assert statements == ["CREATE TABLE a (id INT)", "CREATE TABLE b (id INT)"]


def test_keeps_dollar_quoted_function_bodies_intact():
    sql = """
    CREATE FUNCTION touch() RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER t BEFORE UPDATE ON x FOR EACH ROW EXECUTE FUNCTION touch();
    """
    statements = split_statements(sql)
    assert len(statements) == 2
    assert "NEW.updated_at = now();" in statements[0]
    assert statements[1].startswith("CREATE TRIGGER")


def test_handles_tagged_dollar_quotes():
    sql = "CREATE FUNCTION f() RETURNS TEXT AS $body$ SELECT 'a;b'; $body$ LANGUAGE sql;"
    assert len(split_statements(sql)) == 1


def test_ignores_semicolons_inside_string_literals():
    statements = split_statements("INSERT INTO t VALUES ('a;b'); SELECT 1;")
    assert len(statements) == 2
    assert "'a;b'" in statements[0]


def test_handles_escaped_quotes():
    statements = split_statements("INSERT INTO t VALUES ('it''s; fine'); SELECT 1;")
    assert len(statements) == 2


def test_strips_line_comments():
    statements = split_statements("-- a comment;\nSELECT 1;")
    assert statements == ["SELECT 1"]


def test_trailing_statement_without_semicolon():
    assert split_statements("SELECT 1") == ["SELECT 1"]


def test_blank_input_yields_nothing():
    assert split_statements("   \n  ") == []


# ------------------------------------------------------------------ DB TLS


def test_local_host_needs_no_tls():
    url = "postgresql+asyncpg://postgres:postgres@localhost:5432/nodus"
    assert build_connect_args(url, "auto") == {}


def test_remote_host_gets_tls_in_auto_mode():
    url = "postgresql+asyncpg://postgres:pw@db.example.supabase.co:5432/postgres"
    args = build_connect_args(url, "auto")
    assert "ssl" in args


def test_disable_mode_never_adds_tls():
    url = "postgresql+asyncpg://postgres:pw@db.example.supabase.co:5432/postgres"
    assert build_connect_args(url, "disable") == {}


def test_require_mode_forces_tls_even_locally():
    url = "postgresql+asyncpg://postgres:postgres@localhost:5432/nodus"
    assert "ssl" in build_connect_args(url, "require")


# ------------------------------------------------------- Supabase endpoints

DIRECT = "postgresql+asyncpg://postgres:pw@db.example.supabase.co:5432/postgres"
SESSION_POOLER = (
    "postgresql+asyncpg://postgres.example:pw@aws-0-eu-west-2.pooler.supabase.com:5432/postgres"
)
TRANSACTION_POOLER = (
    "postgresql+asyncpg://postgres.example:pw@aws-0-eu-west-2.pooler.supabase.com:6543/postgres"
)


def test_only_the_transaction_pooler_is_treated_as_pooled():
    assert is_transaction_pooled(TRANSACTION_POOLER)
    assert not is_transaction_pooled(SESSION_POOLER)
    assert not is_transaction_pooled(DIRECT)
    # 6543 on a host that is not a pooler is somebody's own Postgres.
    assert not is_transaction_pooled("postgresql+asyncpg://u:p@db.example.com:6543/postgres")


def test_transaction_pooler_disables_prepared_statement_names():
    args = build_connect_args(TRANSACTION_POOLER, "auto")
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_name_func"]() == ""
    # TLS is still applied: the endpoint is remote.
    assert "ssl" in args


def test_session_pooler_keeps_prepared_statements():
    args = build_connect_args(SESSION_POOLER, "auto")
    assert "statement_cache_size" not in args
    assert "prepared_statement_name_func" not in args


def test_transaction_pooler_lets_supavisor_do_the_pooling():
    assert build_engine_kwargs(TRANSACTION_POOLER) == {"poolclass": NullPool}
    assert "pool_size" in build_engine_kwargs(SESSION_POOLER)
    assert "pool_size" in build_engine_kwargs(DIRECT)


def test_pool_stays_under_the_provider_client_cap(monkeypatch):
    """pool_size + max_overflow is what a pooler counts, so that is what is capped."""
    monkeypatch.setattr(settings, "db_pool_size", 10)
    monkeypatch.setattr(settings, "db_max_overflow", 20)
    monkeypatch.setattr(settings, "db_max_clients", 15)
    monkeypatch.setattr(settings, "db_client_headroom", 3)

    pool_size, overflow, warning = resolve_pool_limits()
    assert pool_size + overflow == 12
    assert warning and "EMAXCONNSESSION" not in warning
    assert "clamped" in warning


def test_pool_within_the_cap_is_left_alone(monkeypatch):
    monkeypatch.setattr(settings, "db_pool_size", 5)
    monkeypatch.setattr(settings, "db_max_overflow", 5)
    monkeypatch.setattr(settings, "db_max_clients", 15)
    monkeypatch.setattr(settings, "db_client_headroom", 3)

    assert resolve_pool_limits() == (5, 5, None)


def test_zero_max_clients_disables_the_clamp(monkeypatch):
    monkeypatch.setattr(settings, "db_pool_size", 40)
    monkeypatch.setattr(settings, "db_max_overflow", 40)
    monkeypatch.setattr(settings, "db_max_clients", 0)

    assert resolve_pool_limits() == (40, 40, None)


def test_pooled_engine_waits_rather_than_opening_a_refused_connection(monkeypatch):
    monkeypatch.setattr(settings, "db_pool_size", 5)
    monkeypatch.setattr(settings, "db_max_overflow", 5)
    kwargs = build_engine_kwargs(SESSION_POOLER)
    assert kwargs["pool_timeout"] == settings.db_pool_timeout
    assert kwargs["pool_recycle"] == settings.db_pool_recycle
    assert kwargs["pool_use_lifo"] is True
