-- Conteos de elegibilidad por banco, mes y código para MLOps (EPIC-7, 7.9).
SELECT
  bank_id,
  DATE_TRUNC(DATE(fecha), MONTH) AS mes,
  eligibility_rules_version,
  eligibility_code,
  label_source,
  COUNT(*) AS filas
FROM `{project}.{dataset}.review_predictions_current`
GROUP BY bank_id, mes, eligibility_rules_version, eligibility_code, label_source
