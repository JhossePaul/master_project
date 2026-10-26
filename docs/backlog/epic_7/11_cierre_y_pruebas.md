# Paso 11. Feature 7.12: Pruebas, *quality gates* y cierre del portal

* **Estado (2026-10-25):** Pendiente.
* **Nivel:** imprescindible.
* **Depende de:** pasos 1 a 10 (los que hayan entrado en el alcance).
* **Objetivo:** cerrar el portal funcional: las pruebas de cada paso ya existen; aquí se completan los huecos, se corre todo junto, se revisa la seguridad y el costo y se prepara la presentación. La tesis (paso 12) no es requisito de este cierre.

## 1. Pruebas

### 1.1 API, sin red

Comprobar que existen y pasan, con cobertura de `api_backend` ≥ 85 %:

* roles: cada ruta responde 403 al rol que no le toca (prueba generada desde `ROUTE_ROLES`);
* **ningún lector recibe texto:** la prueba del centinela cubre todas las rutas de lector;
* *gap* en estrellas e intervalos (signo y fuente PPI o cruda);
* filtros del Explorador, recorte de la ventana y búsqueda;
* **modo ciego:** la predicción no viaja en `monitor_sample` ni en `agreement_sample`;
* versionado de políticas (nueva versión, 409, motivo, grupos completos);
* hash del actor (nunca el correo);
* acciones de MLOps: solo los Jobs y argumentos de la lista.

### 1.2 Portal

* `npm run check`, `npm test` y `npm run build` sin errores de TypeScript;
* `axe` sin violaciones en cada sección;
* ningún hex ni nombre real de banco fuera de `tokens.css` y `banks.ts`.

### 1.3 Punta a punta (deseable)

Playwright contra la API en modo local (`PORTAL_AUTH_MODE=local`, `PORTAL_DATA=fixtures`) sirviendo `dist/`: un recorrido por sección con el rol que le corresponde y uno con rol lector que intenta abrir el Explorador y el HITL.

### 1.4 Monorepo

`ruff`, `ruff format --check`, `pyrefly` y `bandit` sin hallazgos; `pytest` de cada paquete con su umbral de `ci.yaml`.

## 2. Revisión de seguridad (en dev)

* [ ] La URL de Cloud Run sin pasar por IAP no llega a la API (401 o 403 de IAP).
* [ ] Una cuenta con IAP pero sin entrada en el mapa recibe 403 en `/api/*`.
* [ ] Los registros de la API en Cloud Logging de un día de uso no contienen texto de reseñas, comentarios, consultas de búsqueda ni correos (búsqueda por el centinela y por `@`).
* [ ] Los encabezados de seguridad están en las respuestas (`curl -I`).
* [ ] La cuenta `voc-sa-portal-api` solo puede escribir en las tablas de la lista del paso 1 (prueba: un `INSERT` en `review_predictions` con esa cuenta falla).
* [ ] El autor corre una revisión de código del diff de la épica (por ejemplo `/code-review`) y se atienden los hallazgos.

## 3. Costo

Una tabla en "Avance" con los bytes facturados por carga de cada pantalla (de los registros de la API o de `INFORMATION_SCHEMA.JOBS`), el costo mensual estimado con el uso esperado y el de `voc-ml-online` (Cloud Run con mínimo 0).

## 4. Documentación y estado

* `docs/operations/deployment.md`: la sección del portal completa (despliegue, personas, roles, IAP, el servicio en línea, cómo se publica una versión de la tesis).
* `docs/backlog/epic_7.md`: el checklist de aceptación marcado, con su fecha.
* `docs/backlog/epics.md`: el estado de EPIC-7.
* `docs/contracts/analytics_outputs_v3.md`: los cambios de contrato de la épica (`occlusion_v2`, `topic_refit`, revisión "no evaluable") en la sección 8.
* `CLAUDE.md`: el mapa de áreas al día.
* EPIC-8: las deudas que deje la épica, con su motivo.

## 5. Presentación

* [ ] Las cuentas de quienes van a ver la demo entran (probado con días de anticipación, sobre todo las de `bbva.com`).
* [ ] Un guion por sección: qué se muestra, con qué filtro y qué número se comenta.
* [ ] Datos frescos: el delta del día corrió.
* [ ] Respaldo sin red: la API y el portal en la máquina del autor con datos sintéticos (`PORTAL_DATA=fixtures`), por si falla la conexión.
* [ ] PR `develop` → `main` con la aprobación del autor.

## Terminado cuando

* [ ] Las secciones 1 a 4 están completas y la 5 está lista antes de la presentación.
* [ ] El checklist de aceptación de [`epic_7.md`](../epic_7.md) está marcado, salvo la tesis si todavía no se hizo.

## Avance

_(Se llena al ejecutar.)_
