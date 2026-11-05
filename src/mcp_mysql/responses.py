"""Bound JSON tool content and explicitly report any omitted content."""

from dataclasses import dataclass, field
import json
import math
from typing import Any

MAX_FIELD_CHARACTERS = 4000
MAX_RESPONSE_BYTES = 64 * 1024
MAX_TRUNCATION_DETAILS = 32


@dataclass
class _Changes:
    count: int = 0
    paths: list[str] = field(default_factory=list)

    def record(self, path: str) -> None:
        self.count += 1
        if len(self.paths) < MAX_TRUNCATION_DETAILS:
            self.paths.append(path)


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


def encode_response(payload: dict) -> str:
    """Preserve a complete prefix of items and report field and response clipping.

    The byte limit covers the JSON content, before the MCP/HTTP envelope. Large
    first rows receive a smaller cell budget so at least one row can be returned.
    No serialized JSON document is sliced, so every returned response is valid JSON.
    """
    collection = next((key for key in ("rows", "columns", "tables") if isinstance(payload.get(key), list)), None)
    total = len(payload[collection]) if collection else 0

    def candidate(count: int, field_limit: int) -> str:
        content = dict(payload)
        if collection:
            content[collection] = payload[collection][:count]
            if collection == "rows":
                content["row_count"] = count
            elif collection == "tables":
                content["count"] = count
        changes = _Changes()
        content = _normalize(content, "", changes, field_limit)
        omitted = total - count
        if changes.count or omitted:
            detail: dict = {"field_count": changes.count, "field_paths": changes.paths}
            if changes.count > len(changes.paths):
                detail["unlisted_field_count"] = changes.count - len(changes.paths)
            if omitted:
                detail[f"omitted_{collection}"] = omitted
            detail["response_limited"] = bool(omitted or field_limit < MAX_FIELD_CHARACTERS)
            content["truncated"] = True
            content["truncation"] = detail
        return _encode(content)

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

    return _encode({"error": "Response exceeds output limits.", "truncated": True})
