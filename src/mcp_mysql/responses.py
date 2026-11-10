"""Bound JSON tool content and explicitly report any omitted content."""

from dataclasses import dataclass, field
import json
import logging
import math
from typing import Any
from uuid import uuid4

from mcp_mysql.errors import ErrorCode, classify_error, public_error
from mcp_mysql.validation import MAX_OFFSET, TOOL_ARGUMENT_MODELS

MAX_FIELD_CHARACTERS = 4000
MAX_RESPONSE_BYTES = 64 * 1024
MAX_TRUNCATION_DETAILS = 32
_LOGGER = logging.getLogger(__name__)


@dataclass
class _Changes:
    count: int = 0
    paths: list[str] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)

    def record(self, path: str) -> None:
        if path in self.seen:
            return
        self.seen.add(path)
        self.count += 1
        if len(self.paths) < MAX_TRUNCATION_DETAILS:
            self.paths.append(f"data.{path}")


@dataclass(frozen=True)
class Result:
    """Tool data plus row cells that were already shortened before formatting.

    ``clipped`` holds (row index, field) pairs, e.g. a message body read with a
    bounded LEFT() and then converted from HTML, so it may look short but is not complete.
    """
    data: dict
    clipped: tuple[tuple[int, str], ...] = ()


def _normalize(value: Any, path: str, changes: _Changes, row_field_limit: int) -> Any:
    # Only sample cells use the adaptive limit; identifiers in the envelope stay intact.
    limit = row_field_limit if path.startswith("rows[") else MAX_FIELD_CHARACTERS
    shortened_binary = False
    if isinstance(value, (bytes, bytearray, memoryview)):
        shortened_binary = len(value) > limit
        value = str(bytes(value[:limit + 1]))
    elif isinstance(value, float) and not math.isfinite(value):
        value = str(value)
    elif value is not None and not isinstance(value, (str, int, float, bool, list, tuple, dict)):
        value = str(value)

    if isinstance(value, str):
        if len(value) > limit or shortened_binary:
            changes.record(path)
            return value[:limit]
        return value
    if isinstance(value, dict):
        return {
            key: _normalize(item, f"{path}.{key}" if path else key, changes, row_field_limit)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _normalize(item, f"{path}[{index}]", changes, row_field_limit)
            for index, item in enumerate(value)
        ]
    return value


def _encode(payload: dict) -> str:
    # ASCII escaping makes the byte budget include control characters and Unicode escapes.
    return json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def _meta(request_id: str, is_sample: bool = False) -> dict:
    return {"request_id": request_id, "is_sample": is_sample, "truncated": False, "truncation": None}


def error_response(code: ErrorCode, *, operation: str = "unknown", request_id: str | None = None) -> str:
    """Only emit catalog messages and safe log fields, never driver text or input."""
    reference = request_id or uuid4().hex
    safe_operation = operation if operation in TOOL_ARGUMENT_MODELS else "unknown"
    _LOGGER.warning(
        "tool_failure request_id=%s operation=%s code=%s", reference, safe_operation, code.value
    )
    meta = _meta(reference)
    if code == ErrorCode.OUTPUT_LIMIT_EXCEEDED:
        meta["truncated"] = True
        meta["truncation"] = {"field_count": 0, "field_paths": [], "response_limited": True}
    return _encode({
        "ok": False, "data": None,
        "error": public_error(code),
        "meta": meta,
    })


def exception_response(exc: Exception, *, operation: str) -> str:
    return error_response(classify_error(exc), operation=operation)


def encode_response(payload: dict | Result, *, is_sample: bool = False) -> str:
    """Preserve a complete prefix of items and report field and response clipping.

    The byte limit covers the JSON content, before the MCP/HTTP envelope. Large
    first rows receive a smaller cell budget so at least one row can be returned.
    No serialized JSON document is sliced, so every returned response is valid JSON.
    """
    clipped: tuple[tuple[int, str], ...] = ()
    if isinstance(payload, Result):
        payload, clipped = payload.data, payload.clipped
    collection = next((key for key in ("rows", "columns", "tables", "groups") if isinstance(payload.get(key), list)), None)
    total = len(payload[collection]) if collection else 0
    reference = uuid4().hex

    def candidate(count: int, field_limit: int) -> str:
        content = dict(payload)
        if collection:
            content[collection] = payload[collection][:count]
            if collection == "rows":
                content["row_count"] = count
                if count < total and "has_more" in content:
                    content["has_more"] = True
                    if "next_offset" in content:
                        next_offset = content.get("offset", 0) + count
                        capped = next_offset > MAX_OFFSET
                        content["next_offset"] = None if capped else next_offset
                        content["pagination_limit_reached"] = capped
                    for cursor in ("next_after_entry_id", "next_before_entry_id"):
                        if cursor in content:
                            content[cursor] = content["rows"][-1]["entry_id"] if count else None
            elif collection == "tables":
                content["count"] = count
            elif collection == "groups":
                content["group_count"] = count
                if count < total and "has_more" in content:
                    content["has_more"] = True
                    if "next_offset" in content:
                        next_offset = content.get("offset", 0) + count
                        capped = next_offset > MAX_OFFSET
                        content["next_offset"] = None if capped else next_offset
                        content["pagination_limit_reached"] = capped
        changes = _Changes()
        content = _normalize(content, "", changes, field_limit)
        if collection == "rows":
            for index, name in clipped:
                # A cell clipped upstream and again by the cell budget is reported once.
                if index < count:
                    changes.record(f"rows[{index}].{name}")
        meta = _meta(reference, is_sample)
        omitted = total - count
        if changes.count or omitted:
            detail: dict = {"field_count": changes.count, "field_paths": changes.paths}
            if changes.count > len(changes.paths):
                detail["unlisted_field_count"] = changes.count - len(changes.paths)
            if omitted:
                detail[f"omitted_{collection}"] = omitted
            detail["response_limited"] = bool(omitted or field_limit < MAX_FIELD_CHARACTERS)
            meta["truncated"] = True
            meta["truncation"] = detail
        return _encode({"ok": True, "data": content, "error": None, "meta": meta})

    field_limit = MAX_FIELD_CHARACTERS
    full = candidate(total, field_limit)
    if len(full.encode("utf-8")) <= MAX_RESPONSE_BYTES:
        return full

    if collection and total:
        # If a single row is too large, shorten its cells further before omitting rows.
        first = candidate(1, field_limit)
        while len(first.encode("utf-8")) > MAX_RESPONSE_BYTES and collection == "rows" and field_limit > 1:
            field_limit = max(1, field_limit // 2)
            first = candidate(1, field_limit)
        if len(first.encode("utf-8")) <= MAX_RESPONSE_BYTES:
            full = candidate(total, field_limit)
            if len(full.encode("utf-8")) <= MAX_RESPONSE_BYTES:
                return full
            best = first
            low, high = 2, total
            while low <= high:
                middle = (low + high) // 2
                encoded = candidate(middle, field_limit)
                if len(encoded.encode("utf-8")) <= MAX_RESPONSE_BYTES:
                    best = encoded
                    low = middle + 1
                else:
                    high = middle - 1
            return best

    return error_response(ErrorCode.OUTPUT_LIMIT_EXCEEDED, request_id=reference)
