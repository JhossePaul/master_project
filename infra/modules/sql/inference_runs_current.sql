-- Estado vigente de cada corrida: la fila de cierre si existe; si no, la de
-- inicio (running). Las corridas que solo escriben su cierre tienen una fila.
SELECT *
FROM `{project}.{dataset}.inference_runs`
WHERE TRUE
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY run_id ORDER BY IF(status = 'running', 1, 0), ended_at DESC
) = 1
