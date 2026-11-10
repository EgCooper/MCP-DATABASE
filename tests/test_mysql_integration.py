"""Opt-in real SQL tests. Only use a disposable MySQL/MariaDB on loopback, never .env.

Set MCP_TEST_MYSQL_PORT to a temporary server port (root, empty password).
Each run creates a uniquely named schema and a reader account that only has
column-level SELECT on the access policy columns, then removes both.
"""

import asyncio
from datetime import datetime, timedelta
import json
import os
from uuid import uuid4

import mysql.connector
import pytest

from mcp_mysql import db, tickets, tools
from mcp_mysql.access import all_query_tables
from mcp_mysql.config import MySQLConfig
from mcp_mysql.server import mcp

pytestmark = pytest.mark.skipif(not os.environ.get("MCP_TEST_MYSQL_PORT"), reason="Requires an explicit disposable MySQL port")

from mysql_fixture import TABLES, _seed, _grant_policy_columns


@pytest.fixture(scope="module")
def isolated_database():
    port = int(os.environ["MCP_TEST_MYSQL_PORT"])
    token = uuid4().hex[:12]
    schema, reader = f"mcp_query_test_{token}", f"reader_{token}"
    account = f"'{reader}'@'%'"
    admin = mysql.connector.connect(host="127.0.0.1", port=port, user="root", password="", use_pure=True)
    cursor = admin.cursor()
    try:
        cursor.execute(f"CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cursor.execute(f"USE `{schema}`")
        for table, columns in TABLES.items():
            cursor.execute(f"CREATE TABLE `{table}` ({columns})")
        _seed(cursor)
        admin.commit()
        cursor.execute(f"CREATE USER {account} IDENTIFIED BY 'test-only'")
        _grant_policy_columns(cursor, schema, account)
        ca = os.environ.get("MCP_TEST_MYSQL_CA")
        yield MySQLConfig(host="127.0.0.1", port=port, user=reader, password="test-only", database=schema,
                          ssl_ca=ca, ssl_verify_identity=bool(ca))
    finally:
        cursor.execute(f"DROP DATABASE IF EXISTS `{schema}`")
        cursor.execute(f"DROP USER IF EXISTS {account}")
        cursor.close()
        admin.close()


@pytest.fixture
def live(isolated_database, monkeypatch):
    monkeypatch.setattr(MySQLConfig, "from_env", lambda: isolated_database)
    tickets.clear_schema_cache()


def result(encoded):
    payload = json.loads(encoded)
    assert payload["ok"] is True, payload["error"]
    return payload["data"]


def code(encoded):
    return json.loads(encoded)["error"]["code"]


def test_company_resolution_and_latest_ticket_beyond_first_hundred_rows(live):
    companies = result(tools.find_companies("HOSPICIO"))["rows"]
    assert [c["company_id"] for c in companies] == [218]
    data = result(tools.list_company_tickets(218, limit=1))
    assert data["rows"][0]["ticket_id"] == 90002
    assert data["rows"][0]["company"] == "HOSPICIO" and data["rows"][0]["company_id"] == 218
    assert data["has_more"] is True and data["next_offset"] == 1
    assert "never-expose" not in json.dumps(data)


def test_full_count_and_paginated_results_agree_without_duplicates(live):
    assert result(tools.count_tickets(company_id=218))["total"] == 152
    found, offset = [], 0
    while True:
        page = result(tools.list_company_tickets(218, offset=offset, limit=50))
        found.extend(row["ticket_id"] for row in page["rows"])
        if not page["has_more"]:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert len(found) == len(set(found)) == 152
    assert found[:2] == [90002, 90001]


def test_inclusive_dates_exact_status_and_literal_subject(live):
    filters = dict(company_id=218, staff_id=10, user_id=9, status="Resuelto", created_from="2026-11-05", created_to="2026-11-05")
    assert result(tools.count_tickets(**filters))["total"] == 2
    assert [r["ticket_id"] for r in result(tools.search_tickets(**filters, order="oldest"))["rows"]] == [90001, 90002]
    assert result(tools.search_tickets(subject="_%="))["rows"][0]["ticket_id"] == 90002
    assert result(tools.count_tickets(subject="' OR 1=1 --"))["total"] == 0


def test_state_assignment_overdue_priority_and_closed_filters(live):
    assert result(tools.count_tickets(state="closed"))["total"] == 2
    assert result(tools.count_tickets(state="open", overdue=True))["total"] == 1
    assert result(tools.count_tickets(assigned=False))["total"] == 1
    assert result(tools.count_tickets(priority_id=3))["total"] == 1
    assert result(tools.count_tickets(dept_id=2))["total"] == 1
    assert result(tools.count_tickets(closed_from="2026-11-06", closed_to="2026-11-06"))["total"] == 1
    assert result(tools.count_tickets(user_id=8))["total"] == 154
    assert result(tools.count_tickets(user_id=8, include_collaborations=True))["total"] == 155
    assert result(tools.search_tickets(order="last_updated", limit=1))["rows"][0]["ticket_id"] == 90001


def test_exact_detail_handles_absent_cdata_missing_ticket_and_duplicate_numbers(live):
    assert result(tools.get_ticket(number="000001"))["rows"][0]["ticket_id"] == 90001
    row = result(tools.get_ticket(ticket_id=90004))["rows"][0]
    assert row["ticket_id"] == 90004 and row["subject"] is None
    assert result(tools.count_tickets())["total"] == 156
    assert code(tools.get_ticket(ticket_id=999999)) == "NOT_FOUND"
    assert code(tools.get_ticket(number="DUPLICATE")) == "AMBIGUOUS_MATCH"


def test_detail_resolves_labels_people_and_reports_missing_optional_tables(live):
    data = result(tools.get_ticket(ticket_id=90001))
    ticket = data["rows"][0]
    assert ticket["priority"] == "High" and ticket["request_type"] == "Incidente" and ticket["cause"] == "Configuración"
    assert ticket["help_topic"] == "Incidente" and ticket["customer_email"] == "dos@cliente.test"
    assert ticket["recorded_time"] == "02:15" and ticket["overtime"] == "0:45"
    assert ticket["support_staff"] == [{"staff_id": 10, "team_id": None, "name": "Luis Prueba", "slot": 1, "recorded_time": "1:00"}]
    assert ticket["thread_summary"]["responses"] == 20
    assert {"sla", "compensated_time", "start_date"}.issubset(data["unavailable_fields"])
    collaborated = result(tools.get_ticket(ticket_id=90002))["rows"][0]
    assert collaborated["collaborators"] == [{"user_id": 8, "name": "Cliente Ana", "email": "ana@cliente.test"}]
    assert "never-expose" not in json.dumps(data)


def test_reports_group_on_the_server_and_sum_hhmm_durations(live):
    agents = result(tools.ticket_report("agent", include_time=True))
    ana = next(g for g in agents["groups"] if g["key"] == 7)
    assert ana["label"] == "Ana Pérez" and ana["tickets"] == 153
    assert ana["recorded_time"] == {"hhmm": "225:00", "hours": 225.0}
    assert ana["unparsed_time_values"] == 1  # "1.5h" is reported, never guessed
    assert agents["total_tickets"] == 156
    months = result(tools.ticket_report("month", created_from="2026-11-01"))
    assert months["groups"] == [{"key": "2026-11", "label": "2026-11", "tickets": 3}]
    companies = result(tools.ticket_report("company", limit=1))
    assert companies["groups"][0]["key"] == 218 and companies["has_more"] is True
    for group_by in ("status", "state", "department", "priority", "help_topic", "request_type", "source", "user"):
        assert result(tools.ticket_report(group_by))["total_tickets"] == 156


def test_report_continuation_matches_complete_report_including_null_group(live):
    complete = result(tools.ticket_report("company", include_time=True))["groups"]
    collected, offset = [], 0
    while True:
        page = result(tools.ticket_report("company", include_time=True, limit=1, offset=offset))
        collected.extend(page["groups"])
        if not page["has_more"]:
            assert page["next_offset"] is None
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert collected == complete


def test_report_time_totals_cover_filters_not_the_page(live):
    expected = {'recorded_time': {'hhmm': '227:35', 'hours': 227.58},
                'overtime': {'hhmm': '0:45', 'hours': 0.75}, 'unparsed_time_values': 1}
    for offset in (0, 1, 50):
        page = result(tools.ticket_report('company', include_time=True, limit=1, offset=offset))
        assert page['time_totals'] == expected
        assert page['time_totals_scope'] == 'all_matching_tickets'
    filtered = result(tools.ticket_report('agent', include_time=True, created_from='2026-11-01'))
    assert filtered['time_totals']['recorded_time']['hhmm'] == '2:35'
    empty = result(tools.ticket_report('company', include_time=True, subject='NO MATCH IN FIXTURE'))
    assert empty['time_totals'] == {'recorded_time': {'hhmm': '0:00', 'hours': 0.0},
                                   'overtime': {'hhmm': '0:00', 'hours': 0.0}, 'unparsed_time_values': 0}
    assert 'time_totals' not in result(tools.ticket_report('company'))


def test_customer_profile_offsets_execute_real_sql(live):
    first = result(tools.get_user(8))["rows"][0]
    second = result(tools.get_user(8, emails_offset=1, companies_offset=1))["rows"][0]
    assert second["emails"] == first["emails"][1:]
    company_page = result(tools.ticket_report("company", user_id=8, limit=10, offset=1))
    assert second["companies"] == [
        {"company_id": g["key"], "name": g["label"], "tickets": g["tickets"]}
        for g in company_page["groups"] if g["key"] is not None]
    assert second["emails_pagination"]["offset"] == second["companies_pagination"]["offset"] == 1


def test_large_report_and_profile_can_be_read_completely(live, isolated_database):
    """Real SQL must recover >100 groups, >20 emails and >10 companies without duplicates."""
    admin = mysql.connector.connect(host="127.0.0.1", port=isolated_database.port, user="root", password="",
                                    database=isolated_database.database, use_pure=True)
    cursor = admin.cursor()
    try:
        cursor.execute("INSERT INTO ost_user (id, name, default_email_id) VALUES (800000, 'Synthetic', 800001)")
        cursor.executemany("INSERT INTO ost_user_email (id, user_id, address) VALUES (%s, 800000, %s)",
                           [(800000 + i, f"synthetic{i}@example.test") for i in range(1, 24)])
        cursor.executemany("INSERT INTO ost_list_items (id, list_id, status, value) VALUES (%s, 3, 1, %s)",
                           [(800000 + i, f"Synthetic {i}") for i in range(1, 13)])
        cursor.executemany("INSERT INTO ost_ticket (ticket_id, number, user_id, status_id, created) "
                           "VALUES (%s, %s, %s, 1, '2026-11-10')",
                           [(800000 + i, f"SYNTHETIC{i}", 800000 + i) for i in range(125)] +
                           [(900000 + i, f"PROFILE{i}", 800000) for i in range(1, 13)])
        cursor.executemany("INSERT INTO ost_ticket__cdata (ticket_id, listaEmpresa) VALUES (%s, %s)",
                           [(900000 + i, str(800000 + i)) for i in range(1, 13)])
        admin.commit()
        groups, offset = [], 0
        while True:
            page = result(tools.ticket_report("user", limit=100, offset=offset))
            groups.extend(page["groups"])
            if not page["has_more"]:
                break
            offset = page["next_offset"]
        keys = [g["key"] for g in groups]
        assert set(range(800000, 800125)) <= set(keys)
        assert len(keys) == len(set(keys)) and len(keys) > 100
        emails, companies, email_offset, company_offset = [], [], 0, 0
        while True:
            profile = result(tools.get_user(800000, emails_offset=email_offset or 0,
                                            companies_offset=company_offset or 0))["rows"][0]
            # Completed collections may be fetched again but are never accumulated twice.
            if email_offset is not None:
                emails.extend(profile["emails"])
            if company_offset is not None:
                companies.extend(profile["companies"])
            email_offset = profile["emails_pagination"]["next_offset"] if email_offset is not None else None
            company_offset = profile["companies_pagination"]["next_offset"] if company_offset is not None else None
            if email_offset is None and company_offset is None:
                break
        assert len(emails) == len({email["address"] for email in emails}) == 23
        assert len(companies) == len({company["company_id"] for company in companies}) == 12
    finally:
        cursor.execute("DELETE FROM ost_ticket__cdata WHERE ticket_id BETWEEN 900001 AND 900012")
        cursor.execute("DELETE FROM ost_ticket WHERE ticket_id BETWEEN 800000 AND 800124 "
                       "OR ticket_id BETWEEN 900001 AND 900012")
        cursor.execute("DELETE FROM ost_list_items WHERE id BETWEEN 800001 AND 800012")
        cursor.execute("DELETE FROM ost_user_email WHERE user_id = 800000")
        cursor.execute("DELETE FROM ost_user WHERE id = 800000")
        admin.commit()
        cursor.close()
        admin.close()


def test_agent_report_counts_workload_activity_and_support_role(live):
    report = result(tools.get_agent_report(10, date_from="2026-11-01", date_to="2026-11-30"))
    assert report["actor_activity"]["tickets_closed_by_agent"] == 0
    assert report["agent"]["name"] == "Luis Prueba" and report["agent"]["department"] == "Desarrollo"


    assert report["assigned_now"]["by_state"] == {"closed": 2}
    assert report["in_period"]["assigned_tickets_created"] == 2 and report["in_period"]["assigned_tickets_closed"] == 1
    assert report["support_role"] == {"tickets": 2, "recorded_time": {"hhmm": "1:00", "hours": 1.0}}
    ana = result(tools.get_agent_report(7, date_from="2026-11-05", date_to="2026-11-05"))
    assert ana["thread_activity"]["responses"] == 20 and ana["thread_activity"]["internal_notes"] == 1
    assert ana["assigned_now"]["open_overdue"] == 1
    assert code(tools.get_agent_report(999)) == "NOT_FOUND"


def test_closures_follow_actor_not_current_assignment_and_deduplicate(live):
    actor = result(tools.get_agent_report(7, date_from="2026-11-01", date_to="2026-11-30"))
    assert actor["actor_activity"] == {"tickets_closed_by_agent": 1, "closure_events": 2}
    assert actor["in_period"]["assigned_tickets_closed"] == 0


def test_tls_verifies_ca_and_hostname_when_fixture_is_configured(live, isolated_database, monkeypatch):
    if not isolated_database.ssl_ca:
        pytest.skip("Requires MCP_TEST_MYSQL_CA with ephemeral TLS server")
    from dataclasses import replace
    import socket
    from pathlib import Path
    assert db.fetch_one("SHOW SESSION STATUS LIKE 'Ssl_cipher'")["Value"]
    wrong_ca = Path(isolated_database.ssl_ca).with_name('wrong-ca.crt')
    with pytest.raises(mysql.connector.Error):
        db.get_connection(replace(isolated_database, ssl_ca=str(wrong_ca)))
    original = socket.getaddrinfo
    monkeypatch.setattr(socket, 'getaddrinfo', lambda host,*args,**kwargs:
        original('127.0.0.1' if host=='wrong-host.invalid' else host,*args,**kwargs))
    with pytest.raises(mysql.connector.Error):
        db.get_connection(replace(isolated_database, host='wrong-host.invalid'))


def test_people_resolve_ids_without_exposing_authentication_data(live):
    assert result(tools.find_agents("Ana"))["rows"] == [{"staff_id": 7, "name": "Ana Pérez", "isactive": 1, "department": "Soporte"}]
    assert result(tools.find_users("Cliente", limit=1))["next_offset"] == 1
    assert result(tools.find_users("Cliente", limit=1, offset=1))["rows"][0]["user_id"] == 9
    assert [r["user_id"] for r in result(tools.find_users("personal@correo"))["rows"]] == [8]
    assert result(tools.count_tickets(staff_id=7))["total"] == 153
    assert result(tools.find_agents("' OR 1=1 --"))["rows"] == []
    companies = result(tools.find_companies("Empresa", limit=50))
    assert companies["has_more"] is True and companies["next_offset"] == 50
    assert result(tools.find_companies("Empresa", offset=50))["rows"][0]["company_id"] == 51


def test_user_profile_combines_emails_history_and_collaborations(live):
    user = result(tools.get_user(8))["rows"][0]
    assert [e["address"] for e in user["emails"]] == ["ana@cliente.test", "ana.personal@correo.test"]
    assert user["emails"][0]["is_default"] is True
    assert user["tickets"]["as_requester"] == 154 and user["tickets"]["as_collaborator"] == 1
    assert user["tickets"]["latest"]["ticket_id"] == 90003
    assert {c["company_id"] for c in user["companies"]} == {218, 219}


def test_thread_pages_only_include_the_requested_ticket_and_mark_clipped_text(live):
    first = json.loads(tools.get_ticket_thread(90002, limit=2))
    assert first["meta"]["truncated"] is True
    assert len(first["data"]["rows"][1]["body"]) == 4000
    assert first["data"]["next_after_entry_id"] == 2
    rest = result(tools.get_ticket_thread(90002, after_entry_id=2))
    assert [r["entry_id"] for r in rest["rows"]] == [3, 4, 5, 8]
    assert rest["rows"][-1]["body"] == "Revisar servidor" and rest["rows"][-1]["entry_type"] == "internal_note"
    assert rest["has_more"] is False and rest["entry_counts"]["total"] == 6


def test_newest_first_thread_and_type_filter(live):
    notes = result(tools.get_ticket_thread(90002, entry_types=["internal_note"]))
    assert [r["entry_id"] for r in notes["rows"]] == [8]
    latest = result(tools.get_ticket_thread(90002, order="newest", limit=2))
    assert [r["entry_id"] for r in latest["rows"]] == [8, 5] and latest["next_before_entry_id"] == 5
    older = result(tools.get_ticket_thread(90002, order="newest", before_entry_id=5, limit=10))
    assert [r["entry_id"] for r in older["rows"]] == [4, 3, 2, 1]


def test_byte_limited_thread_can_be_read_without_skipping_entries(live):
    found, cursor = [], 0
    while True:
        data = result(tools.get_ticket_thread(90001, after_entry_id=cursor, limit=50))
        found.extend(row["entry_id"] for row in data["rows"])
        if not data["has_more"]:
            break
        assert data["next_after_entry_id"] > cursor
        cursor = data["next_after_entry_id"]
    assert found == list(range(100, 120))


def test_catalogs_and_missing_catalog_tables(live):
    statuses = result(tools.list_catalog("statuses"))["rows"]
    assert {s["name"]: s["state"] for s in statuses} == {"Abierto": "open", "Resuelto": "closed", "Cerrado": "closed"}
    assert result(tools.list_catalog("priorities"))["rows"][0]["name"] == "High"
    assert code(tools.list_catalog("slas")) == "SCHEMA_UNAVAILABLE"


def test_column_grants_block_secrets_even_for_direct_sql(live):
    with pytest.raises(mysql.connector.Error) as denied:
        db.fetch_all("SELECT passwd FROM ost_staff")
    assert denied.value.errno == 1143  # ER_COLUMNACCESS_DENIED_ERROR
    hidden = db.fetch_all(
        "SELECT COLUMN_NAME AS c FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        ("ost_ticket__cdata",))
    assert "secret_token" not in {row["c"] for row in hidden}


def test_mcp_handlers_work_with_real_sql_and_read_only_sessions(live, monkeypatch):
    monkeypatch.setenv("MCP_ENABLE_EXPLORATION_TOOLS", "true")

    async def flow():
        for name, arguments in [
            ("test_connection", {}), ("list_tables", {}),
            ("describe_table", {"table_name": "ost_staff"}),
            ("sample_rows", {"table_name": "ost_staff"}),
            ("list_catalog", {"kind": "statuses"}),
            ("find_companies", {"name": "HOSPICIO"}),
            ("list_company_tickets", {"company_id": 218, "limit": 1}),
            ("search_tickets", {"staff_id": 7, "limit": 1}),
            ("count_tickets", {"company_id": 218}),
            ("ticket_report", {"group_by": "agent", "include_time": True}),
            ("get_ticket", {"number": "000002"}),
            ("get_ticket_thread", {"ticket_id": 90002, "limit": 1}),
            ("find_agents", {"name": "Ana"}), ("get_agent_report", {"staff_id": 7}),
            ("find_users", {"query": "Cliente"}), ("get_user", {"user_id": 8}),
        ]:
            response = await mcp.call_tool(name, arguments)
            assert response.isError is False, (name, response.content)
            assert "never-expose" not in response.content[0].text
    asyncio.run(flow())
    connection = json.loads(tools.test_connection())["data"]
    assert connection["server_time"] and connection["time_zone"]
    # MariaDB (and MySQL before 8.0.3) name the session flag tx_read_only.
    variable = "tx_read_only" if "mariadb" in connection["version"].lower() else "transaction_read_only"
    assert db.fetch_one(f"SELECT @@session.{variable} AS readonly")["readonly"] == 1
    with pytest.raises(mysql.connector.Error):
        db.fetch_all("UPDATE ost_ticket SET number = 'forbidden' WHERE ticket_id = 90001")
    assert result(tools.get_ticket(ticket_id=90001))["rows"][0]["number"] == "000001"


def test_pooled_connections_stay_read_only_and_always_see_fresh_data(live, isolated_database, monkeypatch):
    monkeypatch.setenv("MCP_DB_POOL_SIZE", "2")
    db.clear_pool()
    mariadb = "mariadb" in db.fetch_one("SELECT VERSION() AS v")["v"].lower()
    first = db.fetch_one("SELECT CONNECTION_ID() AS id")["id"]
    assert db.fetch_one("SELECT CONNECTION_ID() AS id")["id"] == first          # the same session is reused
    variable = "tx_read_only" if mariadb else "transaction_read_only"
    assert db.fetch_one(f"SELECT @@session.{variable} AS readonly")["readonly"] == 1

    # Another client commits a change between two pooled calls: the next call must see it,
    # which proves each call ends its snapshot instead of reusing an old transaction.
    assert result(tools.list_catalog("teams"))["row_count"] == 1
    admin = mysql.connector.connect(host="127.0.0.1", port=isolated_database.port, user="root", password="",
                                    database=isolated_database.database, use_pure=True)
    try:
        cursor = admin.cursor()
        cursor.execute("INSERT INTO ost_team VALUES (99, 'Temporal')")
        admin.commit()
        assert result(tools.list_catalog("teams"))["row_count"] == 2
        assert db.fetch_one("SELECT CONNECTION_ID() AS id")["id"] == first
    finally:
        cursor.execute("DELETE FROM ost_team WHERE team_id = 99")
        admin.commit()
        admin.close()

    with pytest.raises(mysql.connector.Error):
        db.fetch_all("UPDATE ost_ticket SET number = 'forbidden' WHERE ticket_id = 90001")
    assert db.fetch_one("SELECT CONNECTION_ID() AS id")["id"] != first          # a failed session is not reused
    assert result(tools.get_ticket(ticket_id=90001))["rows"][0]["number"] == "000001"
