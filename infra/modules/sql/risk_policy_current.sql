-- Apetito de riesgo vigente (global): última versión con valid_from <= ahora.
SELECT *
FROM `{project}.{dataset}.risk_policy`
WHERE valid_from <= CURRENT_TIMESTAMP()
QUALIFY ROW_NUMBER() OVER (ORDER BY valid_from DESC) = 1
