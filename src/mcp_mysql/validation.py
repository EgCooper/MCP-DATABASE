"""Strict argument contracts shared by MCP schemas and server validation."""

from types import MappingProxyType
from typing import Annotated, Literal
from datetime import date
import base64
import hashlib
import json

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

MAX_TABLE_NAME_LENGTH = 64
MAX_SAMPLE_ROWS = 100
MAX_OFFSET = 10000
MAX_REPORT_GROUPS = 100

TableName = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=MAX_TABLE_NAME_LENGTH, pattern=r"^[A-Za-z0-9_]+$"),
]
SampleLimit = Annotated[int, Field(strict=True, ge=1, le=MAX_SAMPLE_ROWS)]
BusinessLimit = Annotated[int, Field(strict=True, ge=1, le=50)]
RecordId = Annotated[int, Field(strict=True, ge=1, le=2147483647,
                               description='JSON integer ID, e.g. 3. Never a quoted string like "3"; resolve names first.')]
# Kept for callers that still import the original name.
CompanyId = RecordId
Offset = Annotated[int, Field(strict=True, ge=0, le=MAX_OFFSET)]
EntryId = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
Flag = Annotated[bool, Field(strict=True)]


def _clean_text(value: str, minimum: int) -> str:
    normalized = value.strip()
    if len(normalized) < minimum or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise ValueError("Invalid search text")
    return normalized


CompanyName = Annotated[
    str, Field(strict=True, min_length=2, max_length=120), AfterValidator(lambda v: _clean_text(v, 2)),
]
SearchText = Annotated[
    str, Field(strict=True, min_length=1, max_length=120), AfterValidator(lambda v: _clean_text(v, 1)),
]
TicketNumber = Annotated[
    str, Field(strict=True, min_length=1, max_length=32), AfterValidator(lambda v: _clean_text(v, 1)),
]


def _iso_date(value: str) -> str:
    date.fromisoformat(value)
    if value == "9999-12-31":
        # An inclusive end date is queried as "< next day", which does not exist here.
        raise ValueError("Date is outside the supported range")
    return value


ISODate = Annotated[
    str, Field(strict=True, min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$",
               json_schema_extra={"format": "date"}), AfterValidator(_iso_date),
]

TicketState = Literal["open", "closed", "archived", "deleted"]
EntryType = Literal["message", "response", "internal_note"]
ContentField = Literal["subject", "cause", "analysis", "solution", "environment", "thread_title", "thread_body"]
CONTENT_FIELDS = ("subject", "cause", "analysis", "solution", "environment", "thread_title", "thread_body")
ReportGroup = Literal[
    "status", "state", "department", "agent", "company", "priority",
    "help_topic", "request_type", "source", "user", "month",
]
CatalogKind = Literal["statuses", "departments", "priorities", "help_topics", "teams", "slas"]


class NoArguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class TableArguments(NoArguments):
    table_name: TableName


class SampleArguments(TableArguments):
    limit: SampleLimit = 10


class CompanySearchArguments(NoArguments):
    name: CompanyName
    limit: BusinessLimit = 20
    offset: Offset = 0


def _check_range(start: str | None, end: str | None, label: str) -> None:
    if start and end and start > end:
        raise ValueError(f"{label}_from must not be later than {label}_to")


class TicketFilters(NoArguments):
    company_id: RecordId | None = None
    staff_id: RecordId | None = None
    assigned: Flag | None = None
    user_id: RecordId | None = None
    include_collaborations: Flag = False
    status: SearchText | None = None
    state: TicketState | None = None
    dept_id: RecordId | None = None
    priority_id: RecordId | None = None
    topic_id: RecordId | None = None
    overdue: Flag | None = None
    created_from: ISODate | None = None
    created_to: ISODate | None = None
    closed_from: ISODate | None = None
    closed_to: ISODate | None = None
    subject: SearchText | None = None

    @model_validator(mode="after")
    def consistent_filters(self):
        _check_range(self.created_from, self.created_to, "created")
        _check_range(self.closed_from, self.closed_to, "closed")
        if self.include_collaborations and self.user_id is None:
            raise ValueError("include_collaborations requires user_id")
        if self.assigned is False and self.staff_id is not None:
            raise ValueError("assigned=false cannot be combined with staff_id")
        return self


class SearchTicketsArguments(TicketFilters):
    limit: BusinessLimit = 20
    offset: Offset = 0
    order: Literal["newest", "oldest", "last_updated"] = "newest"


class CompanyTicketsArguments(SearchTicketsArguments):
    company_id: RecordId
    limit: BusinessLimit = 10


class TicketReportArguments(TicketFilters):
    group_by: ReportGroup
    limit: Annotated[int, Field(strict=True, ge=1, le=MAX_REPORT_GROUPS)] = 50
    offset: Offset = 0
    include_time: Flag = False


class TicketArguments(NoArguments):
    ticket_id: RecordId | None = None
    number: TicketNumber | None = None

    @model_validator(mode="after")
    def one_identifier(self):
        # Enforced here instead of a top-level oneOf: several LLM tool APIs reject
        # oneOf/anyOf/allOf at the root of an input schema.
        if (self.ticket_id is None) == (self.number is None):
            raise ValueError("Provide exactly one of ticket_id or number")
        return self


class ThreadArguments(NoArguments):
    ticket_id: RecordId
    order: Literal["oldest", "newest"] = "oldest"
    after_entry_id: EntryId = 0
    before_entry_id: EntryId = 0
    entry_types: Annotated[list[EntryType], Field(min_length=1, max_length=3)] | None = None
    limit: BusinessLimit = 20

    @model_validator(mode="after")
    def cursor_matches_order(self):
        if self.order == "oldest" and self.before_entry_id:
            raise ValueError("before_entry_id is only valid with order=newest")
        if self.order == "newest" and self.after_entry_id:
            raise ValueError("after_entry_id is only valid with order=oldest")
        return self


class ReadTicketTextArguments(NoArguments):
    ticket_id: RecordId
    field: ContentField
    entry_id: RecordId | None = None
    offset: Annotated[int, Field(strict=True, ge=0, le=4294967295)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=2000)] = 2000
    revision: Annotated[str, Field(strict=True, min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")] | None = None

    @model_validator(mode="after")
    def entry_matches_field(self):
        if self.field.startswith("thread_") != (self.entry_id is not None):
            raise ValueError("Provide entry_id exactly when reading a thread field")
        return self


class SearchTicketContentArguments(TicketFilters):
    query: SearchText
    fields: Annotated[list[ContentField], Field(min_length=1, max_length=7)] | None = None
    ticket_id: RecordId | None = None
    entry_types: Annotated[list[EntryType], Field(min_length=1, max_length=3)] | None = None
    limit: Annotated[int, Field(strict=True, ge=1, le=10)] = 10
    cursor: Annotated[str, Field(strict=True, min_length=20, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")] | None = None

    def _cursor_identity(self) -> str:
        values = self.model_dump(exclude={"cursor", "limit"})
        values["fields"] = list(self.fields or CONTENT_FIELDS)
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode()).hexdigest()

    def cursor_position(self) -> tuple[str, int] | None:
        if self.cursor is None:
            return None
        try:
            raw = base64.b64decode(self.cursor + "=" * (-len(self.cursor) % 4), altchars=b"-_", validate=True)
            value = json.loads(raw)
            if (not isinstance(value, dict) or set(value) != {"v", "field", "after", "identity"}
                    or type(value["v"]) is not int or value["v"] != 1
                    or value["field"] not in (self.fields or CONTENT_FIELDS)
                    or type(value["after"]) is not int or not 1 <= value["after"] <= 2147483647
                    or value["identity"] != self._cursor_identity()):
                raise ValueError("Invalid continuation")
            return value["field"], value["after"]
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            raise ValueError("Cursor must belong to the same content query and filters") from error

    def make_cursor(self, field: str, after: int) -> str:
        value = {"v": 1, "field": field, "after": after, "identity": self._cursor_identity()}
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")

    @model_validator(mode="after")
    def valid_content_scope(self):
        if self.fields is not None:
            if len(set(self.fields)) != len(self.fields):
                raise ValueError("Duplicate content fields")
            self.fields = sorted(self.fields, key=CONTENT_FIELDS.index)
        if self.entry_types is not None:
            if len(set(self.entry_types)) != len(self.entry_types):
                raise ValueError("Duplicate entry types")
            self.entry_types = sorted(self.entry_types)
            if not any(field.startswith("thread_") for field in (self.fields or CONTENT_FIELDS)):
                raise ValueError("entry_types requires a thread field")
        self.cursor_position()
        return self


class PeopleArguments(NoArguments):
    name: CompanyName
    limit: BusinessLimit = 20
    offset: Offset = 0


class UserSearchArguments(NoArguments):
    query: CompanyName
    limit: BusinessLimit = 20
    offset: Offset = 0


class UserArguments(NoArguments):
    user_id: RecordId
    emails_offset: Offset = 0
    companies_offset: Offset = 0


class AgentReportArguments(NoArguments):
    staff_id: RecordId
    date_from: ISODate | None = None
    date_to: ISODate | None = None
    include_time: Flag = True

    @model_validator(mode="after")
    def valid_period(self):
        _check_range(self.date_from, self.date_to, "date")
        return self


class CatalogArguments(NoArguments):
    kind: CatalogKind


TOOL_ARGUMENT_MODELS = MappingProxyType({
    "test_connection": NoArguments,
    "list_tables": NoArguments,
    "describe_table": TableArguments,
    "sample_rows": SampleArguments,
    "list_catalog": CatalogArguments,
    "find_companies": CompanySearchArguments,
    "list_company_tickets": CompanyTicketsArguments,
    "search_tickets": SearchTicketsArguments,
    "count_tickets": TicketFilters,
    "ticket_report": TicketReportArguments,
    "get_ticket": TicketArguments,
    "get_ticket_thread": ThreadArguments,
    "search_ticket_content": SearchTicketContentArguments,
    "read_ticket_text": ReadTicketTextArguments,
    "find_agents": PeopleArguments,
    "get_agent_report": AgentReportArguments,
    "find_users": UserSearchArguments,
    "get_user": UserArguments,
})

EXPLORATION_TOOLS = frozenset({"list_tables", "describe_table", "sample_rows"})
