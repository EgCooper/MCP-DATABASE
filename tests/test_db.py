"""Read-only setup, bounded retrieval and cleanup without a real MySQL server."""

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from mysql.connector import MySQLConnection
from mysql.connector.constants import ClientFlag
from mysql.connector.cursor import MySQLCursorDict
from mysql.connector.errors import DatabaseError, InternalError, ReadTimeoutError, WriteTimeoutError

from mcp_mysql import db
from mcp_mysql.config import MySQLConfig


@pytest.fixture(autouse=True)
def connector(monkeypatch):
    config = MySQLConfig(
        host="example.invalid", port=3306, user="readonly",
        password="dummy;password${literal}'", database="test",
    )
    setup = Mock()
    cursor = Mock(spec=MySQLCursorDict)
    cursor.fetchmany.return_value = []
    connection = Mock(spec=MySQLConnection)
    connection.unread_result = False
    connection.cursor.side_effect = [setup, cursor]
    connect = Mock(return_value=connection)
    monkeypatch.setattr(db.mysql.connector, "connect", connect)
    monkeypatch.setattr(MySQLConfig, "from_env", Mock(return_value=config))
    yield SimpleNamespace(
        config=config, setup=setup, cursor=cursor, connection=connection, connect=connect,
    )
    connection.commit.assert_not_called()
    connection.consume_results.assert_not_called()
    connection.get_rows.assert_not_called()
    cursor.fetchall.assert_not_called()


def test_connection_is_protected_before_query_cursor_is_yielded(connector):
    with db.db_cursor() as cursor:
        connector.setup.execute.assert_has_calls([
            call("SET SESSION TRANSACTION READ ONLY"),
            call("SET SESSION MAX_EXECUTION_TIME = %s", (15000,)),
        ])
        connector.setup.close.assert_called_once()
        connector.connection.start_transaction.assert_called_once_with(readonly=True)
        assert cursor is connector.cursor
        cursor.execute("SELECT 1")
    connector.connection.cursor.assert_called_with(dictionary=True, buffered=False)
    connector.connection.rollback.assert_called_once()
    connector.cursor.close.assert_called_once()
    connector.connection.close.assert_called_once()


def test_connection_options_disable_unsafe_defaults_and_preserve_password(connector):
    conn = db.get_connection(connector.config)
    assert conn is connector.connection
    options = connector.connect.call_args.kwargs
    assert options["password"] == connector.config.password
    assert options["connection_timeout"] == 10
    assert options["read_timeout"] == options["write_timeout"] == 30
    assert options["autocommit"] is False
    assert options["buffered"] is False
    assert options["consume_results"] is False
    assert options["use_pure"] is True
    assert options["allow_local_infile"] is False
    assert -ClientFlag.MULTI_STATEMENTS in options["client_flags"]
    assert -ClientFlag.LOCAL_FILES in options["client_flags"]


@pytest.mark.parametrize("stage", ["cursor", "readonly", "timeout", "close", "transaction"])
def test_setup_failure_never_exposes_an_unprotected_connection(connector, stage):
    failure = DatabaseError("Setup unavailable")
    if stage == "cursor":
        connector.connection.cursor.side_effect = failure
    elif stage == "readonly":
        connector.setup.execute.side_effect = failure
    elif stage == "timeout":
        connector.setup.execute.side_effect = [None, failure]
    elif stage == "close":
        connector.setup.close.side_effect = failure
    else:
        connector.connection.start_transaction.side_effect = failure
    with pytest.raises(DatabaseError) as caught:
        with db.db_cursor():
            pytest.fail("An unprotected connection was exposed")
    assert caught.value is failure
    connector.cursor.execute.assert_not_called()
    connector.connection.close.assert_called_once()


def test_connection_error_is_propagated_without_trying_to_create_a_cursor(connector):
    failure = DatabaseError("Connection failed")
    connector.connect.side_effect = failure
    with pytest.raises(DatabaseError) as caught:
        db.fetch_all("SELECT 1")
    assert caught.value is failure
    connector.connection.cursor.assert_not_called()


def test_query_cursor_creation_failure_still_aborts_and_closes(connector):
    failure = DatabaseError("Cannot create cursor")
    connector.connection.cursor.side_effect = [connector.setup, failure]
    with pytest.raises(DatabaseError) as caught:
        db.fetch_all("SELECT 1")
    assert caught.value is failure
    connector.connection.rollback.assert_called_once()
    connector.connection.close.assert_called_once()


@pytest.mark.parametrize("stage", ["rollback", "cursor_close", "connection_close"])
def test_cleanup_attempts_other_steps_before_raising(connector, stage):
    failure = DatabaseError("Cleanup failed")
    if stage == "rollback":
        connector.connection.rollback.side_effect = failure
    elif stage == "cursor_close":
        connector.cursor.close.side_effect = failure
    else:
        connector.connection.close.side_effect = failure
    with pytest.raises(DatabaseError) as caught:
        db.fetch_all("SELECT 1")
    assert caught.value is failure
    connector.cursor.close.assert_called_once()
    connector.connection.close.assert_called_once()


def test_cleanup_errors_do_not_mask_query_failure_or_add_sensitive_details(connector):
    original = DatabaseError("Query failed")
    connector.cursor.execute.side_effect = original
    connector.connection.rollback.side_effect = RuntimeError("sensitive rollback details")
    connector.cursor.close.side_effect = RuntimeError("sensitive cursor details")
    connector.connection.close.side_effect = RuntimeError("sensitive connection details")
    with pytest.raises(DatabaseError) as caught:
        db.fetch_all("SELECT 1")
    assert caught.value is original
    assert "Database cleanup also failed" in original.__notes__[0]
    assert "sensitive" not in str(original.__notes__)
    connector.cursor.close.assert_called_once()
    connector.connection.close.assert_called_once()


@pytest.mark.parametrize("failure", [
    ReadTimeoutError("Read timeout"), WriteTimeoutError("Write timeout"),
    DatabaseError("Query execution timeout", errno=3024), KeyboardInterrupt(),
])
def test_query_errors_timeouts_and_interruptions_close_resources(connector, failure):
    connector.cursor.execute.side_effect = failure
    with pytest.raises(type(failure)) as caught:
        db.fetch_all("SELECT 1")
    assert caught.value is failure
    connector.connection.rollback.assert_called_once()
    connector.cursor.close.assert_called_once()
    connector.connection.close.assert_called_once()


def test_read_failure_aborts_pending_results_without_draining_them(connector):
    failure = ReadTimeoutError("Fetch timed out")

    def fail_fetch(size):
        connector.connection.unread_result = True
        raise failure

    connector.cursor.fetchmany.side_effect = fail_fetch
    connector.cursor.close.side_effect = InternalError("Unread result found")
    with pytest.raises(ReadTimeoutError) as caught:
        db.fetch_all("SELECT 1")
    assert caught.value is failure
    connector.connection.rollback.assert_not_called()
    connector.cursor.close.assert_called_once()
    connector.connection.close.assert_called_once()


def test_context_rejects_unconsumed_results_and_disconnects(connector):
    with pytest.raises(RuntimeError, match="fully consumed"):
        with db.db_cursor():
            connector.connection.unread_result = True
    connector.connection.rollback.assert_not_called()
    connector.cursor.close.assert_called_once()
    connector.connection.close.assert_called_once()


def test_fetch_all_uses_a_bounded_read_and_preserves_parameters(connector):
    connector.cursor.fetchmany.return_value = [{"id": 1}, {"id": 2}]
    parameters = {"name": "a;b'${literal}"}
    assert db.fetch_all("SELECT id WHERE name = %(name)s", parameters, max_rows=2) == [
        {"id": 1}, {"id": 2},
    ]
    connector.cursor.execute.assert_called_once_with("SELECT id WHERE name = %(name)s", parameters)
    connector.cursor.fetchmany.assert_called_once_with(3)


def test_result_overflow_raises_without_draining_or_returning_partial_rows(connector):
    def overflow(size):
        connector.connection.unread_result = True
        return [{"id": n} for n in range(size)]

    connector.cursor.fetchmany.side_effect = overflow
    connector.cursor.close.side_effect = InternalError("Unread result found")
    with pytest.raises(db.ResultLimitError, match="maximum of 1000"):
        db.fetch_all("SELECT id")
    connector.cursor.fetchmany.assert_called_once_with(1001)
    connector.connection.rollback.assert_not_called()
    connector.connection.close.assert_called_once()


@pytest.mark.parametrize("rows, expected", [([], None), ([{"ok": 1}], {"ok": 1})])
def test_fetch_one_returns_only_zero_or_one_row(connector, rows, expected):
    connector.cursor.fetchmany.return_value = rows
    assert db.fetch_one("SELECT 1") == expected
    connector.cursor.fetchmany.assert_called_once_with(2)


def test_fetch_one_rejects_multiple_rows(connector):
    connector.cursor.fetchmany.return_value = [{"id": 1}, {"id": 2}]
    with pytest.raises(db.ResultLimitError, match="maximum of 1 rows"):
        db.fetch_one("SELECT id")


@pytest.mark.parametrize("limit", [0, -1, 1001, True, 2.5, "5", None])
def test_invalid_internal_limits_fail_before_connecting(connector, limit):
    with pytest.raises(ValueError, match="max_rows"):
        db.fetch_all("SELECT 1", max_rows=limit)
    connector.connect.assert_not_called()
