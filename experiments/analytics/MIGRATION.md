# Mapa de rutas de `experiments/analytics`

Reorganización del código de EPIC-5 en el paquete `voc_analytics` (`src/`),
agrupado por etapa del pipeline (ver [`README.md`](README.md)). Las rutas son
relativas a `experiments/analytics/`. Los scripts ya no se corren por ruta
sino como módulo, desde esta carpeta: `uv run python -m <módulo>`. La app de
anotación se corre con `uv run streamlit run src/voc_analytics/annotation/app.py`.

## Rutas anteriores → nuevas

| Ruta anterior | Ruta nueva | Módulo | Notas |
| --- | --- | --- | --- |
| `annotation/app.py` | `src/voc_analytics/annotation/app.py` | — | se corre con `streamlit run` |
| `eda/eda_global.py` | `src/voc_analytics/eda/eda_global.py` | `voc_analytics.eda.eda_global` |  |
| `eda/eda_temporal.py` | `src/voc_analytics/eda/eda_temporal.py` | `voc_analytics.eda.eda_temporal` |  |
| `labeling/analyze_gold.py` | `src/voc_analytics/analysis/analyze_gold_v0.py` | `voc_analytics.analysis.analyze_gold_v0` | renombrado; histórico; `CLASSES`, `kappa`, `confusion`, `weighted_share` → `labeling/agreement.py` |
| `labeling/analyze_gold_v1.py` | `src/voc_analytics/analysis/analyze_gold_v1.py` | `voc_analytics.analysis.analyze_gold_v1` |  |
| `labeling/analyze_reannotation.py` | `src/voc_analytics/analysis/analyze_gold_v0_r2.py` | `voc_analytics.analysis.analyze_gold_v0_r2` | renombrado; histórico |
| `labeling/analyze_silver.py` | `src/voc_analytics/analysis/analyze_silver.py` | `voc_analytics.analysis.analyze_silver` |  |
| `labeling/eligibility.py` | `src/voc_analytics/labeling/eligibility.py` | `voc_analytics.labeling.eligibility` |  |
| `labeling/label_gemini.py` | `src/voc_analytics/labeling/label_gemini.py` | `voc_analytics.labeling.label_gemini` |  |
| `labeling/prompt_v0.md` | `src/voc_analytics/labeling/prompts/prompt_v0.md` | — | histórico |
| `labeling/prompt_v1.md` | `src/voc_analytics/labeling/prompts/prompt_v1.md` | — | histórico |
| `labeling/prompt_v2.md` | `src/voc_analytics/labeling/prompts/prompt_v2.md` | — | histórico |
| `labeling/prompt_v3.md` | `src/voc_analytics/labeling/prompts/prompt_v3.md` | — |  |
| `labeling/sample_gold.py` | `src/voc_analytics/sampling/sample_gold_v0.py` | `voc_analytics.sampling.sample_gold_v0` | renombrado; histórico; `PERIODS`, `period` → `sampling/strata.py` |
| `labeling/sample_gold_v1.py` | `src/voc_analytics/sampling/sample_gold_v1.py` | `voc_analytics.sampling.sample_gold_v1` |  |
| `labeling/sample_pilot.py` | `src/voc_analytics/sampling/sample_pilot.py` | `voc_analytics.sampling.sample_pilot` | histórico |
| `labeling/sample_reannotation.py` | `src/voc_analytics/sampling/sample_gold_v0_r2.py` | `voc_analytics.sampling.sample_gold_v0_r2` | renombrado; histórico |
| `labeling/sample_silver.py` | `src/voc_analytics/sampling/sample_silver.py` | `voc_analytics.sampling.sample_silver` |  |
| `labeling/temporal_context.py` | `src/voc_analytics/labeling/temporal_context.py` | `voc_analytics.labeling.temporal_context` |  |
| `labeling/validate_prompt.py` | `src/voc_analytics/analysis/validate_prompt.py` | `voc_analytics.analysis.validate_prompt` | histórico |
| `scripts/consolidate_tds_snapshot.py` | `src/voc_analytics/snapshot/consolidate_tds_snapshot.py` | `voc_analytics.snapshot.consolidate_tds_snapshot` |  |
| `sentiment/baselines.py` | `src/voc_analytics/sentiment/models/baselines.py` | `voc_analytics.sentiment.models.baselines` |  |
| `sentiment/data.py` | `src/voc_analytics/sentiment/data.py` | `voc_analytics.sentiment.data` |  |
| `sentiment/delora.py` | `src/voc_analytics/sentiment/models/delora.py` | `voc_analytics.sentiment.models.delora` |  |
| `sentiment/encoder.py` | `src/voc_analytics/sentiment/encoder.py` | `voc_analytics.sentiment.encoder` |  |
| `sentiment/evaluate.py` | `src/voc_analytics/sentiment/evaluate.py` | `voc_analytics.sentiment.evaluate` |  |
| `sentiment/export_bundle.py` | `src/voc_analytics/sentiment/kaggle/export_bundle.py` | `voc_analytics.sentiment.kaggle.export_bundle` |  |
| `sentiment/finetune.py` | `src/voc_analytics/sentiment/models/finetune.py` | `voc_analytics.sentiment.models.finetune` |  |
| `sentiment/kaggle_push.py` | `src/voc_analytics/sentiment/kaggle/kaggle_push.py` | `voc_analytics.sentiment.kaggle.kaggle_push` |  |
| `sentiment/metrics.py` | `src/voc_analytics/sentiment/metrics.py` | `voc_analytics.sentiment.metrics` |  |
| `sentiment/noisy.py` | `src/voc_analytics/sentiment/models/noisy.py` | `voc_analytics.sentiment.models.noisy` |  |
| `sentiment/pretrained.py` | `src/voc_analytics/sentiment/models/pretrained.py` | `voc_analytics.sentiment.models.pretrained` |  |

## Archivos nuevos

| Ruta | Contenido |
| --- | --- |
| `src/voc_analytics/paths.py` | `ANALYTICS`, `ROOT`, `DATA`, `LABELS`, `MODELS`, `DOCS`; reemplaza los `Path(__file__).parents[n]` de cada script |
| `src/voc_analytics/labeling/agreement.py` | κ, matrices de confusión y proporciones ponderadas del oro, antes en `labeling/analyze_gold.py` |
| `src/voc_analytics/sampling/strata.py` | periodos de la estratificación del oro, antes en `labeling/sample_gold.py` |
| `src/voc_analytics/**/__init__.py` | paquetes vacíos |

## Cambios de comportamiento

* **Ninguno en los resultados.** Las salidas (`data/…`, `docs/analytics/*.json`
  y figuras), las versiones de prompt y los identificadores de corrida son
  los mismos; `label_gemini` lee los prompts de `labeling/prompts/`.
* **Sin `sys.path.insert`:** los imports entre módulos son absolutos
  (`from voc_analytics.sentiment.data import …`).
* **Kaggle:** `export_bundle` copia los módulos de `voc_analytics` que usan
  los encoders, con la misma estructura, y los lotes de `kaggle_push` corren
  `python -m voc_analytics.sentiment.models.{finetune,delora}`. Los tags
  de las corridas no cambian. Antes de la próxima corrida en Kaggle hay que
  regenerar el paquete y subirlo (`dataset <usuario> --update`).
* **M1:** `m1_tfidf_lr.pkl` se sigue guardando desde `__main__` de
  `baselines`, así que `sample_gold_v1.load_m1` carga igual los pickles
  anteriores y los nuevos.

## Pendiente para la sesión de documentación

* Citan rutas o nombres anteriores (aplicar la tabla de arriba):
  * `docs/analytics/`: `eda_report.md`, `eda_temporal_report.md`,
    `labeling_pilot_v0.md`, `gold_v0_report.md`, `gold_v0_r2_report.md`,
    `gold_v1_report.md`, `silver_v0_report.md`,
    `sentiment_models_v0_report.md`;
  * `docs/backlog/`: `epic_5.md`, `epic_5_deployment.md`, `epic_6.md`;
  * `docs/governance/ethical_fmea_matrix.md` (`label_gemini.py`).
* Mapa de responsabilidades de `CLAUDE.md`: 5.1 → `labeling/eligibility.py`;
  5.2 → `eda/`, `snapshot/`; 5.3 → `labeling/` (salvo `eligibility.py`),
  `sampling/`, `annotation/`, `analysis/`; 5.4 → `sentiment/`; todas bajo
  `experiments/analytics/src/voc_analytics/`. `paths.py` es compartido.
* `experiments/project_viability/` (EDA preliminar, T0) se versiona sin
  salidas, con su [`README.md`](../project_viability/README.md).
