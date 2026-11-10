"""Schema-aware, parameterized osTicket queries. No caller-supplied SQL fragments.

Every identifier interpolated into SQL comes from constants in this module and is
checked against the access policy and the installed schema. Every value is bound
as a parameter. The connector only substitutes ``%s``; it does not unescape
``%%``, so LIKE wildcards and DATE_FORMAT patterns are always parameters too.
"""

from dataclasses import dataclass
from datetime import date, timedelta
import json
import threading
import time

from mcp_mysql import db
from mcp_mysql.access import all_query_tables, get_query_columns
from mcp_mysql.config import MySQLConfig, schema_cache_seconds
from mcp_mysql.errors import AccessDeniedError, AmbiguousRecordError, RecordNotFoundError, SchemaUnavailableError
from mcp_mysql.responses import MAX_FIELD_CHARACTERS, Result
from mcp_mysql.text import body_to_text
from mcp_mysql.validation import (
    MAX_OFFSET, AgentReportArguments, CatalogArguments, CompanySearchArguments, CompanyTicketsArguments,
    PeopleArguments, SearchTicketsArguments, ThreadArguments, TicketArguments, TicketFilters,
    TicketReportArguments, UserArguments, UserSearchArguments,
)

TEXT_LIMIT = MAX_FIELD_CHARACTERS + 1
# Message bodies are fetched larger than the output limit because HTML markup
# shrinks once converted to text. Anything longer is reported as clipped.
BODY_FETCH_LIMIT = 65536
MAX_COLLABORATORS = 50
SUPPORT_FIELDS = ("apoyo1", "apoyo2", "apoyo3")
# h:mm or h:mm:ss with up to three hour digits, as recorded in the "Tiempo (HH:MM)" fields.
DURATION_PATTERN = r"^ *[0-9]{1,3}:[0-5][0-9](:[0-5][0-9])? *$"
ENTRY_TYPES = {"M": "message", "R": "response", "N": "internal_note"}
ENTRY_CODES = {name: code for code, name in ENTRY_TYPES.items()}
_COMPANY_KEY = "TRIM(SUBSTRING_INDEX(c.listaEmpresa, ',', 1))"


def escape_like(text: str) -> str:
    """Treat LIKE metacharacters as literal input, using a SQL-mode-independent escape."""
    return text.replace("=", "==").replace("%", "=%").replace("_", "=_")


def literal_pattern(text: str) -> str:
    return f"%{escape_like(text)}%"


# Schema discovery -----------------------------------------------------------------

@dataclass
class Schema:
    columns: dict[str, set[str]]

    def has(self, table: str, column: str) -> bool:
        try:
            permitted = get_query_columns(table)
        except AccessDeniedError:
            return False
        return column in permitted and column.casefold() in self.columns.get(table, set())

    def require(self, table: str, *columns: str) -> None:
        if not set(columns).issubset(get_query_columns(table)):
            raise AccessDeniedError("Query outside access policy")
        if not all(self.has(table, column) for column in columns):
            raise SchemaUnavailableError("Missing required fields")


_schema_lock = threading.Lock()
_schema_cache: dict[tuple, tuple[float, Schema]] = {}


def clear_schema_cache() -> None:
    with _schema_lock:
        _schema_cache.clear()


def _read_schema() -> Schema:
    tables, columns = [], set()
    for table in sorted(all_query_tables()):
        try:
            permitted = get_query_columns(table)
        except AccessDeniedError:
            continue
        tables.append(table)
        columns.update(permitted)
    if not tables or not columns:
        raise AccessDeniedError("No permitted query fields")
    placeholders = ", ".join("%s" for _ in tables)
    column_placeholders = ", ".join("%s" for _ in columns)
    rows = db.fetch_all(
        f"""SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ({placeholders})
              AND COLUMN_NAME IN ({column_placeholders})""",
        (*tables, *sorted(columns)),
    )
    found: dict[str, set[str]] = {}
    for row in rows:
        if row.get("table_name") in tables and isinstance(row.get("column_name"), str):
            found.setdefault(row["table_name"], set()).add(row["column_name"].casefold())
    return Schema(found)


def _load_schema() -> Schema:
    """Return the installed schema, re-read at most every MCP_SCHEMA_CACHE_SECONDS.

    The policy is still checked on every use, so a cached schema never widens access.
    """
    config = MySQLConfig.from_env()
    key = (config.host, config.port, config.database)
    now = time.monotonic()
    with _schema_lock:
        cached = _schema_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]
    schema = _read_schema()
    with _schema_lock:
        _schema_cache[key] = (now + schema_cache_seconds(), schema)
    return schema


# Shared helpers -------------------------------------------------------------------

def page_rows(rows: list[dict], limit: int, offset: int = 0) -> dict:
    returned = rows[:limit]
    more = len(rows) > limit
    next_offset = offset + len(returned)
    capped = more and next_offset > MAX_OFFSET
    return {"rows": returned, "row_count": len(returned), "limit": limit,
            "offset": offset, "has_more": more, "pagination_limit_reached": capped,
            "next_offset": next_offset if more and not capped else None}


def _next_day(value: str) -> str:
    return (date.fromisoformat(value) + timedelta(days=1)).isoformat()


def _duration(seconds) -> dict:
    total = int(seconds or 0)
    return {"hhmm": f"{total // 3600}:{total % 3600 // 60:02d}", "hours": round(total / 3600, 2)}


def _seconds_sql(column: str) -> tuple[str, list]:
    """Seconds of an h:mm text duration; anything else counts as zero."""
    return f"CASE WHEN {column} REGEXP %s THEN TIME_TO_SEC(TRIM({column})) ELSE 0 END", [DURATION_PATTERN]


def _unparsed_sql(column: str) -> tuple[str, list]:
    return (f"CASE WHEN {column} IS NOT NULL AND TRIM({column}) <> '' AND NOT ({column} REGEXP %s) "
            f"THEN 1 ELSE 0 END"), [DURATION_PATTERN]


def _filters_dump(arguments: TicketFilters) -> dict:
    return arguments.model_dump(exclude_defaults=True, include=set(TicketFilters.model_fields))


def _company_list_id() -> int:
    return MySQLConfig.from_env().company_list_id


# Ticket query builder ---------------------------------------------------------------

_ALIAS_TABLES = {
    "t": "ost_ticket", "c": "ost_ticket__cdata", "s": "ost_ticket_status", "d": "ost_department",
    "u": "ost_user", "a": "ost_staff", "h": "ost_help_topic", "tm": "ost_team", "sl": "ost_sla",
    "p": "ost_ticket_priority", "ue": "ost_user_email", "li": "ost_list_items",
    "rt": "ost_list_items", "ca": "ost_list_items",
}
# alias, ON clause, columns the clause needs, parent alias. Order respects dependencies.
_JOINS = (
    ("c", "c.`ticket_id` = t.`ticket_id`", (("t", "ticket_id"), ("c", "ticket_id")), None),
    ("s", "s.`id` = t.`status_id`", (("t", "status_id"), ("s", "id")), None),
    ("d", "d.`id` = t.`dept_id`", (("t", "dept_id"), ("d", "id")), None),
    ("u", "u.`id` = t.`user_id`", (("t", "user_id"), ("u", "id")), None),
    ("a", "a.`staff_id` = t.`staff_id`", (("t", "staff_id"), ("a", "staff_id")), None),
    ("h", "h.`topic_id` = t.`topic_id`", (("t", "topic_id"), ("h", "topic_id")), None),
    ("tm", "tm.`team_id` = t.`team_id`", (("t", "team_id"), ("tm", "team_id")), None),
    ("sl", "sl.`id` = t.`sla_id`", (("t", "sla_id"), ("sl", "id")), None),
    ("p", "p.`priority_id` = c.`priority`", (("c", "priority"), ("p", "priority_id")), "c"),
    ("ue", "ue.`id` = u.`default_email_id`", (("u", "default_email_id"), ("ue", "id")), "u"),
    # List item IDs are unique across lists; the company join also pins the configured list.
    ("li", f"li.`list_id` = %s AND li.`id` = {_COMPANY_KEY}",
     (("c", "listaEmpresa"), ("li", "id"), ("li", "list_id")), "c"),
    ("rt", "rt.`id` = TRIM(SUBSTRING_INDEX(c.`tipoSolicitud`, ',', 1))", (("c", "tipoSolicitud"), ("rt", "id")), "c"),
    ("ca", "ca.`id` = TRIM(SUBSTRING_INDEX(c.`causa`, ',', 1))", (("c", "causa"), ("ca", "id")), "c"),
)

# output name, alias, column, is text
_SUMMARY_FIELDS = (
    ("ticket_id", "t", "ticket_id", False), ("number", "t", "number", True),
    ("created", "t", "created", False), ("lastupdate", "t", "lastupdate", False),
    ("closed", "t", "closed", False), ("status", "s", "name", True),
    ("status_state", "s", "state", True), ("is_overdue", "t", "isoverdue", False),
    ("department", "d", "name", True), ("priority", "p", "priority_desc", True),
    ("staff_id", "t", "staff_id", False), ("user_id", "t", "user_id", False),
    ("customer", "u", "name", True), ("company_id", "li", "id", False),
    ("company", "li", "value", True), ("subject", "c", "subject", True),
)
_DETAIL_FIELDS = _SUMMARY_FIELDS + (
    ("ticket_pid", "t", "ticket_pid", False), ("source", "t", "source", True),
    ("is_answered", "t", "isanswered", False), ("due_date", "t", "duedate", False),
    ("estimated_due_date", "t", "est_duedate", False), ("reopened", "t", "reopened", False),
    ("updated", "t", "updated", False), ("help_topic", "h", "topic", True),
    ("team", "tm", "name", True), ("sla", "sl", "name", True),
    ("customer_email", "ue", "address", True), ("request_type", "rt", "value", True),
    ("cause", "ca", "value", True), ("environment", "c", "ambiente", True),
    ("support_expiration", "c", "vencimientoSoporte", True),
    ("start_date", "c", "fechaInicio", True), ("end_date", "c", "fechaFin", True),
    ("analysis", "c", "analisis", True), ("solution", "c", "solucion", True),
    ("recorded_time", "c", "time", True), ("overtime", "c", "timeExtra", True),
    ("overtime_flag", "c", "horaExtra", True), ("compensated_time", "c", "horaCompensada", True),
)
# Raw support-staff cells, folded into support_staff and never returned as-is.
_SUPPORT_CELLS = tuple(
    (f"_{column}", "c", column, True)
    for slot in (1, 2, 3) for column in (f"apoyo{slot}", f"timeApoyo{slot}")
)


class TicketQuery:
    def __init__(self, schema: Schema, company_list_id: int):
        self.schema = schema
        schema.require("ost_ticket", "ticket_id")
        self.tables = {"t": "ost_ticket"}
        self.joins: dict[str, tuple[str, tuple]] = {}
        self.parents: dict[str, str | None] = {}
        for alias, condition, needs, parent in _JOINS:
            table = _ALIAS_TABLES[alias]
            if all(schema.has(table, column) if owner == alias else self.has(owner, column)
                   for owner, column in needs):
                parameters = (company_list_id,) if "%s" in condition else ()
                self.tables[alias] = table
                self.joins[alias] = (f"LEFT JOIN `{table}` {alias} ON {condition}", parameters)
                self.parents[alias] = parent

    def has(self, alias: str, column: str) -> bool:
        return alias in self.tables and self.schema.has(self.tables[alias], column)

    def require(self, alias: str, column: str) -> None:
        self.schema.require(_ALIAS_TABLES[alias], column)
        if alias not in self.tables:
            raise SchemaUnavailableError("Missing required relationship")

    def source(self, aliases: set[str] | None = None) -> tuple[str, tuple]:
        wanted = set(self.joins) if aliases is None else set()
        for alias in aliases or ():
            while alias and alias != "t":
                wanted.add(alias)
                alias = self.parents.get(alias)
        clauses, parameters = ["FROM ost_ticket t"], []
        for alias, (clause, values) in self.joins.items():
            if alias in wanted:
                clauses.append(clause)
                parameters.extend(values)
        return " ".join(clauses), tuple(parameters)

    def company(self, identifier: int) -> dict:
        self.schema.require("ost_list_items", "id", "list_id", "value")
        row = db.fetch_one(
            "SELECT id AS company_id, LEFT(value, %s) AS name FROM ost_list_items WHERE list_id = %s AND id = %s",
            (TEXT_LIMIT, _company_list_id(), identifier),
        )
        if row is None:
            raise RecordNotFoundError("Company not found")
        return row

    def where(self, filters: TicketFilters) -> tuple[str, tuple, dict | None, set[str]]:
        """Build the WHERE clause; a filter whose field is unavailable is an error, never ignored."""
        clauses, parameters, needed = [], [], set()
        company = None

        def add(clause: str, *values, alias: str = "t", column: str | None = None) -> None:
            if column is not None:
                self.require(alias, column)
            if alias != "t":
                needed.add(alias)
            clauses.append(clause)
            parameters.extend(values)

        if filters.company_id is not None:
            self.require("c", "listaEmpresa")
            company = self.company(filters.company_id)
            add(f"{_COMPANY_KEY} = %s", str(filters.company_id), alias="c")
        if filters.staff_id is not None:
            add("t.`staff_id` = %s", filters.staff_id, column="staff_id")
        if filters.assigned is not None:
            add("t.`staff_id` > 0" if filters.assigned else "COALESCE(t.`staff_id`, 0) = 0", column="staff_id")
        if filters.user_id is not None:
            self.require("t", "user_id")
            if filters.include_collaborations:
                self.schema.require("ost_thread", "id", "object_id", "object_type")
                self.schema.require("ost_thread_collaborator", "thread_id", "user_id")
                add("(t.`user_id` = %s OR EXISTS (SELECT 1 FROM ost_thread th "
                    "JOIN ost_thread_collaborator tc ON tc.thread_id = th.id "
                    "WHERE th.object_type = 'T' AND th.object_id = t.ticket_id AND tc.user_id = %s))",
                    filters.user_id, filters.user_id)
            else:
                add("t.`user_id` = %s", filters.user_id)
        if filters.status is not None:
            add("s.name = %s", filters.status, alias="s", column="name")
        if filters.state is not None:
            add("s.state = %s", filters.state, alias="s", column="state")
        if filters.dept_id is not None:
            add("t.`dept_id` = %s", filters.dept_id, column="dept_id")
        if filters.priority_id is not None:
            add("c.`priority` = %s", str(filters.priority_id), alias="c", column="priority")
        if filters.topic_id is not None:
            add("t.`topic_id` = %s", filters.topic_id, column="topic_id")
        if filters.overdue is not None:
            add("t.`isoverdue` = %s", int(filters.overdue), column="isoverdue")
        if filters.subject is not None:
            add("c.subject LIKE %s ESCAPE '='", literal_pattern(filters.subject), alias="c", column="subject")
        if filters.created_from:
            add("t.created >= %s", filters.created_from, column="created")
        if filters.created_to:
            add("t.created < %s", _next_day(filters.created_to), column="created")
        if filters.closed_from:
            add("t.closed >= %s", filters.closed_from, column="closed")
        if filters.closed_to:
            add("t.closed < %s", _next_day(filters.closed_to), column="closed")
        return ("WHERE " + " AND ".join(clauses) if clauses else ""), tuple(parameters), company, needed

    def projection(self, fields=_SUMMARY_FIELDS) -> tuple[str, tuple, list[str], set[str]]:
        expressions, parameters, unavailable, used = [], [], [], set()
        for output, alias, column, text in fields:
            if not self.has(alias, column):
                expressions.append(f"NULL AS `{output}`")
                if not output.startswith("_"):
                    unavailable.append(output)
                continue
            used.add(alias)
            if text:
                expressions.append(f"LEFT({alias}.`{column}`, %s) AS `{output}`")
                parameters.append(TEXT_LIMIT)
            else:
                expressions.append(f"{alias}.`{column}` AS `{output}`")
        if self.has("a", "firstname") and self.has("a", "lastname"):
            used.add("a")
            expressions.append("LEFT(CONCAT_WS(' ', a.firstname, a.lastname), %s) AS assigned_agent")
            parameters.append(TEXT_LIMIT)
        else:
            expressions.append("NULL AS assigned_agent")
            unavailable.append("assigned_agent")
        return ", ".join(expressions), tuple(parameters), unavailable, used


def _ticket_query() -> TicketQuery:
    return TicketQuery(_load_schema(), _company_list_id())


_ORDERS = {
    "newest": ("t.created DESC, t.ticket_id DESC", "newest_first"),
    "oldest": ("t.created ASC, t.ticket_id ASC", "oldest_first"),
    "last_updated": ("t.lastupdate DESC, t.ticket_id DESC", "last_updated_first"),
}


def search(arguments: SearchTicketsArguments) -> dict:
    query = _ticket_query()
    query.require("t", "created")
    if arguments.order == "last_updated":
        query.require("t", "lastupdate")
    where, parameters, company, needed = query.where(arguments)
    projection, projection_parameters, unavailable, used = query.projection()
    source, source_parameters = query.source(used | needed)
    # The order is selected from constants; it is never interpolated from arbitrary input.
    order, label = _ORDERS[arguments.order]
    rows = db.fetch_all(
        f"SELECT {projection} {source} {where} ORDER BY {order} LIMIT %s OFFSET %s",
        (*projection_parameters, *source_parameters, *parameters, arguments.limit + 1, arguments.offset),
    )
    data = page_rows(rows, arguments.limit, arguments.offset)
    data.update(order=label, unavailable_fields=unavailable)
    if company is not None:
        data["company"] = company
    return data


def company_tickets(arguments: CompanyTicketsArguments) -> dict:
    return search(arguments)


def count(arguments: TicketFilters) -> dict:
    query = _ticket_query()
    where, parameters, company, needed = query.where(arguments)
    source, source_parameters = query.source(needed)
    row = db.fetch_one(f"SELECT COUNT(*) AS total {source} {where}", (*source_parameters, *parameters))
    if row is None:
        raise SchemaUnavailableError("Missing count result")
    result = {"total": int(row["total"]), "filters": _filters_dump(arguments)}
    if company is not None:
        result["company"] = company
    return result


# group key, label (None: same as key), aliases, required (alias, column) pairs
_GROUPS = {
    "status": ("t.`status_id`", "s.`name`", {"s"}, (("t", "status_id"), ("s", "name"))),
    "state": ("s.`state`", None, {"s"}, (("s", "state"),)),
    "department": ("t.`dept_id`", "d.`name`", {"d"}, (("t", "dept_id"), ("d", "name"))),
    "agent": ("t.`staff_id`", "CONCAT_WS(' ', a.`firstname`, a.`lastname`)", {"a"},
              (("t", "staff_id"), ("a", "firstname"), ("a", "lastname"))),
    "company": ("li.`id`", "li.`value`", {"li"}, (("li", "id"), ("li", "value"))),
    "priority": ("p.`priority_id`", "p.`priority_desc`", {"p"}, (("p", "priority_id"), ("p", "priority_desc"))),
    "help_topic": ("t.`topic_id`", "h.`topic`", {"h"}, (("t", "topic_id"), ("h", "topic"))),
    "request_type": ("rt.`id`", "rt.`value`", {"rt"}, (("rt", "id"), ("rt", "value"))),
    "source": ("t.`source`", None, set(), (("t", "source"),)),
    "user": ("t.`user_id`", "u.`name`", {"u"}, (("t", "user_id"), ("u", "name"))),
    "month": ("DATE_FORMAT(t.`created`, %s)", None, set(), (("t", "created"),)),
}


def _time_columns(query: TicketQuery) -> tuple[list[str], list]:
    query.require("c", "time")
    expressions, parameters = [], []
    for output, column in (("time_seconds", "c.`time`"), ("overtime_seconds", "c.`timeExtra`")):
        if output == "overtime_seconds" and not query.has("c", "timeExtra"):
            expressions.append("0 AS overtime_seconds")
            continue
        sql, values = _seconds_sql(column)
        expressions.append(f"SUM({sql}) AS {output}")
        parameters.extend(values)
    sql, values = _unparsed_sql("c.`time`")
    expressions.append(f"SUM({sql}) AS time_unparsed")
    parameters.extend(values)
    return expressions, parameters


def _time_totals(row: dict) -> dict:
    return {
        "recorded_time": _duration(row.get("time_seconds")),
        "overtime": _duration(row.get("overtime_seconds")),
        "unparsed_time_values": int(row.get("time_unparsed") or 0),
    }


def report(arguments: TicketReportArguments) -> dict:
    query = _ticket_query()
    key, label, aliases, required = _GROUPS[arguments.group_by]
    for alias, column in required:
        query.require(alias, column)
    where, parameters, company, needed = query.where(arguments)
    select_parameters: list = ["%Y-%m"] if arguments.group_by == "month" else []
    columns = [f"{key} AS group_key", f"MAX({label}) AS label" if label else "NULL AS label", "COUNT(*) AS tickets"]
    used = set(aliases) | needed
    if arguments.include_time:
        expressions, values = _time_columns(query)
        columns.extend(expressions)
        select_parameters.extend(values)
        used.add("c")
    source, source_parameters = query.source(used)
    # Months read chronologically; every other dimension is ranked by volume.
    order = "group_key ASC" if arguments.group_by == "month" else "tickets DESC, group_key ASC"
    rows = db.fetch_all(
        f"SELECT {', '.join(columns)} {source} {where} GROUP BY group_key ORDER BY {order} LIMIT %s OFFSET %s",
        (*select_parameters, *source_parameters, *parameters, arguments.limit + 1, arguments.offset),
    )
    count_source, count_parameters = query.source(needed)
    total = db.fetch_one(f"SELECT COUNT(*) AS total {count_source} {where}", (*count_parameters, *parameters))
    groups = []
    for row in rows[:arguments.limit]:
        group = {"key": row.get("group_key"),
                 "label": row.get("label") if label else row.get("group_key"),
                 "tickets": int(row.get("tickets") or 0)}
        if arguments.include_time:
            group.update(_time_totals(row))
        groups.append(group)
    page = page_rows(rows, arguments.limit, arguments.offset)
    data = {
        "group_by": arguments.group_by, "groups": groups, "group_count": len(groups),
        **{key: value for key, value in page.items() if key not in ("rows", "row_count")},
        "total_tickets": int(total["total"]) if total else None,
        "filters": _filters_dump(arguments),
    }
    if company is not None:
        data["company"] = company
    return data


# Ticket detail ----------------------------------------------------------------------

def _parse_assignee(value) -> dict | None:
    """osTicket assignee answers look like {"s12": "Name"} (staff) or {"t3": "Name"} (team)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and len(parsed) == 1:
            ((key, name),) = parsed.items()
            entry = {"staff_id": None, "team_id": None, "name": name if isinstance(name, str) else None}
            if isinstance(key, str) and key[1:].isdigit():
                if key[0] == "s":
                    entry["staff_id"] = int(key[1:])
                elif key[0] == "t":
                    entry["team_id"] = int(key[1:])
            return entry
    return {"staff_id": None, "team_id": None, "name": text}


def _support_staff(schema: Schema, ticket_id: int, row: dict) -> list[dict]:
    """Support people (apoyo1..3) with their recorded time.

    The form answers hold the staff ID; the cached ticket data often keeps only a name.
    """
    answers: dict[str, str] = {}
    if (schema.has("ost_form_entry", "object_id") and schema.has("ost_form_entry", "object_type")
            and schema.has("ost_form_entry_values", "value") and schema.has("ost_form_field", "name")):
        placeholders = ", ".join("%s" for _ in SUPPORT_FIELDS)
        for answer in db.fetch_all(
            f"""SELECT f.name AS field, LEFT(v.value, %s) AS value
                FROM ost_form_entry e
                JOIN ost_form_entry_values v ON v.entry_id = e.id
                JOIN ost_form_field f ON f.id = v.field_id
                WHERE e.object_type = 'T' AND e.object_id = %s AND f.name IN ({placeholders})
                  AND v.value IS NOT NULL AND v.value <> ''
                ORDER BY e.id""",
            (TEXT_LIMIT, ticket_id, *SUPPORT_FIELDS), max_rows=30,
        ):
            answers.setdefault(answer.get("field"), answer.get("value"))
    people = []
    for slot, field in enumerate(SUPPORT_FIELDS, start=1):
        person = _parse_assignee(answers.get(field)) or _parse_assignee(row.get(f"_{field}"))
        if person is not None:
            person["slot"] = slot
            person["recorded_time"] = row.get(f"_timeApoyo{slot}")
            people.append(person)
    return people


def _collaborators(schema: Schema, ticket_id: int) -> tuple[list[dict], bool]:
    if not (schema.has("ost_thread", "object_id") and schema.has("ost_thread", "object_type")
            and schema.has("ost_thread_collaborator", "thread_id") and schema.has("ost_thread_collaborator", "user_id")):
        return [], False
    name = "LEFT(u.name, %s)" if schema.has("ost_user", "name") and schema.has("ost_user", "id") else "NULL"
    email = ("LEFT(ue.address, %s)" if name != "NULL" and schema.has("ost_user", "default_email_id")
             and schema.has("ost_user_email", "address") else "NULL")
    parameters = [TEXT_LIMIT] * ((name != "NULL") + (email != "NULL"))
    joins = ""
    if name != "NULL":
        joins += " LEFT JOIN ost_user u ON u.id = tc.user_id"
    if email != "NULL":
        joins += " LEFT JOIN ost_user_email ue ON ue.id = u.default_email_id"
    rows = db.fetch_all(
        f"""SELECT tc.user_id, {name} AS name, {email} AS email
            FROM ost_thread th JOIN ost_thread_collaborator tc ON tc.thread_id = th.id{joins}
            WHERE th.object_type = 'T' AND th.object_id = %s ORDER BY tc.id LIMIT %s""",
        (*parameters, ticket_id, MAX_COLLABORATORS + 1),
    )
    return rows[:MAX_COLLABORATORS], len(rows) > MAX_COLLABORATORS


def _thread_summary(schema: Schema, ticket_id: int) -> dict | None:
    if not (schema.has("ost_thread", "object_id") and schema.has("ost_thread_entry", "thread_id")
            and schema.has("ost_thread_entry", "type")):
        return None
    last = "MAX(e.created)" if schema.has("ost_thread_entry", "created") else "NULL"
    rows = db.fetch_all(
        f"""SELECT e.type AS type, COUNT(*) AS entries, {last} AS last_at
            FROM ost_thread th JOIN ost_thread_entry e ON e.thread_id = th.id
            WHERE th.object_type = 'T' AND th.object_id = %s GROUP BY e.type""",
        (ticket_id,),
    )
    summary = {f"{name}s": 0 for name in ENTRY_TYPES.values()}
    for row in rows:
        name = ENTRY_TYPES.get(row.get("type"))
        if name:
            summary[f"{name}s"] = int(row.get("entries") or 0)
            summary[f"last_{name}_at"] = row.get("last_at")
    summary["total_entries"] = sum(summary[f"{name}s"] for name in ENTRY_TYPES.values())
    return summary


def detail(arguments: TicketArguments) -> dict:
    schema = _load_schema()
    query = TicketQuery(schema, _company_list_id())
    field = "ticket_id" if arguments.ticket_id is not None else "number"
    query.require("t", field)
    projection, parameters, unavailable, used = query.projection(_DETAIL_FIELDS + _SUPPORT_CELLS)
    source, source_parameters = query.source(used)
    value = arguments.ticket_id if field == "ticket_id" else arguments.number
    rows = db.fetch_all(
        f"SELECT {projection} {source} WHERE t.`{field}` = %s ORDER BY t.ticket_id DESC LIMIT 2",
        (*parameters, *source_parameters, value),
    )
    if not rows:
        raise RecordNotFoundError("Ticket not found")
    if len(rows) > 1:
        raise AmbiguousRecordError("Ticket number is ambiguous")
    ticket = dict(rows[0])
    ticket_id = ticket["ticket_id"]
    ticket["support_staff"] = _support_staff(schema, ticket_id, ticket)
    for name in [key for key in ticket if key.startswith("_")]:
        del ticket[name]
    collaborators, more = _collaborators(schema, ticket_id)
    ticket["collaborators"] = collaborators
    ticket["collaborators_has_more"] = more
    ticket["thread_summary"] = _thread_summary(schema, ticket_id)
    # Keep a rows collection so the common formatter can adapt oversized content safely.
    return {"rows": [ticket], "row_count": 1, "unavailable_fields": unavailable}


# Thread -------------------------------------------------------------------------------

_THREAD_TEXT = ("poster", "title")
_THREAD_PLAIN = ("staff_id", "user_id", "created", "updated")


def thread(arguments: ThreadArguments) -> Result:
    schema = _load_schema()
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


# Companies, agents and users ----------------------------------------------------------

def companies(arguments: CompanySearchArguments) -> dict:
    """Search the company catalog on the server, including entries beyond any sample."""
    _load_schema().require("ost_list_items", "id", "list_id", "value", "status")
    catalog = _company_list_id()
    rows = db.fetch_all(
        """
        SELECT id AS company_id, LEFT(value, %s) AS name, status
        FROM ost_list_items
        WHERE list_id = %s AND value LIKE %s ESCAPE '='
        ORDER BY (value = %s) DESC, value ASC, id ASC
        LIMIT %s OFFSET %s
        """,
        (TEXT_LIMIT, catalog, literal_pattern(arguments.name), arguments.name, arguments.limit + 1, arguments.offset),
    )
    return {"query": arguments.name, "company_list_id": catalog,
            **page_rows(rows, arguments.limit, arguments.offset)}


def agents(arguments: PeopleArguments) -> dict:
    schema = _load_schema()
    schema.require("ost_staff", "staff_id", "firstname", "lastname")
    active = "a.isactive" if schema.has("ost_staff", "isactive") else "NULL"
    department, join, parameters = "NULL", "", [TEXT_LIMIT]
    if schema.has("ost_staff", "dept_id") and schema.has("ost_department", "id") and schema.has("ost_department", "name"):
        department, join = "LEFT(d.name, %s)", " LEFT JOIN ost_department d ON d.id = a.dept_id"
        parameters.append(TEXT_LIMIT)
    name = "CONCAT_WS(' ', a.firstname, a.lastname)"
    rows = db.fetch_all(
        f"SELECT a.staff_id AS staff_id, LEFT({name}, %s) AS name, {active} AS isactive, {department} AS department "
        f"FROM ost_staff a{join} WHERE {name} LIKE %s ESCAPE '=' "
        f"ORDER BY {name} ASC, a.staff_id ASC LIMIT %s OFFSET %s",
        (*parameters, literal_pattern(arguments.name), arguments.limit + 1, arguments.offset),
    )
    return page_rows(rows, arguments.limit, arguments.offset)


def users(arguments: UserSearchArguments) -> dict:
    """Find requesters by literal substring of their name or of any of their email addresses."""
    schema = _load_schema()
    schema.require("ost_user", "id", "name")
    pattern = literal_pattern(arguments.query)
    emails = schema.has("ost_user_email", "user_id") and schema.has("ost_user_email", "address")
    if emails and schema.has("ost_user", "default_email_id") and schema.has("ost_user_email", "id"):
        email, join, email_parameters = "LEFT(ue.address, %s)", " LEFT JOIN ost_user_email ue ON ue.id = u.default_email_id", [TEXT_LIMIT]
    else:
        email, join, email_parameters = "NULL", "", []
    match, match_parameters = "u.name LIKE %s ESCAPE '='", [pattern]
    exact, exact_parameters = "u.name = %s", [arguments.query]
    if emails:
        match += " OR EXISTS (SELECT 1 FROM ost_user_email m WHERE m.user_id = u.id AND m.address LIKE %s ESCAPE '=')"
        match_parameters.append(pattern)
        exact += " OR EXISTS (SELECT 1 FROM ost_user_email x WHERE x.user_id = u.id AND x.address = %s)"
        exact_parameters.append(arguments.query)
    rows = db.fetch_all(
        f"SELECT u.id AS user_id, LEFT(u.name, %s) AS name, {email} AS email FROM ost_user u{join} "
        f"WHERE {match} ORDER BY ({exact}) DESC, u.name ASC, u.id ASC LIMIT %s OFFSET %s",
        (TEXT_LIMIT, *email_parameters, *match_parameters, *exact_parameters, arguments.limit + 1, arguments.offset),
    )
    return {"query": arguments.query, **page_rows(rows, arguments.limit, arguments.offset)}


def user_profile(arguments: UserArguments) -> dict:
    schema = _load_schema()
    schema.require("ost_user", "id", "name")
    plain = [column for column in ("status", "created", "updated", "default_email_id") if schema.has("ost_user", column)]
    columns = "".join(f", u.`{column}`" for column in plain)
    user = db.fetch_one(
        f"SELECT u.id AS user_id, LEFT(u.name, %s) AS name{columns} FROM ost_user u WHERE u.id = %s",
        (TEXT_LIMIT, arguments.user_id),
    )
    if user is None:
        raise RecordNotFoundError("User not found")
    user = dict(user)
    unavailable = []
    for column in ("status", "created", "updated"):
        if column not in plain:
            user[column] = None
            unavailable.append(column)
    default_email = user.pop("default_email_id", None)
    if all(schema.has("ost_user_email", column) for column in ("id", "user_id", "address")):
        addresses = db.fetch_all(
            "SELECT id, LEFT(address, %s) AS address FROM ost_user_email WHERE user_id = %s ORDER BY id LIMIT 21 OFFSET %s",
            (TEXT_LIMIT, arguments.user_id, arguments.emails_offset),
        )
        default_available = "default_email_id" in plain
        if not default_available:
            unavailable.append("emails.is_default")
        user["emails"] = [{"address": row.get("address"),
                           "is_default": row.get("id") == default_email if default_available else None}
                          for row in addresses[:20]]
        page = page_rows(addresses, 20, arguments.emails_offset)
        user["emails_pagination"] = {key: value for key, value in page.items() if key not in ("rows", "row_count")}
    else:
        user["emails"] = None
        user["emails_pagination"] = None
        unavailable.append("emails")
    try:
        by_state = report(TicketReportArguments(group_by="state", user_id=arguments.user_id))
        total = by_state["total_tickets"]
        states = {group["key"] or "unknown": group["tickets"] for group in by_state["groups"]}
    except SchemaUnavailableError:
        total = count(TicketFilters(user_id=arguments.user_id))["total"]
        states = None
        unavailable.append("tickets.by_state")
    latest = search(SearchTicketsArguments(user_id=arguments.user_id, limit=1))
    unavailable.extend(f"tickets.latest.{field}" for field in latest["unavailable_fields"])
    tickets = {"as_requester": total,
               "by_state": states,
               "latest": latest["rows"][0] if latest["rows"] else None}
    try:
        top = report(TicketReportArguments(group_by="company", user_id=arguments.user_id, limit=10,
                                         offset=arguments.companies_offset))
        # Tickets without a company form a null group; the profile lists real companies only.
        user["companies"] = [{"company_id": g["key"], "name": g["label"], "tickets": g["tickets"]}
                             for g in top["groups"] if g["key"] is not None]
        # Offset counts report groups, including the group without a company.
        user["companies_pagination"] = {key: top[key] for key in
                                       ("limit", "offset", "has_more", "next_offset", "pagination_limit_reached")}
    except SchemaUnavailableError:
        user["companies"] = None
        user["companies_pagination"] = None
        unavailable.append("companies")
    if (all(schema.has("ost_thread_collaborator", column) for column in ("user_id", "thread_id"))
            and all(schema.has("ost_thread", column) for column in ("id", "object_id", "object_type"))):
        row = db.fetch_one(
            """SELECT COUNT(DISTINCT th.object_id) AS tickets FROM ost_thread_collaborator tc
               JOIN ost_thread th ON th.id = tc.thread_id
               WHERE th.object_type = 'T' AND tc.user_id = %s""",
            (arguments.user_id,),
        )
        tickets["as_collaborator"] = int(row["tickets"]) if row else 0
    else:
        tickets["as_collaborator"] = None
        unavailable.append("tickets.as_collaborator")
    user["tickets"] = tickets
    return {"rows": [user], "row_count": 1, "unavailable_fields": unavailable}


def _support_activity(schema: Schema, staff_id: int, filters: TicketFilters, include_time: bool) -> dict | None:
    """Tickets where the agent was recorded as support staff (apoyo1..3)."""
    if not all((schema.has("ost_form_entry", "object_id"), schema.has("ost_form_entry", "object_type"),
                schema.has("ost_form_entry_values", "value"), schema.has("ost_form_field", "name"))):
        return None
    query = TicketQuery(schema, _company_list_id())
    where, parameters, _, _ = query.where(filters)
    placeholders = ", ".join("%s" for _ in SUPPORT_FIELDS)
    columns, column_parameters = ["COUNT(DISTINCT ap.ticket_id) AS tickets"], []
    if include_time and all(schema.has("ost_ticket__cdata", f"timeApoyo{slot}") for slot in (1, 2, 3)):
        cases = []
        for slot, field in enumerate(SUPPORT_FIELDS, start=1):
            sql, values = _seconds_sql(f"c.`timeApoyo{slot}`")
            cases.append(f"WHEN %s THEN {sql}")
            column_parameters.extend([field, *values])
        columns.append(f"SUM(CASE ap.field {' '.join(cases)} ELSE 0 END) AS time_seconds")
    where = where.replace("WHERE ", "AND ", 1) if where else ""
    row = db.fetch_one(
        f"""SELECT {', '.join(columns)}
            FROM (SELECT DISTINCT e.object_id AS ticket_id, f.name AS field
                  FROM ost_form_entry e
                  JOIN ost_form_entry_values v ON v.entry_id = e.id
                  JOIN ost_form_field f ON f.id = v.field_id
                  WHERE e.object_type = 'T' AND f.name IN ({placeholders}) AND v.value LIKE %s ESCAPE '=') ap
            JOIN ost_ticket t ON t.ticket_id = ap.ticket_id
            LEFT JOIN ost_ticket__cdata c ON c.ticket_id = t.ticket_id
            WHERE 1 = 1 {where}""",
        # Answers are stored as {"s<staff_id>":"Name"}; match the key prefix literally.
        (*column_parameters, *SUPPORT_FIELDS, escape_like(f'{{"s{staff_id}":') + "%", *parameters),
    )
    result = {"tickets": int(row["tickets"]) if row else 0}
    if "time_seconds" in (row or {}):
        result["recorded_time"] = _duration(row["time_seconds"])
    return result


def agent_report(arguments: AgentReportArguments) -> dict:
    schema = _load_schema()
    schema.require("ost_staff", "staff_id", "firstname", "lastname")
    schema.require("ost_ticket", "staff_id")
    department, join, parameters = "NULL", "", [TEXT_LIMIT]
    if schema.has("ost_staff", "dept_id") and schema.has("ost_department", "name"):
        department, join = "LEFT(d.name, %s)", " LEFT JOIN ost_department d ON d.id = a.dept_id"
        parameters.append(TEXT_LIMIT)
    flags = "".join(f", a.`{column}`" for column in ("isactive", "onvacation") if schema.has("ost_staff", column))
    agent = db.fetch_one(
        f"SELECT a.staff_id, LEFT(CONCAT_WS(' ', a.firstname, a.lastname), %s) AS name{flags}, "
        f"{department} AS department FROM ost_staff a{join} WHERE a.staff_id = %s",
        (*parameters, arguments.staff_id),
    )
    if agent is None:
        raise RecordNotFoundError("Agent not found")
    staff = arguments.staff_id
    period = {"date_from": arguments.date_from, "date_to": arguments.date_to}
    created = TicketFilters(staff_id=staff, created_from=arguments.date_from, created_to=arguments.date_to)

    by_state = report(TicketReportArguments(group_by="state", staff_id=staff))
    open_by_status = report(TicketReportArguments(group_by="status", staff_id=staff, state="open"))
    assigned_now = {
        "total": by_state["total_tickets"],
        "by_state": {group["key"] or "unknown": group["tickets"] for group in by_state["groups"]},
        "open_by_status": {group["label"]: group["tickets"] for group in open_by_status["groups"]},
        "open_overdue": count(TicketFilters(staff_id=staff, state="open", overdue=True))["total"],
    }
    in_period = {"assigned_tickets_created": count(created)["total"]}
    if arguments.date_from or arguments.date_to:
        closed = TicketFilters(staff_id=staff, closed_from=arguments.date_from, closed_to=arguments.date_to)
        in_period["assigned_tickets_closed"] = count(closed)["total"]

    activity = None
    if schema.has("ost_thread_entry", "staff_id") and schema.has("ost_thread_entry", "type"):
        conditions, values = ["th.object_type = 'T'", "e.staff_id = %s", "e.type IN ('R', 'N')"], [staff]
        if arguments.date_from:
            conditions.append("e.created >= %s")
            values.append(arguments.date_from)
        if arguments.date_to:
            conditions.append("e.created < %s")
            values.append(_next_day(arguments.date_to))
        rows = db.fetch_all(
            f"""SELECT e.type AS type, COUNT(*) AS entries, COUNT(DISTINCT th.object_id) AS tickets
                FROM ost_thread_entry e JOIN ost_thread th ON th.id = e.thread_id
                WHERE {' AND '.join(conditions)} GROUP BY e.type""",
            tuple(values),
        )
        activity = {"responses": 0, "tickets_with_responses": 0, "internal_notes": 0, "tickets_with_notes": 0}
        for row in rows:
            if row.get("type") == "R":
                activity.update(responses=int(row["entries"]), tickets_with_responses=int(row["tickets"]))
            elif row.get("type") == "N":
                activity.update(internal_notes=int(row["entries"]), tickets_with_notes=int(row["tickets"]))

    data = {
        "agent": agent, "period": period, "assigned_now": assigned_now, "in_period": in_period,
        "thread_activity": activity,
        "support_role": _support_activity(schema, staff, TicketFilters(created_from=arguments.date_from,
                                                                       created_to=arguments.date_to),
                                          arguments.include_time),
    }
    if arguments.include_time and schema.has("ost_ticket__cdata", "time"):
        query = TicketQuery(schema, _company_list_id())
        where, where_parameters, _, needed = query.where(created)
        expressions, time_parameters = _time_columns(query)
        source, source_parameters = query.source(needed | {"c"})
        row = db.fetch_one(f"SELECT {', '.join(expressions)} {source} {where}",
                           (*time_parameters, *source_parameters, *where_parameters))
        in_period.update(_time_totals(row or {}))
    return data


# Catalogs -------------------------------------------------------------------------------

_CATALOGS = {
    "statuses": ("ost_ticket_status", ("id", "name", "state"),
                 "SELECT id AS status_id, name, state FROM ost_ticket_status ORDER BY name, id"),
    "departments": ("ost_department", ("id", "name"),
                    "SELECT id AS dept_id, name FROM ost_department ORDER BY name, id"),
    "priorities": ("ost_ticket_priority", ("priority_id", "priority_desc", "priority_urgency"),
                   "SELECT priority_id, priority_desc AS name, priority_urgency AS urgency "
                   "FROM ost_ticket_priority ORDER BY priority_urgency, priority_id"),
    "help_topics": ("ost_help_topic", ("topic_id", "topic", "dept_id"),
                    "SELECT topic_id, topic AS name, dept_id FROM ost_help_topic ORDER BY topic, topic_id"),
    "teams": ("ost_team", ("team_id", "name"), "SELECT team_id, name FROM ost_team ORDER BY name, team_id"),
    "slas": ("ost_sla", ("id", "name", "grace_period"),
             "SELECT id AS sla_id, name, grace_period AS grace_period_hours FROM ost_sla ORDER BY name, id"),
}


def catalog(arguments: CatalogArguments) -> dict:
    table, columns, sql = _CATALOGS[arguments.kind]
    _load_schema().require(table, *columns)
    rows = db.fetch_all(sql)
    return {"kind": arguments.kind, "rows": rows, "row_count": len(rows)}
