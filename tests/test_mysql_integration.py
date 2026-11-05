"""Opt-in real SQL tests. Only use a disposable MySQL on loopback, never .env.

Set MCP_TEST_MYSQL_PORT to a temporary MySQL port (root, empty password).
Each run creates a uniquely named schema and SELECT-only user, then removes them.
"""

import asyncio
from datetime import datetime, timedelta
import json
import os
from uuid import uuid4

import mysql.connector
import pytest

from mcp_mysql import db, tools
from mcp_mysql.config import MySQLConfig
from mcp_mysql.server import mcp

pytestmark = pytest.mark.skipif(not os.environ.get("MCP_TEST_MYSQL_PORT"), reason="Requires an explicit disposable MySQL port")


@pytest.fixture(scope="module")
def isolated_database():
    port = int(os.environ["MCP_TEST_MYSQL_PORT"])
    token = uuid4().hex[:12]
    schema, reader = f"mcp_query_test_{token}", f"reader_{token}"
    admin = mysql.connector.connect(host="127.0.0.1", port=port, user="root", password="", use_pure=True)
    cursor = admin.cursor()
    try:
        cursor.execute(f"CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cursor.execute(f"USE `{schema}`")
        definitions = {
            "ost_ticket": "ticket_id INT PRIMARY KEY, number VARCHAR(32), status_id INT, dept_id INT, user_id INT, staff_id INT, created DATETIME, lastupdate DATETIME, closed DATETIME",
            # Deliberately omit optional custom fields and include an unapproved field.
            "ost_ticket__cdata": "ticket_id INT PRIMARY KEY, subject TEXT, listaEmpresa TEXT, analisis TEXT, solucion TEXT, time VARCHAR(32), secret_token TEXT",
            "ost_ticket_status": "id INT PRIMARY KEY, name VARCHAR(64), state VARCHAR(32)",
            "ost_department": "id INT PRIMARY KEY, name VARCHAR(64)",
            "ost_user": "id INT PRIMARY KEY, name VARCHAR(64)",
            "ost_staff": "staff_id INT PRIMARY KEY, firstname VARCHAR(64), lastname VARCHAR(64), isactive INT, passwd TEXT",
            "ost_list_items": "id INT PRIMARY KEY, list_id INT, status INT, value VARCHAR(128)",
            "ost_thread": "id INT PRIMARY KEY, object_id INT, object_type CHAR(1)",
            "ost_thread_entry": "id INT PRIMARY KEY, thread_id INT, staff_id INT, user_id INT, type CHAR(1), poster VARCHAR(64), title TEXT, body MEDIUMTEXT, format VARCHAR(16), created DATETIME, updated DATETIME",
        }
        for table, columns in definitions.items():
            cursor.execute(f"CREATE TABLE `{table}` ({columns})")
        cursor.execute("INSERT INTO ost_ticket_status VALUES (1, 'Abierto', 'open'), (2, 'Resuelto', 'closed')")
        cursor.execute("INSERT INTO ost_department VALUES (1, 'Soporte')")
        cursor.execute("INSERT INTO ost_user VALUES (8, 'Cliente Ana'), (9, 'Cliente Dos')")
        cursor.execute("INSERT INTO ost_staff VALUES (7, 'Ana', 'Pérez', 1, 'never-expose'), (10, 'Luis', 'Prueba', 0, 'never-expose')")
        companies = [(i, 3, 1, f"Empresa {i:03}") for i in range(1, 151)]
        companies += [(218, 3, 1, "HOSPICIO"), (219, 3, 1, "Otra empresa"), (300, 9, 1, "HOSPICIO otra lista")]
        cursor.executemany("INSERT INTO ost_list_items VALUES (%s,%s,%s,%s)", companies)
        old = [(2000+i, f"{2000+i:08}", 1, 1, 8, 7, datetime(2024, 1, 1)+timedelta(days=i), None, None) for i in range(150)]
        recent = [
            (90001, "000001", 2, 1, 9, 10, "2026-11-05 23:59:59", None, "2026-11-06 00:00:01"),
            (90002, "000002", 2, 1, 9, 10, "2026-11-05 23:59:59", None, None),
            (90003, "000003", 1, 1, 8, 7, "2026-11-06 00:00:00", None, None),
            (90004, "000004", 1, 1, 8, 7, "2023-01-01 00:00:00", None, None),
            (90005, "DUPLICATE", 1, 1, 8, 7, "2025-01-01 00:00:00", None, None),
            (90006, "DUPLICATE", 1, 1, 8, 7, "2025-01-01 00:00:00", None, None),
        ]
        cursor.executemany("INSERT INTO ost_ticket VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", old+recent)
        custom = [(row[0], f"Consulta {row[0]}", "218,HOSPICIO", "Diagnóstico", "Solución", "01:30", "never-expose") for row in old]
        custom += [
            (90001, "Ticket reciente", "218,HOSPICIO", "Análisis", "Solución", "02:15", "never-expose"),
            (90002, "Literal _%= prueba", " 218 ,HOSPICIO", None, None, "00:20", "never-expose"),
            (90003, "Ticket siguiente día", "219,Otra empresa", None, None, None, "never-expose"),
        ]
        cursor.executemany("INSERT INTO ost_ticket__cdata VALUES (%s,%s,%s,%s,%s,%s,%s)", custom)
        cursor.execute("INSERT INTO ost_thread VALUES (50,90002,'T'), (51,90002,'A'), (52,90003,'T'), (60,90001,'T')")
        entries = [(i, 50, 7, 8, "M", "Cliente", "Mensaje", "x"*5000 if i == 2 else f"Mensaje {i}", "text", None, None) for i in range(1,6)]
        entries += [(6,51,7,8,"N","Agente","Tarea","NOT A TICKET","text",None,None), (7,52,7,8,"N","Agente","Otro","OTHER TICKET","text",None,None)]
        entries += [(i,60,7,8,"R","Agente","Respuesta","😀"*4001,"text",None,None) for i in range(100,120)]
        cursor.executemany("INSERT INTO ost_thread_entry VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", entries)
        admin.commit()
        cursor.execute("CREATE USER %s@'%%' IDENTIFIED BY %s", (reader, "test-only"))
        cursor.execute(f"GRANT SELECT ON `{schema}`.* TO %s@'%%'", (reader,))
        yield MySQLConfig(host="127.0.0.1", port=port, user=reader, password="test-only", database=schema)
    finally:
        cursor.execute(f"DROP DATABASE IF EXISTS `{schema}`")
        cursor.execute("DROP USER IF EXISTS %s@'%%'", (reader,))
        cursor.close()
        admin.close()


@pytest.fixture
def live(isolated_database, monkeypatch):
    monkeypatch.setattr(MySQLConfig, "from_env", lambda: isolated_database)


def result(encoded):
    payload = json.loads(encoded)
    assert payload["ok"] is True, payload["error"]
    return payload["data"]


def test_company_resolution_and_latest_ticket_beyond_first_hundred_rows(live):
    companies = result(tools.find_companies("HOSPICIO"))["rows"]
    assert [c["company_id"] for c in companies] == [218]
    data = result(tools.list_company_tickets(218, limit=1))
    assert data["rows"][0]["ticket_id"] == 90002
    assert data["has_more"] is True and data["next_offset"] == 1
    assert "overtime" in data["unavailable_fields"]
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
    assert [r["ticket_id"] for r in result(tools.search_tickets(**filters, order="oldest"))["rows"]] == [90001,90002]
    assert result(tools.search_tickets(subject="_%="))["rows"][0]["ticket_id"] == 90002
    assert result(tools.count_tickets(subject="' OR 1=1 --"))["total"] == 0


def test_exact_detail_handles_absent_cdata_missing_ticket_and_duplicate_numbers(live):
    assert result(tools.get_ticket(number="000001"))["rows"][0]["ticket_id"] == 90001
    row = result(tools.get_ticket(ticket_id=90004))["rows"][0]
    assert row["ticket_id"] == 90004 and row["subject"] is None
    assert result(tools.count_tickets())["total"] == 156
    assert json.loads(tools.get_ticket(ticket_id=999999))["error"]["code"] == "NOT_FOUND"
    assert json.loads(tools.get_ticket(number="DUPLICATE"))["error"]["code"] == "AMBIGUOUS_MATCH"


def test_people_resolve_ids_without_exposing_authentication_data(live):
    assert result(tools.find_agents("Ana"))["rows"] == [{"staff_id":7,"name":"Ana Pérez","isactive":1}]
    assert result(tools.find_users("Cliente", limit=1))["next_offset"] == 1
    assert result(tools.find_users("Cliente", limit=1, offset=1))["rows"][0]["user_id"] == 9
    assert result(tools.count_tickets(staff_id=7))["total"] == 154
    assert result(tools.find_agents("' OR 1=1 --"))["rows"] == []
    companies = result(tools.find_companies("Empresa", limit=50))
    assert companies["has_more"] is True and companies["next_offset"] == 50
    assert result(tools.find_companies("Empresa", offset=50))["rows"][0]["company_id"] == 51


def test_thread_pages_only_include_the_requested_ticket_and_mark_clipped_text(live):
    first = json.loads(tools.get_ticket_thread(90002, limit=2))
    assert first["meta"]["truncated"] is True
    assert len(first["data"]["rows"][1]["body"]) == 4000
    assert first["data"]["next_after_entry_id"] == 2
    rest = result(tools.get_ticket_thread(90002, after_entry_id=2))
    assert [r["entry_id"] for r in rest["rows"]] == [3,4,5]
    assert rest["has_more"] is False


def test_byte_limited_thread_can_be_read_without_skipping_entries(live):
    found, cursor = [], 0
    while True:
        data = result(tools.get_ticket_thread(90001, after_entry_id=cursor, limit=50))
        found.extend(row["entry_id"] for row in data["rows"])
        if not data["has_more"]:
            break
        assert data["next_after_entry_id"] > cursor
        cursor = data["next_after_entry_id"]
    assert found == list(range(100,120))


def test_mcp_handlers_work_with_real_sql_and_read_only_sessions(live):
    async def flow():
        for name, arguments in [
            ("test_connection", {}), ("list_tables", {}),
            ("describe_table", {"table_name":"ost_staff"}),
            ("sample_rows", {"table_name":"ost_staff"}),
            ("find_companies", {"name":"HOSPICIO"}),
            ("list_company_tickets", {"company_id":218,"limit":1}),
            ("search_tickets", {"staff_id":7,"limit":1}),
            ("count_tickets", {"company_id":218}),
            ("get_ticket", {"number":"000002"}),
            ("get_ticket_thread", {"ticket_id":90002,"limit":1}),
            ("find_agents", {"name":"Ana"}), ("find_users", {"name":"Cliente"}),
        ]:
            response = await mcp.call_tool(name, arguments)
            assert response.isError is False, (name,response.content)
            assert "never-expose" not in response.content[0].text
    asyncio.run(flow())
    assert db.fetch_one("SELECT @@session.transaction_read_only AS readonly")["readonly"] == 1
    with pytest.raises(mysql.connector.Error):
        db.fetch_all("UPDATE ost_ticket SET number = 'forbidden' WHERE ticket_id = 90001")
    assert result(tools.get_ticket(ticket_id=90001))["rows"][0]["number"] == "000001"
