# Matriz Ethical FMEA

Análisis de modos de falla del manejo de datos personales y de la ingesta,
sanitización y almacenamiento (EPIC-1 a EPIC-4). Las filas de EPIC-5 a EPIC-7
(modelo, explicabilidad y HITL) se añaden cuando esas épicas tengan diseño
cerrado; ver la sección final. La experimentación de EPIC-5 (etiquetado,
copias locales y entrenamiento) ya tiene filas propias, F-10 a F-13.

**Estado:** borrador del autor. Las calificaciones S/O/D son una propuesta
razonada con la evidencia disponible y deben validarse con el Data Owner y el
QA independiente que exige la Norma de Gobierno de Modelos de BBVA.

## Escalas

| Escala | 1 | 5 | 10 |
| :--- | :--- | :--- | :--- |
| **S** Severidad | Sin efecto sobre personas | Exposición de un dato de identidad parcial (p. ej. nombre de pila) | Exposición de datos financieros o de identidad completa |
| **O** Ocurrencia | Improbable (no observado, causa controlada) | Ocasional | Ocurre de forma sistemática |
| **D** Detección | Un control automático lo detecta siempre | Solo una revisión periódica manual lo detecta | Sin mecanismo de detección |

`RPN = S × O × D`. **Umbral de acción:** `RPN ≥ 100`, o `S ≥ 8` con cualquier
ocurrencia. Las filas bajo el umbral se monitorean; las que lo superan exigen
una acción con responsable antes del siguiente despliegue.

## Evidencia usada

* **Medición de PII** sobre `experiments/playstore/evidence/` (798 reseñas únicas de BBVA, muestra no
  aleatoria, mediana de 4 palabras): `experiments/pii_measurement/measure_pii.py`.
  Reproducible con `uv run python experiments/pii_measurement/measure_pii.py`;
  imprime solo conteos. Los resultados y su interpretación están en el
  [README del servicio](../../services/sanitization-pipeline/README.md#política-de-sanitización-decisión-basada-en-datos).
* Código y contratos: `SanitizedReviewRecord` (sin `usuario` ni `imagen_usuario`),
  `LocalRegexFallbackSanitizer`, `infra/modules/storage_bq.py` (TTL de 7 días del
  crudo), `infra/modules/pubsub.py` (retención de 7 días).

## Matriz (EPIC-1 a EPIC-4)

| ID | Modo de falla | Efecto | Causa | Controles actuales | S | O | D | RPN | Acción / estado |
| :--- | :--- | :--- | :--- | :--- | :-: | :-: | :-: | :-: | :--- |
| **F-01** | Un nombre propio escrito en el texto libre llega al TDS | El nombre queda visible para quien consulte `sanitized_reviews_tds` y en el portal HITL | La regex local no detecta nombres; Cloud DLP (NER) está desactivado por defecto | Regex local para datos estructurados; `usuario`/`imagen_usuario` no existen en el TDS; solo texto, calificación e id; muestra: 0 de 798 con presentación o firma con nombre; oro `gold_v1`: 0 nombres en 1 300 reseñas anotadas (en las 1 000 aleatorias, cota superior al 95 % de ~0.4 %; 0.3 % sin efecto de diseño) | 5 | 2 | 7 | 70 | Monitorear. Acción 1 hecha; falta la acción 2 para bajar D (ver detalle) |
| **F-02** | La respuesta de la entidad (que saluda al autor por su nombre) se almacena | Nombre de pila del autor en el TDS (medido en 249 de 302 respuestas) | `texto_respuesta` se capturaba y persistía | Se descarta antes de persistir: `titulo`, `texto_respuesta` y `fecha_respuesta` quedan `NULL` (commit `0da26dd`) | 5 | 2 | 3 | 30 | Controlado; el dato crudo sigue en tránsito (F-05) |
| **F-03** | Falso positivo de la regex altera el texto | Pérdida de señal (p. ej. un monto de 10 dígitos se vuelve `[BBVA_ACCOUNT_NUMBER]`); sesgo menor en el modelo | Reglas numéricas sin contexto suficiente | El contexto (`cuenta`, `cel`…) decide entre cuenta y teléfono; pruebas con corpus adversarial; se conserva `ref: 3702…` | 3 | 3 | 5 | 45 | Monitorear: medir la tasa en el conjunto de oro |
| **F-04** | Re-identificación a partir de `usuario_hash` | Un atacante con la sal puede confirmar si un usuario conocido está en el TDS | Sin `user_hash_salt`, el stack usa `DEV_USER_HASH_SALT`, una constante pública del repositorio; además la sal viaja como variable de entorno de Cloud Run, no como secreto | SHA-256 salado e irreversible; prod exige sal propia (validador); la sal de `dev` se fijó el 2026-10-15 cifrada con Cloud KMS (el repositorio es público) | 6 | 2 | 6 | 72 | Parcialmente controlado: queda la variable de entorno en claro |
| **F-05** | Acceso indebido al crudo retenido (`raw_staging/` y Pub/Sub, 7 días) | Quien lo lea ve `usuario`, `imagen_usuario`, respuesta y texto sin sanitizar | La sanitización ocurre después de publicar el sobre crudo | TTL de 7 días en GCS y retención de 7 días en Pub/Sub; IAM por recurso (`voc-sa-sanitization`, `voc-sa-ingestion`); sin invocación pública | 5 | 2 | 5 | 50 | Monitorear; reducir si la ingesta deja de capturar usuario y respuesta |
| **F-06** | `experiments/playstore/evidence/` y `.env` con datos sensibles fuera de control | Nombres y URL de avatares en respuestas crudas; el `.env` local contiene una passphrase y la sal | Artefactos de trabajo en el árbol del repositorio | `evidence/` (cualquier nivel) y `.env` en `.gitignore` y `.gcloudignore`, y fuera de la lista de permitidos de `.dockerignore`; no se versionan | 5 | 2 | 4 | 40 | Monitorear; borrar `experiments/playstore/evidence/` al terminar el análisis |
| **F-07** | La política real deja de coincidir con el compromiso del caso de uso | El caso de uso promete "sanitización del 100 % de PII" y un KPI de PII; el sistema cumple con regex local y no almacena la respuesta | Cambio de política (Cloud DLP pasó a opcional) sin actualizar el documento comprometido | Nota de revisión en `epic_4.md`, README del servicio, este análisis | 6 | 4 | 3 | 72 | Actualizar el objetivo 3 y el KPI del caso de uso con la redacción medible |
| **F-08** | Una página queda cerrada con hueco por un error del lector y no por expiración | Pérdida silenciosa de reseñas en el TDS (1 645 filas, las páginas finales de los cinco bancos, el 2026-10-16) | El replay rápido cierra la página de forma irreversible (el primero gana) y trataba cualquier captura ilegible como `STAGING_EXPIRED`; la imagen de sanitización traía un parser anterior a la ingesta | Conteo esperado frente a TDS, evento `Page closed` con `GAPS_DETECTED`; ahora `CaptureUnreadable` deja la página abierta y el Job sale con error | 2 | 4 | 3 | 24 | Controlado; desplegar siempre juntas las imágenes que comparten código |
| **F-09** | Crudo sin sanitizar acumulado en la cola de Pub/Sub durante la carga histórica, y permisos de invocación ampliados | ~2.6 M de mensajes con `usuario`, `imagen_usuario` y respuesta retenidos hasta 7 días (ver F-05); `serviceAccountTokenCreator` y `run.invoker` concedidos a cuentas de usuario | El replay rápido no consume Pub/Sub; el token de usuario da 401 y se usó una cuenta de servicio | DLQ vacía; IAM por recurso; `seek` y revocación de permisos en las etapas 4 y 4c del plan | 5 | 3 | 4 | 60 | Abierto hasta hacer el `seek` y revocar los permisos |

## Detalle de las filas sobre el umbral

### F-01 Nombres propios en texto libre

**Qué se midió.** En 798 reseñas únicas: 0 tokens de PII estructurada tras la
regex; 0 presentaciones ("me llamo…") o firmas con nombre; 2 reseñas (0.3 %)
cuyo texto contiene un token del nombre de usuario del propio autor. Esas dos no
se revisaron una a una; pueden ser coincidencias con palabras comunes.

**Alcance de la conclusión.** Con 0 hallazgos en 798, la tasa de PII que la
regex detecta es menor que ~0.4 % (regla del tres, 95 %). Para reseñas largas
(≥ 40 palabras, solo 63) la cota sube a ~5 %. La regex no puede ver nombres, así
que la ausencia de hallazgos de nombres descansa en heurísticas de presentación,
no en una detección real. El riesgo residual existe.

**Acciones propuestas** (responsable: autor del proyecto):

1. Durante el etiquetado manual del conjunto de oro (EPIC-5), añadir un campo
   "contiene nombre propio de una persona" a cada reseña. Da una tasa real y un
   intervalo, no una cota por heurística.
2. Muestreo periódico del TDS (≥ 500 reseñas recientes) con el mismo campo.
3. **Disparador:** si se encuentra al menos un nombre en una muestra de ≥ 500, o
   si la tasa supera 1 %, activar Cloud DLP (`--use-cloud-dlp-api`, ya
   implementado y probado) y reprocesar.

Con las acciones 1 y 2 y el disparador definidos, la detección baja de D=7 a D=4
y el RPN a 60.

**Estado (2026-10-20):** la acción 1 está **hecha**. Con el campo
`nombre_persona` (guía `annotation_guideline_v2.1`) el autor anotó 1 300 reseñas
de `gold_v1` y no encontró ningún nombre: 0 en las 1 000 del bloque aleatorio
y 0 en las 300 del dirigido. La cota superior al 95 % es de ~0.4 %: la regla del
tres con el tamaño efectivo de ~720, porque el bloque aleatorio es estratificado
con pesos desiguales (efecto de diseño de Kish de ~1.4, ver el
[diseño de `gold_v1`](../analytics/labeling/gold_v1_design.md)). Sin el efecto de diseño
sería 0.3 %. Las dos quedan bajo el 1 % del disparador. El
segundo anotador tampoco marcó nombres en sus 100 ítems. No se cumple el
disparador. Ver el [reporte de `gold_v1`](../analytics/labeling/gold_v1_report.md),
secciones 5 y 7.

**Calificación (decisión del autor, 2026-10-20):** O baja de 3 a 2 (no
observado, pero la causa sigue sin control: la regex no ve nombres). D sigue en
7 porque el criterio de arriba exige también la acción 2, que no se ha hecho.
RPN 5 × 2 × 7 = **70**, bajo el umbral: la fila pasa a monitorearse. Con la
acción 2, D bajaría a 4 y el RPN a 40.

### F-04 `usuario_hash` y la sal

`infra/__main__.py` usa `DEV_USER_HASH_SALT` cuando `bbva-voc-infra:user_hash_salt`
no está configurado fuera de producción. Esa constante es pública
(`packages/voc-common/src/voc_common/config.py`), así que los hashes se podrían
reproducir. **Estado (2026-10-15):** la sal de `dev` está fijada como secreto de
Pulumi. El stack usa Cloud KMS; con una passphrase vacía y `Pulumi.dev.yaml`
versionado en un repositorio público el secreto habría sido descifrable por
cualquiera, y se descartó antes de escribir la sal.

**Residual:** la sal llega a Cloud Run como variable de entorno en claro y no
desde Secret Manager, así que quien pueda leer el servicio la ve. Valorar Secret
Manager para entornos que no sean sandbox. Cambiar la sal tras escribir datos
deja hashes inconsistentes entre sí.

## Pendiente: EPIC-5 a EPIC-7

Modos de falla ya conocidos que se calificarán cuando exista el diseño. **Estado al cerrar 5.8 (2026-10-22):**

* Etiquetado por estrellas como señal ruidosa (*Label Noise Bias*) y su efecto
  en el recall de reseñas negativas. **Calificado y confirmado con el oro *test*:**
  ver la propuesta de calificación al final de esta sección.
* Exposición de texto fuera del TDS durante la experimentación y el backfill:
  filas F-10 a F-14.
* Probabilidades sin calibrar que disparan o no el protocolo HITL. **Resuelto en
  5.6** (*temperature scaling*); el riesgo que queda está en F-17.
* Pérdida de cobertura de tópicos: la taxonomía de 8 categorías se reemplazó por
  las 11 familias `aspects_v2_1`; su riesgo está en F-18.
* Exposición de texto de reseñas en el portal: F-15 (Explorador); el HITL ya
  estaba considerado en el diseño de EPIC-7. Los embeddings se guardan sin texto
  (`text_embeddings`).
* Deriva entre versiones de la app (*Concept Drift*): monitor por banco de 5.7
  (P7-9). La detección de incidentes quedó fuera del alcance (2026-10-22) y F-19
  cubre ahora la lectura de las etiquetas de temas por día.
* Paridad dialectal: se descartó del alcance; queda declarada en la
  [Model Card](model_card.md) (límite 11).
* Licencia (F-16) y sesgo del anotador (F-20): filas nuevas de 5.8.
* Texto nuevo del esquema v3 (comentario del revisor, nota de la alerta) y
  oro en BigQuery (`gold_labels`): F-21, fila nueva del detalle de EPIC-6.

### Matriz (EPIC-5, experimentación)

Las filas calificadas usan las escalas de arriba y son una propuesta del autor.
Las demás quedan **por calificar** hasta que exista el dato que falta.

| ID | Modo de falla | Efecto | Causa | Controles actuales | S | O | D | RPN | Acción / estado |
| :--- | :--- | :--- | :--- | :--- | :-: | :-: | :-: | :-: | :--- |
| **F-10** | Un dato personal residual del texto llega al LLM de etiquetado | El nombre que la regex no detecta (F-01) sale del TDS hacia Gemini | El oro y la plata se etiquetan con `gemini-3.6-flash` en Vertex AI | Vertex AI en el propio proyecto (flag `enable_vertex_ai_api`, sin endpoints dedicados); solo viaja `texto_sanitizado` con un índice local, sin `id_resena`, `usuario_hash` ni estrellas (`voc_analytics.labeling.label_gemini`); ~70 000 textos únicos de la plata, más los pilotos y el oro. 5.5 (codificar aspectos y nombrar tópicos con Gemini) usa el mismo canal y solo texto sanitizado de negativas: entra en esta fila. Nombrar tópicos: Gemini ve reseñas representativas del tópico (texto sanitizado, en Vertex AI dentro de GCP). Los embeddings de BERTopic se calculan en CPU local (F-11) o en GCP, pendiente de confirmación del autor; no en Kaggle (F-13 cubre solo 5.4). Un envío fuera de Vertex AI en el proyecto (API externa, otro proveedor, Kaggle) requiere fila nueva y la autorización del autor | 5 | 2 | 7 | 70 | Monitorear. S y D heredan F-01 y bajan con ella. La ubicación configurada es `global`, no una región fija: confirmar la residencia de datos si el proyecto la exige |
| **F-11** | Acceso indebido a las copias locales del Mac del autor | Quien acceda al disco ve el TDS completo (texto sanitizado, `usuario_hash`), las etiquetas de oro y plata y las anotaciones | Snapshot `tds_20261016T054714Z` (2 649 047 filas) y etiquetas en `experiments/analytics/data/` para trabajar sin BigQuery | `experiments/analytics/data/` en `.gitignore`; `experiments/` en `.gcloudignore` y fuera de la lista de permitidos de `.dockerignore`; solo se versionan agregados; la app de anotación (Streamlit) escucha solo en `localhost` | 5 | 2 | 4 | 40 | Monitorear, como F-06. **Cierre de EPIC-5 (decisión del autor, 2026-10-23):** (1) el snapshot y el archivo de EPIC-5 (`labels/`, `eda/`, `topics/working_v0`, `topics/phase2_v0`, `models/preds`) se subieron a `gs://voc-datalake-<proyecto>/archive/epic5/`, dentro de GCP y con el IAM del bucket (sin CMEK por defecto), con conteos y bytes verificados; la copia local se borra, salvo el oro (`labels/gold_*`) y `eda/` (léxico y `muestra_v21`), que necesita 6.3; (2) los duplicados de lo que ya está en GCS o en `models/weights/` (`backfill/20261022/texts/`, `backfill/kaggle_dataset/`, `kaggle_bundle/`) se borran; (3) lo que carga 6.3 (`backfill/20261022/`, `models/weights/`, `topics/phase4_v0`, el oro y `eda/`) se queda en local hasta que `load_local` y `seed` verifiquen la carga, y entonces se borra (responsable: 6.3). El riesgo residual es el disco local hasta ese momento. **Carga de 6.3 (decisión del autor, 2026-10-24, D16 de EPIC-6):** `ml_inference load-local` corre en el Mac y lee del TDS `id_resena`, `bank_id`, `fecha` y `texto_limpio` en memoria para la elegibilidad, sin escribirlos a disco; lo que sube a BigQuery no lleva texto (`text_key` y etiquetas) |
| **F-12** | El texto de reseñas queda expuesto a un segundo anotador | Una persona fuera del proyecto lee 100 reseñas de `gold_v1_a2` | Medir el acuerdo entre personas sin la contaminación por Gemini | Subconjunto de 100 ítems, a ciegas, misma app y misma guía; la cola solo lleva el texto. Sesión presencial en la app local del Mac del autor, sin copia del archivo; acuerdo verbal de confidencialidad (ambos confirmados por el autor). El nombre del segundo anotador está en el CSV de anotaciones (`labels/gold_v1_a2/annotations.csv`), fuera de git y no en `docs/`: en local (cubierto por F-11) y, desde el 2026-10-23, en el archivo de EPIC-5 en GCS (`archive/epic5/`, IAM del bucket; decisión del autor de conservarlo ahí). 0 nombres marcados en esos 100 ítems | 5 | 1 | 5 | 25 | **Cerrado.** Calificada después de la anotación (2026-10-20), aunque el plan la ponía antes; calificación aprobada por el autor. La anotación se hizo una sola vez y el texto no salió del equipo |
| **F-13** | Entrenamiento de modelos fuera de GCP | Textos y etiquetas salen del perímetro del proyecto hacia Kaggle | Los encoders de 5.4 (M4 con BETO, M8 Delora y sus semillas) necesitan GPU | Solo viaja `texto_sanitizado` con etiquetas de la plata, el oro *dev* y `holdout_nuevo`; el oro *test* no está en la carga. La medición de nombres de F-01 (acción 1, `nombre_persona` en `gold_v1`) dimensiona este riesgo: 0 nombres en 1 300 reseñas anotadas, bajo el disparador | — | — | — | — | **Riesgo aceptado por el autor (2026-10-19)**, con su criterio: priorizar el entrenamiento, que es crucial para continuar, porque la PII observada tras la regex es insignificante. Se descartó la GPU en el propio proyecto. La tasa de `nombre_persona` no supera el disparador de F-01 (2026-10-20). **En producción (2026-10-25):** el reentrenamiento del Job `voc-ml-training` y el *re-scoring* de `voc-ml-rescoring` suben a Kaggle solo ids de tokens, etiquetas y la máscara de validación (y los ids de tokens del oro *dev*), nunca texto; el dataset privado se borra al verificar la subida. Con `retrain_trigger = auto` cada reentrenamiento sale sin aprobación por corrida: pasar la `risk_policy` a `auto` es esa aprobación (decisión del autor, 2026-10-24); la promoción siempre es humana |
| **F-14** | Backfill del corpus completo fuera de GCP | Todos los textos únicos del TDS (~1.4 M de `texto_sanitizado`) salen del perímetro hacia un dataset privado de Kaggle | El backfill de M4 en CPU tomaría ~17 h en Cloud Run; en la T4 de Kaggle, ~9 min por semilla (5.7, P7-1) | Solo viaja `texto_sanitizado` con una clave SHA-256 del propio texto y su número de filas: sin `id_resena`, `usuario_hash`, banco, fecha ni estrellas. Dataset y kernel privados; las predicciones vuelven a GCP. **La copia del backfill de EPIC-5 (`voc-backfill-corpus`) se borró el 2026-10-23**, al cerrar la épica; el kernel `voc-backfill-m4` sigue, y su salida solo tiene `text_key` y probabilidades. **Regla para el *re-scoring* de EPIC-6** (decisión del autor, 2026-10-23): un dataset privado por corrida (`voc-backfill-corpus-<corrida>`), que se borra en cuanto la carga en BigQuery queda verificada. Desde el 2026-10-24 (D13) todo el ciclo corre en el Job `voc-ml-rescoring` en GCP, con el token de Kaggle en Secret Manager: los textos van de GCS a Kaggle sin pasar por ningún equipo local, y el borrado es un paso del Job. La tasa medida en F-01 (0 nombres en 1 300 reseñas anotadas; cota superior al 95 % de ~0.4 %) dimensiona el riesgo | — | — | — | — | **Riesgo aceptado por el autor (2026-10-22, P7-1)**, con su criterio: priorizar el tiempo de ejecución del backfill y del *re-scoring* (P7-4). En producción todo quedaría en GCP. Copia de EPIC-5 borrada (2026-10-23); cada *re-scoring* deja su copia solo mientras dura la corrida |
| **F-15** | El Explorador de reseñas del portal amplía quién lee el texto | Analistas, además de los revisores HITL, leen reseñas sanitizadas con filtros y búsqueda semántica; un nombre que la regex no detectó (F-01) queda visible para más personas | El frontal de EPIC-7 (P8-12, 2026-10-22) incluye una tabla con *crossfilter* y la ficha de cada reseña (7.6) | Portal privado con IAP y rol de analista (7.2); solo `texto_sanitizado`; sin descarga de texto (exportación de agregados: el CSV solo trae conteos); la consulta de la búsqueda semántica no se guarda ni se registra (el registro de la API solo lleva la ruta); el servicio de explicación solo lo invoca la cuenta de la API; accesos en Cloud Audit Logs; la tasa de F-01 (0 nombres en 1 300 reseñas anotadas) como riesgo base | — | — | — | — | **Asignada a EPIC-7 (7.2 y 7.6)** (decisión del autor, 2026-10-23, al cerrar EPIC-5). Propuesta de partida: S 5, O 2 (F-01: 0 nombres en 1 300 reseñas), D 5 (revisión trimestral de accesos), RPN 50; se confirma al implementar. Acción propuesta: lista nominal de analistas y revisión trimestral de accesos |
| **F-16** | Uso del modelo fuera de la licencia | M4 parte de un checkpoint de `pysentimiento`, solo para uso no comercial e investigación (heredado de TASS) | Se eligió RoBERTuito por desempeño (P8-1, P8-2) | Uso académico declarado en la [Model Card](model_card.md) (límite 1); un uso comercial exige reentrenar desde un checkpoint sin esa restricción o usar M9 | 2 | 2 | 5 | 20 | **Calificada (decisión del autor, 2026-10-23, al cerrar EPIC-5):** S 2, sin efecto sobre personas; O 2, uso académico declarado en la Model Card; D 5, solo una revisión manual detecta un uso comercial. Bajo el umbral: se monitorea. Acción propuesta: aviso de licencia en el portal (7.3) |
| **F-17** | Priorización errónea por una predicción incierta aceptada sin revisión | Una queja mal clasificada no llega a familias ni a la cola, o un incidente se ordena mal | En los casos difíciles (*dev* dirigido) el error sigue en 17–23 % aun revisando el 20 %, y la confianza calibrada vale menos (ECE 0.10–0.14) | Revisión humana con 90 % de cobertura (error aceptado 0.42 % [0.03, 1.06] en el aleatorio); muestra trimestral a ciegas; avisos de tasa de corrección y de acuerdo con Gemini (P7-10) | 3 | 3 | 4 | 36 | **Calificada (decisión del autor, 2026-10-23, al cerrar EPIC-5):** O 3, error aceptado de 0.42 % en el *dev* aleatorio; D 4, aviso semanal de tasa de corrección y muestra trimestral a ciegas (P7-10). La validación única de la cola en 5.9 dio 18.3 % de corrección, debajo del aviso de 28 %. Bajo el umbral: se monitorea y se revisa en 6.4. Reemplaza a la fila de la especificación anterior ("mitigado por entropía ≥ 0.65") |
| **F-18** | Familias mal asignadas por Gemini | Un incidente se atribuye a otra familia o no se detecta | Las 11 familias `aspects_v2_1` las etiqueta Gemini, con κ de 0.55 a 0.86 contra el autor según la familia | Revalidación con `muestra_v21` al cambiar el modelo o el prompt (P7-11); HITL de aspectos (7.7); solo se vigilan las familias con prevalencia ≥ 5 % | 3 | 5 | 5 | 75 | **Calificada (decisión del autor, 2026-10-23, al cerrar EPIC-5):** O 5, κ de 0.55 a 0.86 según la familia; D 5, la revalidación con `muestra_v21` solo corre al cambiar el modelo o el prompt (P7-11). Bajo el umbral: se monitorea |
| **F-19** | Un pico de negativas se lee como incidente confirmado | El lector atribuye a un incidente o a un tema un pico que puede ser ruido, una quincena o un cambio de volumen | El dashboard muestra por día las familias y los tópicos de las negativas, sin una señal de incidentes validada: la detección quedó fuera del alcance (decisión del autor, 2026-10-22). Antes, esta fila cubría alertas con umbrales poco validados | Etiquetas descriptivas, sin alertas automáticas de incidentes ni umbrales en la serie diaria. En el cockpit (7.5): aviso permanente en el panel del día ("describe lo que dicen las reseñas negativas de ese día; no es un diagnóstico ni la detección de un incidente"), participación habitual de 28 días al lado de la del día, insignia "Solo modelo", el mismo z robusto del monitor en la vista de anomalía (el cockpit y las alertas no se contradicen) y, en la pestaña por versión, "descriptivo: no hay pruebas de cambio de nivel entre versiones"; las familias declaran su κ (F-18) | 1 | 1 | 1 | 1 | **Calificada (decisión del autor, 2026-10-26, al cerrar 7.5):** S 1, O 1, D 1. Es un hallazgo de la investigación y el producto no está en producción: el riesgo de que se malinterprete un pico es mínimo, perder la funcionalidad no tiene efecto y el conflicto para la entrega del trabajo es muy bajo. Bajo el umbral: se monitorea. Redefinida el 2026-10-22, al acotar 5.9
| **F-20** | Sesgo del anotador en las métricas | Las métricas y la calibración heredan el criterio de una sola persona | El oro lo anotó el autor; el segundo anotador solo cubrió 100 reseñas (κ 0.81–0.87) | Guía versionada (`v2.2`); oro *test* a ciegas; doble revisión en el HITL (`agreement_sample`, 7.7) | 2 | 4 | 5 | 40 | **Calificada (decisión del autor, 2026-10-23, al cerrar EPIC-5):** O 4, un solo anotador principal (segundo anotador en 100 ítems, κ 0.81–0.87); D 5, la doble revisión (`agreement_sample`) llega con el HITL de EPIC-7 (7.7). Bajo el umbral: se monitorea |
| **F-21** | Texto nuevo y etiquetas individuales en las tablas de producción | Un dato personal que escribe un revisor (o que la regex no detecta, F-01) queda en el comentario de una revisión o en la nota de una alerta; las etiquetas del oro, por reseña, quedan en BigQuery | El esquema v3 guarda `hitl_reviews.comment` y `drift_alert_events.note` (EPIC-7, 7.7 y 7.8) y la tabla `gold_labels` (D10 de EPIC-6), que carga el oro *dev* aleatorio y `muestra_v21` | Comentario y nota pasan por la sanitización de EPIC-4 antes de guardarse (el comentario del revisor, por `api_backend/dlp.py` con las mismas plantillas de DLP, y si DLP falla no se guarda nada; la pantalla avisa que no se copie el texto de la reseña); revisores como hash SHA-256; `gold_labels` solo en BigQuery, nunca en git, y sin el oro *test*. Las tablas usan CMEK solo si el stack lo activa (`enable_cmek`, apagado en dev); `voc-sa-ml-backend` tiene `bigquery.dataEditor` en todo el proyecto, no solo en `gold_labels`. Ninguna vista de 6.2 lee texto del TDS | 5 | 2 | 4 | 40 | **Calificada (decisión del autor, 2026-10-23, al implementar 6.2):** S 5, dato personal, como F-10 y F-11; O 2, tasa de F-01 (0 nombres en 1 300 reseñas) y comentario opcional; D 4, la sanitización de EPIC-4 filtra el comentario y la nota, pero un nombre se escapa como en F-01. Bajo el umbral: se monitorea |

### Propuesta de calificación: *Label Noise Bias* (5.4, *dev* ampliado)

**Propuesta del autor**, no validada. Usa el *dev* aleatorio ampliado con
`gold_v1` ([reporte](../analytics/labeling/gold_v1_report.md), métricas en
[`sentiment_models_gold_v1_metrics.json`](../analytics/sentiment/sentiment_models_gold_v1_metrics.json),
commits `56786f4` y `763b63a`). **Confirmada con el oro *test* en 5.8 (2026-10-22):** M4
`s1` pierde 5 de 212 quejas (recall 97.6 %, O = 2, RPN 60), así que M4, el modelo
elegido (P8-1), queda bajo el umbral.

**Evidencia.** En el oro *dev* aleatorio (n = 794 evaluables: 199 de `gold_v0` y
595 de `gold_v1`; 273 quejas `NEG`). El bloque dirigido no entra en estas cifras:

| Etiqueta de sentimiento | Recall de `NEG` (IC 95 %) | Quejas perdidas | Precisión de `NEG` | κ (IC 95 %) |
| :--- | ---: | ---: | ---: | ---: |
| M0 estrellas (1–2 `NEG`, 3 `NEU`, 4–5 `POS`) | 66.3 % (62.7–70.2) | 92 de 273 (33.7 %) | 95.3 % | 0.68 (0.65–0.72) |
| M1 TF-IDF + LR (entrenado con la plata) | 93.0 % (90.0–95.8) | 19 de 273 (7.0 %) | 94.1 % | 0.87 (0.84–0.90) |
| M4 RoBERTuito ajustado con la plata | 96.0 % (93.8–98.1) | 11 de 273 (4.0 %) | 96.0 % | 0.91 (0.89–0.94) |

* **M4** se reentrenó en el Mac con una semilla y sin ninguna reseña de las
  colas del oro. Supera a M1 en κ por +0.04 (IC 95 % [0.02, 0.07]).
* Ponderado por diseño (población), el recall de `NEG` es 66.7 % para M0,
  94.8 % para M1 y 97.3 % para M4: se pierde el 33.3 %, el 5.2 % y el 2.7 % de
  las quejas.
* Con el *dev* de 199 ítems, M1 perdía 1 de 45 quejas (2.2 %). Esa cifra estaba
  inflada por el anclaje: esos textos se anotaron primero viendo la propuesta de
  Gemini, de la que M1 aprende.
* Las quejas que las estrellas esconden están en 3★ y 4★: en la plata, el 73.3 %
  de las 3★ y el 28.5 % de las 4★ son `NEG` ([reporte](../analytics/labeling/silver_v0_report.md)).
* El efecto no es de privacidad, sino de omisión: quien se queja con 3★ o 4★ no
  aparece en los agregados de quejas ni llega a priorización.

**Criterio.** Las escalas de arriba miden exposición de datos; para este modo se
leen así:

* **S**, según el daño a los usuarios cuyas quejas no se ven: 1 = ninguna queja
  perdida; 5 = pérdida ocasional; 10 = una clase de usuarios queda invisible de
  forma sistemática.
* **O**, según la fracción de quejas perdidas en el oro (muestra): ≤ 5 % → 2;
  5–15 % → 4; 15–30 % → 6; > 30 % → 7 o más.
* **D**, con la escala de arriba: hoy solo el oro, anotado a mano y por rondas,
  revela las quejas perdidas.

| Escenario | S | O | D | RPN | Lectura |
| :--- | :-: | :-: | :-: | :-: | :--- |
| Estrellas como etiqueta | 6 | 7 | 5 | **210** | Sobre el umbral: una de cada tres quejas se pierde (33.7 %) |
| M1 como etiqueta | 6 | 4 | 5 | **120** | Sobre el umbral: se pierde el 7.0 % (con 199 ítems era 2.2 %, O = 2 y RPN 60) |
| M4 como etiqueta | 6 | 2 | 5 | 60 | Bajo el umbral: se pierde el 4.0 % (2.7 % ponderado) |

* **S = 6** en todos: el daño de cada queja perdida no cambia con el modelo, solo
  su frecuencia. Queda debajo de 8 porque no expone datos ni decide sobre una
  persona.
* **D = 5** en todos: no hay control automático; la detección depende de
  re-anotar oro. Bajaría con un muestreo periódico de reseñas de 3★ y 4★
  contra el modelo.
* **M1 cruza el umbral** con el *dev* ampliado. Ponderado por población (5.2 %)
  queda en el borde entre O = 2 y O = 4.
* **M4 es el único escenario medido bajo el umbral.** Está cerca del borde de
  O = 2 (4.0 % contra 5 %) y viene de una sola semilla. La acción es fijar en
  5.8 la etiqueta que baje O, o un control que baje D, y confirmarlo con el oro
  *test*.
* **Límites:**
  * *dev* ya no es chico (273 `NEG`; una queja equivale a 0.4 puntos de recall),
    pero las 199 de `gold_v0` conservan el residuo de anclaje que favorece a M1;
  * M1 aprende el criterio de Gemini, incluidos sus sesgos;
  * el oro *test* (594 evaluables, 212 `NEG`) se evaluó en 5.8 y no movió O:
    M4 `s1` pierde el 2.4 % de las quejas (la media de las 3 semillas, el 2.5 %).

## Revisión

Revisar esta matriz en cada cambio de política de sanitización, en cada nueva
fuente de datos y antes del despliegue a un entorno que no sea sandbox.
