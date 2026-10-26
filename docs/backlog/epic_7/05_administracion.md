# Paso 5. Feature 7.10: Administración y configuración

* **Estado (2026-10-26):** Implementado en código (lógica, API y pantalla); faltan la prueba en dev con el autor y fijar los parámetros sin evidencia. Trabajado en su propio *worktree* (rama `admin-7-10`).
* **Nivel:** imprescindible.
* **Depende de:** paso 2.
* **Objetivo:** ajustar el apetito de riesgo (`risk_policy`, global) y la deriva (`drift_policy`, por banco) como decisiones informadas, cada una con su evidencia y su ayuda; ver y comparar el historial de versiones, y crear versiones del oro desde la muestra de monitoreo. Cambiar un parámetro **crea una versión nueva**, con quién (hash) y por qué, y la siguiente corrida la usa.

## 1. Lógica compartida que se mueve

`point_for`, `next_policy_version` y `propose_risk_policy` (`services/ml-inference/src/ml_inference/lifecycle.py:195-237`) son puras, pero importarlas desde `ml-inference` arrastra BigQuery, Gemini y pyarrow. Se mueven a **`packages/voc-nlp/src/voc_nlp/policy.py`** (`voc-nlp` sin extras solo depende de `voc-common`, numpy y emoji), **sin cambiar el criterio**, con sus pruebas. `lifecycle.py` las importa de ahí y las re-exporta, para que nada de `ml-inference` cambie. Lo mismo con `Rate` y `rates()` de `ml_inference/monitor/drift_rates.py` (con `REFERENCE`, `TOLERANCE` y `CEILING`), a `voc_nlp/drift_rates.py`; `report()` y su SQL se quedan en `ml-inference`. Corren las pruebas de `voc-nlp` y de `ml-inference`.

Si `propose_risk_policy` no basta para cambiar parámetros distintos de la cobertura, se agrega a `voc_nlp.policy` una función `next_risk_policy(current, changes, curve, actor_hash, reason, now) -> RiskPolicy` que aplica los cambios con `model_copy` y deja que el modelo `RiskPolicy` los valide, y que recalcula el umbral con `point_for` solo si cambia la cobertura.

## 2. Parámetros y su ayuda

La ayuda de cada parámetro vive en `web/portal/src/config/policyHelp.ts` (`{ label, unit, means, evidence, link, up, down, min, max, step }`), en lenguaje común. El punto de partida, que se redacta con estos datos:

| Parámetro | Vigente | De dónde sale (para "evidencia") | Si sube | Si baja |
| :--- | :--- | :--- | :--- | :--- |
| `hitl_target_coverage` | 0.90 | Calibración: con 90 % de cobertura se revisan ~350 textos por semana y el error entre lo aceptado es de 0.4 % ([reporte](../../analytics/calibration/calibration_report.md)) | Menos revisión y más error aceptado | Más revisión (costo en minutos) y menos error |
| `hitl_weekly_cap` | nulo (sin tope) | No hay evidencia en los experimentos; la semana real de los temas por día dio 387 casos con el umbral del 90 % | — | Se revisan solo los primeros N casos de la semana |
| `drift_boost_coverage`, `drift_boost_days`, `drift_boost_weekly_cap` | nulos (sin subida) | Sin evidencia; la curva da el costo de cada cobertura con el volumen del banco | Una alerta sube la revisión de ese banco | — |
| `monitor_sample_size`, `monitor_frequency` | 300 por trimestre | El κ con 300 revisiones detecta la caída al piso ([escala, §8](../../analytics/scale/scale_report.md)) | Más precisión del κ, más minutos | Menos precisión |
| `retrain_kappa_floor` | 0.89 | Percentil 5 del κ de un modelo sin cambios ([escala, §8](../../analytics/scale/scale_report.md)) | Se reentrena antes | Se tolera más degradación |
| `retrain_trigger` | `manual` | Decisión del autor: en `auto`, el texto sale a Kaggle sin aprobación por corrida | — | — |
| `topic_refit_frequency`, `topic_refit_trigger` | trimestral, `scheduled` | No hay umbral con evidencia para re-ajustar tópicos | — | — |
| `human_agreement_sample_size`, `human_agreement_frequency` | nulos (sin doble revisión) | Sin evidencia; el oro tuvo un segundo anotador con κ 0.81–0.87 ([oro](../../analytics/labeling/gold_v1_report.md)) | Más medición del acuerdo, más minutos | — |
| `warn_correction_rate` | 0.28 (4 semanas) | Tasa de corrección de la cola en los experimentos | Avisa menos | Avisa más |
| `warn_agreement_floor`, `agreement_sample_weekly` | 0.94, 500 textos por semana | Acuerdo del modelo con Gemini ([escala, §8](../../analytics/scale/scale_report.md)); ~$0.02 por semana | Avisa más | Avisa menos |
| `families_exact_floor`, `families_min_prevalence` | 0.53, 0.05 | Revalidación de las familias con las 300 reseñas anotadas por el autor | Rechaza más cambios de prompt | Acepta más |
| Umbrales de `drift_policy` | z ≥ 4; PSI ≥ 0.25 en longitud | Con esa plantilla cada serie alertó de 0 a 1.4 meses al año por banco ([escala, §2](../../analytics/scale/scale_report.md)) | Menos alertas | Más alertas (z ≥ 3 daría ~1.6 veces más) |
| `baseline_months`, `min_baseline_months`, `min_rows_per_month`, `entry_months` | 12, 6, 200, 12 | Línea base histórica del monitor | Entrada más tardía y base más estable | Más bancos y meses entran antes |

## 3. API (`sections/admin/`)

Todas de rol administrador.

| Método y ruta | Qué hace |
| :--- | :--- |
| `GET /api/v1/admin/risk-policy` | `{ current: RiskPolicy, history: list[RiskPolicy] }` (la tabla completa, ordenada por `valid_from`) |
| `GET /api/v1/admin/coverage-curve?model_version=` | `CoverageCurveResponse`: la curva (`HitlCoverageCurve`), el punto vigente, los volúmenes semanales total y por banco, el tiempo medido (`median_seconds`, `n`, ventana de 90 días de `hitl_reviews`) y las subidas activas (`hitl_boosts_active`). Sin `model_version`, la del modelo promovido |
| `POST /api/v1/admin/risk-policy/preview` | Cuerpo `{ base_version, changes }`. Devuelve la versión propuesta sin guardarla, el `diff` campo por campo, `large_change` (la cobertura cambia más de 5 puntos) y las advertencias (`retrain_trigger = auto`, un grupo incompleto) |
| `POST /api/v1/admin/risk-policy` | Cuerpo `{ base_version, changes, reason, confirm_word? }`. Crea la versión. 409 si `base_version` ya no es la vigente; 422 si `large_change` y `confirm_word != "CONFIRMAR"` |
| `GET /api/v1/admin/drift-policy?bank=` | `{ current, template, history, diff_vs_template }` del banco |
| `POST /api/v1/admin/drift-policy/rates` | Cuerpo `{ bank, thresholds }`. Por serie: meses evaluados, alertas y tasa por año con los umbrales propuestos, la tasa con los vigentes y la referencia de los experimentos (`REFERENCE`) |
| `POST /api/v1/admin/drift-policy` | Cuerpo `{ bank, base_version, changes, reason }`. Crea la versión del banco (`drift_policy_v<n>_<banco>`) con `template_version` de la vigente |
| `GET /api/v1/admin/gold-versions` | Versiones del oro creadas desde el HITL |
| `POST /api/v1/admin/gold-versions/preview` | Cuerpo `GoldCriteria`. Devuelve cuántas revisiones entrarían, por banco y por etiqueta |
| `POST /api/v1/admin/gold-versions` | Cuerpo `{ criteria, reason }`. Inserta en `gold_versions` (`gold_hitl_v<n>`, `cutoff_at` = ahora) |
| `GET /api/v1/admin/gold-versions/{gold_version}/items` | Los ítems que da su criterio a su `cutoff_at`: `item_id`, `id_resena`, `validated_label`, `submitted_at` y el hash corto del revisor. Sin texto |

```python
class GoldCriteria(BaseModel):
    reason: Literal["monitor_sample"] = "monitor_sample"
    submitted_from: date
    submitted_to: date
    guideline_version: str           # una sola guía por versión del oro
    review_round: Literal[1] = 1
    exclude_flags: list[ReviewFlag] = [ReviewFlag.NO_EVALUABLE]
```

**Reglas al crear una versión:**

* La valida el modelo de `voc-common` (`RiskPolicy`, `DriftPolicy`). Los grupos se configuran completos o se dejan nulos (subida por deriva, doble revisión), como en la `risk_policy` v1.
* `valid_from` es el momento de guardar (UTC); `set_by_hash` es el `actor_hash` del administrador; `reason` es obligatorio (al menos 10 caracteres).
* Si cambia la cobertura, el umbral sale de `point_for` sobre la curva del modelo promovido, y `model_version` es el de esa curva.
* Nada se edita ni se borra: `writer.insert` con la clave de la versión.
* **Tasas de la `drift_policy` propuesta:** una consulta a `drift_metrics` (última `computed_at` por banco, mes y serie, solo los meses evaluados según la regla de entrada) cuenta los meses con `ABS(z) >= @umbral_z` o `psi >= @umbral_psi` por serie, con los umbrales como parámetros, y pasa el resultado a `voc_nlp.drift_rates.rates()`.
* **Oro desde el HITL:** el aviso de la pantalla dice que, para que el monitor y el reentrenamiento usen la versión nueva, hay que cambiar `GOLD_VERSION` en los Jobs y subir sus ids de exclusión (pendiente 4 de [EPIC-8](../epic_8.md)). Este paso no lo automatiza.

## 4. Pantalla (`src/sections/admin/`)

Pestañas: **Apetito de riesgo**, **Deriva por banco**, **Historial**, **Oro** (y **Muestras** en el paso 9).

### 4.1 Apetito de riesgo

* **Curva de cobertura y riesgo** del modelo promovido (D3): eje X la cobertura (de 0.80 a 1.00), eje Y el error esperado entre lo aceptado con su banda de intervalo, el punto vigente con el rombo dorado y, al mover el control de cobertura, un segundo punto "propuesto".
* **Tabla de la curva:** por cobertura, el error esperado, los errores atrapados, las revisiones por semana y los minutos por semana con dos columnas: los de la curva y los recalculados con el tiempo medido (`median_seconds × revisiones`), con el `n` del tiempo medido.
* **Formulario** (React Hook Form + Zod, con los rangos de `policyHelp.ts`), agrupado:
  * revisión humana: cobertura objetivo (control deslizante con paso de 0.01 y campo numérico) y tope semanal;
  * reacción a la deriva: los tres campos de la subida, con un conmutador "sin subida automática";
  * muestras: muestra de monitoreo y doble revisión (con su conmutador);
  * avisos: corrección, acuerdo con Gemini y familias;
  * modelos: disparo del reentrenamiento (`manual` o `auto`, y en `auto` el aviso "en automático, el texto sale a Kaggle sin aprobación por corrida; cambiarlo es esa aprobación") y re-ajuste de tópicos (`scheduled` o `manual`, frecuencia).
* Junto a cada campo, un ícono de ayuda que abre `means`, `evidence` (con su enlace), `up` y `down`.
* **Revisar cambios:** llama a `preview` y muestra el *diff* y las advertencias; **Guardar** abre `ConfirmWithReason` y, si `large_change`, pide escribir `CONFIRMAR`.
* **Subidas activas por banco**, con su alerta, cobertura y fin.

### 4.2 Deriva por banco

* Selector de banco; tabla de series con el umbral vigente, el de la plantilla (las diferencias resaltadas) y un campo para el propuesto.
* **Tasas:** al cambiar un umbral, `rates` devuelve la tasa por año con el propuesto, la vigente y la referencia de los experimentos; una barra por serie con la referencia como línea dorada.
* Los parámetros de entrada (línea base, filas mínimas, meses de entrada) con su ayuda.
* Guardar con `ConfirmWithReason`.

### 4.3 Historial

* Por política (riesgo o deriva de un banco): lista de versiones con fecha, quién ("tú" si es el hash propio; si no, los primeros 8 caracteres del hash) y motivo.
* Elegir dos versiones muestra su comparación campo por campo.

### 4.4 Oro

* Formulario de `GoldCriteria`, vista previa con conteos por banco y etiqueta, creación con motivo, lista de versiones y sus ítems.
* El aviso de `GOLD_VERSION` de la sección 3.

## 5. Pruebas

* **`voc-nlp`:** `policy.py` y `drift_rates.py` con las pruebas que ya tenían en `ml-inference`, más `next_risk_policy` si se agrega; `ml-inference` sigue pasando sus pruebas sin cambios de comportamiento.
* **API:**
  * cambiar la cobertura recalcula el umbral con `point_for` y guarda el `model_version` de la curva;
  * un grupo incompleto da 422;
  * más de 5 puntos sin `CONFIRMAR` da 422;
  * `base_version` vieja da 409;
  * `set_by_hash` y `reason` siempre presentes; nunca se escribe en otra tabla;
  * las tasas con umbrales propuestos coinciden con un cálculo a mano sobre `drift_metrics` en memoria;
  * los criterios del oro excluyen `no_evaluable` y la segunda ronda;
  * un analista recibe 403 en todas las rutas.
* **Portal:** el control de cobertura mueve el punto propuesto; el *diff* lista solo lo que cambió; Guardar exige motivo; la advertencia de `auto` aparece; `axe` sin violaciones.

## Terminado cuando

* [ ] Un cambio crea una versión nueva y auditada (quién y por qué) y aparece en el historial.
* [ ] En dev, después de cambiar la cobertura (por ejemplo a 0.89 y de vuelta a 0.90, con motivo "prueba de la pantalla de administración"), el siguiente delta escribe `review_predictions` con la `risk_policy_version` nueva. El autor aprueba esa prueba antes de hacerla.
* [ ] Las tasas de la plantilla vigente coinciden con `drift-rates` del paso 12 de 6.6.
* [ ] Los parámetros sin evidencia (tope semanal, subida, doble revisión) quedan fijados o explícitamente nulos por el autor, con su motivo.

## Decisiones al implementar

* **Un solo `next_risk_policy`.** `propose_risk_policy` no cambia más que la cobertura, así que se agregó `voc_nlp.policy.next_risk_policy(current, changes, curve, actor_hash, reason, now)`. Revalida la fila completa con `RiskPolicy.model_validate` (un `model_copy` no valida, y el grupo incompleto debe fallar), rechaza los campos que fija el sistema (`policy_version`, `valid_from`, `hitl_signal`, `hitl_threshold`, `model_version`, `set_by_hash`, `reason`) y los desconocidos, y recalcula umbral y `model_version` solo si cambia la cobertura. `lifecycle.py` y `monitor/drift_rates.py` re-exportan lo movido; sus pruebas no cambiaron.
* **Vista previa con `errors`, no con 422.** `preview` siempre responde 200: si los cambios no pasan la validación (un grupo incompleto, un rango), `proposed` es nulo y `errors` dice por qué; guardar sí da 422. Así la pantalla muestra el motivo junto al formulario.
* **El motivo del oro vive en `criteria`.** `gold_versions` no tiene columna de motivo; se guarda como `criteria.created_reason`, y los ítems se reproducen con el resto de `criteria` (los campos extra se ignoran). No cambia el contrato.
* **Tasas de deriva en Python.** La consulta trae los meses evaluados (con umbral, última `computed_at`) y el servicio cuenta las alertas con los umbrales propuestos y con los vigentes antes de pasar el resultado a `voc_nlp.drift_rates.rates()`; son unas miles de filas por banco y la prueba compara con un cálculo a mano. Los meses son los que el monitor evaluó con su política vigente (`threshold IS NOT NULL`), como en el comando `drift-rates`.
* **Versión de deriva por banco:** se incrementa el número y se conserva el resto del id (`drift_policy_v<n>_<banco>`; en dev el banco va en minúscula, `drift_policy_v2_nubank`); solo se editan los umbrales y los cuatro parámetros de entrada, y `template_version` se hereda de la vigente.
* **Versión vigente = última con `valid_from` ≤ ahora**, igual que las vistas: una versión guardada es la vigente de inmediato y la anterior queda en el historial. `base_version` debe ser la vigente (409 si no).
* **Oro:** el corte es el momento de crear la versión; los ítems de una versión son las revisiones que cumplen su criterio hasta ese corte, sin texto. Requiere al menos una revisión y la guía es una sola por versión.
* **Permisos de BigQuery:** el servicio ya podía insertar en `risk_policy`, `drift_policy` y `gold_versions` (`PORTAL_WRITABLE_TABLES`); no hubo cambios en `infra/`.
* **Pantalla:** cuatro pestañas por `?tab=` (`riesgo`, `deriva`, `historial`, `oro`; **Muestras** llega en el paso 9). El formulario usa React Hook Form con Zod, con los rangos de `policyHelp.ts`; Guardar usa `ConfirmWithReason` y, si `large_change`, pide `CONFIRMAR`. El historial compara dos versiones en el portal.
* **Nombres de banco:** la pantalla muestra el seudónimo, pero los identificadores de versión (`drift_policy_v1_BBVA`) llevan el id real del banco; es una pantalla de administrador y son ids técnicos.

## Avance

* **Lógica compartida (2026-10-26):** `voc_nlp.policy` (`point_for`, `next_policy_version`, `propose_risk_policy`, `next_risk_policy`) y `voc_nlp.drift_rates` (`Rate`, `rates`, `REFERENCE`, `TOLERANCE`, `CEILING`) con sus pruebas. Pasan las pruebas de `lifecycle`, `drift_rates` y `rescore` de `ml-inference`.
* **API (2026-10-26):** `sections/admin/` con las 11 rutas de la sección 3 (rol administrador, en `ROUTE_ROLES`), datos de muestra para `PORTAL_DATA=fixtures` y `openapi.json` regenerado. 35 pruebas nuevas en `test_admin.py`, `test_admin_edges.py` y `test_admin_bigquery.py`: la cobertura recalcula el umbral y guarda `model_version`; más de 5 puntos sin `CONFIRMAR` da 422; grupo incompleto, 422; base vieja, 409; `set_by_hash` y `reason` siempre presentes y solo se escribe en la tabla de la política; las tasas propuestas coinciden con un cálculo a mano; los criterios del oro excluyen `no_evaluable` y la segunda ronda; analista, lector y revisor reciben 403 en todas las rutas. `api_backend` queda en 96 % de cobertura (mínimo del CI: 85 %); `ruff`, `pyrefly` y `bandit` en verde.
* **Portal (2026-10-26):** `/admin` con las cuatro pestañas, `policyHelp.ts` con la ayuda de cada parámetro, el gráfico de la curva con el punto vigente y el propuesto, la tabla con los minutos de la curva y los medidos, el formulario agrupado, las tasas por serie con la referencia dorada, el historial con comparación y el oro con su aviso de `GOLD_VERSION`. 15 pruebas nuevas (`npm test`: 154; `check`, `tsc` y `build` en verde, incluido `axe`). Revisado en local con datos de muestra.

* **Tasas contra `drift-rates` (2026-10-26, dev, solo lectura):** el servicio de administración, con los umbrales vigentes de cada banco, y `python -m ml_inference drift-rates` dan los mismos meses y alertas en las 35 series por banco (0 diferencias; ninguna fuera de tolerancia). La comparación destapó que `next_drift_version` esperaba el banco en mayúscula y en dev va en minúscula; se corrigió y se probó con `drift_policy_v2_nubank`.

## Pendiente

* Probar en dev con el autor: mezclar, desplegar y cambiar la cobertura (0.89 y de vuelta a 0.90, motivo "prueba de la pantalla de administración") para ver la `risk_policy_version` nueva en el siguiente delta. No se hizo: necesita la aprobación del autor.
* Que el autor fije o deje nulos con su motivo el tope semanal, la subida por deriva y la doble revisión.
