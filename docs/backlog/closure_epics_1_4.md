# Cierre de las épicas 1 a 4

Estado al 2026-10-16. Resume qué se entregó, qué se midió en producción (stack
`dev`) y qué límites quedan documentados para quien use el TDS en EPIC-5. Los
criterios de aceptación de cada épica están en su `epic_N.md`; aquí solo se
registra lo verificado con datos reales.

## Qué existe y qué se probó en producción

| Épica | Entregado | Verificado en producción |
| --- | --- | --- |
| 1. `voc-common` y CI | Contratos, constantes, configuración, estado v2, logs estructurados, CI (ruff, pyrefly, bandit, pytest) | Los cuatro gates pasan; se usó en las 5 ingestas históricas y en la sanitización |
| 2. Infraestructura (Pulumi) | APIs, IAM, KMS, Pub/Sub (+DLQ), GCS, BigQuery, Cloud Run Service/Jobs, Schedulers | `pulumi preview` sin cambios (54 recursos); desplegado con imágenes fijadas por digest |
| 3. Ingesta | Cliente `batchexecute`, lease + CAS, páginas duraderas, runner, API incremental, Job histórico | Los 5 bancos recorridos hasta agotar el cursor (2012–2024 hasta 2026-10-14) |
| 4. Sanitización | Pipeline Pub/Sub → regex local → BigQuery `MERGE`, ledger de recibos, replay desde GCS | **Replay rápido** (`GCS_FAST_REPLAY`) cargó el histórico completo |

Herramientas de operación: `tools/backfill_controller.py` (`drain`, `ingest`) y
`tools/deploy_images.py` (despliegue de las dos imágenes por digest); ver
`docs/deployment.md` y `docs/full_backfill.md`.

## Resultado del histórico

**2 649 047 filas únicas** en `bbva_voc_tds.sanitized_reviews_tds`, sin
duplicados por `(bank_id, id_resena)`:

| Banco | Filas | Más antigua | Metadatos de la tienda | Diferencia |
| --- | ---: | --- | ---: | ---: |
| BBVA | 787 875 | 2011-04-01 | 790 803 | −0.4 % |
| NUBANK | 128 204 | 2015-08-17 | 107 286 | +19.4 % |
| SANTANDER | 623 594 | 2012-03-23 | 627 776 | −0.7 % |
| AZTECA | 590 981 | 2017-03-30 | 588 658 | +0.4 % |
| BANORTE | 518 393 | 2012-03-21 | 519 825 | −0.3 % |

- Cada plan terminó en `SOURCE_EXHAUSTED_OBSERVED`; el fin del histórico se
  infiere de una página parcial sin cursor (el protocolo no manda una señal
  explícita de fin).
- Todas las páginas cerradas `RESOLVED`; colas Pub/Sub y DLQ en 0.
- Costos de la carga: ingesta ~72 reseñas/s (51–77), 50 000 por ejecución (tope
  de 100 páginas); replay 351–573 msg/s. La ruta normal con recibos por evento
  habría rendido ~18 msg/s.

## Límites conocidos (léelos antes de analizar)

1. **Reseñas sin texto.** El extractor descarta las filas sin texto del origen:
   **100 de 2 649 145** (0.004 %; BBVA 67, SANTANDER 17, BANORTE 15, AZTECA 1,
   NUBANK 0). Quedan registradas en el ledger de descartes de cada página, no
   en el TDS. Es una excepción a "conservar todo", aceptada por su tamaño.
2. **NUBANK.** Superó su cifra de metadatos (la cifra no es un tope) y tiene
   ~175 reseñas de 2015–2019, anteriores al lanzamiento en México. Pendiente
   confirmar ID de aplicación y país (`hl`/`gl`); decidir en EPIC-5 si se filtran
   por fecha.
3. **Retraso de ~24 h.** La reseña más reciente de cada banco es del 2026-10-14
   aunque la carga corrió el 2026-10-15. Causa sin determinar; la ingesta
   incremental diaria debería cubrirlo (ventana de revisita de 3 días).
4. **PII y vacíos.** 16 hallazgos de PII en total y 8 textos vacíos tras
   sanear, sin revisar a fondo. La sanitización es solo regex local (Cloud DLP
   desactivado por defecto): ver F-01 y F-03 en la FMEA.
5. **Cobertura exacta del origen.** Se infiere del agotamiento del cursor y de
   las cifras de la tienda; no hay una prueba independiente de exhaustividad.
6. **Fechas.** Los datos de la tienda traen la fecha de la última edición, no
   de la creación; una reseña editada llega con fecha nueva.

## Incidentes de la puesta en marcha (y qué cambió)

| Incidente | Causa | Cambio |
| --- | --- | --- |
| Estado cruzado entre bancos (`protocol_shape`, `app_id does not match`) | IDs de AZTECA/BANORTE incorrectos | IDs corregidos; aislamiento por banco |
| Páginas finales rechazadas (`protocol_shape`) en los 5 bancos | El parser exigía bloque de paginación en la última página | Se acepta sin cursor solo con filas (`END_CANDIDATE`) |
| 1 645 filas cerradas como `STAGING_EXPIRED` sin estarlo | La imagen de sanitización traía el parser viejo y el cierre es irreversible | `CaptureUnreadable` deja la página abierta; `tools/deploy_images.py` exige el mismo SHA en las dos imágenes |
| 401 al invocar la ingesta con token de usuario | Sin determinar | `ingest --impersonate` con una cuenta de servicio |
| Diff permanente en `pulumi preview` | Valor por defecto de la API no declarado | `scaling` a nivel de servicio declarado |

## Validación de la operación diaria (2026-10-18)

Dos días de corridas programadas tras la carga (16 y 17 de octubre):

| Comprobación | Resultado |
| --- | --- |
| Ingesta incremental (14:00Z, 5 bancos × 2 días) | Las 10 en `TARGET_REACHED`, 9–23 s; 1 000 reseñas publicadas por banco (500 NUBANK) por la ventana de revisita de 3 días |
| Sanitización (14:30Z) | `exit_code: 0`, `stop_reason: drained`; 4 500 mensajes cada día (847 y 901 filas escritas, el resto ya procesado); 0 cuarentenas, 0 reintentos, 0 `poison`, 0 capturas expiradas, sin errores por banco |
| Cierre de páginas | Las 9 páginas de cada día `RESOLVED` |
| TDS | Sin duplicados; crece cada día (+226 AZTECA, +349 BANORTE, +401 BBVA, +102 NUBANK, +382 SANTANDER desde el cierre de la carga) |
| Colas | `voc-raw-reviews-sub` y DLQ en 0 |
| Infraestructura | `pulumi preview`: 54 recursos sin cambios |
| Permisos temporales | Revocados: `run.invoker` de usuarios sobre `voc-ingestion-worker` y `serviceAccountTokenCreator` sobre `voc-sa-scheduler` |

Observaciones que no bloquean:

- **Retraso de ~24 h estable.** La reseña más reciente de cada banco es de las
  ~13:50 del día anterior a la corrida de las 14:00Z, los dos días. El patrón es
  constante (apunta al origen, no al pipeline), pero no está demostrado contra
  la ficha de Play en vivo.
- **Contador `PENDING` del informe final.** `Sanitization run finished` suma los
  estados intermedios de cada microbatch (p. ej. `PENDING: 16, RESOLVED: 9`)
  aunque todas las páginas cierren `RESOLVED`. Es un defecto de presentación del
  informe; mejora menor: reportar solo el estado final por página.
- **Propietarios del proyecto.** Hay tres cuentas con `roles/owner`
  (`0287289@up.edu.mx`, `traslasnovenas@gmail.com`, `jpaul.marquez.ruiz@gmail.com`);
  no se tocaron. Confirmar que ese nivel es intencional.

## Estado

La ingeniería de extracción (EPIC-1 a EPIC-4) queda **cerrada**: el histórico
está cargado y verificado, la operación diaria funciona sin intervención y los
accesos temporales se retiraron.

## Fuera de las épicas 1–4

- `Data Card` y `Model Card` (`docs/governance/`) siguen vacías; la FMEA no
  cubre aún EPIC-5 ni EPIC-6.
- Dudas de datos para el análisis: fechas anteriores al lanzamiento de NUBANK
  en México, y el retraso de ~24 h (ver límites 2 y 3).
- EPIC-5 (Delora, conjunto de oro, `topico`, `embedding_vector` solo para un
  subconjunto) y EPIC-6 (portal).
