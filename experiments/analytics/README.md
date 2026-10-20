# experiments/analytics

Experimentación de EPIC-5 (ver [`docs/backlog/epic_5.md`](../../docs/backlog/epic_5.md) y la
historia de los resultados en [`docs/analytics/`](../../docs/analytics/README.md)).
Es un proyecto `uv` propio, fuera del workspace, para que sus dependencias no
entren al `uv.lock` de producción. El código es el paquete `voc_analytics`
(`src/`), instalado en modo editable por `uv sync`. Todo se corre desde esta
carpeta con `uv run python -m voc_analytics.<etapa>.<script>`; las rutas a
`data/` y `docs/analytics/` salen de `voc_analytics.paths`, no del directorio
de trabajo. El mapa de rutas anteriores está en [`MIGRATION.md`](MIGRATION.md).

## Estructura

| Paquete | Etapa | Módulos |
| --- | --- | --- |
| `paths` | común | rutas de `data/` y `docs/analytics/` |
| `snapshot` | datos | `consolidate_tds_snapshot` |
| `eda` | EDA (5.2) | `eda_global`, `eda_temporal` |
| `labeling` | módulos compartidos de etiquetado | `eligibility` (5.1), `temporal_context`, `label_gemini`, `agreement`, `prompts/prompt_v0..v3.md` |
| `sampling` | muestreo (5.3) | `sample_pilot`\*, `sample_gold_v0`\*, `sample_gold_v0_r2`\*, `sample_silver`, `sample_gold_v1`, `strata` |
| `annotation` | anotación humana (5.3) | `app` (Streamlit) |
| `analysis` | análisis del etiquetado (5.3) | `analyze_gold_v0`\*, `validate_prompt`\*, `analyze_gold_v0_r2`\*, `analyze_silver`, `analyze_gold_v1` |
| `sentiment` | competencia de modelos (5.4) | `data`, `metrics`, `encoder`, `evaluate` |
| `sentiment.models` | modelos (5.4) | `baselines`, `pretrained`, `noisy`, `finetune`, `delora` |
| `sentiment.kaggle` | corridas con GPU (5.4) | `export_bundle`, `kaggle_push` |

\* **Histórico:** etapa cerrada y superada por una versión posterior. Se
conserva ejecutable para reproducir los reportes que lo citan. Lo mismo vale
para `prompt_v0` a `prompt_v2`; `prompt_v3` es el vigente. Las versiones de
prompt y los identificadores de corrida (`run_<run>.json`) no cambian con
esta estructura.

El EDA preliminar de viabilidad (referencia T0) está en
[`../project_viability/`](../project_viability/README.md), fuera de este
proyecto.

## Datos locales

`data/` está en `.gitignore`: contiene texto de reseñas (sanitizado solo con
regex, puede haber PII residual). Nunca versionar ni publicar su contenido.

| Archivo | Contenido |
| --- | --- |
| `data/tds_<SNAPSHOT>.parquet` | Copia completa de `bbva_voc_tds.sanitized_reviews_tds` (zstd, ordenada por banco y fecha) |
| `data/tds_<SNAPSHOT>.manifest.json` | Filas totales y por banco, rango de `fecha`, esquema y SHA-256 |
| `data/labels/<conjunto>/` | Muestras, colas, anotaciones y corridas de Gemini (`pilot_v0`, `gold_v0`, `gold_v0_r2`, `silver_v0`, `gold_v1`, `gold_v1_a2`) |
| `data/models/` | Predicciones (`preds/`), caché de validación cruzada y modelos de 5.4 |

Snapshot vigente: `20261016T054714Z`, 2 649 047 filas, 17 columnas. Los
`TIMESTAMP` de BigQuery se exportan sin zona y están en UTC.

## Pipeline, en orden de ejecución

Todos los comandos se corren desde `experiments/analytics`, con
`M=voc_analytics` definido en la terminal para abreviar el prefijo.

### 0. Snapshot del TDS

Exportar a GCS no consume cuota de consultas; la descarga (~500 MB) cabe en el
egress gratuito.

```sh
SNAP=$(date -u +%Y%m%dT%H%M%SZ)
bq --location=us-central1 extract --destination_format=PARQUET --compression=SNAPPY \
  project-7bafd424-a385-4c05-b5b:bbva_voc_tds.sanitized_reviews_tds \
  "gs://voc-datalake-project-7bafd424-a385-4c05-b5b/exports/sanitized_reviews_tds/$SNAP/part-*.parquet"
mkdir -p data/raw/$SNAP
gcloud storage cp "gs://voc-datalake-project-7bafd424-a385-4c05-b5b/exports/sanitized_reviews_tds/$SNAP/*.parquet" \
  data/raw/$SNAP/
uv run python -m voc_analytics.snapshot.consolidate_tds_snapshot $SNAP
rm -rf data/raw/$SNAP
```

BigQuery reparte el export en ~14 000 archivos pequeños; el script los
consolida, falla si hay claves `(bank_id, id_resena)` repetidas y escribe el
manifiesto.

### 1. EDA (5.2)

```sh
uv run python -m $M.eda.eda_global data/tds_<SNAPSHOT>.parquet
uv run python -m $M.eda.eda_temporal data/tds_<SNAPSHOT>.parquet
```

Solo escriben agregados en `docs/analytics/eda/`. Reportes:
[`eda_report.md`](../../docs/analytics/eda_report.md) y
[`eda_temporal_report.md`](../../docs/analytics/eda_temporal_report.md).

### 2. Etiquetado (5.3)

Las etapas con Gemini requieren ADC (`gcloud auth application-default
login`) y la API de Vertex AI habilitada (`enable_vertex_ai_api` en Pulumi).
La app de anotación sigue la
[guía de anotación](../../docs/analytics/annotation_guideline.md), no muestra
estrellas ni banco y agrega cada anotación a
`data/labels/<GOLD_DIR>/annotations.csv` (al corregir, gana la última fila
por `item_id`). `.streamlit/config.toml` la limita a `localhost`.

1. **Piloto\*:** muestra y etiquetas con cada prompt
   ([`labeling_pilot_v0.md`](../../docs/analytics/labeling_pilot_v0.md)).

   ```sh
   uv run python -m $M.sampling.sample_pilot data/tds_<SNAPSHOT>.parquet
   uv run python -m $M.labeling.label_gemini data/labels/pilot_v0/sample.parquet prompt_v2
   ```

2. **Oro, primera ronda\*:** cola `gold_v0` (calibración, aleatorio ciego y
   asistido, re-anotación), anotación, métricas y validación de `prompt_v2`
   ([`gold_v0_report.md`](../../docs/analytics/gold_v0_report.md)).
   `sample_gold_v0` no regenera la cola si ya existe `annotations.csv`.

   ```sh
   uv run python -m $M.sampling.sample_gold_v0 data/tds_<SNAPSHOT>.parquet
   uv run streamlit run src/voc_analytics/annotation/app.py
   uv run python -m $M.analysis.analyze_gold_v0 data/tds_<SNAPSHOT>.parquet <run_v0>
   uv run python -m $M.analysis.validate_prompt <run_v0> <run_candidato> [<run_candidato_2>]
   ```

3. **Re-anotación a ciegas\*** con la guía vigente; de aquí sale la elección
   de `prompt_v3` ([`gold_v0_r2_report.md`](../../docs/analytics/gold_v0_r2_report.md)).

   ```sh
   uv run python -m $M.sampling.sample_gold_v0_r2
   GOLD_DIR=gold_v0_r2 uv run streamlit run src/voc_analytics/annotation/app.py
   uv run python -m $M.analysis.analyze_gold_v0_r2 data/tds_<SNAPSHOT>.parquet
   ```

4. **Plata** con `prompt_v3`
   ([`silver_v0_report.md`](../../docs/analytics/silver_v0_report.md)).

   ```sh
   uv run python -m $M.sampling.sample_silver sample data/tds_<SNAPSHOT>.parquet
   uv run python -m $M.sampling.sample_silver label [--limit N]
   uv run python -m $M.analysis.analyze_silver
   ```

5. **Oro, segunda ronda (`gold_v1`):** necesita la plata y M1 (paso 3.1,
   `baselines`). `plan` no gasta; `queue` etiqueta el bloque aleatorio con
   `prompt_v3` (~$0.05)
   ([`gold_v1_report.md`](../../docs/analytics/gold_v1_report.md)).

   ```sh
   uv run python -m $M.sampling.sample_gold_v1 plan
   uv run python -m $M.sampling.sample_gold_v1 queue --option B
   GOLD_DIR=gold_v1 uv run streamlit run src/voc_analytics/annotation/app.py
   uv run python -m $M.analysis.analyze_gold_v1
   ```

### 3. Competencia de sentimiento (5.4)

Protocolo en [`sentiment_models_protocol.md`](../../docs/analytics/sentiment_models_protocol.md). Cada modelo
solo guarda predicciones del oro *dev* y de `holdout_nuevo` en
`data/models/preds/`; `evaluate` calcula todas las métricas con el mismo
protocolo. El oro *test* no se predice.

1. Líneas base y encoders sin ajuste:

   ```sh
   uv run python -m $M.sentiment.models.baselines   # M0 y M1 (validación cruzada ~7 min en CPU)
   uv run python -m $M.sentiment.models.pretrained  # M2 (RoBERTuito, BETO) y T0 (TextBlob), MPS
   ```

   `pretrained` descarga los checkpoints de Hugging Face la primera vez.

2. Escalera de ruido y encoders ajustados:

   ```sh
   uv run python -m $M.sentiment.models.noisy                 # M3, M6, M7 (TF-IDF con estrellas), CPU
   uv run python -m $M.sentiment.models.finetune robertuito   # M4, ~50 min en MPS
   uv run python -m $M.sentiment.models.delora robertuito     # M8 (Delora), horas en MPS
   ```

   En el Mac de 8 GB los encoders usan lote 8 × 4 y embeddings congelados.

3. Kaggle (opcional, GPU): `export_bundle` arma `data/kaggle_bundle/` (sin el
   oro *test*) con los módulos de `voc_analytics` que usan los encoders;
   `kaggle_push` sube el dataset y lanza lotes que corren
   `python -m voc_analytics.sentiment.models.<modelo>`. Requiere el token de
   la API de Kaggle en `~/.kaggle/access_token`. Las predicciones
   descargadas se copian a `data/models/preds/`.

   ```sh
   uv run python -m $M.sentiment.kaggle.export_bundle
   uv run python -m $M.sentiment.kaggle.kaggle_push dataset <usuario> [--update]
   uv run python -m $M.sentiment.kaggle.kaggle_push kernel <usuario> <lote>
   ```

4. Evaluación común (~6 min de bootstrap):

   ```sh
   uv run python -m $M.sentiment.evaluate
   ```

Reporte: [`sentiment_models_v0_report.md`](../../docs/analytics/sentiment_models_v0_report.md).
