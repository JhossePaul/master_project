-- Versión de tópicos que asigna: la más reciente por fitted_at cuyos tópicos
-- emparejados con la versión anterior tienen todos una decisión del curador
-- en curation_topics (mapping_confirmed verdadero o falso). La primera
-- versión no tiene pares, así que vale desde que se carga. El ruido (-1) no
-- está en el catálogo.
WITH undecided AS (
  SELECT c.topic_model_version, COUNT(*) AS topics
  FROM `{project}.{dataset}.topic_catalog` AS c
  LEFT JOIN (
    SELECT DISTINCT topic_model_version, topic_id
    FROM `{project}.{dataset}.curation_topics`
  ) AS k USING (topic_model_version, topic_id)
  WHERE c.previous_topic_id IS NOT NULL AND k.topic_id IS NULL
  GROUP BY c.topic_model_version
)
SELECT v.*
FROM `{project}.{dataset}.topic_model_versions` AS v
LEFT JOIN undecided AS u USING (topic_model_version)
WHERE u.topics IS NULL
QUALIFY ROW_NUMBER() OVER (ORDER BY v.fitted_at DESC) = 1
