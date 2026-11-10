"""Public error codes and classification without inspecting exception messages."""

from enum import StrEnum
from types import MappingProxyType

from mysql.connector import errorcode
from mysql.connector.errors import (
    ConnectionTimeoutError, Error as MySQLError, ReadTimeoutError, WriteTimeoutError,
)


class AccessDeniedError(ValueError):
    """A table is outside the application access policy."""


class ConfigurationError(ValueError):
    """The server's database configuration is invalid."""


class ResultLimitError(ValueError):
    """A query produced more rows than the operation can return."""


class SchemaUnavailableError(ValueError):
    """The installed schema lacks a required, permitted relationship or field."""


class RecordNotFoundError(ValueError):
    """An explicitly requested identifier does not exist."""


class AmbiguousRecordError(ValueError):
    """A lookup expected a single record but found more than one."""


class ContentChangedError(ValueError):
    """A source field changed between searches or text pages."""


class ErrorCode(StrEnum):
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    ACCESS_DENIED = "ACCESS_DENIED"
    NO_PERMITTED_COLUMNS = "NO_PERMITTED_COLUMNS"
    NOT_FOUND = "NOT_FOUND"
    SCHEMA_UNAVAILABLE = "SCHEMA_UNAVAILABLE"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    CONTENT_CHANGED = "CONTENT_CHANGED"
    DATABASE_AUTHENTICATION_FAILED = "DATABASE_AUTHENTICATION_FAILED"
    DATABASE_PERMISSION_DENIED = "DATABASE_PERMISSION_DENIED"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    DATABASE_TIMEOUT = "DATABASE_TIMEOUT"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    DATABASE_QUERY_FAILED = "DATABASE_QUERY_FAILED"
    DATABASE_PROTECTION_UNAVAILABLE = "DATABASE_PROTECTION_UNAVAILABLE"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    RESULT_LIMIT_EXCEEDED = "RESULT_LIMIT_EXCEEDED"
    OUTPUT_LIMIT_EXCEEDED = "OUTPUT_LIMIT_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ERROR_DETAILS = MappingProxyType({
    ErrorCode.INVALID_ARGUMENTS: ("Invalid arguments. Use the tool's input schema.", False),
    ErrorCode.UNKNOWN_TOOL: ("Unknown tool.", False),
    ErrorCode.ACCESS_DENIED: ("Table is not available through this MCP.", False),
    ErrorCode.NO_PERMITTED_COLUMNS: ("No permitted columns are available for this table.", False),
    ErrorCode.NOT_FOUND: ("The requested record was not found.", False),
    ErrorCode.SCHEMA_UNAVAILABLE: ("The database does not provide the fields required for this query. Contact the administrator.", False),
    ErrorCode.AMBIGUOUS_MATCH: ("More than one record matches this identifier. Use its numeric ID.", False),
    ErrorCode.CONTENT_CHANGED: ("Text changed. Restart reading at offset 0 without the previous revision.", False),
    ErrorCode.DATABASE_AUTHENTICATION_FAILED: (
        "Database authentication failed. Contact the service administrator.", False,
    ),
    ErrorCode.DATABASE_PERMISSION_DENIED: (
        "The database account does not have permission for this operation.", False,
    ),
    ErrorCode.DATABASE_UNAVAILABLE: ("The database is unavailable. Try again later.", True),
    ErrorCode.DATABASE_TIMEOUT: ("Database communication timed out. Try again later.", True),
    ErrorCode.QUERY_TIMEOUT: ("The query timed out. Request a smaller sample or try again later.", True),
    ErrorCode.DATABASE_QUERY_FAILED: (
        "The database could not complete the operation. Contact the service administrator.", False,
    ),
    ErrorCode.DATABASE_PROTECTION_UNAVAILABLE: (
        "The database cannot enable the required protections. Contact the service administrator.", False,
    ),
    ErrorCode.CONFIGURATION_ERROR: (
        "The database service configuration is invalid. Contact the service administrator.", False,
    ),
    ErrorCode.RESULT_LIMIT_EXCEEDED: ("The query exceeded its row limit. Request a smaller sample.", False),
    ErrorCode.OUTPUT_LIMIT_EXCEEDED: ("Response exceeds output limits. Request a smaller sample.", False),
    ErrorCode.INTERNAL_ERROR: ("The service could not complete the operation. Contact the administrator.", False),
})


def public_error(code: ErrorCode) -> dict:
    message, retryable = ERROR_DETAILS[code]
    return {"code": code.value, "message": message, "retryable": retryable}


def classify_error(exc: Exception) -> ErrorCode:
    """Use exception types and numeric driver codes; never stringify an exception."""
    if isinstance(exc, AccessDeniedError):
        return ErrorCode.ACCESS_DENIED
    if isinstance(exc, ConfigurationError):
        return ErrorCode.CONFIGURATION_ERROR
    if isinstance(exc, ResultLimitError):
        return ErrorCode.RESULT_LIMIT_EXCEEDED
    if isinstance(exc, SchemaUnavailableError):
        return ErrorCode.SCHEMA_UNAVAILABLE
    if isinstance(exc, RecordNotFoundError):
        return ErrorCode.NOT_FOUND
    if isinstance(exc, AmbiguousRecordError):
        return ErrorCode.AMBIGUOUS_MATCH
    if isinstance(exc, ContentChangedError):
        return ErrorCode.CONTENT_CHANGED
    if isinstance(exc, ConnectionTimeoutError):
        return ErrorCode.DATABASE_TIMEOUT
    if isinstance(exc, (ReadTimeoutError, WriteTimeoutError, TimeoutError)):
        return ErrorCode.DATABASE_TIMEOUT
    if isinstance(exc, MySQLError):
        number = exc.errno if type(exc.errno) is int else None
        if number in {errorcode.ER_ACCESS_DENIED_ERROR, errorcode.ER_ACCESS_DENIED_NO_PASSWORD_ERROR}:
            return ErrorCode.DATABASE_AUTHENTICATION_FAILED
        if number in {
            errorcode.ER_DBACCESS_DENIED_ERROR, errorcode.ER_TABLEACCESS_DENIED_ERROR,
            errorcode.ER_COLUMNACCESS_DENIED_ERROR, errorcode.ER_SPECIFIC_ACCESS_DENIED_ERROR,
            errorcode.ER_CANT_EXECUTE_IN_READ_ONLY_TRANSACTION,
        }:
            return ErrorCode.DATABASE_PERMISSION_DENIED
        # MariaDB uses 1969 (ER_STATEMENT_TIMEOUT) for max_statement_time.
        if number in {errorcode.ER_QUERY_TIMEOUT, errorcode.ER_QUERY_INTERRUPTED, 1969}:
            return ErrorCode.QUERY_TIMEOUT
        if number in {
            errorcode.CR_CONNECTION_ERROR, errorcode.CR_CONN_HOST_ERROR,
            errorcode.CR_SERVER_GONE_ERROR, errorcode.CR_SERVER_LOST,
            errorcode.CR_SERVER_LOST_EXTENDED,
        }:
            return ErrorCode.DATABASE_UNAVAILABLE
        if number in {errorcode.ER_UNKNOWN_SYSTEM_VARIABLE, errorcode.ER_NOT_SUPPORTED_YET}:
            return ErrorCode.DATABASE_PROTECTION_UNAVAILABLE
        return ErrorCode.DATABASE_QUERY_FAILED
    if isinstance(exc, OSError):
        return ErrorCode.DATABASE_UNAVAILABLE
    return ErrorCode.INTERNAL_ERROR
