"""Read ticket conversations with bounded rows and entry-ID continuation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_mysql import db
from mcp_mysql.errors import RecordNotFoundError
from mcp_mysql.responses import MAX_FIELD_CHARACTERS, Result
from mcp_mysql.text import body_to_text
from mcp_mysql.validation import ThreadArguments

if TYPE_CHECKING:
    from mcp_mysql.tickets import Schema

TEXT_LIMIT = MAX_FIELD_CHARACTERS + 1
BODY_FETCH_LIMIT = 65536
ENTRY_TYPES = {"M": "message", "R": "response", "N": "internal_note"}
ENTRY_CODES = {name: code for code, name in ENTRY_TYPES.items()}

_THREAD_TEXT = ("poster", "title")
_THREAD_PLAIN = ("staff_id", "user_id", "created", "updated")


def read_thread(arguments: ThreadArguments, schema: Schema) -> Result:
    schema.require("ost_ticket", "ticket_id")
    schema.require("ost_thread", "id", "object_id", "object_type")
    schema.require("ost_thread_entry", "id", "thread_id", "type")
    counts = db.fetch_one(
        """SELECT t.ticket_id, COUNT(e.id) AS total,
                  SUM(e.type = 'M') AS messages, SUM(e.type = 'R') AS responses, SUM(e.type = 'N') AS notes
           FROM ost_ticket t
           LEFT JOIN ost_thread th ON th.object_type = 'T' AND th.object_id = t.ticket_id
           LEFT JOIN ost_thread_entry e ON e.thread_id = th.id
           WHERE t.ticket_id = %s GROUP BY t.ticket_id""",
        (arguments.ticket_id,),
    )
    if counts is None:
        raise RecordNotFoundError("Ticket not found")

    expressions = ["e.id AS entry_id", "e.thread_id", "e.type AS type_code"]
    parameters, unavailable = [], []
    for column in (*_THREAD_TEXT, *_THREAD_PLAIN):
        if not schema.has("ost_thread_entry", column):
            expressions.append(f"NULL AS `{column}`")
            unavailable.append(column)
        elif column in _THREAD_PLAIN:
            expressions.append(f"e.`{column}`")
        else:
            expressions.append(f"LEFT(e.`{column}`, %s) AS `{column}`")
            parameters.append(TEXT_LIMIT)
    if schema.has("ost_thread_entry", "body"):
        expressions.append("LEFT(e.`body`, %s) AS body")
        parameters.append(BODY_FETCH_LIMIT)
    else:
        expressions.append("NULL AS body")
        unavailable.append("body")
    expressions.append("e.`format` AS body_format" if schema.has("ost_thread_entry", "format") else "NULL AS body_format")

    conditions = ["th.object_type = 'T'", "th.object_id = %s"]
    values: list = [arguments.ticket_id]
    if arguments.order == "oldest":
        conditions.append("e.id > %s")
        values.append(arguments.after_entry_id)
        order = "ASC"
    else:
        if arguments.before_entry_id:
            conditions.append("e.id < %s")
            values.append(arguments.before_entry_id)
        order = "DESC"
    if arguments.entry_types:
        codes = sorted({ENTRY_CODES[name] for name in arguments.entry_types})
        conditions.append(f"e.type IN ({', '.join('%s' for _ in codes)})")
        values.extend(codes)
    rows = db.fetch_all(
        f"""SELECT {', '.join(expressions)} FROM ost_thread_entry e
            JOIN ost_thread th ON th.id = e.thread_id
            WHERE {' AND '.join(conditions)}
            ORDER BY e.id {order} LIMIT %s""",
        (*parameters, *values, arguments.limit + 1),
    )
    returned, more = rows[:arguments.limit], len(rows) > arguments.limit
    entries, clipped = [], []
    for index, row in enumerate(returned):
        raw = row.get("body")
        if isinstance(raw, str) and len(raw) >= BODY_FETCH_LIMIT:
            clipped.append((index, "body"))
        entry = {
            "entry_id": row.get("entry_id"), "thread_id": row.get("thread_id"),
            "entry_type": ENTRY_TYPES.get(row.get("type_code"), "other"),
            "poster": row.get("poster"), "staff_id": row.get("staff_id"), "user_id": row.get("user_id"),
            "title": row.get("title"),
            "body": body_to_text(raw, row.get("body_format")) if isinstance(raw, str) else raw,
            "created": row.get("created"), "updated": row.get("updated"),
        }
        entries.append(entry)
    cursor = "next_after_entry_id" if arguments.order == "oldest" else "next_before_entry_id"
    data = {
        "ticket_id": arguments.ticket_id, "order": f"{arguments.order}_first",
        "rows": entries, "row_count": len(entries), "has_more": more,
        cursor: entries[-1]["entry_id"] if more and entries else None,
        "entry_counts": {
            "total": int(counts.get("total") or 0), "messages": int(counts.get("messages") or 0),
            "responses": int(counts.get("responses") or 0), "internal_notes": int(counts.get("notes") or 0),
        },
        "unavailable_fields": unavailable,
    }
    return Result(data, tuple(clipped))


