# Data Card — Corpus de reseñas de banca móvil (TDS)

* **Versión:** borrador 0.1 (2026-10-17). Se completa en iteraciones de EPIC-5: etiquetado (5.3), modelos (5.4) y registro de decisión (5.8).
* **Formato:** sigue la estructura de *Datasheets for Datasets* (Gebru et al., 2021); ver [`references.md`](references.md).
* **Fuentes de esta versión:** [cierre de EPIC-1–4](../backlog/closure_epics_1_4.md), [EDA global](../analytics/eda_report.md) y [reglas de elegibilidad](../analytics/eligibility_rules.md).

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
    * Ver el [reporte de `gold_v1`](../analytics/gold_v1_report.md) y la [historia del etiquetado](../analytics/README.md#3-etiquetado-guía-pilotos-oro-y-plata).
  * **Plata:** 99 926 filas (70 284 textos únicos) etiquetadas por Gemini 3.6 Flash con `prompt_v3`; κ contra el oro de 0.84 a 0.93. Ver [reporte](../analytics/silver_v0_report.md).
  * **Acuerdo entre personas:** un segundo anotador independiente etiquetó a ciegas 100 ítems de `gold_v1`; κ con el autor 0.81 [0.70, 0.91] con 4 clases y 0.87 con 3. El desacuerdo principal es la regla 2 amplia (cualquier queja concreta es `NEG`), que el segundo anotador tendía a decidir por el tono.
  * **Limitación:** el oro refleja cómo aplica la guía un anotador, el autor, cuya calibración no es del todo independiente de Gemini. Los modelos con κ 0.91–0.93 contra ese oro ya están al nivel del acuerdo entre personas.
* **Características relevantes** (EDA):
  * Muy concentrado en textos cortos: 18.3 % de una palabra; mediana anual de 3–19 palabras; p99 de 50–89; 1.46 % supera 60 palabras.
  * Alta repetición: 52.2 % de textos únicos; "excelente" aparece 171 013 veces.
  * Distribución de estrellas en J: 58–76 % de 5★ según el banco; BBVA con 24 % de 1★.
  * La longitud se relaciona fuertemente con las estrellas: 4.75★ con una palabra, ~1.9★ con más de 60.
  * Español informal con faltas frecuentes ("exelente", "mui"); muy pocas reseñas en otros idiomas.
  * Votos de utilidad escasos: el 2–12 % de las reseñas tiene al menos uno.

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
  * Por eso **puede quedar PII residual** (FMEA F-01/F-03): no publicar ejemplos sin revisión. Antes de enviar textos a servicios externos (por ejemplo, Gemini en 5.3), valorar este riesgo.
* **Limpieza:** `texto_limpio` pasa a minúsculas y quita URLs, menciones y hashtags, y repeticiones de 3 o más caracteres (`limpiar_texto_bancario`). El texto sanitizado sin limpiar se conserva en `texto_sanitizado`.
* **Sin filtro de longitud en el almacenamiento:** el rango 2–60 palabras del EDA inicial se aplica, si acaso, en el análisis.
* **Elegibilidad por tarea** (`eligibility_rules_v0.1`, reglas deterministas):
  * Se excluyen de la predicción del sentimiento real los textos vacíos (8), sin contenido alfanumérico (19 586) y las 175 reseñas de NUBANK anteriores a 2020.
  * Las reseñas de una palabra (484 829) tienen la decisión pendiente.
  * Las filas excluidas se conservan y se reportan, nunca se borran.

## 5. Usos

* **Previstos:**
  * estimar el sentimiento real frente a las estrellas;
  * descubrir y seguir tópicos de quejas por banco, versión y periodo;
  * priorizar incidencias en un portal con revisión humana (EPIC-6).
* **No previstos o desaconsejados:**
  * identificar o perfilar usuarios;
  * comparar bancos como medición oficial de satisfacción;
  * entrenar modelos con el texto para fines ajenos al proyecto;
  * publicar textos individuales.
* **Sesgos a considerar en cualquier uso:**
  * **Autoselección:** quien escribe reseñas no representa a todos los usuarios.
  * **Campañas aparentes de calificación** que inflan las estrellas en algunos meses (EDA, H5).
  * **Deriva fuerte de las estrellas en el tiempo** (EDA, H6).
  * **Exclusiones por regla:** cambian los agregados (por ejemplo, −0.10 a −0.21 estrellas si se excluyen las reseñas de una palabra).

## 6. Distribución y acceso

* **BigQuery:** `bbva_voc_tds.sanitized_reviews_tds`, en un proyecto GCP privado.
* **Copias locales para experimentación:** en `experiments/analytics/data/`, excluidas de git.
* **Repositorio:** solo se versionan agregados y frases genéricas repetidas al menos 500 veces y de hasta 4 palabras.

## 7. Mantenimiento

* **Ingesta incremental diaria** con ventana de revisita de 3 días.
* **Snapshots de análisis** fechados, con manifiesto (filas, rango de fechas, esquema, SHA-256).
* **Cambios de reglas o limpieza** se versionan (`eligibility_rules_vX`), y cada corrida de predicción registra la versión usada.

## 8. Pendiente para siguientes iteraciones

* Tasa de incongruencia estrellas–texto por banco y periodo (5.2 con el piloto de 5.3).
* Longitud en tokens con los tokenizadores candidatos (5.4).
* Decisión sobre las reseñas de una palabra y sensibilidad de los agregados (5.8).
