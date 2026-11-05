"""Strict argument contracts shared by MCP schemas and server validation."""

from types import MappingProxyType
from typing import Annotated, Literal
from datetime import date

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

MAX_TABLE_NAME_LENGTH = 64
MAX_SAMPLE_ROWS = 100
MAX_OFFSET = 10000

TableName = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=MAX_TABLE_NAME_LENGTH, pattern=r"^[A-Za-z0-9_]+$"),
]
SampleLimit = Annotated[int, Field(strict=True, ge=1, le=MAX_SAMPLE_ROWS)]
BusinessLimit = Annotated[int, Field(strict=True, ge=1, le=50)]
CompanyId = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
Offset = Annotated[int, Field(strict=True, ge=0, le=MAX_OFFSET)]
EntryId = Annotated[int, Field(strict=True, ge=0, le=2147483647)]


def _company_name(value: str) -> str:
    normalized = value.strip()
    if len(normalized) < 2 or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise ValueError("Invalid company search name")
    return normalized


CompanyName = Annotated[
    str, Field(strict=True, min_length=2, max_length=120), AfterValidator(_company_name),
]


def _text(value: str) -> str:
    normalized = value.strip()
    if not normalized or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise ValueError("Invalid search text")
    return normalized


SearchText = Annotated[str, Field(strict=True, min_length=1, max_length=120), AfterValidator(_text)]
TicketNumber = Annotated[str, Field(strict=True, min_length=1, max_length=32), AfterValidator(_text)]


def _iso_date(value: str) -> str:
    date.fromisoformat(value)
    return value


ISODate = Annotated[
    str, Field(strict=True, min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$",
               json_schema_extra={"format": "date"}), AfterValidator(_iso_date),
]


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


class TicketFilters(NoArguments):
    company_id: CompanyId | None = None
    staff_id: CompanyId | None = None
    user_id: CompanyId | None = None
    status: SearchText | None = None
    created_from: ISODate | None = None
    created_to: ISODate | None = None
    subject: SearchText | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.created_from and self.created_to and self.created_from > self.created_to:
            raise ValueError("created_from must not be later than created_to")
        if self.created_to == "9999-12-31":
            raise ValueError("created_to is outside the supported date range")
        return self


class SearchTicketsArguments(TicketFilters):
    limit: BusinessLimit = 20
    offset: Offset = 0
    order: Literal["newest", "oldest"] = "newest"


class CompanyTicketsArguments(SearchTicketsArguments):
    company_id: CompanyId
    limit: BusinessLimit = 10


class TicketArguments(NoArguments):
    model_config = ConfigDict(strict=True, extra="forbid", json_schema_extra={
        "oneOf": [
            {"required": ["ticket_id"], "properties": {"ticket_id": {"type": "integer"}, "number": {"type": "null"}}},
            {"required": ["number"], "properties": {"number": {"type": "string"}, "ticket_id": {"type": "null"}}},
        ],
    })
    ticket_id: CompanyId | None = None
    number: TicketNumber | None = None

    @model_validator(mode="after")
    def one_identifier(self):
        if (self.ticket_id is None) == (self.number is None):
            raise ValueError("Provide exactly one of ticket_id or number")
        return self


class ThreadArguments(NoArguments):
    ticket_id: CompanyId
    after_entry_id: EntryId = 0
    limit: BusinessLimit = 20


class PeopleArguments(NoArguments):
    name: CompanyName
    limit: BusinessLimit = 20
    offset: Offset = 0


TOOL_ARGUMENT_MODELS = MappingProxyType({
    "test_connection": NoArguments,
    "list_tables": NoArguments,
    "describe_table": TableArguments,
    "sample_rows": SampleArguments,
    "find_companies": CompanySearchArguments,
    "list_company_tickets": CompanyTicketsArguments,
    "search_tickets": SearchTicketsArguments,
    "count_tickets": TicketFilters,
    "get_ticket": TicketArguments,
    "get_ticket_thread": ThreadArguments,
    "find_agents": PeopleArguments,
    "find_users": PeopleArguments,
})
