"""asyncpg rejects multi-statement SQL, so migrations split before executing."""

from app.db.session import build_connect_args
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
