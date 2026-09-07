"""Actual zero-row query contracts, shared by local SQLite and PostgreSQL CI."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
import student_profile
from agents import auto_tutor


def check_schema_hotpath(conn):
    # SQLite executes the exact zero-row SQL locally; the CI invocation uses
    # a real PostgreSQL connection without this branch adapter.
    class NonSQLiteBranch:
        dialect = SimpleNamespace(name="postgresql")

        def execute(self, *args, **kwargs):
            return conn.execute(*args, **kwargs)

    @contextmanager
    def borrowed():
        yield conn if conn.dialect.name == "postgresql" else NonSQLiteBranch()

    statements = []
    def count(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(conn, "before_cursor_execute", count)
    try:
        with patch.object(student_profile, "get_connection", borrowed), \
             patch.object(auto_tutor, "get_connection", borrowed):
            for check in (student_profile.init_db, auto_tutor._ensure_session_table):
                for _ in range(2):
                    statements.clear()
                    check()
                    assert len(statements) == 1, statements
                    assert statements[0].lstrip().upper().startswith("SELECT"), statements
                # No process-wide cache may hide live drift after a success.
                mutation = ("ALTER TABLE student_profiles RENAME COLUMN interaction_summary_json TO missing_summary"
                            if check is student_profile.init_db else
                            "ALTER TABLE autotutor_sessions RENAME COLUMN last_request_hash TO missing_hash")
                savepoint = conn.begin_nested()
                try:
                    conn.execute(text(mutation))
                    try:
                        check()
                        raise AssertionError("missing column accepted")
                    except DBAPIError:
                        pass
                finally:
                    savepoint.rollback()
                check()

            # A missing table is not silently recreated by the request path.
            savepoint = conn.begin_nested()
            try:
                conn.execute(text("ALTER TABLE memory_entries RENAME TO absent_memory_entries"))
                try:
                    student_profile.init_db()
                    raise AssertionError("missing table accepted")
                except DBAPIError:
                    pass
            finally:
                savepoint.rollback()
            student_profile.init_db()
    finally:
        event.remove(conn, "before_cursor_execute", count)
    print(f"autotutor_schema_hotpath_{conn.dialect.name}=PASS (profile=1 query, session=1 query, DDL=0)")
