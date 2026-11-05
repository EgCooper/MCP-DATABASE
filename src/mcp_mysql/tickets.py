"""Schema-aware, parameterized osTicket queries. No caller-supplied SQL fragments."""

from dataclasses import dataclass
from datetime import date, timedelta

from mcp_mysql import db
from mcp_mysql.access import get_allowed_columns
from mcp_mysql.config import MySQLConfig
from mcp_mysql.errors import AccessDeniedError, AmbiguousRecordError, RecordNotFoundError, SchemaUnavailableError
from mcp_mysql.responses import MAX_FIELD_CHARACTERS
from mcp_mysql.validation import (
    MAX_OFFSET, CompanyTicketsArguments, PeopleArguments, SearchTicketsArguments,
    ThreadArguments, TicketArguments, TicketFilters,
)

_TABLES = (
    "ost_ticket", "ost_ticket__cdata", "ost_ticket_status", "ost_department",
    "ost_user", "ost_user_email", "ost_staff", "ost_list_items", "ost_thread", "ost_thread_entry",
)
_ALIASES = {"t": "ost_ticket", "c": "ost_ticket__cdata", "s": "ost_ticket_status",
            "d": "ost_department", "u": "ost_user", "a": "ost_staff"}


def literal_pattern(text: str) -> str:
    return "%" + text.replace("=", "==").replace("%", "=%").replace("_", "=_") + "%"


@dataclass
class Schema:
    columns: dict[str, set[str]]

    def has(self, table: str, column: str) -> bool:
        try:
            permitted = get_allowed_columns(table)
        except AccessDeniedError:
            return False
        return column in permitted and column.casefold() in self.columns.get(table, set())

    def require(self, table: str, *columns: str) -> None:
        if not set(columns).issubset(get_allowed_columns(table)):
            raise AccessDeniedError("Query outside access policy")
        if not all(self.has(table, column) for column in columns):
            raise SchemaUnavailableError("Missing required fields")


def _load_schema() -> Schema:
    tables = []
    columns = set()
    for table in _TABLES:
        try:
            permitted = get_allowed_columns(table)
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


def page_rows(rows: list[dict], limit: int, offset: int = 0) -> dict:
    returned = rows[:limit]
    more = len(rows) > limit
    next_offset = offset + len(returned)
    capped = more and next_offset > MAX_OFFSET
    return {"rows": returned, "row_count": len(returned), "limit": limit,
            "offset": offset, "has_more": more, "pagination_limit_reached": capped,
            "next_offset": next_offset if more and not capped else None}


class TicketQuery:
    def __init__(self, schema: Schema):
        self.schema = schema
        schema.require("ost_ticket", "ticket_id")
        self.joins: dict[str, str] = {}
        self.available = {"t"}
        for alias, foreign, target in (
            ("c", "ticket_id", "ticket_id"), ("s", "status_id", "id"),
            ("d", "dept_id", "id"), ("u", "user_id", "id"), ("a", "staff_id", "staff_id"),
        ):
            table = _ALIASES[alias]
            if schema.has("ost_ticket", foreign) and schema.has(table, target):
                self.available.add(alias)
                self.joins[alias] = f"LEFT JOIN `{table}` {alias} ON {alias}.`{target}` = t.`{foreign}`"

    def has(self, alias: str, column: str) -> bool:
        return alias in self.available and self.schema.has(_ALIASES[alias], column)

    def require(self, alias: str, column: str) -> None:
        self.schema.require(_ALIASES[alias], column)
        if alias not in self.available:
            raise SchemaUnavailableError("Missing required relationship")

    def source(self, aliases: set[str] | None = None) -> str:
        return "FROM ost_ticket t " + " ".join(
            clause for alias, clause in self.joins.items() if aliases is None or alias in aliases
        )

    def company(self, identifier: int) -> dict:
        self.schema.require("ost_list_items", "id", "list_id", "value")
        row = db.fetch_one(
            "SELECT id AS company_id, LEFT(value, %s) AS name FROM ost_list_items WHERE list_id = %s AND id = %s",
            (MAX_FIELD_CHARACTERS + 1, MySQLConfig.from_env().company_list_id, identifier),
        )
        if row is None:
            raise RecordNotFoundError("Company not found")
        return row

    def where(self, filters: TicketFilters) -> tuple[str, tuple, dict | None]:
        clauses, parameters = [], []
        company = None
        if filters.company_id is not None:
            self.require("c", "listaEmpresa")
            company = self.company(filters.company_id)
            clauses.append("TRIM(SUBSTRING_INDEX(c.listaEmpresa, ',', 1)) = %s")
            parameters.append(str(filters.company_id))
        for field in ("staff_id", "user_id"):
            value = getattr(filters, field)
            if value is not None:
                self.require("t", field)
                clauses.append(f"t.`{field}` = %s")
                parameters.append(value)
        if filters.status is not None:
            self.require("s", "name")
            clauses.append("s.name = %s")
            parameters.append(filters.status)
        if filters.subject is not None:
            self.require("c", "subject")
            clauses.append("c.subject LIKE %s ESCAPE '='")
            parameters.append(literal_pattern(filters.subject))
        if filters.created_from:
            self.require("t", "created")
            clauses.append("t.created >= %s")
            parameters.append(filters.created_from)
        if filters.created_to:
            self.require("t", "created")
            clauses.append("t.created < %s")
            parameters.append((date.fromisoformat(filters.created_to) + timedelta(days=1)).isoformat())
        return ("WHERE " + " AND ".join(clauses) if clauses else ""), tuple(parameters), company

    def projection(self) -> tuple[str, tuple, list[str]]:
        fields = (
            ("ticket_id", "t", "ticket_id", False), ("number", "t", "number", True),
            ("created", "t", "created", False), ("lastupdate", "t", "lastupdate", False),
            ("closed", "t", "closed", False), ("staff_id", "t", "staff_id", False),
            ("user_id", "t", "user_id", False), ("status", "s", "name", True),
            ("status_state", "s", "state", True), ("department", "d", "name", True),
            ("customer", "u", "name", True), ("subject", "c", "subject", True),
            ("company_value", "c", "listaEmpresa", True), ("analysis", "c", "analisis", True),
            ("solution", "c", "solucion", True), ("recorded_time", "c", "time", True),
            ("overtime", "c", "timeExtra", True), ("overtime_flag", "c", "horaExtra", True),
            ("compensated_time", "c", "horaCompensada", True),
        )
        expressions, parameters, unavailable = [], [], []
        for output, alias, column, text in fields:
            if not self.has(alias, column):
                expressions.append(f"NULL AS `{output}`")
                unavailable.append(output)
            elif text:
                expressions.append(f"LEFT({alias}.`{column}`, %s) AS `{output}`")
                parameters.append(MAX_FIELD_CHARACTERS + 1)
            else:
                expressions.append(f"{alias}.`{column}` AS `{output}`")
        if self.has("a", "firstname") and self.has("a", "lastname"):
            expressions.append("LEFT(CONCAT_WS(' ', a.firstname, a.lastname), %s) AS assigned_agent")
            parameters.append(MAX_FIELD_CHARACTERS + 1)
        else:
            expressions.append("NULL AS assigned_agent")
            unavailable.append("assigned_agent")
        return ", ".join(expressions), tuple(parameters), unavailable


def search(arguments: SearchTicketsArguments) -> dict:
    query = TicketQuery(_load_schema())
    query.require("t", "created")
    where, parameters, company = query.where(arguments)
    projection, projection_parameters, unavailable = query.projection()
    # The order is selected from two constants; it is never interpolated from arbitrary input.
    direction = "DESC" if arguments.order == "newest" else "ASC"
    rows = db.fetch_all(
        f"SELECT {projection} {query.source()} {where} ORDER BY t.created {direction}, t.ticket_id {direction} LIMIT %s OFFSET %s",
        (*projection_parameters, *parameters, arguments.limit + 1, arguments.offset),
    )
    data = page_rows(rows, arguments.limit, arguments.offset)
    data.update(order="newest_first" if direction == "DESC" else "oldest_first", unavailable_fields=unavailable)
    if company is not None:
        data["company"] = company
    return data


def count(arguments: TicketFilters) -> dict:
    query = TicketQuery(_load_schema())
    where, parameters, company = query.where(arguments)
    needed = set()
    if arguments.company_id is not None or arguments.subject is not None:
        needed.add("c")
    if arguments.status is not None:
        needed.add("s")
    row = db.fetch_one(f"SELECT COUNT(*) AS total {query.source(needed)} {where}", parameters)
    if row is None:
        raise SchemaUnavailableError("Missing count result")
    result = {"total": int(row["total"]), "filters": arguments.model_dump(exclude_none=True)}
    if company is not None:
        result["company"] = company
    return result


def company_tickets(arguments: CompanyTicketsArguments) -> dict:
    return search(arguments)


def detail(arguments: TicketArguments) -> dict:
    query = TicketQuery(_load_schema())
    field = "ticket_id" if arguments.ticket_id is not None else "number"
    query.require("t", field)
    projection, parameters, unavailable = query.projection()
    value = arguments.ticket_id if field == "ticket_id" else arguments.number
    rows = db.fetch_all(
        f"SELECT {projection} {query.source()} WHERE t.`{field}` = %s ORDER BY t.ticket_id DESC LIMIT 2",
        (*parameters, value),
    )
    if not rows:
        raise RecordNotFoundError("Ticket not found")
    if len(rows) > 1:
        raise AmbiguousRecordError("Ticket number is ambiguous")
    # Keep a rows collection so the common formatter can adapt oversized content safely.
    return {"rows": rows, "row_count": 1, "unavailable_fields": unavailable}


def thread(arguments: ThreadArguments) -> dict:
    schema = _load_schema()
    schema.require("ost_ticket", "ticket_id")
    schema.require("ost_thread", "id", "object_id", "object_type")
    schema.require("ost_thread_entry", "id", "thread_id")
    existing = db.fetch_one("SELECT ticket_id FROM ost_ticket WHERE ticket_id = %s", (arguments.ticket_id,))
    if existing is None:
        raise RecordNotFoundError("Ticket not found")
    fields = ("staff_id", "user_id", "type", "poster", "title", "body", "format", "created", "updated")
    expressions = ["e.id AS entry_id", "e.thread_id"]
    parameters, unavailable = [], []
    for column in fields:
        if not schema.has("ost_thread_entry", column):
            expressions.append(f"NULL AS `{column}`")
            unavailable.append(column)
        elif column in ("staff_id", "user_id", "created", "updated"):
            expressions.append(f"e.`{column}`")
        else:
            expressions.append(f"LEFT(e.`{column}`, %s) AS `{column}`")
            parameters.append(MAX_FIELD_CHARACTERS + 1)
    rows = db.fetch_all(
        f"""SELECT {', '.join(expressions)} FROM ost_thread_entry e
            JOIN ost_thread th ON th.id = e.thread_id
            WHERE th.object_type = 'T' AND th.object_id = %s AND e.id > %s
            ORDER BY e.id ASC LIMIT %s""",
        (*parameters, arguments.ticket_id, arguments.after_entry_id, arguments.limit + 1),
    )
    returned, more = rows[:arguments.limit], len(rows) > arguments.limit
    return {"ticket_id": arguments.ticket_id, "rows": returned, "row_count": len(returned),
            "has_more": more, "next_after_entry_id": returned[-1]["entry_id"] if more and returned else None,
            "unavailable_fields": unavailable}


def people(arguments: PeopleArguments, *, agents: bool) -> dict:
    schema = _load_schema()
    table, identifier = ("ost_staff", "staff_id") if agents else ("ost_user", "id")
    schema.require(table, identifier)
    if agents:
        schema.require(table, "firstname", "lastname")
        name = "CONCAT_WS(' ', firstname, lastname)"
        key = "staff_id"
        active = "isactive" if schema.has(table, "isactive") else "NULL"
        extra = f", {active} AS isactive"
    else:
        schema.require(table, "name")
        name, key, extra = "name", "user_id", ""
    rows = db.fetch_all(
        f"SELECT `{identifier}` AS `{key}`, LEFT({name}, %s) AS name {extra} FROM `{table}` "
        f"WHERE {name} LIKE %s ESCAPE '=' ORDER BY {name} ASC, `{identifier}` ASC LIMIT %s OFFSET %s",
        (MAX_FIELD_CHARACTERS + 1, literal_pattern(arguments.name), arguments.limit + 1, arguments.offset),
    )
    return page_rows(rows, arguments.limit, arguments.offset)
