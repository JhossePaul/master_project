# Plan del full histórico

Carga de todo el histórico con texto de los cinco bancos hacia el TDS. Se
apoya en dos controladores (`tools/backfill_controller.py`), en el **replay
rápido** (`GCS_FAST_REPLAY`) y en mediciones reales del 2026-10-15. Lo que no
está medido se marca como supuesto.

## Idea del plan

La ingesta publica cada página a Pub/Sub **y** la deja capturada en
`raw_staging/` con un manifiesto. La sanitización normal lee de Pub/Sub y
escribe un recibo por evento en GCS (~2 M de eventos ≈ 4 M de escrituras): ese
ledger fue el 68 % del tiempo y es el costo que el Free Tier no cubre. Para el
histórico se usa otra ruta con el mismo resultado en BigQuery:

| | Corrida normal (`BATCH_PULL_SERVERLESS`) | Replay rápido (`GCS_FAST_REPLAY`) |
| --- | --- | --- |
| Fuente | Pub/Sub (`pull`) | Capturas de `raw_staging/` por manifiesto |
| Recibos | uno por evento + cierre de página | **solo el cierre de página** (un objeto por página) |
| Carga a BigQuery | un `MERGE` por microbatch (≤ 1000) | un `MERGE` por ~10 000 filas |
| Escrituras GCS por 2 M de eventos | ~4 M | ~4 000 (una por página) |
| Idempotencia | recibos + `MERGE` | cierre condicional (el primero gana) + `MERGE` |
| Sanitización | regex local o DLP | **solo regex local** (con DLP el Job se niega a arrancar) |

El replay rápido no se usa para el flujo diario: ahí conviene el recibo por
evento porque el volumen es de cientos de reseñas.

## Qué se sabe y qué no

| Dato | Valor | Origen |
| --- | --- | --- |
| Rendimiento de la sanitización normal | **16–20 mensajes/s** (3 771 en 231 s), 68 % en el ledger | Medido (`Microbatch finished`) |
| Rendimiento del replay rápido | **464 msg/s** (50 000 en 107.7 s, 100 páginas, 8 `MERGE`). Fases: BigQuery 55 s (51 %), cierres 17 s, lectura de capturas 15 s, regex 6 s | Medido el 2026-10-15 (`Sanitization run finished`) |
| Ritmo de la ingesta | por página de 500: ~0.33 s de consulta + ~2.5 s de publicación + ~2.5 s de pausa ≈ 5.4 s, **~93 reseñas/s** | Medido en producción (`Play Store request`, `Page published`) |
| Presupuesto por ejecución del histórico | Manda el tope de **100 páginas** (`ingestion_max_pages`); el de tiempo del perfil histórico es 3 480 s y no se alcanza. **50 000 reseñas en 650–980 s (51–77 reseñas/s, 6.5–9.8 s por página)**; entre ejecuciones hay 17–48 s de arranque | Medido el 2026-10-15 (`BUDGET_EXHAUSTED/pages`). Subir el tope de páginas ahorraría ~3–5 %: no se hizo |
| Reseñas por banco según los metadatos de la tienda | BBVA 790 803, NUBANK 107 286, SANTANDER 627 776, AZTECA 588 658, BANORTE 519 825 (total 2 634 348) | Extraído por el usuario. Orden de magnitud: NUBANK lo superó en 19 % (ver resultados) |
| Profundidad del cursor de Google Play | **Llega al origen de cada banco** (2012–2024) | Observado: los cinco bancos agotaron el cursor (ver resultados) |
| Retraso de la reseña más reciente | ~24 h en los cinco bancos | Observado; causa sin determinar |
| `MERGE` de BigQuery | ~20 MB facturados y ~2 s por job de 1000 filas | Medido |

## Resultado de la ingesta (2026-10-15)

Los cinco bancos agotaron el cursor. Cada plan terminó con `PROTOCOL_ERROR /
protocol_shape` por la **última página**: una respuesta parcial (menos de 500
filas) **sin bloque de paginación** (`inner[1]` nulo en vez de
`[null, cursor]`), que el parser rechazaba. Se reprodujo la solicitud fallida de
cada banco (solo estructura, sin contenido) y los cinco dan la misma forma:

| Banco | Publicadas | Última página (sin ingerir) | Más antigua | Metadatos de la tienda | Diferencia |
| --- | ---: | ---: | --- | ---: | ---: |
| BBVA | 787 433 | 441 | 2013-01-23 | 790 803 | −0.4 % |
| NUBANK | 128 000 | 204 | 2020-02-21 | 107 286 | **+19.4 %** |
| SANTANDER | 623 483 | 111 | 2012-07-21 | 627 776 | −0.7 % |
| AZTECA | 590 499 | 481 | 2017-10-17 | 588 658 | +0.4 % |
| BANORTE | 517 985 | 408 | 2013-11-11 | 519 825 | −0.3 % |
| **Total** | **2 647 400** | **1 645** | | **2 634 348** | **+0.6 %** |

Notas:

- *Publicadas* suma `reviews_published` de las auditorías; incluye lo reemitido
  por reintentos de Cloud Run tras un `exit(1)` (hubo recuperaciones con
  `ANCHOR_REPLAY`). El TDS deduplica por `(bank_id, id_resena)`: el conteo real
  se conoce tras el replay.
- NUBANK extrajo más que su cifra de la tienda: la cifra de metadatos **no es un
  tope**. Hay que comprobar duplicados en el TDS.
- El fin del histórico se infiere de la forma de la respuesta (página parcial
  sin cursor) y de que la fecha más antigua es plausible para cada app; no hay
  una señal explícita de "fin" en el protocolo.
- **Corrección en el parser** (`playstore_protocol.py`): `inner[1] is None` con
  filas se acepta como página final (`END_CANDIDATE`, sin cursor). Sin filas
  sigue siendo error. Con la imagen corregida, un `ingest` más por banco ingiere
  esa última página y cierra el plan en `SOURCE_EXHAUSTED_OBSERVED`. El evento
  `protocol_shape` ahora trae `detail` con el motivo.

## Resultado de la carga al TDS (2026-10-16)

El replay rápido cargó **2 649 047 filas**, todas únicas por `(bank_id, id_resena)`:

| Banco | Filas | Más antigua | Más reciente |
| --- | ---: | --- | --- |
| BBVA | 787 875 | 2011-04-01 | 2026-10-14 |
| NUBANK | 128 204 | 2015-08-17 | 2026-10-14 |
| SANTANDER | 623 594 | 2012-03-23 | 2026-10-14 |
| AZTECA | 590 981 | 2017-03-30 | 2026-10-14 |
| BANORTE | 518 393 | 2012-03-21 | 2026-10-14 |

- **Ritmo del replay:** 351–573 msg/s en cuatro ejecuciones de 1 500 s
  (865 k, 639 k, 590 k y 502 k mensajes). El ritmo bajó a lo largo de la carga;
  causa sin determinar. Un replay sin trabajo (o con 5 páginas) tarda ~6 min solo
  en leer manifiestos y cierres de los cinco bancos.
- **Las páginas finales** (1 645 filas) se cerraron la primera vez como
  `GAPS_DETECTED / STAGING_EXPIRED` sin estar expiradas: la imagen de
  sanitización empaqueta `ingestion_worker` y seguía con el parser anterior,
  que rechaza la página sin bloque de paginación. El cierre es irreversible (el
  primero gana), así que hubo que desplegar la imagen nueva, **borrar esos cinco
  objetos** `receipts/<BANCO>/_pages/<page_id>.json` y repetir el replay (1 645
  filas, 5 páginas `RESOLVED`). **Lección:** al cambiar el parser de ingesta hay
  que desplegar también la imagen de sanitización. Desde entonces una captura
  que existe pero no se interpreta (`CaptureUnreadable`) deja la página abierta
  y el Job sale con error, en vez de cerrarla como expirada.
- **PII y vacíos:** 16 hallazgos de PII en total y 8 textos vacíos tras sanear;
  sin revisar a fondo.
- **NUBANK:** 5 reseñas de 2015, 20 de 2016, 12 de 2017, 23 de 2018 y 115 de
  2019 anteceden al lanzamiento de Nu en México (~2019–2020). Son ~175 de 128 mil;
  decidir en EPIC-5 si se filtran por fecha y confirmar el ID de aplicación y el
  país (`hl`/`gl`) del banco.
- **La reseña más reciente** de cada banco es del 2026-10-14 (la carga corrió
  el 2026-10-15): el retraso de ~24 h sigue sin explicarse.

## Incidentes de la puesta en marcha (resumen)

Venía del cierre de EPIC-1 a EPIC-4 (ahora en [`epics.md`](../backlog/epics.md#cierre-de-las-épicas-1-a-4)).

| Incidente | Causa | Cambio |
| --- | --- | --- |
| Estado cruzado entre bancos (`protocol_shape`, `app_id does not match`) | IDs de AZTECA/BANORTE incorrectos | IDs corregidos; aislamiento por banco |
| Páginas finales rechazadas (`protocol_shape`) en los 5 bancos | El parser exigía bloque de paginación en la última página | Se acepta sin cursor solo con filas (`END_CANDIDATE`) |
| 1 645 filas cerradas como `STAGING_EXPIRED` sin estarlo | La imagen de sanitización traía el parser viejo y el cierre es irreversible | `CaptureUnreadable` deja la página abierta; `tools/deploy_images.py` exige el mismo SHA en las dos imágenes |
| 401 al invocar la ingesta con token de usuario | Sin determinar | `ingest --impersonate` con una cuenta de servicio |
| Diff permanente en `pulumi preview` | Valor por defecto de la API no declarado | `scaling` a nivel de servicio declarado |

## Estimación (previa a la ingesta; ver resultados arriba)

| | BBVA (788 k) | Total (~2.0 M) | Estado |
| --- | ---: | ---: | --- |
| Solicitudes a Google Play | ~1 580 | ~4 000 | Calculado |
| Ejecuciones del histórico (50 000 c/u) | ~16 | ~40 | Calculado con lo medido |
| Ingesta (72 reseñas/s, ~12 min por ejecución) | ~3.2 h | **~8 h** | Medido el ritmo |
| Drenado con sanitización normal (18 msg/s) | ~12 h | ~31 h | Medido el ritmo |
| Replay rápido (464 msg/s) | ~28 min | **~72 min** | Medido el ritmo |

Con el replay rápido el cuello de botella pasa a ser **la ingesta** (72 reseñas/s
contra 464 del replay). BigQuery es la mitad del replay (7 s por `MERGE`); subir
`--upsert-batch-rows` es la palanca si hiciera falta, pero ya no es el límite.

Con páginas de 199 serían ~10 000 solicitudes y ~14 h de ingesta (39 reseñas/s).
La publicación a Pub/Sub tarda casi lo mismo por página (2.3 s con 199 y 2.5 s
con 500), así que subir el tamaño acelera la ingesta ~2.4×.

**Costo.**

- *Replay rápido:* ~4 000 cierres de página, del orden de **centavos** en
  operaciones de GCS (clase A ≈ US$0.005 por 1000; verificar en la calculadora).
- *Sanitización normal del histórico (lo que se evita):* ~4 M de escrituras,
  del orden de **US$20**, fuera del Free Tier.
- Cómputo de Cloud Run: la ingesta (~6 h) cabe; el drenado normal (~35 h de
  1 vCPU, ~126 mil vCPU-s) estaría cerca del límite gratuito mensual (180 mil
  vCPU-s). El replay rápido lo reduce a unas pocas horas.

## Por qué el `MERGE` filtra por banco y no por fecha

El `MERGE` busca la fila existente por `(bank_id, id_resena)`. Una reseña
**editada** llega con una `fecha` más nueva, así que la fila vieja vive en otra
partición: un filtro por `fecha` no la encontraría y se insertaría un
**duplicado**. Por eso no se filtra por `fecha`.

La poda segura es `AND T.bank_id IN ('BBVA')` con los bancos del lote
(constantes validadas por regex, nunca texto del usuario). La tabla está
agrupada por `bank_id, version_app`, así que BigQuery solo lee los bloques de
esos bancos. **No** se midió el ahorro; el `MERGE` ya leía solo las columnas
referenciadas (~20 MB por job), de modo que la poda es defensa contra el
crecimiento de la tabla, no una mejora observada.

## Tamaño de página: 500 (adoptado el 2026-10-15)

El worker pide **500 reseñas por solicitud** (antes 199). Es política local, no
un máximo del origen: `PLAYSTORE_PAGE_SIZE_POLICY_LIMIT=500` la impone en
Settings y en la API. En `experiments/playstore/evidence/` se probaron 20, 50, 199, 200 y 500, y todas
devolvieron lo pedido (HTTP 200, con cursor); esa evidencia es una sola
observación del 500.

**Cadena validada.** 10 páginas consecutivas de 500 de BBVA (5 000 reseñas, de
09-17 a 10-14) con el adaptador de producción: 0 duplicados, 0 solapes en las 9
fronteras, orden de fechas no creciente, cursor en todas. Un control de 5
páginas de 199 coincide exactamente con las primeras 995 de la cadena de 500.
Latencia 0.32–0.57 s (mediana 0.47 s) y 403–513 KB por página.

**Qué no prueba.** Solo cubre el inicio del histórico de un banco, sin
estrellas, con 15 solicitudes y sin limitación observada. No prueba el
comportamiento en profundidad, ni en los otros bancos, ni a escala. Menos
solicitudes ayuda contra un límite por solicitud, pero no contra uno por bytes.

**Efectos de operación.**

- La página es la unidad de confirmación: una falla repite 500 reseñas.
- Publicar 500 mensajes tomó 2.5 s, con 30 s de margen (`confirmation_timeout_sec`).
- El tamaño es parte del contexto del stream. El estado incremental cerrado abre
  un stream nuevo de 500; una corrida abierta se reanuda con su contexto.
- **Orden de despliegue:** `pulumi up` con la imagen nueva **y**
  `SCRAPER_PAGE_SIZE=500` en el mismo paso. Con la imagen vieja, Settings
  rechaza 500 y el servicio no arranca.

## Palancas del replay rápido

| Opción | Defecto | Efecto |
| --- | ---: | --- |
| `--io-workers` (`SANITIZATION_IO_WORKERS`) | 16 (1–64) | Hilos de lectura de capturas y de cierres; el pool HTTP de GCS se ajusta solo (`hilos + 4`, mín. 10). Se leen ventanas de `2 × hilos` páginas |
| `--upsert-batch-rows` (`SANITIZATION_UPSERT_BATCH_ROWS`) | 10 000 (1–100 000) | Filas por carga y `MERGE`. Más filas, menos jobs de BigQuery y más memoria |
| `--max-runtime-sec` | 1500 | Al agotarse, carga lo ya saneado, cierra esas páginas y se detiene; la siguiente ejecución continúa |

Cada ejecución registra `phase_seconds` con `capture_read_s`, `sanitize_s`,
`bigquery_s` y `closure_s`, y un evento `Fast replay batch finished` por carga
(filas, páginas, `rows_merged`). Con eso se decide qué palanca mover:

- `capture_read_s` domina → subir `--io-workers` (si la latencia por lectura
  sube con más hilos, la vCPU está saturada: probar un Job de 2 vCPU).
- `bigquery_s` domina → subir `--upsert-batch-rows`.
- `sanitize_s` domina → es CPU del regex; solo ayuda más CPU.

## Etapa 0: antes de empezar

- [ ] Imágenes con replay rápido, IDs corregidos, sin filtro de longitud, logs
      estructurados y aislamiento por banco desplegadas (`pulumi up`).
- [ ] Cola vacía: `python tools/backfill_controller.py drain` termina con
      `Cola vacía`; DLQ (`voc-raw-reviews-dlq-sub`) sin mensajes (métrica
      `num_undelivered_messages`; **no** extraer mensajes: son crudos).
- [ ] Cinco bancos con estado `COMPLETED` en `ingestion_runs_log_v2`.
- [ ] Tu cuenta puede invocar `voc-ingestion-worker`. En este proyecto el token
      de usuario de `gcloud auth print-identity-token` da **401 `invalid_token`**
      aunque tenga `roles/run.invoker` (también por `gcloud run services proxy`).
      Solución usada: `--impersonate voc-sa-scheduler@…` en `ingest`, que firma el
      token con esa cuenta de servicio y exige `roles/iam.serviceAccountTokenCreator`
      para ti. Revocar ambos permisos al terminar. Causa del 401 sin determinar.
- [ ] Resuelto, o aceptado como limitación, el retraso de ~24 h (comparar la
      primera reseña de la ficha de Play con `MAX(fecha)` del TDS).
- [ ] Conteos de partida guardados:
      `SELECT bank_id, COUNT(*) FROM bbva_voc_tds.sanitized_reviews_tds GROUP BY 1`.
- [ ] **Probado el `seek` de la suscripción en dev** (etapa 4, paso de la cola).

## Etapa 1: piloto de ingesta con BBVA (una ejecución)

```bash
uv run python tools/backfill_controller.py ingest --project project-7bafd424-a385-4c05-b5b --bank BBVA --max-executions 1 --yes
```

**Puerta (continuar solo si todo se cumple):**

- La ejecución termina `BUDGET_EXHAUSTED` con ~200 mil reseñas publicadas, sin
  `rate_limited`, `transport_error` ni HTTP 403 en los eventos
  `Play Store request`.
- Latencia por solicitud estable (compárala con la ingesta incremental).

Si hay limitación de tasa o bloqueo: **detener**. No se reintenta con rotación
de IP ni evasión; se consulta primero qué responde Google Play.

## Etapa 2: piloto del replay rápido

Con esas ~200 mil reseñas ya capturadas, **no** se drena la cola de Pub/Sub
con la sanitización normal. Se reproduce desde las capturas:

```bash
uv run python tools/backfill_controller.py drain --fast-replay --project project-7bafd424-a385-4c05-b5b --max-executions 1
```

`--fast-replay` equivale a `--job-args "--execution-mode=GCS_FAST_REPLAY"`; se
pueden sumar opciones con coma: `--job-args "--io-workers=32,--upsert-batch-rows=5000"`.

**Puerta:**

- Termina con `stop_reason` `drained` o `runtime_budget` (no
  `transient_failure`) y exit 0.
- Se registra el ritmo real: `messages / elapsed_sec` y `phase_seconds`.
  Compararlo con los 18 msg/s de la sanitización normal. **Si no es claramente
  mejor, parar y revisar antes de seguir**: el plan sin replay rápido sigue
  siendo válido (~31 h).
- Cero `Page closed` con `GAPS_DETECTED` y `expired_captures = 0`.
- Verificación en BigQuery: las filas de BBVA aumentan y
  `COUNT(*) = COUNT(DISTINCT id_resena)`.
- **Repetir el comando debe devolver `messages = 0`** (idempotencia: las páginas
  ya cerradas no se vuelven a leer ni a cargar).

## Etapa 3: completar BBVA

Alternar ingesta y replay hasta que el plan cierre. Las páginas ya cerradas se
saltan, así que el replay puede correr aunque la ingesta siga abierta (solo
procesa páginas confirmadas):

```bash
uv run python tools/backfill_controller.py ingest --project project-7bafd424-a385-4c05-b5b --bank BBVA --max-executions 8 --yes
uv run python tools/backfill_controller.py drain --fast-replay --project project-7bafd424-a385-4c05-b5b
```

El controlador de ingesta reanuda mientras el estado sea `BUDGET_EXHAUSTED` o
`PAUSED_BACKLOG`, espera ante `PARTIAL_RATE_LIMITED` y se detiene ante
cualquier otra cosa (`BLOCKED`, `PROTOCOL_ERROR`, `RECOVERY_REQUIRED`…).

**Plazo.** Las capturas expiran a los **7 días**. Repetir el replay tras cada
ingesta, sin dejar tramos sin reproducir más de unos días; una captura expirada
se cierra como `STAGING_EXPIRED` y esa página solo se recupera reingiriendo.

**Cobertura de BBVA.** La ficha de Play no es un denominador fiable, así que el
cierre se juzga por consistencia interna. Con el plan cerrado
(`SOURCE_EXHAUSTED_OBSERVED`) y el replay sin pendientes:

```sql
SELECT COUNT(*) AS filas, COUNT(DISTINCT id_resena) AS unicas,
       MIN(fecha) AS mas_antigua, MAX(fecha) AS mas_reciente
FROM `bbva_voc_tds.sanitized_reviews_tds` WHERE bank_id = 'BBVA'
```

- `filas = unicas` y el rango llega hasta el origen del banco, con un orden de
  magnitud cercano a ~788 mil: continuar.
- **Muy por debajo** o el cursor termina antes de agotar el histórico: repetir
  con `--stars` (requiere `FULL_BACKFILL`; es un plan nuevo; el `MERGE` es
  idempotente y conserva lo cargado).

## Etapa 4: los demás bancos y la cola de Pub/Sub

NUBANK, SANTANDER, AZTECA y BANORTE, en ese orden, cada uno con su `ingest` y su
replay rápido, repitiendo la puerta de la etapa 1. De uno en uno para no sumar
carga contra Google Play. Con el primer conteo de cada banco se corrige la
estimación del total.

**La cola de Pub/Sub.** La ingesta también publicó cada reseña a
`voc-raw-reviews-sub`, y el replay rápido **no** consume esos mensajes. Si se
dejan, el Job diario los drenaría con la ruta lenta y con recibos por evento
(el costo que se quería evitar). Cuando todos los bancos estén reproducidos y
verificados, descartar el backlog moviendo la suscripción al presente:

```bash
gcloud pubsub subscriptions seek voc-raw-reviews-sub --time="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --project project-7bafd424-a385-4c05-b5b
```

**Esto descarta mensajes sin procesarlos** y es un paso **no verificado**
(el proyecto `dev` es el único entorno). Hacerlo solo cuando el TDS contenga
todas las páginas. Lo publicado después del `seek` entra a la cola con
normalidad.

Procedimiento:

1. *Antes:* la cola debe coincidir con lo ingerido. El 2026-10-16 tenía
   **2 649 045** mensajes sin entregar y la DLQ 0 (métrica
   `pubsub.googleapis.com/subscription/num_undelivered_messages`, filtrada por
   `subscription_id`; solo lectura, **no** extraer mensajes: son crudos).
2. `seek` a la hora actual (comando de arriba). Los mensajes publicados antes de
   esa hora se marcan como entregados.
3. *Después* (la métrica se actualiza en 1–2 min): `voc-raw-reviews-sub` en 0 y
   la DLQ en 0. Si no baja, no reintentar a ciegas: revisar la suscripción.
4. Hasta hacerlo, **no dejar activo** `voc-trigger-sanitization-daily`: drenaría
   la cola por la ruta lenta, con recibos por evento. (El 2026-10-16 ambos
   Schedulers seguían activos; los próximos disparos eran 14:00Z y 14:30Z).

## Etapa 4b: cerrar la ingesta tras el cambio del parser

Con la imagen de ingesta corregida desplegada (`pulumi up`), un `ingest` por
banco ingiere la última página y cierra el plan:

```bash
uv run python tools/backfill_controller.py ingest --project project-7bafd424-a385-4c05-b5b --bank BBVA --max-executions 2 --yes --impersonate voc-sa-scheduler@project-7bafd424-a385-4c05-b5b.iam.gserviceaccount.com
```

Repetir con NUBANK, SANTANDER, AZTECA y BANORTE. Cada uno debe terminar en
`SOURCE_EXHAUSTED_OBSERVED` con unas pocas filas (441, 204, 111, 481, 408). Antes
de la cola y del replay, **pausar los Schedulers** `voc-trigger-sanitization-daily`
y `voc-ingest-daily-sequential-all` hasta cerrar la carga.

## Etapa 4c: permisos temporales

Al terminar las invocaciones manuales, quitar los permisos concedidos para la
carga: `roles/run.invoker` de las cuentas de usuario sobre `voc-ingestion-worker`
y `roles/iam.serviceAccountTokenCreator` sobre `voc-sa-scheduler`. El binding de
la propia `voc-sa-scheduler` queda. Luego `pulumi preview` para ver si esos
cambios manuales producen deriva en el stack.

## Etapa 5: cierre y verificación

- [ ] Replay sin páginas pendientes: la última ejecución devuelve `messages = 0`.
- [ ] Sin `Page closed` con `GAPS_DETECTED` ni `Bank state unreadable`.
- [ ] Sin duplicados:
      `SELECT bank_id, COUNT(*) - COUNT(DISTINCT id_resena) FROM … GROUP BY 1` = 0.
- [ ] Rango de fechas por banco desde el origen del histórico hasta hoy.
- [x] Descartes: 100 de 2 649 145 filas (0.004 %), todas sin texto, medidas sumando `discarded_count` de los manifiestos (la auditoría de la corrida reporta 0, por lo que no sirve para esto). Ver el [cierre de EPIC-1 a EPIC-4](../backlog/epics.md#cierre-de-las-épicas-1-a-4).
- [ ] 0 filas con título o respuesta; `SUM(pii_findings_count)` revisado.
- [ ] Cola de Pub/Sub y DLQ vacías; `raw_staging/` expira solo a los 7 días.

## Cuándo detener y qué hacer

| Señal | Acción |
| --- | --- |
| HTTP 403, `BLOCKED`, `PROTOCOL_ERROR` | Detener el banco; el controlador ya se detiene. Reproducir una solicitud a mano antes de reanudar |
| `rate_limited` repetido | Detener; no acelerar |
| Replay con `transient_failure` | Las páginas de ese lote siguen abiertas; revisar `Fast replay batch failed` (cuota o permisos de BigQuery) y relanzar |
| Replay con `expired_captures` > 0 | Capturas expiradas (>7 días): esa parte hay que reingerirla |
| Mensajes en la DLQ | Detener la ingesta, revisar los logs y reprocesar antes de seguir |
| `drain` sin avance dos veces seguidas | El controlador se detiene; revisar `Microbatch finished` / `Fast replay batch finished` y las cuotas |
| Un banco con estado ilegible | El resto no se frena (aislamiento); corregir ese banco aparte |

Todas las ejecuciones son reanudables: el estado vive en GCS y los cierres en el
ledger, así que relanzar el mismo comando continúa donde quedó.

## Lo que este plan no resuelve

- La exhaustividad del histórico: se infiere del agotamiento del cursor; las cifras de la tienda coinciden salvo NUBANK.
- El retraso de ~24 h de las reseñas más recientes.
- El rendimiento real del replay rápido y el efecto del `seek`: se miden/prueban
  en las etapas 2 y 4.
- El paralelismo: **no** se lanzan varias ejecuciones de sanitización a la vez
  hasta probar que los `MERGE` concurrentes sobre la misma tabla no chocan.
