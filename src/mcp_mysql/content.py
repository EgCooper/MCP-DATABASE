"""Complete source-text pages and literal content references, with bounded DB reads.

All column names come from the fixed maps below. Source text is intentionally not
HTML-normalized: offsets refer to the stored characters and can be reconstructed
without losing tags, entities or text beyond the normal summary limits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_mysql import db
from mcp_mysql.errors import ContentChangedError, RecordNotFoundError, SchemaUnavailableError
from mcp_mysql.threads import ENTRY_CODES, ENTRY_TYPES
from mcp_mysql.validation import CONTENT_FIELDS, ReadTicketTextArguments, SearchTicketContentArguments, TicketFilters

if TYPE_CHECKING:
    from mcp_mysql.tickets import Schema, TicketQuery

_TICKET_FIELDS = {"subject": "subject", "cause": "causa", "analysis": "analisis",
                  "solution": "solucion", "environment": "ambiente"}
_THREAD_FIELDS = {"thread_title": "title", "thread_body": "body"}
_THREAD_REQUIRED = {"ost_thread": ("id", "object_id", "object_type"),
                    "ost_thread_entry": ("id", "thread_id", "type")}
_THREAD_JOIN = (" JOIN ost_thread th ON th.object_type = 'T' AND th.object_id = t.ticket_id"
                " JOIN ost_thread_entry e ON e.thread_id = th.id")
_SNIPPET_CONTEXT = 40
_SNIPPET_CHARACTERS = 240


def _revision(column: str) -> str:
    # NULL and empty text have distinct revisions. A revision is an edit guard,
    # not an authorization token; all users intentionally share the same access.
    return f"SHA2(CONCAT(IF({column} IS NULL, 'N', 'T'), COALESCE({column}, '')), 256)"


def _check_revision(value) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise SchemaUnavailableError("Text revisions are unavailable")
    return value


def _format(schema: Schema, field: str) -> str:
    if field == 'thread_body' and schema.has('ost_thread_entry', 'format'):
        return "CASE WHEN LOWER(e.`format`) = 'html' THEN 'html' ELSE 'text' END"
    return "'text'" if field == 'thread_title' else "NULL"


def _thread_available(schema: Schema) -> bool:
    return all(schema.has(table, column) for table, columns in _THREAD_REQUIRED.items() for column in columns)


def read_text(arguments: ReadTicketTextArguments, schema: Schema) -> dict:
    schema.require('ost_ticket', 'ticket_id')
    is_thread = arguments.field in _THREAD_FIELDS
    if is_thread:
        for table, columns in _THREAD_REQUIRED.items():
            schema.require(table, *columns)
        column = _THREAD_FIELDS[arguments.field]
        schema.require('ost_thread_entry', column)
        value = f'e.`{column}`'
        source = 'FROM ost_ticket t' + _THREAD_JOIN
        identity, identities = 't.ticket_id = %s AND e.id = %s', (arguments.ticket_id, arguments.entry_id)
        entry = 'e.id AS entry_id, e.type AS type_code'
    else:
        column = _TICKET_FIELDS[arguments.field]
        schema.require('ost_ticket__cdata', 'ticket_id', column)
        value = f'c.`{column}`'
        source = 'FROM ost_ticket t LEFT JOIN ost_ticket__cdata c ON c.ticket_id = t.ticket_id'
        identity, identities = 't.ticket_id = %s', (arguments.ticket_id,)
        entry = 'NULL AS entry_id, NULL AS type_code'
    number = 'LEFT(t.number, %s)' if schema.has('ost_ticket', 'number') else 'NULL'
    number_parameters = (33,) if number != 'NULL' else ()
    row = db.fetch_one(
        f"""SELECT t.ticket_id, {number} AS number, {entry}, {_format(schema, arguments.field)} AS source_format,
                   CHAR_LENGTH({value}) AS total_characters, {_revision(value)} AS revision,
                   SUBSTRING({value}, %s, %s) AS text
            {source} WHERE {identity}""",
        (*number_parameters, arguments.offset + 1, arguments.limit, *identities),
    )
    if row is None:
        raise RecordNotFoundError('Ticket or associated thread entry not found')
    revision = _check_revision(row.get('revision'))
    if arguments.revision is not None and arguments.revision != revision:
        raise ContentChangedError('Text changed')
    text = row.get('text')
    if text is not None and not isinstance(text, str):
        raise SchemaUnavailableError('Content is not a text field')
    total = int(row['total_characters']) if row.get('total_characters') is not None else None
    returned = len(text) if text is not None else 0
    next_offset = arguments.offset + returned
    more = total is not None and next_offset < total
    if more and not returned:
        raise SchemaUnavailableError('Text continuation cannot advance')
    entry_id = int(row['entry_id']) if row.get('entry_id') is not None else None
    return {'ticket_id': arguments.ticket_id, 'number': row.get('number'), 'field': arguments.field,
            'entry_id': entry_id, 'entry_type': ENTRY_TYPES.get(row.get('type_code'), 'other') if entry_id is not None else None,
            'representation': 'stored_source', 'source_format': row.get('source_format'),
            'offset': arguments.offset, 'characters_returned': returned, 'total_characters': total,
            'revision': revision, 'text': text, 'has_more': more,
            'next_offset': next_offset if more else None}


def search(arguments: SearchTicketContentArguments, query: TicketQuery) -> dict:
    requested = list(arguments.fields or CONTENT_FIELDS)
    available = [field for field in requested if (
        query.has('c', _TICKET_FIELDS[field]) if field in _TICKET_FIELDS else
        _thread_available(query.schema) and query.schema.has('ost_thread_entry', _THREAD_FIELDS[field]))]
    unavailable = [field for field in requested if field not in available]
    if not available:
        raise SchemaUnavailableError('None of the requested text fields is available')
    where, filters, _, needed = query.where(arguments)
    position = arguments.cursor_position()
    first = CONTENT_FIELDS.index(position[0]) if position else 0
    selects, parameters = [], []
    for field in available:
        index = CONTENT_FIELDS.index(field)
        if index < first:
            continue
        is_thread = field in _THREAD_FIELDS
        value = f'e.`{_THREAD_FIELDS[field]}`' if is_thread else f'c.`{_TICKET_FIELDS[field]}`'
        source, source_parameters = query.source(needed | (set() if is_thread else {'c'}))
        if is_thread:
            source += _THREAD_JOIN
        identifier = 'e.id' if is_thread else 't.ticket_id'
        entry = 'e.id AS entry_id, e.type AS type_code' if is_thread else 'NULL AS entry_id, NULL AS type_code'
        number = 'LEFT(t.number, %s)' if query.has('t', 'number') else 'NULL'
        values = [33] if number != 'NULL' else []
        values.extend((arguments.query, arguments.query, _SNIPPET_CONTEXT,
                       arguments.query, _SNIPPET_CONTEXT, _SNIPPET_CHARACTERS))
        conditions = [where[6:]] if where else []
        conditions.extend((f'{identifier} > %s', f'LOCATE(%s, {value}) > 0'))
        after = position[1] if position and index == first else 0
        tail = [*source_parameters, *filters, after, arguments.query]
        if arguments.ticket_id is not None:
            conditions.append('t.ticket_id = %s')
            tail.append(arguments.ticket_id)
        if is_thread and arguments.entry_types:
            codes = [ENTRY_CODES[kind] for kind in arguments.entry_types]
            conditions.append(f"e.type IN ({', '.join('%s' for _ in codes)})")
            tail.extend(codes)
        selects.append(f"""(SELECT {index} AS source_index, {identifier} AS record_id,
            t.ticket_id, {number} AS number, {entry}, {_format(query.schema, field)} AS source_format,
            CHAR_LENGTH({value}) AS total_characters, LOCATE(%s, {value}) - 1 AS match_offset,
            GREATEST(1, LOCATE(%s, {value}) - %s) - 1 AS snippet_offset,
            SUBSTRING({value}, GREATEST(1, LOCATE(%s, {value}) - %s), %s) AS snippet,
            {_revision(value)} AS revision
            {source} WHERE {' AND '.join(conditions)}
            ORDER BY record_id ASC LIMIT %s)""")
        parameters.extend((*values, *tail, arguments.limit + 1))
    # A single bounded statement gives every source the same query timeout.
    # Each branch returns only limit+1 rows, and the outer page is bounded again.
    raw = db.fetch_all(
        'SELECT source_index, record_id, ticket_id, number, entry_id, type_code, source_format, '
        'total_characters, match_offset, snippet_offset, snippet, revision FROM (' +
        ' UNION ALL '.join(selects) + ') content_matches ORDER BY source_index ASC, record_id ASC LIMIT %s',
        (*parameters, arguments.limit + 1),
    ) if selects else []
    more = len(raw) > arguments.limit
    rows = []
    for row in raw[:arguments.limit]:
        field = CONTENT_FIELDS[int(row['source_index'])]
        # MariaDB can promote the NULL/unsigned-ID UNION column to DECIMAL.
        # Public references must remain JSON integers so strict readers accept them.
        entry_id = int(row['entry_id']) if row.get('entry_id') is not None else None
        rows.append({'ticket_id': int(row['ticket_id']), 'number': row.get('number'), 'field': field,
                     'entry_id': entry_id,
                     'entry_type': ENTRY_TYPES.get(row.get('type_code'), 'other') if entry_id is not None else None,
                     'source_format': row.get('source_format'), 'representation': 'stored_source',
                     'total_characters': int(row['total_characters']),
                     'match_offset': int(row['match_offset']), 'snippet_offset': int(row['snippet_offset']),
                     'snippet': row['snippet'], 'revision': _check_revision(row.get('revision'))})
    last = raw[arguments.limit - 1] if more else None
    next_cursor = arguments.make_cursor(CONTENT_FIELDS[int(last['source_index'])], int(last['record_id'])) if last else None
    return {'query': arguments.query, 'rows': rows, 'row_count': len(rows), 'limit': arguments.limit,
            'has_more': more, 'next_cursor': next_cursor, 'searched_fields': available,
            'unavailable_fields': unavailable, 'coverage_complete': not unavailable,
            'match_unit': 'first_occurrence_per_field_or_entry',
            'matching': 'literal_stored_text_database_collation',
            'filters': arguments.model_dump(include=set(TicketFilters.model_fields), exclude_defaults=True)}
