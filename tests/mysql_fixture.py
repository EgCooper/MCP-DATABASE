"""Disposable osTicket schema shared by SQL tests and benchmarks."""

from datetime import datetime, timedelta
from mcp_mysql.access import all_query_tables

TABLES = {
    "ost_ticket": "ticket_id INT UNSIGNED PRIMARY KEY, ticket_pid INT UNSIGNED, number VARCHAR(20), user_id INT UNSIGNED, "
                  "status_id INT UNSIGNED, dept_id INT UNSIGNED, sla_id INT UNSIGNED, topic_id INT UNSIGNED, staff_id INT UNSIGNED, "
                  "team_id INT UNSIGNED, source ENUM('Web','Email','Phone','API','Other'), isoverdue TINYINT UNSIGNED, "
                  "isanswered TINYINT UNSIGNED, duedate DATETIME, est_duedate DATETIME, reopened DATETIME, closed DATETIME, "
                  "lastupdate DATETIME, created DATETIME, updated DATETIME, ip_address VARCHAR(64)",
    # Optional custom fields horaCompensada, fechaInicio... are deliberately absent; secret_token is unapproved.
    "ost_ticket__cdata": "ticket_id INT UNSIGNED PRIMARY KEY, priority MEDIUMTEXT, subject MEDIUMTEXT, listaEmpresa MEDIUMTEXT, "
                         "tipoSolicitud MEDIUMTEXT, causa MEDIUMTEXT, analisis MEDIUMTEXT, solucion MEDIUMTEXT, time MEDIUMTEXT, "
                         "timeExtra MEDIUMTEXT, apoyo1 MEDIUMTEXT, timeApoyo1 MEDIUMTEXT, apoyo2 MEDIUMTEXT, timeApoyo2 MEDIUMTEXT, "
                         "apoyo3 MEDIUMTEXT, timeApoyo3 MEDIUMTEXT, secret_token MEDIUMTEXT",
    "ost_ticket_status": "id INT PRIMARY KEY, name VARCHAR(60), state VARCHAR(16), sort INT UNSIGNED",
    "ost_ticket_priority": "priority_id TINYINT PRIMARY KEY, priority VARCHAR(60), priority_desc VARCHAR(30), priority_urgency TINYINT UNSIGNED",
    "ost_department": "id INT UNSIGNED PRIMARY KEY, name VARCHAR(128), signature TEXT",
    "ost_help_topic": "topic_id INT UNSIGNED PRIMARY KEY, topic VARCHAR(128), dept_id INT UNSIGNED, notes TEXT",
    "ost_team": "team_id INT UNSIGNED PRIMARY KEY, name VARCHAR(125)",
    "ost_user": "id INT UNSIGNED PRIMARY KEY, default_email_id INT, status INT UNSIGNED, name VARCHAR(128), created DATETIME, updated DATETIME",
    "ost_user_email": "id INT UNSIGNED PRIMARY KEY, user_id INT UNSIGNED, flags INT UNSIGNED, address VARCHAR(255)",
    "ost_staff": "staff_id INT UNSIGNED PRIMARY KEY, dept_id INT UNSIGNED, firstname VARCHAR(32), lastname VARCHAR(32), "
                 "isactive TINYINT, onvacation TINYINT, passwd VARCHAR(128), email VARCHAR(255)",
    "ost_list_items": "id INT UNSIGNED PRIMARY KEY, list_id INT, status INT UNSIGNED, value VARCHAR(255), extra VARCHAR(255)",
    "ost_thread": "id INT UNSIGNED PRIMARY KEY, object_id INT UNSIGNED, object_type CHAR(1), created DATETIME",
    "ost_event": "id INT PRIMARY KEY, name VARCHAR(32)",
    "ost_thread_event": "id INT PRIMARY KEY, thread_id INT, event_id INT, uid INT, uid_type CHAR(1), timestamp DATETIME, annulled INT, staff_id INT",
    "ost_thread_entry": "id INT UNSIGNED PRIMARY KEY, thread_id INT UNSIGNED, staff_id INT UNSIGNED, user_id INT UNSIGNED, type CHAR(1), "
                        "poster VARCHAR(128), title VARCHAR(255), body MEDIUMTEXT, format VARCHAR(16), ip_address VARCHAR(64), "
                        "created DATETIME, updated DATETIME",
    "ost_thread_collaborator": "id INT UNSIGNED PRIMARY KEY, flags INT UNSIGNED, thread_id INT UNSIGNED, user_id INT UNSIGNED, role CHAR(1)",
    "ost_form_field": "id INT UNSIGNED PRIMARY KEY, form_id INT UNSIGNED, name VARCHAR(64), configuration TEXT",
    "ost_form_entry": "id INT UNSIGNED PRIMARY KEY, form_id INT UNSIGNED, object_id INT UNSIGNED, object_type CHAR(1)",
    "ost_form_entry_values": "entry_id INT UNSIGNED, field_id INT UNSIGNED, value TEXT, PRIMARY KEY (entry_id, field_id)",
    # ost_sla is deliberately missing: the detail must report "sla" as unavailable instead of failing.
}


def _insert(cursor, table, rows):
    placeholders = ", ".join(["%s"] * len(rows[0]))
    cursor.executemany(f"INSERT INTO `{table}` VALUES ({placeholders})", rows)


def _seed(cursor):
    _insert(cursor, "ost_event", [(1, "closed"), (2, "created")])
    _insert(cursor, "ost_thread_event", [
        (1, 60, 1, 7, "S", "2026-11-06 10:00:00", 0, 10),
        (2, 60, 1, 7, "S", "2026-11-06 11:00:00", 0, 10),
        (3, 50, 1, 7, "S", "2026-11-06 12:00:00", 1, 7),
        (4, 50, 1, 7, "U", "2026-11-06 12:00:00", 0, 7),
        (5, 50, 1, 7, "S", "2026-10-01 12:00:00", 0, 7),
    ])
    _insert(cursor, "ost_ticket_status", [(1, "Abierto", "open", 1), (2, "Resuelto", "closed", 2), (3, "Cerrado", "closed", 3)])
    _insert(cursor, "ost_ticket_priority", [(1, "low", "Low", 4), (2, "normal", "Normal", 3), (3, "high", "High", 2)])
    _insert(cursor, "ost_department", [(1, "Soporte", "never-expose"), (2, "Desarrollo", "never-expose")])
    _insert(cursor, "ost_help_topic", [(1, "Incidente", 1, "never-expose")])
    _insert(cursor, "ost_team", [(1, "Mesa")])
    _insert(cursor, "ost_user", [(8, 80, 0, "Cliente Ana", None, None), (9, 90, 0, "Cliente Dos", None, None)])
    _insert(cursor, "ost_user_email", [(80, 8, 0, "ana@cliente.test"), (81, 8, 0, "ana.personal@correo.test"), (90, 9, 0, "dos@cliente.test")])
    _insert(cursor, "ost_staff", [(7, 1, "Ana", "Pérez", 1, 0, "never-expose", "never-expose@x.test"),
                                  (10, 2, "Luis", "Prueba", 0, 0, "never-expose", "never-expose@x.test")])
    items = [(i, 3, 1, f"Empresa {i:03}", None) for i in range(1, 151)]
    items += [(218, 3, 1, "HOSPICIO", None), (219, 3, 1, "Otra empresa", None), (300, 9, 1, "HOSPICIO otra lista", None),
              (400, 4, 1, "Incidente", None), (500, 5, 1, "Configuración", None)]
    _insert(cursor, "ost_list_items", items)
    columns = "(ticket_id, number, status_id, dept_id, user_id, staff_id, created, lastupdate, closed, topic_id, isoverdue, source)"
    old = [(2000 + i, f"{2000 + i:08}", 1, 1, 8, 7, datetime(2024, 1, 1) + timedelta(days=i), None, None, 1, 0, "Email") for i in range(150)]
    recent = [
        (90001, "000001", 2, 1, 9, 10, "2026-11-05 23:59:59", "2026-11-06 09:00:00", "2026-11-06 00:00:01", 1, 0, "Web"),
        (90002, "000002", 2, 1, 9, 10, "2026-11-05 23:59:59", "2026-11-05 23:59:59", None, 1, 0, "Web"),
        (90003, "000003", 1, 2, 8, 7, "2026-11-06 00:00:00", None, None, 1, 1, "Phone"),
        (90004, "000004", 1, 1, 8, 7, "2023-01-01 00:00:00", None, None, None, 0, "API"),
        (90005, "DUPLICATE", 1, 1, 8, 7, "2025-01-01 00:00:00", None, None, None, 0, "Web"),
        (90006, "DUPLICATE", 1, 1, 8, 0, "2025-01-01 00:00:00", None, None, None, 0, "Web"),
    ]
    cursor.executemany(f"INSERT INTO ost_ticket {columns} VALUES ({', '.join(['%s'] * 12)})", old + recent)
    cdata = "(ticket_id, priority, subject, listaEmpresa, tipoSolicitud, causa, analisis, solucion, time, timeExtra, apoyo1, timeApoyo1, secret_token)"
    custom = [(row[0], "2", f"Consulta {row[0]}", "218,HOSPICIO", "400,Incidente", "500", "Diagnóstico", "Solución", "01:30", None, None, None, "never-expose") for row in old]
    custom += [
        (90001, "3", "Ticket reciente", "218,HOSPICIO", "400,Incidente", "500", "Análisis", "Solución", "02:15", "0:45", "Luis Prueba", "1:00", "never-expose"),
        (90002, "2", "Literal _%= prueba", " 218 ,HOSPICIO", None, None, None, None, "00:20", None, None, None, "never-expose"),
        (90003, "2", "Ticket siguiente día", "219,Otra empresa", None, None, None, None, "1.5h", None, None, None, "never-expose"),
    ]
    cursor.executemany(f"INSERT INTO ost_ticket__cdata {cdata} VALUES ({', '.join(['%s'] * 13)})", custom)
    _insert(cursor, "ost_thread", [(50, 90002, "T", None), (51, 90002, "A", None), (52, 90003, "T", None), (60, 90001, "T", None)])
    entries = [(i, 50, 7, 8, "M", "Cliente", "Mensaje", "x" * 5000 if i == 2 else f"Mensaje {i}", "text", "10.0.0.1", None, None) for i in range(1, 6)]
    entries += [(6, 51, 7, 8, "N", "Agente", "Tarea", "NOT A TICKET", "text", "10.0.0.1", None, None),
                (7, 52, 7, 8, "N", "Agente", "Otro", "OTHER TICKET", "text", "10.0.0.1", None, None),
                (8, 50, 7, 0, "N", "Ana Pérez", "Nota", "<p>Revisar <b>servidor</b></p><script>x()</script>", "html", "10.0.0.1",
                 "2026-11-05 10:00:00", None)]
    entries += [(i, 60, 7, 8, "R", "Agente", "Respuesta", "😀" * 4001, "text", "10.0.0.1", "2026-11-05 12:00:00", None) for i in range(100, 120)]
    _insert(cursor, "ost_thread_entry", entries)
    _insert(cursor, "ost_thread_collaborator", [(1, 0, 50, 8, "M")])
    _insert(cursor, "ost_form_field", [(1, 2, "apoyo1", "never-expose"), (2, 2, "apoyo2", "never-expose"), (3, 2, "phone", "never-expose")])
    _insert(cursor, "ost_form_entry", [(1, 2, 90001, "T"), (2, 2, 90003, "T"), (3, 1, 8, "U")])
    _insert(cursor, "ost_form_entry_values", [(1, 1, '{"s10":"Luis Prueba"}'), (2, 2, '{"s10":"Luis Prueba"}'), (3, 3, "never-expose")])


def _grant_policy_columns(cursor, schema, account):
    """Column-level SELECT on the policy columns that exist in this schema, as `grants` would."""
    created = {table: {part.split()[0] for part in definition.split(", ") if not part.startswith("PRIMARY")}
               for table, definition in TABLES.items()}
    for table, columns in all_query_tables().items():
        granted = [column for column in columns if column in created.get(table, ())]
        if granted:
            listed = ", ".join(f"`{column}`" for column in granted)
            cursor.execute(f"GRANT SELECT ({listed}) ON `{schema}`.`{table}` TO {account}")


