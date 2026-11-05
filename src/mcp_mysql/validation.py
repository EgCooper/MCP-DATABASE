"""Strict argument contracts shared by MCP schemas and server validation."""

from types import MappingProxyType
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

MAX_TABLE_NAME_LENGTH = 64
MAX_SAMPLE_ROWS = 100

TableName = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=MAX_TABLE_NAME_LENGTH, pattern=r"^[A-Za-z0-9_]+$"),
]
SampleLimit = Annotated[int, Field(strict=True, ge=1, le=MAX_SAMPLE_ROWS)]


class NoArguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class TableArguments(NoArguments):
    table_name: TableName


class SampleArguments(TableArguments):
    limit: SampleLimit = 10


TOOL_ARGUMENT_MODELS = MappingProxyType({
    "test_connection": NoArguments,
    "list_tables": NoArguments,
    "describe_table": TableArguments,
    "sample_rows": SampleArguments,
})
