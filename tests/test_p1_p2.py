import json
from unittest.mock import Mock

import pytest

from mcp_mysql import db, readiness, server, tools, observability
from test_support_tools import database, data
from test_server_cli import _request, _echo_app, TOKEN


def test_closure_actor_is_distinct_from_assignee_and_counts_events(database):
    database.on('FROM ost_staff a', [{'staff_id': 7, 'name': 'Agent'}])
    database.on('COUNT(*) AS total', [{'total': 99}])
    database.on('AS tickets_closed_by_agent', [{'tickets_closed_by_agent': 2, 'closure_events': 3}])
    report = data(tools.get_agent_report(7, date_from='2026-10-01', date_to='2026-10-31'))
    assert report['actor_activity'] == {'tickets_closed_by_agent': 2, 'closure_events': 3}
    assert report['in_period']['assigned_tickets_closed'] == 99
    query, parameters = database.queries('AS tickets_closed_by_agent')[0]
    assert 'e.uid = %s' in query and 'e.annulled = 0' in query and 'e.staff_id' not in query
    assert parameters == ('closed', 'S', 7, '2026-10-01', '2026-11-01')
    assert 'not tickets created by this agent' in report['metric_definitions']['assigned_tickets_created']


def test_missing_actor_history_is_unavailable_not_zero(database):
    database.on('FROM ost_staff a', [{'staff_id': 7, 'name': 'Agent'}])
    database.on('COUNT(*) AS total', [{'total': 0}])
    database.schema.columns.pop('ost_thread_event')
    report = data(tools.get_agent_report(7))
    assert report['actor_activity'] is None and 'actor_activity' in report['unavailable_fields']


def test_agent_name_tokens_handle_whitespace_and_explicit_ambiguity(database):
    database.on('FROM ost_staff a', [{'staff_id': 1, 'name': 'Ana One'}, {'staff_id': 2, 'name': 'Ana Two'}])
    result = data(tools.find_agents('Ana  One'))
    assert result['resolution']['must_wait_for_user']
    query, parameters = database.calls[-1]
    assert "TRIM(a.firstname)" in query and ' AND ' in query
    assert parameters[-4:] == ('%Ana%', '%One%', 21, 0)


def test_ready_is_authenticated_and_health_remains_liveness(monkeypatch):
    probe = Mock(return_value={'status': 'not_ready', 'code': 'DATABASE_UNAVAILABLE'})
    monkeypatch.setattr(readiness, 'probe', probe)
    gate = server.HttpGate(_echo_app, TOKEN)
    assert _request(gate, method='GET', path='/health').status_code == 200
    assert _request(gate, method='GET', path='/ready').status_code == 401
    probe.assert_not_called()
    reply = _request(gate, method='GET', path='/ready', headers={'Authorization': f'Bearer {TOKEN}'})
    assert reply.status_code == 503 and reply.json()['code'] == 'DATABASE_UNAVAILABLE'
    probe.return_value = {'status': 'ready'}
    assert _request(gate, method='GET', path='/ready', headers={'Authorization': f'Bearer {TOKEN}'}).status_code == 200


def test_metrics_are_authenticated_and_do_not_expose_unknown_labels(monkeypatch):
    monkeypatch.setattr(readiness, 'probe', lambda: {'status': 'ready'})
    observability.record_call('PRIVATE_SEARCH', 'PRIVATE_ERROR', 0.2, False)
    gate = server.HttpGate(_echo_app, TOKEN)
    assert _request(gate, method='GET', path='/metrics').status_code == 401
    response = _request(gate, method='GET', path='/metrics', headers={'Authorization': f'Bearer {TOKEN}'})
    assert response.status_code == 200 and 'mcp_database_ready 1' in response.text
    assert 'PRIVATE' not in response.text and 'tool="unknown"' in response.text


def test_probe_closes_protected_connection_and_keeps_driver_errors_private(monkeypatch):
    conn = Mock()
    conn.unread_result = False
    conn.cursor.return_value.fetchone.return_value = (1,)
    connect = Mock(return_value=conn)
    monkeypatch.setattr(readiness, 'get_connection', connect)
    assert readiness.probe() == {'status': 'ready'}
    config = connect.call_args.args[0]
    assert config.connection_timeout == config.read_timeout == 2 and config.query_timeout_ms == 1000
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()
    connect.side_effect = OSError('PRIVATE_DATABASE_PASSWORD')
    result = readiness.probe()
    assert result == {'status': 'not_ready', 'code': 'DATABASE_UNAVAILABLE'}
