# Paso 7. Feature 7.8: Alertas de deriva

* **Estado (2026-10-25):** Pendiente.
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

* [ ] Una alerta nueva (en dev, la primera que emita el monitor; en pruebas, una sintética) aparece en la bandeja y en la landing.
* [ ] Su confirmación o descarte queda auditada en `drift_alert_events` con quién, cuándo, nota y ticket.
* [ ] Descartar una alerta con subida activa la cierra.

## Decisiones al implementar

_(Se llena al ejecutar.)_

## Avance

_(Se llena al ejecutar.)_
