"""Bounded, process-local Prometheus metrics; no user data or dynamic labels."""

from collections import defaultdict
import threading

from mcp_mysql.errors import ErrorCode
from mcp_mysql.validation import TOOL_ARGUMENT_MODELS

_lock = threading.Lock()
_calls = defaultdict(int)
_seconds = defaultdict(float)
_truncated = defaultdict(int)
_unauthorized = 0
_ready = -1
_outcomes = {"ok", "INVALID_RESULT", *(code.value for code in ErrorCode)}


def record_call(operation: str, outcome: str, seconds: float, truncated: bool) -> None:
    name = operation if operation in TOOL_ARGUMENT_MODELS else "unknown"
    status = outcome if outcome in _outcomes else "INTERNAL_ERROR"
    with _lock:
        _calls[name, status] += 1
        _seconds[name] += max(0, seconds)
        _truncated[name] += int(bool(truncated))


def unauthorized() -> None:
    global _unauthorized
    with _lock:
        _unauthorized += 1


def readiness(ready: bool) -> None:
    global _ready
    with _lock:
        _ready = int(ready)


def render() -> bytes:
    with _lock:
        lines = ["# TYPE mcp_tool_calls_total counter"]
        for (name, status), count in sorted(_calls.items()):
            lines.append(f'mcp_tool_calls_total{{tool="{name}",outcome="{status}"}} {count}')
        lines.append("# TYPE mcp_tool_duration_seconds_total counter")
        for name, duration in sorted(_seconds.items()):
            lines.append(f'mcp_tool_duration_seconds_total{{tool="{name}"}} {duration:.6f}')
        lines.append("# TYPE mcp_tool_truncated_total counter")
        for name, count in sorted(_truncated.items()):
            lines.append(f'mcp_tool_truncated_total{{tool="{name}"}} {count}')
        lines.extend(["# TYPE mcp_http_unauthorized_total counter", f"mcp_http_unauthorized_total {_unauthorized}",
                      "# TYPE mcp_database_ready gauge", f"mcp_database_ready {_ready}"])
    return ("\n".join(lines) + "\n").encode()
