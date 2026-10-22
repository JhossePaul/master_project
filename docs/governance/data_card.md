# Data Card — Corpus de reseñas de banca móvil (TDS)

* **Versión:** borrador 0.2 (2026-10-20). Se completa en iteraciones de EPIC-5; la próxima es el registro de decisión (5.8).
  * **0.2:** EDA completo (5.2: tokens, multi-aspecto y léxico), oro y plata vigentes (5.3) y etiquetas de aspecto.
  * **0.1** (2026-10-17): primera versión, con el EDA global y las reglas de elegibilidad.
* **Formato:** sigue la estructura de *Datasheets for Datasets* (Gebru et al., 2021); ver [`references.md`](references.md).
* **Fuentes de esta versión:** [cierre de EPIC-1–4](../backlog/epics.md#cierre-de-las-épicas-1-a-4) y [carga del histórico](../operations/full_backfill.md), [EDA global](../analytics/eda/eda_report.md) (incluida la sección 5), [patrones temporales](../analytics/eda/eda_temporal_report.md), [reglas de elegibilidad](../analytics/eda/eligibility_rules.md), [`gold_v1`](../analytics/labeling/gold_v1_report.md), [plata](../analytics/labeling/silver_v0_report.md) y [guía de aspectos](../analytics/eda/eda_aspects_guideline.md).

## 1. Motivación

| Pregunta | Respuesta |
| :--- | :--- |
| ¿Para qué se creó? | Trabajo académico de maestría: medir la brecha entre las estrellas y el sentimiento real del texto (*Label Noise Bias*), descubrir tópicos de incidencias y priorizarlas, en las apps de banca móvil de México |
| ¿Quién lo creó y financia? | El autor del proyecto, de forma independiente. **No hay relación con los bancos** ni un dueño de negocio; las decisiones de alcance son metodológicas y del autor |
| ¿Qué no es? | No es una muestra representativa de la clientela de cada banco, ni una medición oficial de su satisfacción |

## 2. Composición

* **Unidad:** una reseña pública de Google Play, identificada por `(bank_id, id_resena)`. No hay duplicados de esa clave.
* **Volumen** (snapshot `tds_20261016T054714Z`):

  | Banco | App (`app_id`) | Reseñas | Desde | Estrellas prom. |
  | :--- | :--- | ---: | :--- | ---: |
  | BBVA | `com.bancomer.mbanking` | 787 875 | 2011-04 | 3.72 |
  | SANTANDER | `mx.bancosantander.supermovil` | 623 594 | 2012-03 | 4.03 |
  | AZTECA | `mx.com.bancoazteca.bazdigitalmovil` | 590 981 | 2017-03 | 4.40 |
  | BANORTE | `org.microemu.android.model.common.VTUserApplicationBNRTMB` | 518 393 | 2012-03 | 4.25 |
  | NUBANK | `com.nu.production` | 128 204 | 2015-08 | 4.21 |
  | **Total** | | **2 649 047** | hasta 2026-10-14 | |

* **Campos:**
  * texto sanitizado y limpio;
  * estrellas (1–5);
  * votos de utilidad;
  * versión de la app (`UNKNOWN` en el 8.8 %);
  * fecha;
  * hash irreversible del usuario (`usuario_hash`);
  * conteo de hallazgos de PII;
  * `sanitized_at` y `source_observed_at` (momento de captura).
* **Campos vacíos por diseño:**
  * `titulo`: Google Play no expone títulos.
  * Respuesta del banco y su fecha: excluidas intencionalmente en la ingesta (EPIC-3), porque no son el foco del análisis y a menudo citaban el nombre de usuario.
* **Etiquetas:** las estrellas son una etiqueta **ruidosa** del sentimiento del texto, no la verdad.
  * **Oro** (5.3): 1 730 reseñas anotadas a ciegas por el autor, en dos rondas (`gold_v0_r2` y `gold_v1`): *dev* aleatorio 799, *dev* dirigido 300, *test* 601 y 30 de calibración. Solo los bloques aleatorios, estratificados por banco × periodo (y estrellas en `gold_v1`), dan cifras poblacionales. Guía vigente: `annotation_guideline_v2.2`.
    * Las estrellas difieren del oro en el 12.5 % de las filas elegibles (EE 1.3).
    * Gemini (`prompt_v3`) coincide con el oro con κ 0.92 en 600 textos nuevos.
    * Ver el [reporte de `gold_v1`](../analytics/labeling/gold_v1_report.md) y la [historia del etiquetado](../analytics/README.md#3-etiquetado-guía-pilotos-oro-y-plata).
  * **Plata:** 99 926 filas (70 284 textos únicos) etiquetadas por Gemini 3.6 Flash con `prompt_v3`; κ contra el oro de 0.84 a 0.93. Ver [reporte](../analytics/labeling/silver_v0_report.md).
  * **Acuerdo entre personas:** un segundo anotador independiente etiquetó a ciegas 100 ítems de `gold_v1`; κ con el autor 0.81 [0.70, 0.91] con 4 clases y 0.87 con 3. El desacuerdo principal es la regla 2 amplia (cualquier queja concreta es `NEG`), que el segundo anotador tendía a decidir por el tono.
  * **Aspectos de las negativas** (5.2): 1 434 textos negativos de la plata, codificados por Gemini con la [guía de aspectos `v2.1`](../analytics/eda/eda_aspects_guideline.md) (`aspects_v2_1`). Multi-aspecto: 24.7 % [22.6, 26.8] según Gemini. Contra el autor: κ de `UX` 0.74, marca `u` κ 0.70 (usable); la marca `s` no es concluyente (6–8 positivos). Antecedente: con la [guía `v1`](../analytics/eda/archive/eda_aspects_guideline_v1.md) (`aspects_v1`) era 32.1 % y el autor, a ciegas en 100 textos, marcaba 44 % (κ 0.42). Son una medición exploratoria, no una etiqueta para entrenar. Ver el [EDA](../analytics/eda/eda_report.md#521-guía-de-aspectos-v2-y-v21-reapertura-para-55), sección 5.2.1.
  * **Limitación:** el oro refleja cómo aplica la guía un anotador, el autor, cuya calibración no es del todo independiente de Gemini. Los modelos con κ 0.91–0.93 contra ese oro ya están al nivel del acuerdo entre personas.
* **Características relevantes** (EDA):
  * Muy concentrado en textos cortos: 18.3 % de una palabra; mediana anual de 3–19 palabras; p99 de 50–89; 1.46 % supera 60 palabras.
  * Alta repetición: 52.2 % de textos únicos; "excelente" aparece 171 013 veces.
  * Distribución de estrellas en J: 58–76 % de 5★ según el banco; BBVA con 24 % de 1★.
  * La longitud se relaciona fuertemente con las estrellas: 4.75★ con una palabra, ~1.9★ con más de 60.
  * Español informal con faltas frecuentes ("exelente", "mui"); muy pocas reseñas en otros idiomas.
  * Votos de utilidad escasos: el 2–12 % de las reseñas tiene al menos uno.
  * **En tokens** (tokenizadores de RoBERTuito y BETO, sobre `texto_sanitizado`): mediana de 7–8 tokens, p99 de 83–88; el tope de 128 que usan los modelos trunca menos del 0.1 % de las filas.
  * **Las quejas mezclan problemas:** entre el 32 % (Gemini, cota inferior) y el 44 % (autor) de las reseñas negativas nombra dos o más problemas; la mitad de las de 20 palabras o más. Las familias más frecuentes son acceso, falla general, diseño y actualizaciones y transferencias.
  * **Pocas formas concentran las reseñas de una palabra:** 151 formas normalizadas ("excelente", "buena", "bien"…) cubren el 95.3 % de ellas.

## 3. Proceso de recolección

* **Fuente:** Google Play, idioma `es` y país `mx`. Cliente propio del protocolo interno `batchexecute` (`oCPfdb`), ordenado por más recientes y con páginas de 199 reseñas.
* **Cobertura:** cada banco se recorrió hasta agotar el cursor (`SOURCE_EXHAUSTED_OBSERVED`). Los conteos difieren de las cifras de la tienda entre −0.7 % y +0.4 %, salvo NUBANK (+19.4 %, la cifra de la tienda no es un tope).
* **No hay prueba independiente de exhaustividad.**
* **Excluido en el origen:** 100 de 2 649 145 filas sin texto (0.004 %), registradas en el ledger de descartes.
* **Temporalidad:** `fecha` es la fecha de la **última edición** de la reseña, no la de creación. La carga tiene un retraso de ~24 h frente al origen.
* **Consentimiento:** reseñas públicas. No se recolectan perfiles ni contactos; el nombre de usuario se reemplaza por un hash con sal.

## 4. Preprocesamiento y sanitización

* **Sanitización de PII:** solo regex local (Cloud DLP desactivado por defecto).
  * Detecta correos, teléfonos, tarjetas, CLABE, cuentas, RFC y CURP, y los reemplaza por tokens `[TIPO]`. Se encontraron 15 filas con hallazgos.
  * **No detecta nombres de personas:** solo Cloud DLP lo hacía. Los nombres que el usuario escriba en el texto pueden seguir presentes.
  * Por eso **puede quedar PII residual** (FMEA F-01/F-03): no publicar ejemplos sin revisión. En 1 000 reseñas aleatorias del oro no apareció ningún nombre propio (cota 95 %: 0.3 %; [`gold_v1`](../analytics/labeling/gold_v1_report.md), sección 5). Gemini se usa en Vertex AI, dentro de GCP; enviar texto fuera de GCP requiere la autorización del autor y una fila en la [matriz FMEA](ethical_fmea_matrix.md).
* **Limpieza:** `texto_limpio` pasa a minúsculas y quita URLs, menciones y hashtags, y repeticiones de 3 o más caracteres (`limpiar_texto_bancario`). El texto sanitizado sin limpiar se conserva en `texto_sanitizado`, que es el que usan los modelos de sentimiento (5.4); `texto_limpio` solo define las reglas de longitud.
* **Sin filtro de longitud en el almacenamiento:** el rango 2–60 palabras del EDA inicial se aplica, si acaso, en el análisis.
* **Elegibilidad por tarea** (`eligibility_rules_v0.1`, reglas deterministas):
  * Se excluyen de la predicción del sentimiento real los textos vacíos (8), sin contenido alfanumérico (19 586) y las 175 reseñas de NUBANK anteriores a 2020.
  * Las reseñas de una palabra (484 829; 465 633 tras las demás reglas) tienen la decisión pendiente (5.8): excluirlas o asignarles sentimiento con un léxico determinista. El léxico medido cubre el 95.3 % con 99 % de exactitud en el oro *dev*.
  * Las filas excluidas se conservan y se reportan, nunca se borran.

## 5. Usos

* **Previstos:**
  * estimar el sentimiento real frente a las estrellas;
  * descubrir y seguir tópicos de quejas por banco, versión y periodo;
  * priorizar incidencias en un portal con revisión humana (EPIC-7).
* **No previstos o desaconsejados:**
  * identificar o perfilar usuarios;
  * comparar bancos como medición oficial de satisfacción;
  * entrenar modelos con el texto para fines ajenos al proyecto;
  * publicar textos individuales.
* **Sesgos a considerar en cualquier uso:**
  * **Autoselección:** quien escribe reseñas no representa a todos los usuarios.
  * **Campañas aparentes de calificación** que inflan las estrellas en algunos meses (EDA, H5).
  * **Deriva fuerte de las estrellas en el tiempo** (EDA, H6).
  * **Exclusiones por regla:** cambian los agregados (por ejemplo, −0.10 a −0.21 estrellas si se excluyen las reseñas de una palabra; de −0.001 a −0.007 si solo se excluyen las que el léxico no cubre).

## 6. Distribución y acceso

* **BigQuery:** `bbva_voc_tds.sanitized_reviews_tds`, en un proyecto GCP privado.
* **Copias locales para experimentación:** en `experiments/analytics/data/`, excluidas de git.
* **Repositorio:** solo se versionan agregados y frases genéricas repetidas al menos 500 veces y de hasta 4 palabras. Los textos, las etiquetas individuales y las codificaciones del autor quedan en `experiments/analytics/data/`, fuera de git.

## 7. Mantenimiento

* **Ingesta incremental diaria** con ventana de revisita de 3 días.
* **Snapshots de análisis** fechados, con manifiesto (filas, rango de fechas, esquema, SHA-256).
* **Cambios de reglas o limpieza** se versionan (`eligibility_rules_vX`), y cada corrida de predicción registra la versión usada.

## 8. Pendiente para siguientes iteraciones

* Decisión sobre las reseñas de una palabra (excluir o léxico) y sensibilidad de los agregados (5.8).
* Cobertura por banco × periodo × motivo con las reglas aprobadas (`eligibility_rules` `v1`, 5.8).
* Si 5.5 codifica aspectos con Gemini: guía de aspectos `v2` (definición de diseño y actualizaciones) y nuevo acuerdo con el autor.
* Tópicos de quejas y su ciclo de vida (5.5) y predicciones del backfill (5.7), con la versión del modelo y de las reglas.

*Resuelto en la versión 0.2:* la incongruencia estrellas–texto (12.5 %, EE 1.3, con el oro; sección 2) y la longitud en tokens (sección 2).
