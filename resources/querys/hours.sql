SELECT 
    t.number AS nro_ticket,
    t.created AS fecha_creacion,
    c.subject,
    uo.name AS de,
    ue.address AS de_correo_electronico,
    CASE SUBSTRING_INDEX(c.priority, ',', 1)
        WHEN '1' THEN 'Low'
        WHEN '2' THEN 'Normal'
        WHEN '3' THEN 'High'
        WHEN '4' THEN 'Emergency'
        ELSE SUBSTRING_INDEX(c.priority, ',', -1)
    END AS prioridad,
    d.name AS departamento,
    ht.topic AS tema_ayuda,
    t.source AS fuente,
    s.name AS estado,
    t.closed AS fecha_cierre,
    CASE WHEN t.isoverdue = 1 THEN 'Sí' ELSE 'No' END AS atrasado,
    ot.lastmessage AS fecha_ultimo_mensaje_cliente,
    ot.lastresponse AS fecha_ultima_respuesta_agente,
    CONCAT(u.firstname, ' ', u.lastname) AS agente_asignado,
    li.value AS empresa,
    NULLIF(c.fechaInicio, '0') AS fecha_inicio,
    NULLIF(c.fechaFin, '0') AS fecha_fin,
    c.time AS tiempo,
    c.analisis,
    c.solucion,
    CASE SUBSTRING_INDEX(c.ambiente, ',', 1)
        WHEN '1' THEN 'Producción'
        WHEN '2' THEN 'Certificación'
        ELSE SUBSTRING_INDEX(c.ambiente, ',', -1)
    END AS ambiente,
    ts.value AS tipoSolicitud,
    oli.value AS causa,
    CASE SUBSTRING_INDEX(c.vencimientoSoporte, ',', 1)
        WHEN '1' THEN 'Si'
        WHEN '2' THEN 'No'
        WHEN '3' THEN 'Por Hora'
        ELSE SUBSTRING_INDEX(c.vencimientoSoporte, ',', -1)
    END AS tieneSoporte,
    c.timeExtra AS tiempo_extra,
    c.horaCompensada AS horas_compensadas,
    CASE c.horaExtra WHEN '1' THEN 'Sí' ELSE 'No' END AS horas_noche_fin_semana,
    TRIM(REPLACE(REPLACE(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(c.apoyo1,'$.*')), '"',''), '[',''), ']','')) AS agente_apoyo1,
    c.timeApoyo1 AS tiempo_a1,
    TRIM(REPLACE(REPLACE(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(c.apoyo2,'$.*')), '"',''), '[',''), ']','')) AS agente_apoyo2,
    c.timeApoyo2 AS tiempo_a2,
    TRIM(REPLACE(REPLACE(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(c.apoyo3,'$.*')), '"',''), '[',''), ']','')) AS agente_apoyo3,
    c.timeApoyo3 AS tiempo_a3,    
    CONCAT('https://soporte.tesabiz.com/scp/tickets.php?id=', t.ticket_id) AS enlace_ticket
FROM ost_ticket t
LEFT JOIN ost_staff u ON t.staff_id = u.staff_id
LEFT JOIN ost_user uo ON t.user_id = uo.id
LEFT JOIN ost_user_email ue ON uo.id = ue.user_id
LEFT JOIN ost_ticket__cdata c ON t.ticket_id = c.ticket_id
LEFT JOIN ost_ticket_status s ON t.status_id = s.id
LEFT JOIN ost_department d ON t.dept_id = d.id
LEFT JOIN ost_list_items ts
    ON ts.id = NULLIF(SUBSTRING_INDEX(c.tipoSolicitud, ',', 1), '')
    AND ts.list_id = 4
LEFT JOIN ost_list_items li
    ON li.id = NULLIF(SUBSTRING_INDEX(c.listaEmpresa, ',', 1), '')
    AND li.list_id = 3
LEFT JOIN ost_list_items oli
    ON oli.id = NULLIF(SUBSTRING_INDEX(c.causa, ',', 1), '')
    AND oli.list_id = 5
LEFT JOIN ost_help_topic ht ON t.topic_id = ht.topic_id
LEFT JOIN ost_thread ot ON ot.object_id = t.ticket_id AND ot.object_type = 'T'
WHERE t.ticket_pid IS NULL
  AND s.name NOT IN ('Descartado')
  AND DATE(t.created) BETWEEN STR_TO_DATE(%(desde)s,'%Y%m%d')
                           AND STR_TO_DATE(%(hasta)s,'%Y%m%d')
ORDER BY c.fechaInicio DESC;
