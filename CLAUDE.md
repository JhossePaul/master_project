# Guía para los hilos de Claude en este repositorio

Proyecto de tesis de maestría *App Store Label Noise & Incident Analyzer*. El backlog está en [`docs/backlog/`](docs/backlog/README.md) y la historia de los resultados de EPIC-5 en [`docs/analytics/`](docs/analytics/README.md). La documentación y el código están en español.

## Un hilo por dominio

Cada hilo de Claude es una conversación de larga duración que es dueña de un **dominio amplio** del proyecto. El objetivo es no cargar el contexto con trabajo ajeno y evitar que dos hilos escriban los mismos archivos. Decisión del autor (2026-10-20): un hilo por dominio amplio, no uno por cada tarea puntual.

1. **Un hilo es un *fork* de la conversación principal, no una conversación aparte.** Aclaración del autor (2026-10-20):
   * la conversación principal abre cada hilo como sesión derivada de ella (`start_session` con `context: "fork"`, o `"fresh"` con un brief completo si la principal ya es larga). Así el hilo hereda el contexto y sus reportes le llegan solos a la principal;
   * **el autor no reenvía mensajes entre conversaciones.** La principal recibe el reporte de cada hilo al terminar su turno y le escribe a cada hilo con `SendMessage`;
   * **cada hilo envía su reporte final completo a la principal con `SendMessage`**, porque la nota automática de fin de turno se trunca a 400 caracteres; la principal pasa su id de sesión al abrir el fork. La primera línea es `[Reporte <hilo>] <resumen en una frase>`; no hace falta en turnos triviales (decisión del autor, 2026-10-22);
   * un hilo que necesita algo de otro dominio se lo pide a la principal en su reporte, no al autor;
   * un hilo abierto a mano, fuera de este esquema, se trata como *fork*: termina su trabajo, deja su aviso en el reporte final y la principal lo integra.
2. **Hilos actuales:**
   * **Control de versiones:** ramas, historia, commits, push y PR;
   * **Modelos (5.4)**;
   * **Golden dataset y etiquetado (5.3)**;
   * **Documentación y gobierno**;
   * **Datos y EDA (5.1 y 5.2)**;
   * **Tópicos (5.5)**.

   Se agregan otros cuando aparece un dominio nuevo (por ejemplo 5.6 a 5.8).
3. **La conversación principal orquesta:** abre los *forks*, manda cada actividad nueva al hilo de su dominio, reenvía los avisos entre hilos y revisa los resultados. No implementa. Un hilo nuevo se abre solo para un dominio nuevo, no para cada tarea puntual.
4. **Un hilo no hace trabajo de otro dominio.**
   * Si necesita un cambio en rutas de otro dominio, no lo hace: lo pide a la conversación principal.
   * Leer cualquier ruta está permitido.
   * **Excepción:** el autor puede encargar a un hilo, de forma temporal y explícita, pendientes de otro dominio (por ejemplo, el 2026-10-20 "Datos y EDA" actualizó la *Data Card*, `epic_5.md` y este archivo mientras se reabrían los hilos como *forks*). El hilo lo anota en su reporte.
5. **Los dominios se comunican por artefactos versionados, no por código ajeno.**
   * Quien produce publica una versión nueva (por ejemplo, `gold_v1`) con su reporte y el esquema de sus columnas.
   * Quien consume la incorpora en su propio hilo. Por ejemplo, re-evaluar los modelos contra un oro nuevo es trabajo de "Modelos", no de "Golden dataset y etiquetado".
   * Importar como biblioteca un módulo de otro dominio, sin modificarlo, está permitido (por ejemplo, `eda` usa `label_gemini.label_batch` y `sentiment.data`).
6. **Archivos compartidos:**
   * en [`docs/backlog/epic_5.md`](docs/backlog/epic_5.md), cada hilo edita solo la sección de sus features;
   * los módulos que usan varios dominios (tabla de abajo) se cambian solo en el hilo dueño, avisando a los que los consumen.
7. **Commits:** los hilos de dominio no commitean. Al terminar un cambio lo dicen en su reporte, y "Control de versiones" lo commitea y hace push con la aprobación del autor. Si el autor pide el commit directamente a un hilo, ese hilo lo hace.

## Mapa de responsabilidades

| Dominio | Hilo | Rutas de las que es dueño |
| :--- | :--- | :--- |
| Ramas, historia y publicación | Control de versiones | Ramas, commits, push y PR; no es dueño de rutas de contenido |
| 5.3 Etiquetado (oro y plata) | Golden dataset y etiquetado | `experiments/analytics/src/voc_analytics/labeling/` (salvo `eligibility.py`), `experiments/analytics/src/voc_analytics/sampling/`, `experiments/analytics/src/voc_analytics/annotation/`, `experiments/analytics/src/voc_analytics/analysis/`, `docs/analytics/{annotation_guideline.md,labeling_*,gold_*,silver_*,prompt_validation_*}` |
| 5.4 Competencia de modelos | Modelos | `experiments/analytics/src/voc_analytics/sentiment/`, `docs/analytics/sentiment_models_*` |
| Documentación y gobierno | Documentación y gobierno | `docs/governance/`, `docs/backlog/` (salvo las secciones de `epic_5.md` de cada feature), `docs/analytics/README.md` (índice de la historia), `docs/deployment.md`, `docs/full_backfill.md`, `docs/contracts/` |
| 5.1 Planteamiento y reglas de elegibilidad | Datos y EDA | `docs/analytics/eligibility_rules.md`, `experiments/analytics/src/voc_analytics/labeling/eligibility.py` |
| 5.2 EDA | Datos y EDA | `experiments/analytics/src/voc_analytics/eda/`, `experiments/analytics/src/voc_analytics/snapshot/`, `docs/analytics/eda*` |
| 5.5 Tópicos e incidencias | Tópicos | `experiments/analytics/src/voc_analytics/topics/`, `docs/analytics/topics_*` y la sección de la feature 5.5 en `docs/backlog/epic_5.md`. Consume `eda/prompts/aspects_v2_1.md` y `docs/analytics/eda_aspects_guideline.md` (`v2.1`) (dueño Datos y EDA) |
| EPIC-1 a EPIC-4 (ingesta, sanitización, infraestructura) | Sin hilo: se abre uno cuando vuelva a haber trabajo | `services/`, `packages/`, `infra/`, `web/`, `tools/` |

Mientras un dominio no tiene hilo, sus rutas no se modifican; la conversación principal abre el hilo cuando aparece trabajo. Las features 5.6 a 5.8 se agregan a esta tabla con su hilo cuando arranquen.

El código de EPIC-5 vive en el paquete `voc_analytics` (`experiments/analytics/src/`); el mapa de rutas anteriores está en [`experiments/analytics/MIGRATION.md`](experiments/analytics/MIGRATION.md). Los módulos compartidos de abajo son relativos a `voc_analytics/`.

**Módulos compartidos:**

| Módulo | Dueño | Lo usan |
| :--- | :--- | :--- |
| `labeling/eligibility.py` | Datos y EDA (5.1) | Golden dataset y etiquetado, Modelos |
| `eda/prompts/aspects_v2_1.md` y [`docs/analytics/eda_aspects_guideline.md`](docs/analytics/eda_aspects_guideline.md) | Datos y EDA (5.2) | Tópicos (5.5), si codifica aspectos con Gemini |
| `labeling/temporal_context.py` | Golden dataset y etiquetado | 5.2 (EDA temporal) |
| `labeling/label_gemini.py` | Golden dataset y etiquetado | Modelos (M9) |
| `paths.py` | Ninguno: se cambia solo con aprobación del autor | Todos |

## Convenciones del proyecto

* **Ramas y commits:**
  * trabajo en `develop`; `main` solo recibe PR;
  * solo el hilo "Control de versiones" commitea y hace push, y solo con la aprobación del autor;
  * los mensajes terminan con la línea `Co-Authored-By` indicada para el hilo.
* **Datos:**
  * nunca se versiona texto de reseñas ni etiquetas individuales; `experiments/analytics/data/`, `evidence/` y `.env` están fuera de git;
  * en `docs/` solo van agregados y ejemplos sintéticos;
  * la sanitización por regex no detecta nombres de personas (FMEA F-01). Enviar texto fuera de GCP requiere la autorización del autor y una fila en la [matriz FMEA](docs/governance/ethical_fmea_matrix.md).
* **Proyectos uv:**
  * el workspace de la raíz es producción;
  * `experiments/analytics` es un proyecto uv aparte, con su propio `pyproject.toml`, `uv.lock` y Python 3.11. Sus scripts se corren desde esa carpeta como módulos (`uv run python -m voc_analytics.<etapa>.<script>`), y la app de Streamlit con `uv run streamlit run src/voc_analytics/annotation/app.py`.
* **Decisiones:** los parámetros son decisiones metodológicas del autor; no hay dueño de negocio. Las decisiones se documentan en el reporte de la feature con su criterio.
