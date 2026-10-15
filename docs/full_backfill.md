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
| Rendimiento del replay rápido | **no medido** | Se mide en el piloto (etapa 2) |
| Ritmo de la ingesta | por página de 500: ~0.33 s de consulta + ~2.5 s de publicación + ~2.5 s de pausa ≈ 5.4 s, **~93 reseñas/s** | Medido en producción (`Play Store request`, `Page published`) |
| Presupuesto por ejecución del histórico | 1000 solicitudes, 200 MB o 3480 s; con páginas de 500 limita el **presupuesto de bytes** (~480 solicitudes): **~240 mil reseñas** | Perfil `historical_ingestion` y tamaños medidos |
| BBVA con texto | ~788 mil | Caso de uso. `epic_3.md` advierte que **no es un denominador fiable**: orden de magnitud |
| Otros bancos con texto | desconocido | Supuesto: misma proporción que BBVA da ~2.0 M en total |
| Profundidad del cursor de Google Play | **desconocida** | El sondeo no prueba un máximo ni la exhaustividad |
| Retraso de la reseña más reciente | ~24 h en los cinco bancos | Observado; causa sin determinar |
| `MERGE` de BigQuery | ~20 MB facturados y ~2 s por job de 1000 filas | Medido |

## Estimación

| | BBVA (788 k) | Total (~2.0 M) | Estado |
| --- | ---: | ---: | --- |
| Solicitudes a Google Play | ~1 580 | ~4 000 | Calculado |
| Ejecuciones del histórico | ~4 | ~10 | Calculado |
| Ingesta (~93 reseñas/s) | ~2.4 h | ~6 h | Medido el ritmo |
| Drenado con sanitización normal (18 msg/s) | ~12 h | ~31 h | Medido el ritmo |
| Drenado con replay rápido | ~0.5–1 h | **~1–2 h** | **Supuesto, no medido** |

La cifra del replay rápido sale de suponer que sin el ledger el costo es la
lectura de la captura (~0.5 MB por página), el regex y un `MERGE` de 10 000
filas cada ~2–5 s, y que las lecturas en paralelo escalan con los hilos. Hasta
que el piloto la mida, el plan solo depende de que no sea peor que el drenado
normal (~31 h), que ya cabe en los 7 días de retención.

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
Settings y en la API. En `evidence/` se probaron 20, 50, 199, 200 y 500, y todas
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
- [ ] Tu cuenta tiene `roles/run.invoker` sobre `voc-ingestion-worker`.
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

**Esto descarta mensajes sin procesarlos: probarlo antes en dev** y hacerlo solo
cuando el TDS contenga todas las páginas (comprobar con `drain` en modo normal
que no queda nada nuevo que valga la pena, o con los conteos por banco). Es un
paso **no verificado** de este plan. Si se hace con la ingesta todavía en curso,
lo publicado después del `seek` sigue entrando a la cola normalmente.

## Etapa 5: cierre y verificación

- [ ] Replay sin páginas pendientes: la última ejecución devuelve `messages = 0`.
- [ ] Sin `Page closed` con `GAPS_DETECTED` ni `Bank state unreadable`.
- [ ] Sin duplicados:
      `SELECT bank_id, COUNT(*) - COUNT(DISTINCT id_resena) FROM … GROUP BY 1` = 0.
- [ ] Rango de fechas por banco desde el origen del histórico hasta hoy.
- [ ] `reviews_discarded = 0` en la auditoría.
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

- La profundidad real del cursor de Google Play: se descubre en el piloto.
- La exhaustividad del histórico: solo BBVA tiene una cifra de referencia.
- El retraso de ~24 h de las reseñas más recientes.
- El rendimiento real del replay rápido y el efecto del `seek`: se miden/prueban
  en las etapas 2 y 4.
- El paralelismo: **no** se lanzan varias ejecuciones de sanitización a la vez
  hasta probar que los `MERGE` concurrentes sobre la misma tabla no chocan.
