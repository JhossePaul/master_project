# Matriz Ethical FMEA

Análisis de modos de falla del manejo de datos personales y de la ingesta,
sanitización y almacenamiento (EPIC-1 a EPIC-4). Las filas de EPIC-5 y EPIC-6
(modelo, explicabilidad y HITL) se añaden cuando esas épicas tengan diseño
cerrado; ver la sección final.

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

* **Medición de PII** sobre `evidence/` (798 reseñas únicas de BBVA, muestra no
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
| **F-01** | Un nombre propio escrito en el texto libre llega al TDS | El nombre queda visible para quien consulte `sanitized_reviews_tds` y en el portal HITL | La regex local no detecta nombres; Cloud DLP (NER) está desactivado por defecto | Regex local para datos estructurados; `usuario`/`imagen_usuario` no existen en el TDS; solo texto, calificación e id; muestra: 0 de 798 con presentación o firma con nombre | 5 | 3 | 7 | **105** | **Acción abierta**: ver detalle |
| **F-02** | La respuesta de la entidad (que saluda al autor por su nombre) se almacena | Nombre de pila del autor en el TDS (medido en 249 de 302 respuestas) | `texto_respuesta` se capturaba y persistía | Se descarta antes de persistir: `titulo`, `texto_respuesta` y `fecha_respuesta` quedan `NULL` (commit `0da26dd`) | 5 | 2 | 3 | 30 | Controlado; el dato crudo sigue en tránsito (F-05) |
| **F-03** | Falso positivo de la regex altera el texto | Pérdida de señal (p. ej. un monto de 10 dígitos se vuelve `[BBVA_ACCOUNT_NUMBER]`); sesgo menor en el modelo | Reglas numéricas sin contexto suficiente | El contexto (`cuenta`, `cel`…) decide entre cuenta y teléfono; pruebas con corpus adversarial; se conserva `ref: 3702…` | 3 | 3 | 5 | 45 | Monitorear: medir la tasa en el conjunto de oro |
| **F-04** | Re-identificación a partir de `usuario_hash` | Un atacante con la sal puede confirmar si un usuario conocido está en el TDS | Sin `user_hash_salt`, el stack usa `DEV_USER_HASH_SALT`, una constante pública del repositorio; además la sal viaja como variable de entorno de Cloud Run, no como secreto | SHA-256 salado e irreversible; prod exige sal propia (validador); la sal de `dev` se fijó el 2026-10-15 cifrada con Cloud KMS (el repositorio es público) | 6 | 2 | 6 | 72 | Parcialmente controlado: queda la variable de entorno en claro |
| **F-05** | Acceso indebido al crudo retenido (`raw_staging/` y Pub/Sub, 7 días) | Quien lo lea ve `usuario`, `imagen_usuario`, respuesta y texto sin sanitizar | La sanitización ocurre después de publicar el sobre crudo | TTL de 7 días en GCS y retención de 7 días en Pub/Sub; IAM por recurso (`voc-sa-sanitization`, `voc-sa-ingestion`); sin invocación pública | 5 | 2 | 5 | 50 | Monitorear; reducir si la ingesta deja de capturar usuario y respuesta |
| **F-06** | `evidence/` y `.env` con datos sensibles fuera de control | Nombres y URL de avatares en respuestas crudas; el `.env` local contiene una passphrase y la sal | Artefactos de trabajo en el árbol del repositorio | `evidence/` y `.env` en `.gitignore`, `.dockerignore` y `.gcloudignore`; no se versionan | 5 | 2 | 4 | 40 | Monitorear; borrar `evidence/` al terminar el análisis |
| **F-07** | La política real deja de coincidir con el compromiso del caso de uso | El caso de uso promete "sanitización del 100 % de PII" y un KPI de PII; el sistema cumple con regex local y no almacena la respuesta | Cambio de política (Cloud DLP pasó a opcional) sin actualizar el documento comprometido | Nota de revisión en `epic_4.md`, README del servicio, este análisis | 6 | 4 | 3 | 72 | Actualizar el objetivo 3 y el KPI del caso de uso con la redacción medible |

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

## Pendiente: EPIC-5 y EPIC-6

Modos de falla ya conocidos que se calificarán cuando exista el diseño:

* Etiquetado por estrellas como señal ruidosa (*Label Noise Bias*) y su efecto
  en el recall de reseñas negativas.
* Probabilidades sin calibrar que disparan o no el protocolo HITL.
* Pérdida de cobertura de tópicos (taxonomía propia de 8 categorías, sin
  validación externa en español bancario).
* Exposición de texto de reseñas en el portal HITL y en los embeddings.
* Deriva entre versiones de la app (*Concept Drift*).
* Paridad dialectal: se descartó del alcance; debe quedar como limitación
  declarada en la Model Card.

## Revisión

Revisar esta matriz en cada cambio de política de sanitización, en cada nueva
fuente de datos y antes del despliegue a un entorno que no sea sandbox.
