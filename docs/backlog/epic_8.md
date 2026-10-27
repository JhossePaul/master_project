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
| 10 | **Días en hora de la Ciudad de México** en vez de UTC: `DATE(fecha, 'America/Mexico_City')` en `daily_topic_labels`, en las series diarias de la API y en todas las vistas y tablas que agrupan por día o por mes (`kpi_estimates`, `drift_metrics`), con la validación de temas diarios repetida contra los experimentos | Una reseña de las 20:00 de CDMX cuenta en el día siguiente, y eso mueve reseñas entre días en las series y en el top 5 diario. Decisión del autor (2026-10-25): no le encanta UTC, pero cambiarlo exige tocar todas las vistas que se consumen; mientras tanto el portal rotula el eje "día (UTC)" | Cuestionario de diseño de EPIC-7 (L-05) |
| 11 | **Portal amigable en el teléfono** (ver la sección "Portal móvil") | La decisión `L-04` fijó escritorio primero: por debajo de 1 024 px solo la landing y las tarjetas se leen en una columna, y el HITL, el Explorador y la administración piden una pantalla más ancha | Revisión de la landing en dev (2026-10-26) |
| 12 | **HITL sin espera** (la precarga del paso 4 de EPIC-7 corrigió una carrera con los guardados en camino el 2026-10-26; lo de fondo sigue abierto): sacar de BigQuery el estado de la cola y sus escrituras (ver la sección "HITL sin espera") | Con la memoria del paso 4 de EPIC-7 un caso sigue costando 2 a 4 s de escrituras en BigQuery, y buscar un texto en el TDS escanea 150 a 280 MB. Una revisión fluida pide menos de 300 ms | Revisión del autor del HITL en dev (2026-10-26) |
| 13 | **Observar la primera alerta de deriva real de dev** (sin fecha: depende de que una serie pase su umbral al cerrar un mes) y comprobar que aparece en `/alertas` y en la landing, que llega el correo y el mensaje de Pub/Sub, y que su confirmación o descarte queda en `drift_alert_events` | La API y el portal de alertas se probaron con alertas sintéticas y con BigQuery real en un dataset desechable; lo único que no se ejerció es la emisión por el monitor (correo y Pub/Sub). No bloquea nada: si llega una alerta, se revisa; si no llega, no hay nada que corregir | Paso 7 de EPIC-7 (2026-10-26) |
| 14 | **Cerrar MLOps en dev** (paso 8 de EPIC-7): aplicar la infraestructura (permisos de la API sobre los cuatro Jobs y sobre `ml_artifacts/`), desplegar la imagen, comprobar que el registro muestra `robertuito_sentiment_v1` promovido con sus métricas y, **con aprobación del autor**, lanzar "Re-ajustar tópicos" desde el botón (costo $0) y ver su corrida en `inference_runs` con quién y por qué | La API, `ml-inference` y el portal se probaron con datos de muestra, con lectores falsos y en local; lo que no se ejerció es el Job real lanzado por la cuenta de la API y las lecturas contra `model_versions` y `model_quality` de dev. El botón de re-ajuste de tópicos solo se habilita con `topic_refit_trigger = manual` | Paso 8 de EPIC-7 (2026-10-26) |

---

## Portal móvil

* **Estado (2026-10-26):** pendiente, sin fecha. Decisión del autor: hacer el portal amigable en el teléfono después de cerrar EPIC-7; hoy se diseña para escritorio y para proyectar (`L-04`, opción a).
* **Alcance propuesto:**
  * **Navegación:** en pantallas de menos de 768 px, el menú lateral pasa a un cajón que se abre desde el encabezado; la barra de filtros globales se pliega en un botón "Filtros".
  * **Landing, Reporte y Cockpit:** una columna; las gráficas ocupan el ancho completo, con etiquetas legibles y zoom táctil en las series de dygraphs.
  * **Tablas** (Explorador, Alertas, MLOps): filas como tarjetas o desplazamiento horizontal con la primera columna fija.
  * **HITL:** una revisión por pantalla con botones grandes y atajos táctiles; el modo ciego y el asistido se conservan.
  * **Administración:** puede quedar solo en escritorio, con el aviso actual, porque cambiar políticas desde el teléfono no es un caso de uso.
* **Criterios de terminado:**
  * `axe` sin violaciones a 375 px en todas las secciones que se habiliten;
  * objetivos táctiles de al menos 44 px;
  * sin desplazamiento horizontal de la página;
  * una prueba por sección con la ventana a 375 × 812;
  * la guía visual (sección 8.3) y el cuestionario (`L-04`) actualizados con lo que se decida.
* **Antes de empezar:** revisar con el autor qué secciones sí valen la pena en el teléfono; esta lista es una propuesta.

---

## HITL sin espera

* **Estado (2026-10-26):** pendiente, sin fecha. Pedido del autor: que la revisión sea fluida (*seamless*) y no espere a BigQuery entre un caso y el siguiente.
* **Qué pasa hoy** (medido en dev, antes y después de las mejoras del paso 4 de EPIC-7):
  * cada escritura es un `INSERT` de BigQuery (DML): 1 a 2 s, y un caso necesita tres (`in_review`, la revisión y `submitted`);
  * tomar un caso relee su estado en BigQuery para confirmar que nadie más lo tomó (1.3 s): BigQuery no tiene transacciones, así que la exclusión se comprueba escribiendo y releyendo;
  * el TDS está agrupado por banco y versión de la app, no por `id_resena`: buscar un texto escanea 150 a 280 MB y tarda 4 a 5 s; el paso 4 los trae en lotes de 20 y los guarda en memoria, pero cada lote cuesta lo mismo;
  * la memoria del proceso (cola 15 s, textos 15 min) ayuda con una sola instancia; con varias de Cloud Run cada una tiene la suya.
* **¿Pub/Sub?** Sirve para una parte y no para el corazón del problema:
  * **No sirve para repartir los casos.** Una suscripción de Pub/Sub entrega cada mensaje a un consumidor y lo reentrega si no hay `ack`, que se parece al bloqueo de 15 minutos, pero: no hay prioridad (la cola se ordena por `priority` y `created_at`), el plazo de `ack` máximo es de 10 minutos, no existe "no se lo ofrezcas a este revisor durante 7 días" ni la segunda ronda para otro revisor, y el portal necesita *pedir* un caso y recibirlo en el momento, no escuchar.
  * **Sí sirve para las escrituras de auditoría.** Publicar el evento o la revisión toma milisegundos, y una suscripción **BigQuery** (sin código) lo aterriza en `hitl_events` y `hitl_reviews`; las tablas siguen siendo solo inserción y la vista `hitl_queue` no cambia. El costo: la lectura en BigQuery llega con unos segundos de retraso, así que no puede ser la fuente del bloqueo.
* **Propuesta (a validar con el autor):**
  1. **Firestore (modo nativo) como estado vivo de la cola:** un documento por caso abierto con su bloqueo (`actor_hash`, `locked_until`), quienes lo saltaron y los revisores de cada ronda. Tomar un caso es una transacción (consulta por prioridad y escritura), con latencia de milisegundos y exclusión real entre instancias. El delta y el monitor siguen escribiendo `hitl_items` en BigQuery, y un paso al crear los casos (o un sincronizador) los copia a Firestore.
  2. **Escrituras a BigQuery sin DML:** la API de escritura por *streaming* (`insert_rows_json` o Storage Write API), o Pub/Sub con suscripción a BigQuery, en vez de `INSERT … WHERE NOT EXISTS`; la idempotencia pasa a la clave del mensaje (`insertId`) o al documento de Firestore.
  3. **Texto del caso con el caso:** guardar el texto sanitizado en el documento de Firestore al crear el caso (el delta y el monitor ya lo tienen a la mano) y quitar la lectura del TDS por `id_resena`; la edición de una reseña se detectaría al sincronizar. Tiene costo ético: es texto de reseñas en otro almacén, una fila nueva en la [matriz FMEA](../governance/ethical_fmea_matrix.md) y la misma CMEK.
  4. **Precarga en el portal:** pedir el caso siguiente mientras se revisa el actual (con su propio bloqueo), para que "Guardar y seguir" sea inmediato.
* **Alternativa más barata:** conservar solo BigQuery y agregar Memorystore (Redis) para el bloqueo y la cola. Cuesta una instancia siempre encendida y un conector de red sin servidor (VPC); Firestore no tiene instancia que mantener.
* **Criterios de terminado:**
  * del clic en "Guardar y seguir" al caso siguiente en pantalla, p95 menor de 500 ms en dev;
  * dos instancias de la API nunca entregan el mismo caso al mismo tiempo (prueba de concurrencia);
  * `hitl_events` y `hitl_reviews` conservan el mismo esquema y siguen siendo solo inserción, sin filas duplicadas ante reintentos;
  * el κ del monitor y la tasa de corrección leen lo mismo que antes;
  * el costo mensual estimado (Firestore, Pub/Sub y BigQuery) anotado.
* **Antes de empezar:** decidir con el autor Firestore o Redis y si el texto viaja con el caso (punto 3); medir primero cuánto del tiempo restante es BigQuery y cuánto la red.
