-- Estado vigente de cada caso HITL: su última transición.
WITH last_event AS (
  SELECT item_id, status, actor_hash, at AS status_at
  FROM `{project}.{dataset}.hitl_events`
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY at DESC) = 1
)
SELECT
  i.*,
  e.status,
  e.actor_hash,
  e.status_at
FROM `{project}.{dataset}.hitl_items` AS i
LEFT JOIN last_event AS e USING (item_id)
