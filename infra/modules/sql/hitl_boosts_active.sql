-- Subidas HITL activas: dentro de su ventana y sin fila de cierre.
SELECT b.*
FROM `{project}.{dataset}.hitl_boosts` AS b
WHERE b.ended_reason IS NULL
  AND b.starts_at <= CURRENT_TIMESTAMP()
  AND CURRENT_TIMESTAMP() < b.ends_at
  AND NOT EXISTS (
    SELECT 1
    FROM `{project}.{dataset}.hitl_boosts` AS closed
    WHERE closed.boost_id = b.boost_id AND closed.ended_reason IS NOT NULL
  )
