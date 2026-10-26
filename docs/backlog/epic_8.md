# EPIC-8: Pendientes técnicos

* **Estado (2026-10-25):** abierta como lista. Reúne deudas que no bloquean cerrar EPIC-6 ni empezar EPIC-7; se atienden al final del proyecto o cuando una de ellas empiece a costar.
* **Regla:** una deuda entra aquí con su motivo y su efecto; si se decide no atenderla, se tacha con la fecha y el criterio.

---

## Pendientes

| # | Pendiente | Por qué importa | Origen |
| :-: | :--- | :--- | :--- |
| 1 | **Respaldar en GCS los insumos locales de EPIC-5** (`experiments/analytics/data/`: backfill del 2026-10-22, pesos, curaduría de tópicos, colas del oro, `daily_topics_v0`) y que `load-local`, `upload-gold-ids` y la validación de temas diarios lean de GCS | La carga depende de la máquina del autor y los archivos no tienen respaldo en la nube. Decisión del autor (2026-10-25): fue un error de diseño; se corrige aquí, sin detener el cierre de EPIC-6 | EPIC-6, 6.6 |
| 2 | **Borrar las copias locales** que usó la carga (FMEA F-11), después del pendiente 1 | Mantener texto de reseñas en una laptop es el riesgo que F-11 acota | EPIC-6, antes paso 13 de los pendientes en dev |
| 3 | **Precio de Gemini en la infraestructura:** pasar `GEMINI_PRICE_IN` y `GEMINI_PRICE_OUT` como configuración del stack | Hoy el precio por defecto vive en `ml-inference` y se cambia con variables de entorno a mano; el introductorio vence el 2026-12-31 | Auditoría de EPIC-6 (2026-10-25) |
| 4 | **Plata y oro anclados al archivo de EPIC-5** (`archive/epic5/labels/silver_v0/`, `gold_epic5_v1`) | Cada reentrenamiento parte de la misma plata y del mismo oro *dev*; un oro nuevo (7.10) exige cambiar `GOLD_VERSION` y subir sus ids de exclusión | Auditoría de EPIC-6 |
| 5 | **`topics-refit` con la tabla de versiones vacía** propone `topics_v1`, el mismo nombre que carga `load-local` | Solo pasa si el re-ajuste corre antes de la carga; el orden de 6.6 lo evita | Auditoría de EPIC-6 |
| 6 | **Avisos de los caminos que hoy solo dejan un log**: sin vocabulario, sin cliente de Gemini o sin modelo de tópicos, el delta y el monitor siguen | Un hueco de datos puede pasar sin que nadie lo vea | Auditoría de EPIC-6 |
| 7 | **Un solo modelo y bancos fijos** (`robertuito-sentiment` en Vertex, `BankKey`) | Agregar otro modelo o banco exige cambiar código | Auditoría de EPIC-6 |
| 8 | **El monitor no escribe en `inference_runs`** | MLOps (7.9) infiere su última corrida de `kpi_estimates` y no tiene su duración, su memoria ni su costo | Planificación de EPIC-7 (2026-10-25) |
| 9 | **La ingesta no registra costo** (`ingestion_runs_log_v2`) | AIOps (7.9) muestra la duración derivada y el costo como "sin dato"; medirlo exigiría la exportación de Cloud Billing | Planificación de EPIC-7 (2026-10-25) |
