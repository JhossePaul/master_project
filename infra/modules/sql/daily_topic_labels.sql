-- Top 5 diario de temas de las negativas (5.9, P9-4): port de
-- voc_analytics.incidents.daily_topics. Descriptivo, sin umbral.
-- * Base: reseñas NEG con dos palabras o más, por banco y día (UTC).
-- * Familias de aspects_v2_1 (última etiqueta de cada reseña) con el nombre
--   de la guía v2.1; tópicos útiles de la curaduría (producto o ingeniería)
--   de la versión de tópicos vigente (topic_model_current), con su nombre
--   curado.
-- * participacion: reseñas del día con el tema entre las negativas del día.
-- * habitual: lo mismo en los 28 días previos del banco, sin el día.
-- * Desempate por código (numérico en los tópicos).
WITH base AS (
  SELECT id_resena, bank_id, DATE(fecha) AS dia
  FROM `{project}.{dataset}.review_predictions_current`
  WHERE sentiment = 'NEG' AND palabras >= 2
),
n_day AS (
  SELECT bank_id, dia, COUNT(*) AS n_neg FROM base GROUP BY bank_id, dia
),
aspects AS (
  SELECT id_resena, families, prompt_version
  FROM `{project}.{dataset}.review_aspects`
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY id_resena ORDER BY labeled_at DESC
  ) = 1
),
topic_version AS (
  SELECT topic_model_version
  FROM `{project}.{dataset}.topic_model_current`
),
latest_curation AS (
  SELECT c.topic_id, c.curated_name, c.audience
  FROM `{project}.{dataset}.curation_topics` AS c
  JOIN topic_version USING (topic_model_version)
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY c.topic_id ORDER BY c.curated_at DESC
  ) = 1
),
useful_topics AS (
  SELECT topic_id, curated_name
  FROM latest_curation
  WHERE audience IN ('producto', 'ingenieria')
),
themes AS (
  SELECT DISTINCT
    a.id_resena,
    'familia' AS tipo,
    family AS codigo,
    CAST(NULL AS INT64) AS codigo_num,
    a.prompt_version AS aspects_prompt_version,
    CAST(NULL AS STRING) AS topic_model_version
  FROM aspects AS a, UNNEST(a.families) AS family
  UNION ALL
  SELECT DISTINCT
    t.id_resena,
    'topico' AS tipo,
    CAST(t.topic_id AS STRING) AS codigo,
    t.topic_id AS codigo_num,
    CAST(NULL AS STRING) AS aspects_prompt_version,
    t.topic_model_version
  FROM `{project}.{dataset}.topic_assignments` AS t
  JOIN topic_version USING (topic_model_version)
  JOIN useful_topics USING (topic_id)
),
counts AS (
  SELECT
    b.bank_id,
    b.dia,
    th.tipo,
    th.codigo,
    ANY_VALUE(th.codigo_num) AS codigo_num,
    ANY_VALUE(th.aspects_prompt_version) AS aspects_prompt_version,
    ANY_VALUE(th.topic_model_version) AS topic_model_version,
    COUNT(DISTINCT b.id_resena) AS filas
  FROM base AS b
  JOIN themes AS th USING (id_resena)
  GROUP BY b.bank_id, b.dia, th.tipo, th.codigo
),
codes AS (
  SELECT DISTINCT tipo, codigo, codigo_num FROM counts
),
dense AS (
  SELECT
    n.bank_id,
    n.dia,
    n.n_neg,
    k.tipo,
    k.codigo,
    k.codigo_num,
    c.aspects_prompt_version,
    c.topic_model_version,
    COALESCE(c.filas, 0) AS filas
  FROM n_day AS n
  CROSS JOIN codes AS k
  LEFT JOIN counts AS c
    ON c.bank_id = n.bank_id
    AND c.dia = n.dia
    AND c.tipo = k.tipo
    AND c.codigo = k.codigo
),
windowed AS (
  SELECT
    *,
    filas / n_neg AS participacion,
    SAFE_DIVIDE(
      SUM(filas) OVER habitual_window, SUM(n_neg) OVER habitual_window
    ) AS habitual
  FROM dense
  WINDOW habitual_window AS (
    PARTITION BY bank_id, tipo, codigo
    ORDER BY UNIX_DATE(dia)
    RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING
  )
),
ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY bank_id, dia, tipo
      ORDER BY filas DESC, codigo_num, codigo
    ) AS rango
  FROM windowed
  WHERE filas > 0
)
SELECT
  r.bank_id,
  r.dia,
  r.n_neg,
  r.tipo,
  r.rango,
  r.codigo,
  IF(
    r.tipo = 'familia',
    CASE r.codigo
      WHEN 'AC' THEN 'Acceso y autenticación'
      WHEN 'FA' THEN 'Falla general de la app'
      WHEN 'LE' THEN 'Lentitud general'
      WHEN 'TR' THEN 'Transferencias y pagos'
      WHEN 'DI' THEN 'Dinero y cargos'
      WHEN 'PR' THEN 'Productos y cuentas'
      WHEN 'AT' THEN 'Atención'
      WHEN 'DV' THEN 'Diseño visual'
      WHEN 'UX' THEN 'Usabilidad, recorrido y cambios de funciones'
      WHEN 'CO' THEN 'Compatibilidad, instalación y actualización'
      WHEN 'OT' THEN 'Sin familia'
    END,
    u.curated_name
  ) AS nombre,
  r.filas,
  r.participacion,
  r.habitual,
  r.aspects_prompt_version,
  r.topic_model_version
FROM ranked AS r
LEFT JOIN useful_topics AS u
  ON r.tipo = 'topico' AND u.topic_id = r.codigo_num
WHERE r.rango <= 5
