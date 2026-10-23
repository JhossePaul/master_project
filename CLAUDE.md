# Guía para las sesiones de Claude en este repositorio

Proyecto de tesis de maestría *App Store Label Noise & Incident Analyzer*. El backlog está en [`docs/backlog/`](docs/backlog/README.md) y la historia de los resultados de EPIC-5 en [`docs/analytics/`](docs/analytics/README.md). La documentación y el código están en español.

## Sesiones: una principal y, como máximo, una paralela

Decisión del autor (2026-10-22). Reemplaza el esquema de un hilo por dominio orquestado por la principal (2026-10-20): costaba muchos tokens y los avisos entre hilos se perdían o llegaban truncados.

1. **La sesión principal implementa.** Trabaja la feature activa de punta a punta (código, reportes, backlog) y hace sus commits en `develop` con la aprobación del autor. No hay hilo de control de versiones.
2. **Como máximo una sesión paralela**, solo para una feature independiente de la que lleva la principal:
   * independiente quiere decir que no toca las mismas rutas (ver el [mapa de áreas](#mapa-de-áreas)) ni necesita un resultado que la principal aún no produce;
   * corre en su propio *git worktree* y su propia rama, así que no pisa los archivos de la principal;
   * arranca en limpio (`context: "fresh"`) con un brief corto: qué feature, qué rutas puede tocar y cuándo está terminada. No se abre como *fork*, porque un *fork* copia la conversación completa;
   * commitea en su rama y, al terminar, deja su reporte en `docs/` (el de su feature) y su rama lista para merge. La principal revisa el diff y hace el merge con la aprobación del autor.
3. **La comunicación va por el repo, no por mensajes.** El estado vive en `docs/backlog/epic_N.md`, los reportes de cada feature y este archivo. Si la paralela necesita algo de la principal, lo anota en su reporte y se detiene; no se coordinan con `SendMessage`. Entre features se comparten artefactos versionados (por ejemplo, `gold_v1`) con su reporte y el esquema de sus columnas; importar un módulo de otra área sin modificarlo está permitido.
4. **Exploración amplia con subagentes.** Buscar o leer en muchos archivos se delega a un subagente que devuelve solo la conclusión, para no llenar el contexto de la sesión.
5. **Sesión nueva por tema cuando el contexto crece.** Al cerrar una feature, o cuando la conversación ya es larga, se empieza una sesión nueva. Lo que hay que recordar se escribe antes en el repo (backlog, reporte o este archivo).
6. **Commits:**
   * se agrupan por tema; los cambios chicos o relacionados esperan a juntarse con otros en vez de commitearse uno por uno;
   * la sesión propone los commits con su mensaje y commitea solo cuando el autor aprueba; lo mismo para push y PR;
   * los mensajes terminan con la línea `Co-Authored-By` indicada para la sesión.

## Mapa de áreas

Ya no hay un hilo por área: el mapa sirve para decidir si una sesión paralela es independiente de la principal (no comparten rutas) y para saber qué consumidores revisar cuando cambia un módulo compartido.

| Feature | Área | Rutas |
| :--- | :--- | :--- |
| 5.3 Etiquetado (oro y plata) | Golden dataset y etiquetado | `experiments/analytics/src/voc_analytics/labeling/` (salvo `eligibility.py`), `experiments/analytics/src/voc_analytics/sampling/`, `experiments/analytics/src/voc_analytics/annotation/`, `experiments/analytics/src/voc_analytics/analysis/`, `docs/analytics/labeling/` |
| 5.4 Competencia de modelos | Modelos | `experiments/analytics/src/voc_analytics/sentiment/`, `docs/analytics/sentiment/` |
| Documentación y gobierno | Documentación y gobierno | `docs/governance/`, `docs/backlog/` (salvo las secciones de `epic_5.md` de cada feature), `docs/analytics/README.md` (índice de la historia), `docs/README.md`, `docs/operations/`, `docs/contracts/` |
| 5.1 Planteamiento y reglas de elegibilidad | Datos y EDA | `docs/analytics/eda/eligibility_rules.md`, `experiments/analytics/src/voc_analytics/labeling/eligibility.py` |
| 5.2 EDA | Datos y EDA | `experiments/analytics/src/voc_analytics/eda/`, `experiments/analytics/src/voc_analytics/snapshot/`, `docs/analytics/eda/` |
| 5.5 Tópicos e incidencias | Tópicos | `experiments/analytics/src/voc_analytics/topics/`, `docs/analytics/topics/` y la sección de la feature 5.5 en `docs/backlog/epic_5.md`. Consume `eda/prompts/aspects_v2_1.md` y `docs/analytics/eda/eda_aspects_guideline.md` (`v2.1`) (área Datos y EDA) |
| 5.6 Calibración, HITL, PPI y priorización | Calibración | `experiments/analytics/src/voc_analytics/calibration/`, `experiments/analytics/src/voc_analytics/sampling/sample_ppi.py`, `docs/analytics/calibration/` y la sección de la feature 5.6 en `docs/backlog/epic_5.md` |
| 5.7 Escala, ciclo de vida y monitoreo | Escala | `experiments/analytics/src/voc_analytics/scale/`, `docs/analytics/scale/` y la sección de la feature 5.7 en `docs/backlog/epic_5.md` |
| 5.8 Registro de decisión | Decisión | `docs/analytics/decision_record.md`, el registro de decisiones de `docs/backlog/epic_5.md` y `docs/contracts/analytics_outputs_v3_draft.md` |
| 5.9 Temas por día y versiones (descriptivo) | Temas por día | `experiments/analytics/src/voc_analytics/incidents/`, `docs/analytics/incidents/` y la sección de la feature 5.9 en `docs/backlog/epic_5.md`. Consume (sin modificarlos) `labeling/eligibility.py`, `topics/versions.py`, `scale/backfill.py` y las predicciones del backfill de M4 (`data/backfill/20261022/`) |
| 6.1 Contratos v3 | Contratos | `packages/voc-common/`, `docs/contracts/analytics_outputs_v3.md` (reemplaza al borrador `analytics_outputs_v3_draft.md`) |
| 6.2 Infraestructura de salidas y curadurías | Infraestructura | `infra/`, `.github/workflows/`, `.dockerignore` y el `pyproject.toml` de la raíz |
| 6.3 Inferencia batch y 6.4 Monitoreo y ciclo de vida | Inferencia | `packages/voc-nlp/` (nuevo), `services/ml-inference/` (nuevo; reemplaza al stub `services/ml-delora/`) |
| EPIC-1 a EPIC-4 (ingesta, sanitización, infraestructura) | Ingeniería de extracción (cerrada) | `services/`, `packages/`, `infra/`, `web/`, `tools/` |

Las rutas de EPIC-1 a EPIC-4 solo se cambian cuando hay trabajo de su épica o de EPIC-6 (filas 6.1 a 6.4). EPIC-7 se agrega a esta tabla cuando arranque. Dentro de EPIC-6 el orden es 6.1 → 6.2 → 6.3 → 6.4 ([`epic_6.md`](docs/backlog/epic_6.md)); 6.1 y 6.2 comparten PR, así que no son independientes.

El código de EPIC-5 vive en el paquete `voc_analytics` (`experiments/analytics/src/`) y su evidencia en `docs/analytics/`, con una carpeta por etapa del paquete; el mapa de rutas anteriores está en [`experiments/analytics/MIGRATION.md`](experiments/analytics/MIGRATION.md). Los módulos compartidos de abajo son relativos a `voc_analytics/`.

**Módulos compartidos** (quien los cambie revisa a sus consumidores en la misma sesión):

| Módulo | Área dueña | Lo usan |
| :--- | :--- | :--- |
| `labeling/eligibility.py` | Datos y EDA (5.1) | Golden dataset y etiquetado, Modelos |
| `eda/prompts/aspects_v2_1.md` y [`docs/analytics/eda/eda_aspects_guideline.md`](docs/analytics/eda/eda_aspects_guideline.md) | Datos y EDA (5.2) | Tópicos (5.5), si codifica aspectos con Gemini |
| `labeling/temporal_context.py` | Golden dataset y etiquetado | 5.2 (EDA temporal) |
| `labeling/label_gemini.py` | Golden dataset y etiquetado | Modelos (M9) |
| `paths.py` | Ninguna: se cambia solo con aprobación del autor | Todos |
| `labeling/eligibility.py`, `eda/eda_lexicon.py` y `lexicon_v1`, `calibration/calibrate.py` (temperatura), `calibration/selective.py`, `calibration/ppi.py`, `scale/drift_baseline.py`, `eda/prompts/aspects_v2_1.md` | Su área en EPIC-5 | `packages/voc-nlp/` (EPIC-6) los porta sin cambiar el criterio: si cambia el original, cambia también el port, con su prueba |

## Convenciones del proyecto

* **Ramas y commits:**
  * trabajo en `develop`; `main` solo recibe PR; una sesión paralela trabaja en su propia rama;
  * se commitea y se hace push solo con la aprobación del autor (ver la regla 6 de las sesiones).
* **Datos:**
  * nunca se versiona texto de reseñas ni etiquetas individuales; `experiments/analytics/data/`, `experiments/playstore/evidence/` y `.env` están fuera de git;
  * en `docs/` solo van agregados y ejemplos sintéticos;
  * excepción aprobada (D2 de EPIC-6, 2026-10-23): `packages/voc-nlp/` versiona `lexicon_v1.json`, con 151 formas y su etiqueta agregada (soporte ≥ 3, pureza ≥ 0.9) y su SHA-256; no son reseñas ni etiquetas individuales;
  * la sanitización por regex no detecta nombres de personas (FMEA F-01). Enviar texto fuera de GCP requiere la autorización del autor y una fila en la [matriz FMEA](docs/governance/ethical_fmea_matrix.md).
* **Proyectos uv:**
  * el workspace de la raíz es producción;
  * `experiments/analytics` es un proyecto uv aparte, con su propio `pyproject.toml`, `uv.lock` y Python 3.11. Sus scripts se corren desde esa carpeta como módulos (`uv run python -m voc_analytics.<etapa>.<script>`), y la app de Streamlit con `uv run streamlit run src/voc_analytics/annotation/app.py`.
* **Decisiones:** los parámetros son decisiones metodológicas del autor; no hay dueño de negocio. Las decisiones se documentan en el reporte de la feature con su criterio.
