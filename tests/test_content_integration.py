"""P3 SQL against disposable loopback databases; never production credentials."""

import hashlib
import json
import os

import mysql.connector
import pytest

from mcp_mysql import tickets, tools
from mcp_mysql.config import MySQLConfig
from mcp_mysql.responses import MAX_RESPONSE_BYTES

pytestmark = pytest.mark.skipif(not os.environ.get('MCP_TEST_MYSQL_PORT'),
                                reason='Requires an explicit disposable MySQL port')
NEEDLE = 'P3-MENTION-TAIL'
LITERAL = "_%= ' OR 1=1 --"
BODY = '<p>' + '😀'*70000 + NEEDLE + ' ' + LITERAL + '</p>'


@pytest.fixture(scope='module')
def content_database(isolated_database):
    cfg=isolated_database
    admin=mysql.connector.connect(host='127.0.0.1',port=cfg.port,user='root',password='',
                                  database=cfg.database,charset='utf8mb4',use_pure=True)
    cursor=admin.cursor()
    cursor.executemany('INSERT INTO ost_ticket (ticket_id,number,status_id,dept_id,user_id,staff_id,created,closed) '
                       'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',[
        (91001,'P3-0001',2,1,9,10,'2026-11-05 12:00:00','2026-11-06 13:00:00'),
        (91002,'P3-0002',1,2,8,7,'2026-10-01 12:00:00',None)])
    cursor.executemany('INSERT INTO ost_ticket__cdata '
                       '(ticket_id,subject,causa,analisis,solucion,ambiente,listaEmpresa) VALUES (%s,%s,%s,%s,%s,%s,%s)',[
        (91001,NEEDLE+' subject',NEEDLE+' cause',NEEDLE+' analysis',NEEDLE+' solution',NEEDLE+' environment','218,HOSPICIO'),
        (91002,'Other',None,None,None,None,'219,Otra empresa')])
    cursor.executemany('INSERT INTO ost_thread (id,object_id,object_type) VALUES (%s,%s,%s)',
                       [(190001,91001,'T'),(190002,91002,'T'),(190003,91001,'A')])
    cursor.executemany('INSERT INTO ost_thread_entry (id,thread_id,type,title,body,format) VALUES (%s,%s,%s,%s,%s,%s)',[
        (191001,190001,'M',NEEDLE+' title',BODY,'html'),
        (191002,190001,'N','Note',NEEDLE+' internal note','text'),
        (191003,190002,'R','Reply',NEEDLE+' other ticket','text'),
        (191004,190003,'M','Task',NEEDLE+' task must not leak','text')])
    admin.commit()
    try:
        yield cfg,admin
    finally:
        cursor.close()
        admin.close()


@pytest.fixture
def content_live(content_database,monkeypatch):
    cfg,_=content_database
    monkeypatch.setattr(MySQLConfig,'from_env',lambda:cfg)
    tickets.clear_schema_cache()


def payload(encoded):
    value=json.loads(encoded)
    assert value['ok'],value['error']
    return value['data']


def test_source_pages_reconstruct_all_unicode_and_html_beyond_old_prefix_cap(content_live):
    preview=json.loads(tools.get_ticket_thread(91001,limit=1))
    assert preview['meta']['truncated']
    parts,offset,revision=[],0,None
    while True:
        encoded=tools.read_ticket_text(91001,'thread_body',entry_id=191001,offset=offset,revision=revision)
        value=json.loads(encoded)
        assert value['ok'] and not value['meta']['truncated']
        assert len(encoded.encode())<=MAX_RESPONSE_BYTES
        data=value['data']
        assert data['number']=='P3-0001' and data['source_format']=='html'
        assert data['total_characters']==len(BODY)
        assert data['revision']==hashlib.sha256(('T'+BODY).encode()).hexdigest()
        parts.append(data['text']);revision=data['revision']
        if not data['has_more']:
            assert data['next_offset'] is None
            break
        assert data['next_offset']>offset
        offset=data['next_offset']
    assert ''.join(parts)==BODY
    assert NEEDLE not in preview['data']['rows'][0]['body']


def test_mentions_page_across_fields_entries_and_tickets_with_readable_references(content_live):
    cursor=None
    found=[]
    while True:
        page=payload(tools.search_ticket_content(NEEDLE,limit=2,cursor=cursor))
        assert page['coverage_complete'] and not page['unavailable_fields']
        for row in page['rows']:
            found.append((row['field'],row['ticket_id'],row['entry_id']))
            options={'offset':row['snippet_offset'],'limit':240,'revision':row['revision']}
            if row['entry_id'] is not None:options['entry_id']=row['entry_id']
            source=payload(tools.read_ticket_text(row['ticket_id'],row['field'],**options))
            assert source['text']==row['snippet']
            assert NEEDLE in row['snippet']
        if not page['has_more']:
            assert page['next_cursor'] is None
            break
        assert page['next_cursor']!=cursor
        cursor=page['next_cursor']
    expected={(name,91001,None) for name in ('subject','cause','analysis','solution','environment')}
    expected|={('thread_title',91001,191001),('thread_body',91001,191001),
               ('thread_body',91001,191002),('thread_body',91002,191003)}
    assert len(found)==len(set(found))==9 and set(found)==expected


def test_mentions_apply_ticket_filters_and_internal_note_scope(content_live):
    page=payload(tools.search_ticket_content(NEEDLE,fields=['thread_body'],entry_types=['internal_note'],
                 company_id=218,user_id=9,staff_id=10,state='closed',dept_id=1,
                 created_from='2026-11-05',created_to='2026-11-05'))
    assert [(r['ticket_id'],r['entry_id'],r['entry_type']) for r in page['rows']]==[(91001,191002,'internal_note')]
    assert not page['has_more']
    assert not payload(tools.search_ticket_content(NEEDLE,fields=['thread_body'],company_id=219,state='closed'))['rows']


def test_literal_wildcards_and_quotes_are_not_sql_or_patterns_and_search_beyond_65536(content_live):
    page=payload(tools.search_ticket_content(LITERAL,fields=['thread_body'],ticket_id=91001))
    assert len(page['rows'])==1
    row=page['rows'][0]
    assert row['entry_id']==191001 and row['match_offset']==BODY.index(LITERAL)>65536
    assert payload(tools.get_ticket(ticket_id=91001))['rows'][0]['number']=='P3-0001'


def test_reader_requires_correct_ticket_entry_association_and_excludes_tasks(content_live):
    for ticket,entry in [(91002,191001),(91001,191003),(91001,191004),(999999,191001)]:
        value=json.loads(tools.read_ticket_text(ticket,'thread_body',entry_id=entry))
        assert value['error']['code']=='NOT_FOUND'


def test_reader_detects_a_concurrent_edit_and_allows_restart(content_live,content_database):
    _,admin=content_database
    first=payload(tools.read_ticket_text(91001,'solution',limit=2))
    cursor=admin.cursor()
    try:
        cursor.execute('UPDATE ost_ticket__cdata SET solucion=%s WHERE ticket_id=%s',(NEEDLE+' changed 😀',91001))
        admin.commit()
        changed=json.loads(tools.read_ticket_text(91001,'solution',offset=2,revision=first['revision']))
        assert changed['error']['code']=='CONTENT_CHANGED' and changed['data'] is None
        restarted=payload(tools.read_ticket_text(91001,'solution'))
        assert restarted['text']==NEEDLE+' changed 😀' and restarted['revision']!=first['revision']
    finally:
        cursor.execute('UPDATE ost_ticket__cdata SET solucion=%s WHERE ticket_id=%s',(NEEDLE+' solution',91001))
        admin.commit();cursor.close()


def test_null_empty_and_finished_text_pages_keep_distinct_revisions(content_live,content_database):
    null=payload(tools.read_ticket_text(91002,'environment'))
    assert null['text'] is None and null['total_characters'] is None and not null['has_more']
    _,admin=content_database
    cursor=admin.cursor()
    try:
        cursor.execute('UPDATE ost_ticket__cdata SET ambiente=%s WHERE ticket_id=%s',('',91002))
        admin.commit()
        empty=payload(tools.read_ticket_text(91002,'environment'))
        assert empty['text']=='' and empty['total_characters']==0 and empty['revision']!=null['revision']
    finally:
        cursor.execute('UPDATE ost_ticket__cdata SET ambiente=NULL WHERE ticket_id=%s',(91002,))
        admin.commit();cursor.close()
    ended=payload(tools.read_ticket_text(91001,'solution',offset=10000))
    assert ended['text']=='' and not ended['has_more'] and ended['next_offset'] is None
