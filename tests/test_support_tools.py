"""Support-agent tools: reports, ticket detail, threads, customers and catalogs (simulated DB)."""

import asyncio
import json
import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcp_mysql import access, db, tickets, tools
from mcp_mysql.server import mcp


class FakeDatabase:
    """Answer queries by matching SQL fragments; record every statement for invariant checks."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []
        self.rules: list[tuple[str, object]] = []

    def on(self, fragment: str, rows) -> None:
        self.rules.insert(0, (fragment, rows))

    def fetch_all(self, query, params=None, *, max_rows=1000):
        params = tuple(params or ())
        self.calls.append((query, params))
        for fragment, rows in self.rules:
            if fragment in query:
                return list(rows(params) if callable(rows) else rows)
        return []

    def fetch_one(self, query, params=None):
        rows = self.fetch_all(query, params, max_rows=1)
        return rows[0] if rows else None

    def queries(self, fragment: str) -> list[tuple[str, tuple]]:
        return [call for call in self.calls if fragment in call[0]]


def full_schema() -> tickets.Schema:
    return tickets.Schema({table: {c.casefold() for c in cols} for table, cols in access.all_query_tables().items()})


@pytest.fixture
def database(monkeypatch):
    monkeypatch.setattr(db, "get_connection", Mock(side_effect=AssertionError("No real connections")))
    fake = FakeDatabase()
    monkeypatch.setattr(db, "fetch_all", fake.fetch_all)
    monkeypatch.setattr(db, "fetch_one", fake.fetch_one)
    schema = full_schema()
    monkeypatch.setattr(tickets, "_load_schema", lambda: schema)
    fake.schema = schema
    yield fake
    for query, params in fake.calls:
        # Connector/Python only substitutes %s and does not unescape %%: any other % breaks the SQL.
        assert query.count("%s") == len(params), query
        assert not re.search(r"%(?!s)", query), query


def data(encoded: str) -> dict:
    payload = json.loads(encoded)
    assert payload["ok"] is True, payload["error"]
    return payload["data"]


def error(encoded: str) -> str:
    return json.loads(encoded)["error"]["code"]


# Reports ----------------------------------------------------------------------------------

def test_report_groups_on_the_server_with_bound_time_patterns(database):
    database.on("GROUP BY group_key", [
        {"group_key": 7, "label": "Ana Pérez", "tickets": 12, "time_seconds": 5400, "overtime_seconds": 0, "time_unparsed": 1},
        {"group_key": 8, "label": "Luis", "tickets": 3, "time_seconds": 0, "overtime_seconds": 1800, "time_unparsed": 0},
    ])
    database.on("COUNT(*) AS total", [{"total": 15}])
    result = data(tools.ticket_report("agent", state="open", include_time=True, created_from="2026-01-01"))
    assert result["total_tickets"] == 15 and result["has_more"] is False
    assert result["groups"][0] == {
        "key": 7, "label": "Ana Pérez", "tickets": 12, "recorded_time": {"hhmm": "1:30", "hours": 1.5},
        "overtime": {"hhmm": "0:00", "hours": 0.0}, "unparsed_time_values": 1,
    }
    query, params = database.queries("GROUP BY group_key")[0]
    assert "ORDER BY tickets DESC, group_key ASC" in query and "TIME_TO_SEC" in query
    assert tickets.DURATION_PATTERN in params and "open" in params
    assert result["filters"] == {"state": "open", "created_from": "2026-01-01"}


def test_month_report_binds_the_date_format_and_reads_chronologically(database):
    database.on("GROUP BY group_key", [{"group_key": "2026-01", "label": None, "tickets": 4}])
    result = data(tools.ticket_report("month"))
    assert result["groups"] == [{"key": "2026-01", "label": "2026-01", "tickets": 4}]
    query, params = database.queries("GROUP BY group_key")[0]
    assert "DATE_FORMAT(t.`created`, %s)" in query and params[0] == "%Y-%m"
    assert "ORDER BY group_key ASC" in query


def test_report_limit_reports_more_groups(database):
    database.on("GROUP BY group_key", [{"group_key": i, "label": f"E{i}", "tickets": 10 - i} for i in range(3)])
    result = data(tools.ticket_report("company", limit=2))
    assert result["group_count"] == 2 and result["has_more"] is True
    assert database.queries("GROUP BY group_key")[0][1][-1] == 3


@pytest.mark.parametrize("arguments", [
    {"group_by": "passwd"}, {"group_by": "agent; DROP TABLE ost_ticket"}, {"group_by": "agent", "limit": 101},
    {"group_by": "agent", "include_time": "yes"}, {"group_by": "agent", "order_by": "tickets"}, {},
])
def test_invalid_report_arguments_fail_before_database_work(database, arguments):
    assert error(asyncio.run(mcp.call_tool("ticket_report", arguments)).content[0].text) == "INVALID_ARGUMENTS"
    assert database.calls == []


# Filters ------------------------------------------------------------------------------------

def test_new_filters_are_parameterized_and_require_their_joins(database):
    database.on("COUNT(*) AS total", [{"total": 3}])
    data(tools.count_tickets(state="open", dept_id=4, priority_id=3, overdue=True, assigned=False,
                             closed_from="2026-10-01", closed_to="2026-10-31", topic_id=2))
    query, params = database.queries("COUNT(*) AS total")[0]
    assert "s.state = %s" in query and "c.`priority` = %s" in query and "t.`isoverdue` = %s" in query
    assert "COALESCE(t.`staff_id`, 0) = 0" in query and "t.closed < %s" in query
    assert params == ("open", 4, "3", 2, 1, "2026-10-01", "2026-11-01")
    assert "JOIN `ost_staff`" not in query and "JOIN `ost_department`" not in query


def test_collaborations_match_requester_or_cc_with_bound_ids(database):
    data(tools.search_tickets(user_id=8, include_collaborations=True))
    query, params = database.queries("ORDER BY t.created DESC")[0]
    assert "EXISTS (SELECT 1 FROM ost_thread th JOIN ost_thread_collaborator tc" in query
    assert params[-4:] == (8, 8, 21, 0)


def test_last_updated_order_is_a_constant(database):
    result = data(tools.search_tickets(order="last_updated", limit=1))
    assert result["order"] == "last_updated_first"
    assert "ORDER BY t.lastupdate DESC, t.ticket_id DESC" in database.calls[-1][0]


@pytest.mark.parametrize("arguments", [
    {"include_collaborations": True}, {"assigned": False, "staff_id": 7},
    {"closed_from": "2026-11-02", "closed_to": "2026-11-01"}, {"state": "pending"}, {"overdue": 1},
    {"priority_id": 0}, {"order": "lastupdate DESC"},
])
def test_inconsistent_filters_are_rejected(database, arguments):
    assert error(asyncio.run(mcp.call_tool("search_tickets", arguments)).content[0].text) == "INVALID_ARGUMENTS"
    assert database.calls == []


def test_missing_status_state_column_is_reported_not_ignored(database):
    database.schema.columns["ost_ticket_status"].discard("state")
    assert error(tools.count_tickets(state="open")) == "SCHEMA_UNAVAILABLE"
    assert database.calls == []


# Ticket detail --------------------------------------------------------------------------------

def test_detail_merges_support_staff_collaborators_and_thread_summary(database):
    database.on("WHERE t.`ticket_id` = %s", [{
        "ticket_id": 90, "number": "000090", "subject": "Caída", "_apoyo1": "Ana Pérez", "_timeApoyo1": "1:15",
        "_apoyo2": '{"s9":"Luis Prueba"}', "_timeApoyo2": "0:30", "_apoyo3": None, "_timeApoyo3": None,
    }])
    database.on("FROM ost_form_entry e", [{"field": "apoyo1", "value": '{"s7":"Ana Pérez"}'}])
    database.on("ost_thread_collaborator tc", [{"user_id": i, "name": f"CC {i}", "email": f"cc{i}@x.test"} for i in range(51)])
    database.on("GROUP BY e.type", [{"type": "M", "entries": 3, "last_at": "2026-11-01"}, {"type": "N", "entries": 1, "last_at": None}])
    ticket = data(tools.get_ticket(ticket_id=90))["rows"][0]
    assert ticket["support_staff"] == [
        {"staff_id": 7, "team_id": None, "name": "Ana Pérez", "slot": 1, "recorded_time": "1:15"},
        {"staff_id": 9, "team_id": None, "name": "Luis Prueba", "slot": 2, "recorded_time": "0:30"},
    ]
    assert len(ticket["collaborators"]) == 50 and ticket["collaborators_has_more"] is True
    assert ticket["thread_summary"]["messages"] == 3 and ticket["thread_summary"]["internal_notes"] == 1
    assert ticket["thread_summary"]["total_entries"] == 4
    assert not any(key.startswith("_") for key in ticket)
    query = database.queries("WHERE t.`ticket_id` = %s")[0][0]
    for join in ("ost_help_topic", "ost_sla", "ost_team", "ost_user_email", "ost_ticket_priority"):
        assert f"LEFT JOIN `{join}`" in query


def test_plain_support_names_are_kept_without_inventing_ids():
    assert tickets._parse_assignee("Ana Pérez") == {"staff_id": None, "team_id": None, "name": "Ana Pérez"}
    assert tickets._parse_assignee('{"t3":"Mesa"}') == {"staff_id": None, "team_id": 3, "name": "Mesa"}
    assert tickets._parse_assignee('{"bad json') == {"staff_id": None, "team_id": None, "name": '{"bad json'}
    assert tickets._parse_assignee("  ") is None and tickets._parse_assignee(None) is None


def test_detail_without_form_tables_falls_back_to_cached_names(database):
    for table in access.INTERNAL_TABLE_COLUMNS:
        database.schema.columns.pop(table)
    database.on("WHERE t.`ticket_id` = %s", [{"ticket_id": 90, "_apoyo1": "Ana Pérez", "_timeApoyo1": "1:15"}])
    ticket = data(tools.get_ticket(ticket_id=90))["rows"][0]
    assert ticket["support_staff"] == [{"staff_id": None, "team_id": None, "name": "Ana Pérez", "slot": 1, "recorded_time": "1:15"}]
    assert database.queries("ost_form_entry") == []


# Thread -----------------------------------------------------------------------------------------

def thread_counts(database, total=3):
    database.on("COUNT(e.id) AS total", [{"ticket_id": 90, "total": total, "messages": 2, "responses": 1, "notes": 0}])


def test_thread_converts_html_and_labels_entry_types(database):
    thread_counts(database)
    database.on("FROM ost_thread_entry e", [
        {"entry_id": 1, "type_code": "M", "body": "<p>Hola</p><p>Falla <b>login</b></p>", "body_format": "html"},
        {"entry_id": 2, "type_code": "N", "body": "nota  interna", "body_format": "text"},
    ])
    result = data(tools.get_ticket_thread(90))
    assert [r["entry_type"] for r in result["rows"]] == ["message", "internal_note"]
    assert result["rows"][0]["body"] == "Hola\n\nFalla login"
    assert result["entry_counts"] == {"total": 3, "messages": 2, "responses": 1, "internal_notes": 0}
    assert "body_format" not in result["rows"][0] and "type_code" not in result["rows"][0]


def test_newest_first_pages_backwards_with_a_before_cursor(database):
    thread_counts(database)
    database.on("FROM ost_thread_entry e", [{"entry_id": i, "type_code": "R"} for i in (30, 20, 10)])
    result = data(tools.get_ticket_thread(90, order="newest", before_entry_id=40, limit=2,
                                          entry_types=["response", "internal_note"]))
    assert result["next_before_entry_id"] == 20 and result["has_more"] is True
    query, params = database.queries("FROM ost_thread_entry e")[0]
    assert "e.id < %s" in query and "ORDER BY e.id DESC" in query and "e.type IN (%s, %s)" in query
    assert params[-5:] == (90, 40, "N", "R", 3)


def test_bodies_longer_than_the_fetch_limit_are_marked_truncated(database):
    thread_counts(database, total=1)
    long_html = "<div>" + "x" * (tickets.BODY_FETCH_LIMIT - 5)
    database.on("FROM ost_thread_entry e", [{"entry_id": 1, "type_code": "M", "body": long_html, "body_format": "html"}])
    payload = json.loads(tools.get_ticket_thread(90))
    assert payload["meta"]["truncated"] is True
    assert payload["meta"]["truncation"]["field_paths"] == ["data.rows[0].body"]
    assert payload["meta"]["truncation"]["field_count"] == 1


def test_missing_ticket_thread_is_not_found(database):
    assert error(tools.get_ticket_thread(404)) == "NOT_FOUND"
    assert database.queries("FROM ost_thread_entry e") == []


@pytest.mark.parametrize("arguments", [
    {"ticket_id": 1, "before_entry_id": 5}, {"ticket_id": 1, "order": "newest", "after_entry_id": 5},
    {"ticket_id": 1, "entry_types": ["email"]}, {"ticket_id": 1, "entry_types": []}, {"ticket_id": 1, "order": "random"},
])
def test_invalid_thread_cursors_and_types_are_rejected(database, arguments):
    assert error(asyncio.run(mcp.call_tool("get_ticket_thread", arguments)).content[0].text) == "INVALID_ARGUMENTS"
    assert database.calls == []


# Customers, agents, catalogs -----------------------------------------------------------------------

def test_users_are_found_by_literal_name_or_email(database):
    database.on("FROM ost_user u", [{"user_id": 8, "name": "Cliente Ana", "email": "ana@x.test"}])
    result = data(tools.find_users("ana_%@x.test"))
    assert result["rows"][0]["user_id"] == 8
    query, params = database.queries("FROM ost_user u")[0]
    assert "m.address LIKE %s ESCAPE '='" in query and "x.address = %s" in query
    assert params[-6:] == ("%ana=_=%@x.test%", "%ana=_=%@x.test%", "ana_%@x.test", "ana_%@x.test", 21, 0)


def test_user_profile_combines_history_without_exposing_other_fields(database):
    database.on("FROM ost_user u WHERE u.id = %s", [{"user_id": 8, "name": "Cliente Ana", "status": 0, "default_email_id": 5}])
    database.on("FROM ost_user_email WHERE user_id", [{"id": 5, "address": "ana@x.test"}, {"id": 6, "address": "otra@x.test"}])
    database.on("GROUP BY group_key", lambda params: [{"group_key": "open", "label": None, "tickets": 2}])
    database.on("COUNT(*) AS total", [{"total": 2}])
    database.on("COUNT(DISTINCT th.object_id)", [{"tickets": 4}])
    user = data(tools.get_user(8))["rows"][0]
    assert user["emails"] == [{"address": "ana@x.test", "is_default": True}, {"address": "otra@x.test", "is_default": False}]
    assert user["tickets"]["as_requester"] == 2 and user["tickets"]["as_collaborator"] == 4
    assert "default_email_id" not in user


def test_unknown_user_and_agent_are_not_found(database):
    assert error(tools.get_user(999)) == "NOT_FOUND"
    assert error(tools.get_agent_report(999)) == "NOT_FOUND"


def test_agent_report_combines_workload_activity_support_and_time(database):
    database.on("FROM ost_staff a", [{"staff_id": 7, "name": "Ana Pérez", "isactive": 1, "department": "Soporte"}])
    database.on("GROUP BY group_key", lambda params: (
        [{"group_key": 1, "label": "Abierto", "tickets": 3}] if "open" in params
        else [{"group_key": "open", "label": None, "tickets": 3}, {"group_key": "closed", "label": None, "tickets": 9}]))
    database.on("COUNT(*) AS total", [{"total": 5}])
    database.on("GROUP BY e.type", [{"type": "R", "entries": 40, "tickets": 12}, {"type": "N", "entries": 4, "tickets": 3}])
    database.on("FROM (SELECT DISTINCT e.object_id", [{"tickets": 2, "time_seconds": 3600}])
    database.on("AS time_unparsed", [{"time_seconds": 7200, "overtime_seconds": 900, "time_unparsed": 0}])
    result = data(tools.get_agent_report(7, date_from="2026-10-01", date_to="2026-10-31"))
    assert result["agent"]["department"] == "Soporte"
    assert result["assigned_now"]["by_state"] == {"open": 3, "closed": 9}
    assert result["assigned_now"]["open_by_status"] == {"Abierto": 3}
    assert result["thread_activity"] == {"responses": 40, "tickets_with_responses": 12, "internal_notes": 4, "tickets_with_notes": 3}
    assert result["support_role"] == {"tickets": 2, "recorded_time": {"hhmm": "1:00", "hours": 1.0}}
    assert result["in_period"]["recorded_time"] == {"hhmm": "2:00", "hours": 2.0}
    support_query, support_params = database.queries("FROM (SELECT DISTINCT e.object_id")[0]
    assert '{"s7":%' in support_params and "v.value LIKE %s ESCAPE '='" in support_query
    activity_query, activity_params = database.queries("GROUP BY e.type")[0]
    assert activity_params == (7, "2026-10-01", "2026-11-01")


@pytest.mark.parametrize("kind", ["statuses", "departments", "priorities", "help_topics", "teams", "slas"])
def test_catalogs_are_fixed_queries(database, kind):
    database.on("FROM ost_", [{"id": 1, "name": "x"}])
    assert data(tools.list_catalog(kind))["row_count"] == 1


def test_unknown_catalog_is_rejected(database):
    assert error(tools.list_catalog("ost_staff")) == "INVALID_ARGUMENTS"
    assert database.calls == []


def test_agents_include_department_but_never_contact_or_auth_fields(database):
    data(tools.find_agents("Ana"))
    query, _ = database.calls[-1]
    assert "LEFT JOIN ost_department d" in query
    for secret in ("passwd", "email", "phone", "username", "permissions"):
        assert secret not in query


# Schema cache ----------------------------------------------------------------------------------------

def test_schema_is_cached_until_the_ttl_expires(monkeypatch):
    reads = Mock(return_value=full_schema())
    monkeypatch.setattr(tickets, "_read_schema", reads)
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(tickets.time, "monotonic", lambda: clock.now)
    monkeypatch.setenv("MCP_SCHEMA_CACHE_SECONDS", "60")
    tickets._load_schema()
    tickets._load_schema()
    assert reads.call_count == 1
    clock.now += 61
    tickets._load_schema()
    assert reads.call_count == 2


def test_cached_schema_never_widens_a_later_policy_restriction(monkeypatch):
    schema = full_schema()
    restricted = dict(access.ALLOWED_TABLE_COLUMNS)
    restricted["ost_staff"] = ("staff_id",)
    monkeypatch.setattr(access, "ALLOWED_TABLE_COLUMNS", restricted)
    assert not schema.has("ost_staff", "firstname")
