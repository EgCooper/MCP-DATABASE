"""An independent, single-flight read-only probe with short driver timeouts."""

from dataclasses import replace
import threading

from mcp_mysql.config import MySQLConfig
from mcp_mysql.db import get_connection, _close_connection
from mcp_mysql.errors import classify_error

_lock = threading.Lock()


def probe() -> dict:
    # Keep ownership inside the worker even when its HTTP caller times out.
    if not _lock.acquire(blocking=False):
        return {"status": "not_ready", "code": "PROBE_BUSY"}
    conn = cursor = None
    error = None
    try:
        config = replace(MySQLConfig.from_env(), connection_timeout=2, read_timeout=2,
                         write_timeout=2, query_timeout_ms=1000)
        conn = get_connection(config)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        row = cursor.fetchone()
        return {"status": "ready"} if row and row[0] == 1 else {"status": "not_ready", "code": "PROBE_FAILED"}
    except Exception as exc:
        error = exc
        return {"status": "not_ready", "code": classify_error(exc).value}
    finally:
        try:
            if conn is not None:
                _close_connection(conn, cursor, rollback=True, original_error=error)
        finally:
            _lock.release()
