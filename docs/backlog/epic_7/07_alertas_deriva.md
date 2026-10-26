# Paso 7. Feature 7.8: Alertas de deriva

* **Estado (2026-10-26):** Terminado en local y probado contra BigQuery de dev (solo lecturas); la primera alerta real llegará con el monitor, así que las casillas 1 y 3 se confirman en dev con una alerta real o sintética. Detalle en "Avance".
* **Nivel:** importante.
* **Depende de:** paso 2 (y el sanitizador de comentarios del paso 4 para las notas).
* **Objetivo:** atender las alertas de deriva que emite el monitor semanal con la `drift_policy` de cada banco: una bandeja por banco, la serie de cada alerta contra su umbral, la subida de revisión que disparó y un flujo auditado (`open` → `confirmed` o `dismissed`). **La detección de incidentes de negocio está fuera del alcance:** los picos de negativas, familias o marca `u` se ven en el cockpit como descripción.

## 1. Lo que hay en dev

* `drift_alerts` está vacía: el primer monitor no abrió alertas, porque solo el último mes cerrado alerta y los meses anteriores quedan en `drift_metrics` con su marca. Desde la política v2, las familias y la marca `u` también alertan con z ≥ 4, y se esperan unos 37 meses-alerta al año entre todas las series.
* El monitor escribe el evento `open` de cada alerta (`drift_job.py`) y, si la `risk_policy` tiene subida por deriva, la fila de `hitl_boosts`. En v1 la subida es nula, así que una alerta solo se registra, se publica y manda correo.
* Para desarrollar y probar se usan alertas sintéticas en los datos de prueba.

## 2. Flujo

| Desde | Hacia | Quién | Requiere |
| :--- | :--- | :--- | :--- |
| `open` | `confirmed` (la deriva es real) | analista | Nota (mínimo 10 caracteres); ticket opcional |
| `open` | `dismissed` (falsa alarma o explicada) | analista | Nota; ticket opcional |
| `confirmed` | `dismissed` (se resolvió) | analista | Nota |
| `confirmed` o `dismissed` | `open` (reabrir) | analista | Nota |

* Cada transición es una fila nueva en `drift_alert_events` (`event_id` lo genera el portal, `actor_hash`, `at`, `note` sanitizada con DLP, `ticket`). Nada se edita.
* **Si la alerta tiene una subida activa** (`hitl_boost_id` con fila en `hitl_boosts_active`) y pasa a `dismissed`, la API inserta la fila de cierre en `hitl_boosts`: el mismo `boost_id` con `ended_reason = alert_closed`, como dice el modelo `HitlBoost`. Para eso la cuenta de la API necesita `dataEditor` sobre `hitl_boosts` (se suma a la lista de tablas del paso 1). Confirmar una alerta no cierra su subida.

## 3. API (`sections/alerts/`)

Rol analista.

| Método y ruta | Respuesta |
| :--- | :--- |
| `GET /api/v1/alerts?status=open&bank=` | `list[AlertRow]`: de `drift_alerts_current`, con `alert_id`, `bank_id`, `period`, `series`, `value`, `threshold`, `status`, `status_at`, `drift_policy_version` y `boost` (activa o no, cobertura, fin) |
| `GET /api/v1/alerts/{alert_id}` | `AlertDetail`: la alerta, sus eventos en orden (estado, fecha, hash corto, nota, ticket), la serie del banco en `drift_metrics` de los 24 meses previos (valor, línea base, z o PSI, umbral), la subida y el enlace sugerido al Explorador (banco y mes de la alerta) |
| `POST /api/v1/alerts/{alert_id}/events` | Cuerpo `{ event_id: UUID, status, note, ticket? }`. Valida la transición contra el estado vigente (409 si cambió), sanitiza la nota, inserta y, si corresponde, cierra la subida |
| `GET /api/v1/alerts/summary` | `{ open_by_bank: dict[str, int] }` (rol lector: solo conteos; la usa la landing) |

## 4. Pantalla (`src/sections/alerts/`)

* **Bandeja** (`/alertas`): pestañas Abiertas (por defecto), Confirmadas, Descartadas y Todas; filtro por banco (el global). Tabla con banco, mes, serie (con su nombre en lenguaje común: "palabras por reseña", "proporción de negativas", "familia: acceso y cuenta"…, desde un mapa en `src/config/driftSeries.ts`), valor contra umbral, estado, días abierta y si tiene subida.
* **Detalle** (`/alertas/:alertId`):
  * la gráfica de la serie (24 meses) con la línea base, el umbral (línea discontinua dorada) y el mes de la alerta resaltado; para las series de z, también el z por mes;
  * la subida de revisión, si la hay, y qué significa ("mientras dure, la cobertura de este banco baja a 0.85: se revisan más reseñas");
  * la historia de eventos;
  * las acciones válidas según el estado (botones Confirmar, Descartar y Reabrir) con `ConfirmWithReason` para la nota y un campo de ticket;
  * "Abrir en el Explorador" con el banco y el mes de la alerta;
  * el `Callout` "Una alerta dice que la entrada o la predicción cambió respecto de los 12 meses previos del banco; no dice por qué".
* **Landing:** el conteo de abiertas por banco (paso 2) enlaza aquí.

## 5. Pruebas

* **API:** transiciones válidas e inválidas (409 si el estado cambió entre lectura y escritura); la nota pasa por el sanitizador; descartar cierra la subida activa con `alert_closed` y confirmar no; idempotencia por `event_id`; `summary` de rol lector sin texto (centinela en la nota); 403 para lector en las demás rutas.
* **Portal:** la bandeja filtra por estado; el detalle muestra solo las acciones válidas; Confirmar exige nota; `axe` sin violaciones.

## Terminado cuando

* [x] Una alerta nueva (en dev, la primera que emita el monitor; en pruebas, una sintética) aparece en la bandeja y en la landing. (Probado con alertas sintéticas en la API y en el portal; en dev `drift_alerts` sigue vacía y las consultas devuelven vacío sin error.)
* [x] Su confirmación o descarte queda auditada en `drift_alert_events` con quién, cuándo, nota y ticket. (Probado con la tabla en memoria; la escritura real a BigQuery se estrena con la primera alerta de dev.)
* [x] Descartar una alerta con subida activa la cierra. (Prueba de API: `alert_closed`, y confirmar no la cierra.)

## Decisiones al implementar

* **El cierre de la subida ya estaba permitido.** `hitl_boosts` y `drift_alert_events` están en `PORTAL_WRITABLE_TABLES` desde el paso 1, así que este paso no toca `infra/`.
* **El 409 sale de validar la transición contra el estado vigente.** El cuerpo no lleva el estado que el analista vio, así que "cambió entre lectura y escritura" se detecta releyendo la alerta justo antes de escribir: si la transición ya no es válida desde el estado de ahora (por ejemplo, otro analista descartó mientras tú confirmabas), 409 con el estado actual en el mensaje. Dos envíos que lleguen al mismo tiempo desde el mismo estado pueden escribirse los dos (la tabla es de solo inserción y no hay bloqueo); el último evento manda y la historia deja ambos. No se agregó otra relectura.
* **Reabrir y confirmar de nuevo.** `dismissed → confirmed` no existe: hay que reabrir primero, como dice la tabla del flujo. `open → open` y repetir el mismo estado dan 409.
* **Nota mínima de 10 caracteres en toda transición**, no solo al confirmar: la tabla pide "Nota" en las demás y el diálogo del portal (`ConfirmWithReason`) ya exige 10. Máximo 500 caracteres; el ticket, 100 (un ticket en blanco se guarda nulo).
* **Idempotencia por `event_id`.** Un reintento con el mismo `event_id` devuelve 200 con la alerta tal como está, sin escribir otra vez. Si el reintento es de un descarte, vuelve a intentar cerrar la subida: cubre el fallo a medias (evento escrito, cierre no). El orden de escritura es evento primero y cierre después.
* **El cierre de la subida es literal a la especificación**: al descartar, si `hitl_boost_id` apunta a una subida activa, se inserta la fila de cierre (clave `boost_id` y `ended_reason`, la misma del monitor). Ojo: el monitor reparte **una subida por banco** entre sus alertas (`hitl_boost_id` apunta a la subida del banco aunque otra alerta la haya abierto) y su cierre automático mira solo la alerta que la creó (`boost.alert_id`). Descartar una alerta que comparte subida con otra abierta cierra la subida del banco. Con la subida nula de la política v1 no ocurre; si la política v2 la configura, conviene decidir si se cierra solo cuando no quede otra alerta abierta o confirmada del mismo banco.
* **`period` y los umbrales.** `AlertRow.period` es "2026-09". Para las series de z, `value` es el valor del mes y `threshold` el z (4), así que la bandeja los muestra como "31.0 %" y "z ≥ 4" (y "PSI ≥ 0.25" en la longitud); el z del mes está en el detalle. El detalle trae los 24 meses que terminan en el mes de la alerta (no 24 previos a él), para que el mes resaltado esté dentro de la gráfica.
* **Las series sin umbral (tópicos) tienen nombre en el mapa** (`driftSeries.ts`) aunque nunca alertan, por si una política futura les pone uno.
* **Tres archivos de prueba nuevos** en vez de extender `test_bigquery_integration.py`: `test_alerts.py`, `test_alerts_bigquery.py` (lector y escritor falsos) y `test_alerts_integration.py` (opcional, contra dev).
* **Landing:** cada banco del conteo de abiertas enlaza a `/alertas?bancos=<banco>` para quien es analista. `GET /alerts/summary` queda disponible para el lector, pero la landing sigue leyendo `open_alerts` de su propia respuesta.
* **`ConfirmWithReason` acepta un ticket opcional** (`withTicket`, segundo argumento de `onConfirm`) y limita el motivo a 500 y el ticket a 100 caracteres. `ReferenceLine` acepta `labelOutside` para poner el umbral en el margen derecho y no encima de la serie.
* **El motivo se pierde si el envío falla** (el diálogo se cierra al confirmar): el aviso de error queda en la pantalla y hay que volver a escribirlo. Un reintento del mismo texto reutiliza el `event_id`.
* **FMEA:** las notas pasan por el mismo sanitizador que los comentarios del HITL, que ya cubre la fila F-21; no se agregó una fila nueva (el archivo de la FMEA tiene cambios sin commitear de otra sesión).

## Avance

* **API (2026-10-26):** `sections/alerts/` (`router`, `schemas`, `service`, `repository`, `sample`), registrada en `main.py`; `openapi.json` y `schema.d.ts` regenerados. 35 pruebas nuevas (`test_alerts.py` y `test_alerts_bigquery.py`) y la ruta `summary` en `test_sentinel.py`: bandeja por estado y banco, subida activa o terminada, detalle con 24 meses y enlace al Explorador, las seis transiciones válidas y las cuatro inválidas (409), 409 cuando otro analista cambió el estado, nota sanitizada y DLP caído (502 sin escribir nada), descartar cierra con `alert_closed` y confirmar no, subida vencida sin cierre doble, idempotencia (también la del cierre a medias), `summary` de lector sin notas, 403 para el lector y para el revisor en las demás rutas. Suite de la API: 231 pasan, 42 omitidas (BigQuery de dev).
* **Contra BigQuery de dev** (`RUN_BIGQUERY_TESTS=1`, solo lecturas): las seis consultas (bandeja, una alerta, eventos, subidas, resumen y serie) corren sin error. La bandeja, el resumen, la alerta, los eventos y las subidas leen 0 bytes (tablas casi vacías); la serie de `neg_share` de BBVA lee 10 MB y devuelve sus meses.
* **Portal (2026-10-26):** `/alertas` (pestañas Abiertas, Confirmadas, Descartadas y Todas en `?estado=`, tabla con banco, mes, serie en lenguaje común, valor, umbral, estado, días abierta y subida) y `/alertas/:alertId` (gráfica de 24 meses con la línea base y el mes resaltado; el z por mes con el umbral para las series de z; subida, historia, acciones válidas con nota y ticket, enlace al Explorador y el `Callout`). 16 pruebas nuevas, entre ellas `axe` sin violaciones en la bandeja y en el detalle. `npm run check`, `tsc`, `npm test` (155) y `npm run build` pasan; las dos pantallas son trozos perezosos (6 KB comprimidos la bandeja).
* **Revisada en local** (`PORTAL_DATA=fixtures`): se abrió la bandeja y el detalle, se descartó la alerta con subida activa (nota con un nombre propio, que salió como `[PERSON_NAME]`) y la subida pasó a "se cerró al descartar la alerta" con el evento en la historia. Dos pruebas viejas (`a11y` y `cockpit`) usaban `/alertas` como ejemplo de sección en construcción; ahora usan `/mlops`.
* **Pendiente:** la primera alerta real de dev. La escritura a `drift_alert_events` y `hitl_boosts` por la API se estrena entonces.
