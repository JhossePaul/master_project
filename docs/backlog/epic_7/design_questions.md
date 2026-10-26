# Cuestionario de diseño del portal

> **Estado (2026-10-25):** abierto. Son las preguntas que conviene responder antes de construir para no detener el desarrollo del frontal. Cada una trae su recomendación: si una pregunta que no es "antes de 2" llega sin respuesta a su paso, la sesión de ejecución aplica la recomendación y lo anota. **Las marcadas "antes de 2" se responden antes del paso 2** (portal base), porque fijan *tokens* y estructura que después cuesta cambiar.
>
> Para responder, escribe en "Respuesta" la opción (o tu variante) y la fecha.

## Ya decidido (2026-10-25)

| Tema | Decisión |
| :--- | :--- |
| Marca | Producto Posgrados: verde `#00685E` y dorado `#BA9357`, con negro, blanco y grises cálidos; sin el azul de Preparatoria ni el vino de Licenciatura en la marca ([guía visual](../../design/visual_guide.md)) |
| Tipografía institucional | Panamericana y Seravek no se adoptan; se usa una sustituta libre y sobria (ver `T-01`) |
| Bibliotecas | D3 para gráficas, dygraphs para series largas, MathJax para fórmulas y Mermaid para diagramas; el resto del stack lo eligió la planificación ([stack](../../design/frontend_stack.md)) |
| Cuentas | Entran cuentas de `up.edu.mx` y `bbva.com` (las dos con Google Workspace), además de la del autor |
| Tesis | Borrador redactado por la sesión y revisado por el autor; sin PDF; prioridad mínima, al final del backlog |

## Antes del paso 2

### B-02. Nombre del portal

Aparece en el encabezado, en el título de la pestaña y en el *hero* de la landing.

* **Opciones:** (a) "Observatorio de reseñas de apps bancarias"; (b) "Voz del cliente en apps bancarias"; (c) el nombre del proyecto, *App Store Label Noise & Incident Analyzer* (habla de incidentes, que quedaron fuera del alcance); (d) otro.
* **Recomendación:** (a), descriptivo y en español, sin prometer detección de incidentes.
* **Respuesta:**

### C-02. Color del sentimiento negativo

* **Opciones:** (a) ladrillo `#B23A2E`, distinto de los colores de producto; (b) el vino `#8A1538`, que es el de Licenciatura y era el de la especificación original de la explicación.
* **Recomendación:** (a), por la regla de no mezclar productos; el vino se lee además como marca.
* **Respuesta:**

### C-03. Colores de los bancos

Propuesta de la guía (sección 4.1): BBVA azul `#1F64B0`, AZTECA verde `#3E8E2F`, SANTANDER rojo `#D0261C`, NUBANK morado `#7B2FC9` y BANORTE negro `#2F2B28`, con etiquetas directas y trazos de respaldo por la confusión rojo-verde.

* **Opciones:** (a) aprobar; (b) ajustar algún color.
* **Recomendación:** (a).
* **Respuesta:**

### C-04. Modo oscuro

* **Opciones:** (a) solo modo claro en esta versión; (b) claro y oscuro.
* **Recomendación:** (a). El modo oscuro duplica la revisión de contraste de cada gráfica, y el portal se va a proyectar.
* **Respuesta:**

### T-01. Tipografías

* **Opciones:**
  * (a) **Source Serif 4** (títulos y tesis) + **Source Sans 3** (interfaz) + Source Code Pro: misma superfamilia, serif de transición y sans humanista como Panamericana y Seravek;
  * (b) Literata + Inter: más contemporánea, Inter es más neutra que humanista;
  * (c) EB Garamond + Fira Sans: más clásica y académica, Garamond pierde legibilidad en tamaños chicos de pantalla;
  * (d) IBM Plex Serif + Plex Sans: más técnica.
* **Recomendación:** (a). Si quieres verlas antes de decidir, se puede armar una página de muestra con la paleta y las cuatro opciones.
* **Respuesta:**

### L-01. Navegación

* **Opciones:** (a) menú lateral plegable, agrupado (Consultar, Investigar, Revisar, Operar, Configurar); (b) menú superior.
* **Recomendación:** (a): hay 9 secciones, y algunas con subsecciones.
* **Respuesta:**

### L-02. Periodo por defecto de los filtros globales

* **Opciones:** (a) últimos 90 días; (b) últimos 30 días; (c) últimos 12 meses; (d) último mes cerrado.
* **Recomendación:** (a): muestra la tendencia reciente sin cargar consultas largas.
* **Respuesta:**

### L-03. Bancos por defecto

* **Opciones:** (a) los cinco; (b) solo BBVA.
* **Recomendación:** (a): la comparación es parte del valor del portal.
* **Respuesta:**

### L-04. Pantallas chicas

* **Opciones:** (a) escritorio primero; en pantallas de menos de 1 024 px, la landing, el reporte y las tarjetas del cockpit se leen en una columna, y el HITL, el Explorador y la administración piden una pantalla más ancha; (b) todo el portal usable en el teléfono; (c) solo escritorio.
* **Recomendación:** (a).
* **Respuesta:**

### L-06. Formato de números

* **Opciones:** (a) el de México: punto decimal y coma de miles (`2,654,106` y `12.3 %`), como el resto del repo; (b) coma decimal (`12,3 %`), convención de parte de la academia hispana.
* **Recomendación:** (a).
* **Respuesta:**

## Marca e identidad

### B-01. Logotipo

* **Pregunta:** ¿tienes la marca de producto de Posgrados en SVG (versión en verde y en blanco)? En tus descargas hay archivos `.ai` del escudo y del emblema, pero la guía reserva el escudo para documentos oficiales.
* **Recomendación:** pedir el SVG oficial a Comunicación de la UP; mientras tanto, el encabezado lleva solo el nombre del portal en la tipografía de títulos.
* **Bloquea:** nada (hay un sustituto).
* **Respuesta:**

### B-03. Tahalí y textura de roble

* **Opciones:** (a) tahalí como franja diagonal sencilla en dorado en la landing y la portada de capítulos, y roble solo con el archivo oficial; (b) ninguno; (c) los dos, redibujados.
* **Recomendación:** (a). No se redibuja el roble.
* **Respuesta:**

### B-04. Créditos

* **Pregunta:** el nombre exacto del programa de posgrado, el nombre del asesor y cómo quieres aparecer como autor, para el pie del portal y la portada de la tesis.
* **Bloquea:** el pie (con texto provisional) y la tesis.
* **Respuesta:**

### B-05. Ícono de la pestaña (*favicon*)

* **Opciones:** (a) un monograma con la inicial del nombre del portal en verde; (b) el escudo.
* **Recomendación:** (a); el escudo es para usos oficiales.
* **Respuesta:**

### B-06. Logotipo de BBVA

* **Opciones:** (a) no aparece en el portal; el patrocinio se declara en texto en la introducción de la tesis; (b) aparece en el pie como patrocinador.
* **Recomendación:** (a): mezclaría marcas y contradice la anonimización.
* **Respuesta:**

## Color

### C-05. Colores de estado

`ok` en verde, aviso en ámbar `#8A5A00`, reentrenar, rechazado o error en rojo `#A12C2C`, información en gris. Siempre con ícono y texto.

* **Recomendación:** aprobar.
* **Respuesta:**

## Tipografía

### T-02. Cuerpo de la tesis

* **Opciones:** (a) serif (Source Serif 4, 18 px); (b) sans, como la interfaz.
* **Recomendación:** (a), por lectura larga y por el tono académico.
* **Bloquea:** paso 12.
* **Respuesta:**

### T-03. Fuente de las fórmulas

* **Opciones:** (a) New Computer Modern, la de MathJax por defecto (aspecto LaTeX); (b) STIX Two (aspecto Times, más cercana a una serif de texto).
* **Recomendación:** (a).
* **Bloquea:** paso 12.
* **Respuesta:**

## Estructura y formatos

### L-05. Días de las series

* **Opciones:** (a) día UTC, como lo calculan las vistas y los experimentos (una reseña de las 20:00 de CDMX cuenta en el día siguiente); (b) día de la Ciudad de México, lo que exige cambiar `daily_topic_labels` y las consultas.
* **Recomendación:** (a), con el eje rotulado "día (UTC)".
* **Bloquea:** paso 3.
* **Respuesta:**

### L-08. Modo presentación

* **Opciones:** (a) ninguno: se usa el zoom del navegador al proyectar; (b) un conmutador que agranda la tipografía y oculta la navegación.
* **Recomendación:** (a).
* **Respuesta:**

## Cockpit (paso 3)

### K-01. Forma visual de los temas del día

* **Opciones:** (a) panel lateral al elegir un día, con las 5 familias y los 5 tópicos con su participación del día y la habitual; (b) *tooltip* al pasar el cursor; (c) tabla debajo de la serie.
* **Recomendación:** (a): un *tooltip* con 10 temas y dos cifras cada uno es ilegible.
* **Respuesta:**

### K-02. Suavizado de la serie diaria

* **Opciones:** (a) la serie cruda tenue con la media móvil de 7 días encima; (b) solo la cruda; (c) solo semanal.
* **Recomendación:** (a): los días con pocas reseñas hacen ruido.
* **Respuesta:**

### K-03. Métrica por defecto de la serie

* **Opciones:** (a) proporción de negativas; (b) *gap* crudo; (c) quejas con 4–5★.
* **Recomendación:** (a).
* **Respuesta:**

### K-05. Qué hacen los filtros de familia y sentimiento en el cockpit

* **Opciones:** (a) resaltan en las gráficas de familias y tópicos y viajan al Explorador, sin recalcular las series de sentimiento; (b) recalculan todo el cockpit para esa familia.
* **Recomendación:** (a): las familias solo existen para las negativas, así que recalcular el sentimiento por familia no tiene sentido.
* **Respuesta:**

### K-07. Comparación de las tarjetas

* **Opciones:** (a) contra el mismo mes del año anterior; (b) contra el mes anterior.
* **Recomendación:** (a), por la estacionalidad que mostró el EDA temporal.
* **Respuesta:**

### K-08. Tarjetas

* **Pregunta:** ¿las tarjetas por banco llevan *gap* en estrellas, proporción de negativas, quejas con 4–5★ y alertas abiertas, como dice la épica?
* **Recomendación:** sí.
* **Respuesta:**

## Explorador (paso 6)

### X-02. Estrellas y banco en la ficha

* **Opciones:** (a) sí se muestran (el Explorador no es revisión, no hay anclaje que cuidar); (b) no.
* **Recomendación:** (a).
* **Respuesta:**

### X-04. Cómo se muestra la cercanía de un resultado de búsqueda

* **Opciones:** (a) similitud en porcentaje (`1 − distancia`); (b) la distancia coseno.
* **Recomendación:** (a), más legible; la distancia va en "Ver datos".
* **Respuesta:**

### X-05. Ventana de búsqueda

* **Opciones:** (a) 12 meses como máximo, por costo; (b) permitir ampliar a 24 o más.
* **Recomendación:** (a): con 12 meses caben ~2 000 búsquedas al mes en el free tier.
* **Respuesta:**

## HITL (pasos 4 y 9)

### H-02. ¿Se muestra el motivo del caso?

* **Opciones:** (a) no: el revisor no sabe si un caso es de la muestra aleatoria o de baja confianza, como en el prototipo; (b) sí.
* **Recomendación:** (a).
* **Respuesta:**

### H-03. Propuesta en el modo asistido

* **Opciones:** (a) preseleccionada, para aceptarla o cambiarla (como el prototipo); (b) visible pero sin preseleccionar.
* **Recomendación:** (a): el modo asistido existe para ser rápido; el ciego cubre lo que mide al modelo.
* **Respuesta:**

### H-04. Meta por sesión

* **Opciones:** (a) sin meta, con un contador de la sesión; (b) lotes de 20 con pausa sugerida.
* **Recomendación:** (a).
* **Respuesta:**

### H-05. Ticket

* **Opciones:** (a) texto libre de hasta 100 caracteres; (b) URL validada de un sistema concreto.
* **Recomendación:** (a): no hay un sistema de tickets definido.
* **Respuesta:**

### H-06. Tiempos de la cola

15 minutos de bloqueo de un caso abierto y 7 días sin volver a ofrecer un caso saltado al mismo revisor.

* **Recomendación:** aprobar.
* **Respuesta:**

### H-07. Elogio en la cola de aspectos

* **Opciones:** (a) no se pregunta ni se guarda: `hitl_reviews` no tiene columna y nada lo consume; (b) se agrega la columna (cambio de contrato).
* **Recomendación:** (a).
* **Respuesta:**

### H-08. Acuerdo del revisor

* **Opciones:** (a) no se le muestra en esta versión; (b) se le muestra su tasa de corrección y su acuerdo con otros.
* **Recomendación:** (a).
* **Respuesta:**

## Administración (paso 5)

### A-01. Cambio grande

* **Opciones:** (a) pide escribir `CONFIRMAR` si la cobertura cambia más de 5 puntos o un umbral de deriva cambia 1 o más unidades de z; (b) solo la cobertura.
* **Recomendación:** (a).
* **Respuesta:**

### A-02. Segundo visto bueno

* **Opciones:** (a) no en esta versión (hay un solo administrador); (b) un segundo administrador aprueba cada cambio.
* **Recomendación:** (a).
* **Respuesta:**

### A-03. Parámetros sin evidencia

Tope semanal, subida por deriva y doble revisión están nulos desde la primera política.

* **Opciones:** (a) se quedan nulos hasta tener un trimestre de alertas y revisiones; (b) activar la doble revisión con 30 casos por trimestre para medir el acuerdo entre personas; (c) fijar los tres ahora.
* **Recomendación:** (a), y decidir (b) cuando haya un segundo revisor.
* **Respuesta:**

## MLOps (paso 8)

### M-01. Quién lanza acciones sobre el modelo

* **Opciones:** (a) solo administrador; (b) también analista.
* **Recomendación:** (a).
* **Respuesta:**

### M-02. Re-ajuste de tópicos a mano con el modo programado

* **Opciones:** (a) el botón solo funciona con `topic_refit_trigger = manual`, como dice la épica; (b) funciona siempre (con `--force`).
* **Recomendación:** (a).
* **Respuesta:**

### M-03. Confirmación del reentrenamiento

* **Opciones:** (a) pedir escribir `REENTRENAR`, por el costo (~$1, tope $2) y porque el texto sale a Kaggle; (b) solo el motivo.
* **Recomendación:** (a).
* **Respuesta:**

## Alertas (paso 7)

### R-01. Transiciones

`open` → `confirmed` o `dismissed`; `confirmed` → `dismissed`; reabrir desde cualquiera. Todas con nota.

* **Recomendación:** aprobar.
* **Respuesta:**

### R-02. Quién atiende las alertas

* **Opciones:** (a) analista; (b) solo administrador.
* **Recomendación:** (a).
* **Respuesta:**

## Seguridad y usuarios

### S-01. Personas y roles

* **Pregunta:** la lista de correos con sus roles (lector, analista, revisor de sentimiento, revisor de aspectos o de tópicos, administrador). Va cifrada en Pulumi, nunca en claro en git.
* **Bloquea:** el despliegue del paso 1.
* **Respuesta:**

### S-02. ¿El administrador revisa casos HITL sin ser revisor?

* **Opciones:** (a) no: el rol de revisor se da explícitamente (puedes tener los dos); (b) sí.
* **Recomendación:** (a).
* **Respuesta:**

### S-03. Si el Workspace de BBVA o de la UP bloquea la entrada

* **Opciones:** (a) esas personas entran con una cuenta Gmail; (b) se pide la excepción al administrador de su Workspace; (c) esas personas no entran.
* **Recomendación:** (b) y, mientras tanto, (a).
* **Respuesta:**

### S-04. Si IAP directo en Cloud Run no acepta cuentas externas

* **Opciones:** (a) balanceador HTTPS con IAP y un dominio propio (el dominio cuesta del orden de US$12 al año y la regla del balanceador del orden de US$18 al mes; confirmar precios vigentes); (b) mover el proyecto a una organización que lo permita; (c) solo cuentas de la organización.
* **Recomendación:** decidir con el resultado de la prueba de acceso del paso 0.
* **Respuesta:**

### S-05. Alcance de los seudónimos

* **Opciones:** (a) seudónimos en etiquetas, gráficas y tablas de todo el portal; el texto de las reseñas queda tal cual, aunque nombre a un banco (la sanitización no quita nombres de bancos); (b) además, enmascarar los nombres de bancos en el texto.
* **Recomendación:** (a). La anonimización es de presentación: con el color representativo de cada banco, quien conoce el mercado los reconoce.
* **Respuesta:**

## Datos y contenido

### D-01. Glosario

* **Opciones:** (a) lo redacta la sesión de ejecución desde los reportes y lo revisas; (b) lo escribes tú.
* **Recomendación:** (a).
* **Respuesta:**

### D-02. Ayudas de los parámetros

* **Opciones:** (a) las redacta la sesión desde la tabla del paso 5 y lo revisas; (b) las escribes tú.
* **Recomendación:** (a).
* **Respuesta:**

### D-03. Seudónimos de los bancos

* **Opciones:** (a) por su color: Banco Índigo (BBVA), Banco Jade (AZTECA), Banco Carmín (SANTANDER), Banco Violeta (NUBANK) y Banco Ónix (BANORTE); (b) letras: Banco A a Banco E; (c) otros.
* **Recomendación:** (a): se recuerdan mejor y van con el color que ya se decidió. Mientras no haya respuesta, el portal usa (b).
* **Respuesta:**

## Tesis (paso 12, prioridad mínima)

### P-01. Aporte

* **Pregunta:** el aporte reformulado (2 o 3 frases) y las preguntas de investigación, ya sin la detección de incidentes.
* **Respuesta:**

### P-02. Patrocinio y anonimización

* **Opciones:** (a) la introducción nombra a BBVA como patrocinador y se acepta que se puede inferir cuál es su seudónimo (por el color azul); (b) dice "una de las instituciones analizadas patrocinó la maestría", sin nombrarla.
* **Recomendación:** (a), porque ya decidiste declararlo; (b) si la anonimización debe sostenerse ante el jurado.
* **Respuesta:**

### P-03. Estilo de citas

* **Opciones:** (a) APA 7; (b) IEEE; (c) Chicago autor-fecha.
* **Recomendación:** (a), salvo que el programa pida otro.
* **Respuesta:**

### P-04. Extensión

* **Pregunta:** ¿el programa fija una extensión o un formato? Sin requisito, se apunta a unas 25 000–35 000 palabras en total.
* **Respuesta:**

### P-05. Resumen

* **Opciones:** (a) resumen en español y *abstract* en inglés; (b) solo en español.
* **Recomendación:** (a).
* **Respuesta:**
