"""P3: source completeness, safe references and consistent continuation."""

import asyncio
import base64
import hashlib
import json
from decimal import Decimal

import pytest

from mcp_mysql import tools
from mcp_mysql.responses import MAX_RESPONSE_BYTES
from mcp_mysql.server import mcp
from mcp_mysql.validation import SearchTicketContentArguments
from test_support_tools import database, data, error


def revision(text):
    return hashlib.sha256((('N' if text is None else 'T') + (text or '')).encode()).hexdigest()


def text_source(database, text, *, field='thread_body'):
    def respond(params):
        start, length = params[1] - 1, params[2]
        return [{'ticket_id': 123, 'number': '000123', 'entry_id': 7 if field.startswith('thread_') else None,
                 'type_code': 'N' if field.startswith('thread_') else None, 'source_format': 'html',
                 'text': text[start:start+length] if text is not None else None,
                 'total_characters': len(text) if text is not None else None, 'revision': revision(text)}]
    database.on('AS text', respond)


def match(identifier, *, source=0, text='needle', number='000123'):
    return {'source_index': source, 'record_id': identifier, 'ticket_id': identifier,
            'number': number, 'entry_id': identifier if source >= 5 else None,
            'type_code': 'N' if source >= 5 else None, 'source_format': 'text',
            'total_characters': 10000, 'match_offset': 9000, 'snippet_offset': 8960,
            'snippet': text, 'revision': revision('source')}


@pytest.mark.parametrize('name,args', [
    ('read_ticket_text', {'ticket_id': '1', 'field': 'subject'}),
    ('read_ticket_text', {'ticket_id': 1, 'field': 'thread_body'}),
    ('read_ticket_text', {'ticket_id': 1, 'field': 'subject', 'entry_id': 7}),
    ('read_ticket_text', {'ticket_id': 1, 'field': 'thread_body', 'entry_id': 0}),
    ('read_ticket_text', {'ticket_id': 1, 'field': 'subject', 'offset': -1}),
    ('read_ticket_text', {'ticket_id': 1, 'field': 'subject', 'offset': '20'}),
    ('read_ticket_text', {'ticket_id': 1, 'field': 'subject', 'offset': 4294967296}),
    ('read_ticket_text', {'ticket_id': 1, 'field': 'subject', 'limit': 2001}),
    ('read_ticket_text', {'ticket_id': 1, 'field': 'subject', 'limit': True}),
    ('read_ticket_text', {'ticket_id': 1, 'field': 'password'}),
    ('read_ticket_text', {'ticket_id': 1, 'field': 'subject', 'revision': 'secret'}),
    ('read_ticket_text', {'ticket_id': 1, 'field': 'subject', 'revision': 'z'*64}),
    ('read_ticket_text', {'ticket_id': 1, 'field': 'subject', 'sql': 'SELECT 1'}),
    ('search_ticket_content', {'query': ''}),
    ('search_ticket_content', {'query': 'x'*121}),
    ('search_ticket_content', {'query': 'needle\nline'}),
    ('search_ticket_content', {'query': 'needle', 'limit': 11}),
    ('search_ticket_content', {'query': 'needle', 'limit': '2'}),
    ('search_ticket_content', {'query': 'needle', 'fields': []}),
    ('search_ticket_content', {'query': 'needle', 'fields': ['subject','subject']}),
    ('search_ticket_content', {'query': 'needle', 'fields': ['password']}),
    ('search_ticket_content', {'query': 'needle', 'cursor': 'a'*40}),
    ('search_ticket_content', {'query': 'needle', 'entry_types': ['message','message']}),
    ('search_ticket_content', {'query': 'needle', 'fields': ['subject'], 'entry_types': ['message']}),
    ('search_ticket_content', {'query': 'needle', 'include_collaborations': True}),
    ('search_ticket_content', {'query': 'needle', 'ticket_id': False}),
])
def test_invalid_content_arguments_never_touch_database(database, name, args):
    result = asyncio.run(mcp.call_tool(name,args))
    assert result.isError
    assert error(result.content[0].text) == 'INVALID_ARGUMENTS'
    assert not database.calls


def test_complete_source_pages_preserve_html_unicode_and_all_characters(database):
    original = '<p>α😀 &amp; literal</p>\r\n' * 210 + 'END'
    text_source(database, original)
    parts, offset, checksum = [], 0, None
    while True:
        page = data(tools.read_ticket_text(123,'thread_body',entry_id=7,offset=offset,limit=701,revision=checksum))
        parts.append(page['text'])
        assert page['representation'] == 'stored_source' and page['source_format'] == 'html'
        assert page['total_characters'] == len(original)
        assert page['characters_returned'] == len(page['text'])
        checksum = page['revision']
        if not page['has_more']:
            assert page['next_offset'] is None
            break
        assert page['next_offset'] == offset + len(page['text'])
        offset = page['next_offset']
    assert ''.join(parts) == original
    statement, _ = database.queries('AS text')[0]
    assert "th.object_type = 'T'" in statement and 'e.id = %s' in statement
    assert 'SUBSTRING(e.`body`, %s, %s)' in statement


@pytest.mark.parametrize('value',[None,''])
def test_null_and_empty_text_are_distinct_and_have_no_continuation(database,value):
    text_source(database,value,field='analysis')
    page=data(tools.read_ticket_text(123,'analysis'))
    assert page['text'] == value
    assert page['total_characters'] == (None if value is None else 0)
    assert not page['has_more'] and page['next_offset'] is None


def test_text_revision_rejects_an_edit_without_exposing_the_changed_source(database):
    text_source(database,'private modified text')
    result=json.loads(tools.read_ticket_text(123,'thread_body',entry_id=7,revision=revision('old text')))
    assert result['error']['code']=='CONTENT_CHANGED' and not result['error']['retryable']
    assert result['data'] is None and 'private modified' not in json.dumps(result)


def test_nonexistent_entry_and_unavailable_column_are_explicit(database):
    assert error(tools.read_ticket_text(123,'thread_body',entry_id=7))=='NOT_FOUND'
    database.schema.columns['ost_thread_entry'].discard('body')
    assert error(tools.read_ticket_text(123,'thread_body',entry_id=7))=='SCHEMA_UNAVAILABLE'


def test_text_offsets_beyond_end_return_an_empty_finished_page(database):
    text_source(database,'finished',field='subject')
    page=data(tools.read_ticket_text(123,'subject',offset=100))
    assert page['text']=='' and page['total_characters']==8 and not page['has_more']


def test_search_uses_complete_columns_and_binds_literal_input_and_filters(database):
    needle="_%= ' OR 1=1 --"
    database.on('content_matches',[])
    result=data(tools.search_ticket_content(needle,fields=['thread_body','subject'],state='open',ticket_id=123))
    statement,params=database.queries('content_matches')[0]
    assert needle not in statement and needle in params
    assert 'LOCATE(%s, e.`body`)' in statement and 'LOCATE(%s, c.`subject`)' in statement
    assert 'LEFT(e.`body`' not in statement and "th.object_type = 'T'" in statement
    assert 'UNION ALL' in statement and 'open' in params and 123 in params
    assert result['matching']=='literal_stored_text_database_collation'
    assert result['row_count']==0 and not result['has_more'] and result['coverage_complete']


def test_search_cursor_pages_without_duplicates_and_allows_a_new_page_size(database):
    rows=[match(i) for i in (1,2,3)]
    database.on('content_matches',lambda p:[r for r in rows if r['record_id']>p[-4]][:p[-1]])
    first=data(tools.search_ticket_content('needle',fields=['subject'],limit=1))
    second=data(tools.search_ticket_content('needle',fields=['subject'],limit=2,cursor=first['next_cursor']))
    assert [r['ticket_id'] for r in first['rows']+second['rows']]==[1,2,3]
    assert first['has_more'] and not second['has_more'] and second['next_cursor'] is None


def test_union_numeric_references_remain_json_integers(database):
    database.on('content_matches',[match(Decimal(i),source=6) for i in (1,2)])
    page=data(tools.search_ticket_content('needle',fields=['thread_body'],limit=1))
    assert type(page['rows'][0]['ticket_id']) is int
    assert type(page['rows'][0]['entry_id']) is int
    continued=SearchTicketContentArguments(query='needle',fields=['thread_body'],cursor=page['next_cursor'])
    assert continued.cursor_position()==('thread_body',1)


def test_cursor_cannot_be_reused_with_changed_query_or_filters(database):
    arguments=SearchTicketContentArguments(query='needle',fields=['subject'])
    cursor=arguments.make_cursor('subject',12)
    for changed in ({'query':'different'}, {'query':'needle','ticket_id':123}):
        result=asyncio.run(mcp.call_tool('search_ticket_content',{**changed,'fields':['subject'],'cursor':cursor}))
        assert error(result.content[0].text)=='INVALID_ARGUMENTS'
    assert not database.calls


def test_cursor_rejects_invalid_version_and_boolean_ids(database):
    args=SearchTicketContentArguments(query='needle')
    for field,value in [('v',True),('v',2),('after',True),('after',0),('after','3'),('field','password')]:
        payload={'v':1,'field':'subject','after':3,'identity':args._cursor_identity(),field:value}
        cursor=base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        result=asyncio.run(mcp.call_tool('search_ticket_content',{'query':'needle','cursor':cursor}))
        assert error(result.content[0].text)=='INVALID_ARGUMENTS'
    assert not database.calls


def test_unavailable_sources_are_reported_instead_of_claiming_complete_search(database):
    database.schema.columns['ost_thread_entry'].discard('body')
    result=data(tools.search_ticket_content('needle',fields=['subject','thread_body']))
    assert result['unavailable_fields']==['thread_body'] and not result['coverage_complete']
    assert result['searched_fields']==['subject'] and not result['has_more']
    assert error(tools.search_ticket_content('needle',fields=['thread_body']))=='SCHEMA_UNAVAILABLE'


def test_search_pages_fit_the_output_budget_without_shortening_a_cursor_page(database):
    database.on('content_matches',[match(i,text='😀'*240,number='😀'*33) for i in range(1,12)])
    encoded=tools.search_ticket_content('😀'*120,fields=['subject'],subject='😀'*120,status='😀'*120)
    payload=json.loads(encoded)
    assert len(encoded.encode())<=MAX_RESPONSE_BYTES
    assert len(payload['data']['rows'])==10 and payload['data']['next_cursor']
    assert payload['meta']['truncated'] is False
    text_source(database,'😀'*4000,field='subject')
    encoded=tools.read_ticket_text(123,'subject')
    payload=json.loads(encoded)
    assert len(encoded.encode())<=MAX_RESPONSE_BYTES and len(payload['data']['text'])==2000
    assert payload['meta']['truncated'] is False and payload['data']['next_offset']==2000
