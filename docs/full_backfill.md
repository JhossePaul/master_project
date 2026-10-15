# Plan del full histórico

Carga de todo el histórico con texto de los cinco bancos hacia el TDS. Se
apoya en dos controladores (`tools/backfill_controller.py`) y en mediciones
reales del 2026-10-15; lo que no está medido se marca como supuesto.

## Qué se sabe y qué no

| Dato | Valor | Origen |
| --- | --- | --- |
| Rendimiento de sanitización | **16–20 mensajes/s** (3 771 en 231 s) | Medido (logs `Microbatch finished`) |
| Ritmo de la ingesta | por página de 500: ~0.33 s de consulta + ~2.5 s de publicación + ~2.5 s de pausa ≈ 5.4 s, **~93 reseñas/s** | Medido en producción (logs `Play Store request` y `Page published`, 2026-10-15) |
| Presupuesto por ejecución del histórico | 1000 solicitudes, 200 MB o 3480 s; con páginas de 500 limita el **presupuesto de bytes** (~480 solicitudes): **~240 mil reseñas** | Perfil `historical_ingestion` y tamaños medidos |
| BBVA con texto | ~788 mil | Caso de uso (ficha de Play). `epic_3.md` advierte que **no es un denominador fiable** del histórico recuperable: usar solo como orden de magnitud |
| Otros bancos con texto | desconocido | Supuesto: misma proporción que BBVA (13 % de las calificaciones) da ~2.0 M en total |
| Profundidad del cursor de Google Play | **desconocida** | El sondeo no prueba un máximo ni la exhaustividad del histórico |
| Retraso de la reseña más reciente | ~24 h en los cinco bancos | Observado; causa sin determinar |

## Estimación (páginas de 500, con los supuestos anteriores)

| | BBVA (788 k) | Total (~2.0 M) |
| --- | ---: | ---: |
| Solicitudes a Google Play | ~1 580 | ~4 000 |
| Ejecuciones del histórico | ~4 | ~10 |
| Tiempo de ingesta (~93 reseñas/s) | ~2.4 h | ~6 h |
| Tiempo de drenado (18 msg/s) | ~12 h | ~31 h |

Con páginas de 199 serían ~10 000 solicitudes y ~14 h de ingesta (39 reseñas/s).
La publicación a Pub/Sub tarda casi lo mismo por página (2.3 s con 199 y 2.5 s
con 500, medido), así que subir el tamaño acelera la ingesta ~2.4×. Una
estimación previa que suponía publicación proporcional al tamaño estaba mal.

La ingesta (~93 reseñas/s) es ~5× más rápida que la sanitización (~18 msg/s), así que la cola de Pub/Sub
crece y se vacía después. La reseña más vieja esperaría ~31 h como máximo, muy
por debajo de los **7 días** de retención de Pub/Sub y de `raw_staging/`. Eso
solo se cumple si el drenado no se detiene: es la condición que vigila el plan.

**Costo.** Cada evento escribe dos recibos en GCS (recibo de página e índice) y
las lecturas de consulta y cierre: ~4 M de escrituras para 2 M de eventos. Con
precios de memoria (clase A ≈ US$0.005 por 1000) son del orden de **US$20 en
operaciones de GCS**, que el Free Tier no cubre; verificar en la calculadora de
precios. Cómputo de Cloud Run: ~35 h de 1 vCPU / 1 GiB (~126 mil vCPU-s), cerca
del límite gratuito mensual (180 mil vCPU-s, de memoria) junto con la ingesta.

## Tamaño de página: 500 (adoptado el 2026-10-15)

El worker pide **500 reseñas por solicitud** (antes 199). Es política local, no
un máximo del origen: `PLAYSTORE_PAGE_SIZE_POLICY_LIMIT=500` la impone en
Settings y en la API. En `evidence/` se probaron 20, 50, 199, 200 y 500, y todas
devolvieron lo pedido (HTTP 200, con cursor); esa evidencia es una sola
observación del 500 (las cuatro copias de los reportes repiten los valores).

**Cadena validada.** 10 páginas consecutivas de 500 de BBVA (5 000 reseñas, de
09-17 a 10-14) con el adaptador de producción: 0 duplicados, 0 solapes en las 9
fronteras, orden de fechas no creciente sin violaciones, cursor en todas. Un
control de 5 páginas de 199 (995 reseñas) coincide exactamente y en el mismo
orden con las primeras 995 de la cadena de 500, cuya frontera cae a media página
de 199. Latencia 0.32–0.57 s (mediana 0.47 s) y 403–513 KB por página.

**Qué no prueba.** Solo cubre el inicio del histórico de un banco, sin
estrellas, con 15 solicitudes y sin limitación observada. No prueba el
comportamiento en profundidad, ni en los otros bancos, ni a escala. Menos
solicitudes ayuda contra un límite por solicitud, pero no contra uno por bytes
(0.81 KB por reseña frente a 0.83 KB con 199).

**Efectos de operación.**

- La página es la unidad de confirmación: una falla repite 500 reseñas.
- Publicar 500 mensajes tomó 2.5 s (medido), con 30 s de margen (`confirmation_timeout_sec`).
- El tamaño es parte del contexto del stream. El estado incremental cerrado
  (`active_run_id` nulo en los cinco bancos) abre un stream nuevo de 500 en la
  siguiente corrida; el anterior conserva su contexto de 199. Una corrida abierta
  se reanuda con el contexto con el que nació. Ambos casos tienen prueba.
- **Orden de despliegue:** `pulumi up` con la imagen nueva **y** `SCRAPER_PAGE_SIZE=500`
  en el mismo paso. Con la imagen vieja, Settings rechaza 500 y el servicio no arranca.

## Palanca: hilos de E/S del ledger

La sanitización rindió 16.3 msg/s con 8 hilos y un pool HTTP de 10 conexiones.
El 68 % del tiempo fue E/S del ledger en GCS (recibos 36 %, cierre de páginas
22 %, consulta 10 %); BigQuery 19 %, `pull` 12 % y el saneamiento 1.4 %. Ahora
`--io-workers` (16 por defecto, 1 a 64, también `SANITIZATION_IO_WORKERS`)
fija los hilos y el pool HTTP del cliente de GCS se ajusta solo (`hilos + 4`,
mínimo 10), porque con el pool de 10 los hilos de más abren y descartan
conexiones.

**Mejora esperada (estimada, no medida).** Si la E/S escala con los hilos y no
satura la vCPU: con 16 hilos ~1.5× (~25 msg/s), con 32 hasta ~2× (~33 msg/s).
Con ese ritmo el drenado de ~2.0 M baja de ~31 h a ~17–21 h. El tope es CPU:
el Job tiene 1 vCPU. Lo no afectado (BigQuery y `pull`, 31 %) pasa a dominar,
y ahí el siguiente paso sería solapar el `pull` con el procesamiento.

**Cómo medirlo.** Cada ejecución registra `io_workers` y `messages_per_second`
por microbatch. Con cola de reseñas nuevas, probar escalonadamente y comparar:

```bash
uv run python tools/backfill_controller.py drain --max-executions 1 --job-args "--io-workers=16"
uv run python tools/backfill_controller.py drain --max-executions 1 --job-args "--io-workers=32"
```

Quedarse con el valor donde `messages_per_second` deje de subir. Si la latencia
por operación sube con más hilos, la vCPU está saturada y conviene un Job de
2 vCPU antes que más hilos.

## Etapa 0: antes de empezar

- [ ] Imágenes con IDs corregidos, sin filtro de longitud, logs estructurados y
      aislamiento por banco desplegadas (`pulumi up`).
- [ ] Cola vacía: `python tools/backfill_controller.py drain` termina con
      `Cola vacía`; la DLQ (`voc-raw-reviews-dlq-sub`) sin mensajes (métrica
      `num_undelivered_messages` en Metrics Explorer; **no** extraer mensajes: son
      crudos y sin sanitizar).
- [ ] Cinco bancos con estado `COMPLETED` en `ingestion_runs_log_v2`.
- [ ] Tu cuenta tiene `roles/run.invoker` sobre `voc-ingestion-worker`.
- [ ] Resuelto, o aceptado como limitación, el retraso de ~24 h (comparar la
      primera reseña de la ficha de Play con `MAX(fecha)` del TDS).
- [ ] Conteos de partida guardados:
      `SELECT bank_id, COUNT(*) FROM bbva_voc_tds.sanitized_reviews_tds GROUP BY 1`.

## Etapa 1: piloto con BBVA (una sola ejecución)

```bash
uv run python tools/backfill_controller.py ingest --project project-7bafd424-a385-4c05-b5b --bank BBVA --max-executions 1 --yes
```

En otra terminal, drenado continuo:

```bash
uv run python tools/backfill_controller.py drain --project project-7bafd424-a385-4c05-b5b
```

**Puerta (continuar solo si todo se cumple):**

- La ejecución termina `BUDGET_EXHAUSTED` (por tiempo, bytes o solicitudes) con ~198 mil reseñas
  publicadas, sin `rate_limited`, `transport_error` ni HTTP 403 en los eventos
  `Play Store request`.
- Latencia por solicitud estable (compárala con las 5 de la ingesta incremental).
- `drain` mantiene ≥ 14 msg/s y termina en `Cola vacía`.
- Cero mensajes en la DLQ y cero `Page closed` con `GAPS_DETECTED`.

Si hay limitación de tasa o bloqueo: **detener**. No se reintenta con rotación
de IP ni evasión; se consulta primero qué responde Google Play.

## Etapa 2: completar BBVA

Sin partición por estrellas primero (un solo plan):

```bash
uv run python tools/backfill_controller.py ingest --project project-7bafd424-a385-4c05-b5b --bank BBVA --max-executions 8 --yes
```

El controlador reanuda mientras el estado sea `BUDGET_EXHAUSTED` o
`PAUSED_BACKLOG`, espera ante `PARTIAL_RATE_LIMITED` y se detiene ante
cualquier otra cosa (`BLOCKED`, `PROTOCOL_ERROR`, `RECOVERY_REQUIRED`…).

**Cobertura de BBVA.** La ficha de Play no es un denominador fiable (lo dice
`epic_3.md`), así que el cierre se juzga por consistencia interna, y la cifra
de ~788 mil solo como orden de magnitud. Cuando el plan cierre
(`SOURCE_EXHAUSTED_OBSERVED`) y la cola se vacíe:

```sql
SELECT COUNT(*) AS filas, COUNT(DISTINCT id_resena) AS unicas,
       MIN(fecha) AS mas_antigua, MAX(fecha) AS mas_reciente
FROM `bbva_voc_tds.sanitized_reviews_tds` WHERE bank_id = 'BBVA'
```

- `filas = unicas`, el plan terminó en `SOURCE_EXHAUSTED_OBSERVED` y el rango de
  fechas llega hasta el origen del banco, con un orden de magnitud cercano a
  ~788 mil: continuar.
- **Muy por debajo** o el cursor termina antes de agotar el histórico: repetir
  con `--stars`, que extrae cada calificación por separado y requiere
  `FULL_BACKFILL`. Es un plan nuevo; conservar los datos ya cargados (el `MERGE`
  es idempotente).

## Etapa 3: los demás bancos, uno a la vez

NUBANK, SANTANDER, AZTECA y BANORTE, en ese orden, cada uno con su propio
`ingest` y su `drain`, repitiendo la puerta de la etapa 1. De uno en uno para no
sumar carga contra Google Play. Con el primer conteo de cada banco se corrige la
estimación del total.

## Etapa 4: cierre y verificación

- [ ] Todas las páginas cerradas: sin `Page closed` con `GAPS_DETECTED` ni
      `Bank state unreadable` en los logs de la sanitización.
- [ ] Sin duplicados:
      `SELECT bank_id, COUNT(*) - COUNT(DISTINCT id_resena) FROM … GROUP BY 1` = 0.
- [ ] Rango de fechas por banco desde el origen del histórico hasta hoy.
- [ ] `reviews_discarded = 0` en la auditoría (el endpoint solo devuelve
      reseñas con texto).
- [ ] 0 filas con título o respuesta; `SUM(pii_findings_count)` revisado.
- [ ] DLQ vacía; `raw_staging/` expira solo a los 7 días.

## Cuándo detener y qué hacer

| Señal | Acción |
| --- | --- |
| HTTP 403, `BLOCKED`, `PROTOCOL_ERROR` | Detener el banco; el controlador ya se detiene. Reproducir una solicitud a mano antes de reanudar |
| `rate_limited` repetido | Detener; no acelerar |
| Mensajes en la DLQ | Detener la ingesta, revisar los logs de la sanitización y reprocesar antes de seguir |
| `drain` sin avance dos veces seguidas | El controlador se detiene; revisar `Microbatch finished` y las cuotas |
| La cola más vieja supera ~4 días | No lanzar más ingesta hasta drenar |
| Un banco con estado ilegible | El resto no se frena (aislamiento); corregir ese banco aparte |

Todas las ejecuciones son reanudables: el estado vive en GCS y los recibos en
el ledger, así que relanzar el mismo comando continúa donde quedó.

## Lo que este plan no resuelve

- La profundidad real del cursor de Google Play: se descubre en el piloto.
- La exhaustividad del histórico: solo BBVA tiene una cifra de referencia.
- El retraso de ~24 h de las reseñas más recientes.
- El paralelismo: **no** se lanzan varias ejecuciones de sanitización a la vez
  hasta probar que los `MERGE` concurrentes sobre la misma tabla de BigQuery no
  chocan. Una vez medido el piloto, el siguiente 2× está en subir los hilos de
  E/S y el pool HTTP del cliente.
