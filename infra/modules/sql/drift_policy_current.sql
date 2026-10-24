-- Política de deriva vigente de cada banco: su última versión con
-- valid_from <= ahora.
SELECT *
FROM `{project}.{dataset}.drift_policy`
WHERE valid_from <= CURRENT_TIMESTAMP()
QUALIFY ROW_NUMBER() OVER (PARTITION BY bank_id ORDER BY valid_from DESC) = 1
