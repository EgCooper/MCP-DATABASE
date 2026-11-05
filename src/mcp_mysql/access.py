"""Explicit table and column access for the osTicket tools.

Names not present here are denied, including columns added by future upgrades.
Custom ticket columns come from the project's previous hours report.
"""

from collections.abc import Mapping
from types import MappingProxyType

from mcp_mysql.validation import MAX_TABLE_NAME_LENGTH
from mcp_mysql.errors import AccessDeniedError


ALLOWED_TABLE_COLUMNS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "ost_ticket": (
        "ticket_id", "ticket_pid", "number", "user_id", "user_email_id",
        "status_id", "dept_id", "sla_id", "topic_id", "staff_id", "team_id",
        "source", "isoverdue", "isanswered", "duedate", "est_duedate",
        "reopened", "closed", "lastupdate", "created", "updated",
    ),
    "ost_ticket__cdata": (
        "ticket_id", "subject", "priority", "listaEmpresa", "tipoSolicitud",
        "causa", "ambiente", "vencimientoSoporte", "fechaInicio", "fechaFin",
        "time", "timeExtra", "horaExtra", "horaCompensada", "analisis",
        "solucion", "apoyo1", "timeApoyo1", "apoyo2", "timeApoyo2",
        "apoyo3", "timeApoyo3",
    ),
    "ost_ticket_status": (
        "id", "name", "state", "mode", "sort", "created", "updated",
    ),
    "ost_ticket_priority": (
        "priority_id", "priority", "priority_desc", "priority_urgency", "ispublic",
    ),
    "ost_thread": (
        "id", "object_id", "object_type", "lastresponse", "lastmessage", "created",
    ),
    "ost_thread_entry": (
        "id", "pid", "thread_id", "staff_id", "user_id", "type", "poster",
        "source", "title", "body", "format", "created", "updated",
    ),
    "ost_thread_event": (
        "id", "thread_id", "thread_type", "event_id", "staff_id", "team_id",
        "dept_id", "topic_id", "username", "uid", "uid_type", "annulled", "timestamp",
    ),
    # Requesters and CC participants of a ticket thread.
    "ost_thread_collaborator": ("id", "thread_id", "user_id", "role", "created"),
    "ost_event": ("id", "name", "description"),
    "ost_user": (
        "id", "name", "default_email_id", "status", "created", "updated",
    ),
    "ost_user_email": ("id", "user_id", "address"),
    # Authentication fields, permissions, extra and personal contact data are excluded.
    "ost_staff": (
        "staff_id", "dept_id", "firstname", "lastname", "isactive",
        "onvacation", "created", "updated",
    ),
    "ost_department": (
        "id", "pid", "name", "manager_id", "ispublic", "created", "updated",
    ),
    "ost_team": ("team_id", "lead_id", "name", "created", "updated"),
    "ost_team_member": ("team_id", "staff_id"),
    "ost_sla": ("id", "name", "grace_period"),
    "ost_list": ("id", "name", "name_plural", "type", "created", "updated"),
    "ost_list_items": ("id", "list_id", "status", "value", "sort"),
    "ost_help_topic": (
        "topic_id", "topic_pid", "topic", "status_id", "priority_id", "dept_id",
        "staff_id", "team_id", "sla_id", "ispublic", "created", "updated",
    ),
})

# Read only by fixed business queries, restricted to the support-staff fields
# (apoyo1..3). They hold every custom form answer, so they are never listed,
# described or sampled by the exploration tools.
INTERNAL_TABLE_COLUMNS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "ost_form_entry": ("id", "form_id", "object_id", "object_type"),
    "ost_form_entry_values": ("entry_id", "field_id", "value"),
    "ost_form_field": ("id", "form_id", "name"),
})


def _valid_name(table_name: object) -> bool:
    return type(table_name) is str and 1 <= len(table_name) <= MAX_TABLE_NAME_LENGTH


def get_allowed_columns(table_name: str) -> tuple[str, ...]:
    """Columns visible to exploration tools; reject unknown or malformed names before any database access."""
    if not _valid_name(table_name) or table_name not in ALLOWED_TABLE_COLUMNS:
        raise AccessDeniedError("Table is not available through this MCP.")
    return ALLOWED_TABLE_COLUMNS[table_name]


def get_query_columns(table_name: str) -> tuple[str, ...]:
    """Columns that fixed business queries may reference (exploration set plus internal tables)."""
    if _valid_name(table_name) and table_name in INTERNAL_TABLE_COLUMNS:
        return INTERNAL_TABLE_COLUMNS[table_name]
    return get_allowed_columns(table_name)


def all_query_tables() -> dict[str, tuple[str, ...]]:
    return {**ALLOWED_TABLE_COLUMNS, **INTERNAL_TABLE_COLUMNS}
