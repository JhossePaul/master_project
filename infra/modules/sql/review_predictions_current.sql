-- Predicción vigente por reseña: filas de la versión promovida y, por
-- id_resena, la última (una reseña editada cambia de text_key y suma otra
-- fila). Calcula la clase de las estrellas y las marcas de incongruencia.
WITH model_state AS (
  SELECT
    model_version,
    status,
    ROW_NUMBER() OVER (
      PARTITION BY model_version ORDER BY recorded_at DESC
    ) AS rn
  FROM `{project}.{dataset}.model_versions`
),
promoted AS (
  SELECT model_version FROM model_state WHERE rn = 1 AND status = 'promoted'
),
latest AS (
  SELECT
    p.*,
    ROW_NUMBER() OVER (
      PARTITION BY p.id_resena ORDER BY p.fecha DESC, p.predicted_at DESC
    ) AS rn
  FROM `{project}.{dataset}.review_predictions` AS p
  JOIN promoted USING (model_version)
),
classed AS (
  SELECT
    * EXCEPT (rn),
    CASE
      WHEN estrellas <= 2 THEN 'NEG'
      WHEN estrellas = 3 THEN 'NEU'
      ELSE 'POS'
    END AS estrellas_clase
  FROM latest
  WHERE rn = 1
)
SELECT
  *,
  sentiment IN ('NEG', 'NEU', 'POS')
    AND estrellas_clase != sentiment AS estrellas_difiere,
  (estrellas <= 2 AND sentiment = 'POS')
    OR (estrellas >= 4 AND sentiment = 'NEG') AS incongruencia_extremos,
  sentiment IN ('NEG', 'NEU', 'POS')
    AND STRPOS('NEGNEUPOS', sentiment) < STRPOS('NEGNEUPOS', estrellas_clase)
    AS texto_peor,
  sentiment IN ('NEG', 'NEU', 'POS')
    AND STRPOS('NEGNEUPOS', sentiment) > STRPOS('NEGNEUPOS', estrellas_clase)
    AS texto_mejor
FROM classed
