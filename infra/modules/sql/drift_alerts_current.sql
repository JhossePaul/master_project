-- Estado vigente de cada alerta de deriva: su último evento.
WITH last_event AS (
  SELECT alert_id, status, actor_hash, at AS status_at, note, ticket
  FROM `{project}.{dataset}.drift_alert_events`
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY alert_id ORDER BY at DESC) = 1
)
SELECT
  a.*,
  e.status,
  e.actor_hash,
  e.status_at,
  e.note,
  e.ticket
FROM `{project}.{dataset}.drift_alerts` AS a
LEFT JOIN last_event AS e USING (alert_id)
