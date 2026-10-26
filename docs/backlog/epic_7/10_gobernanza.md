# Paso 10. Feature 7.11: Data Card, Model Card y FMEA

* **Estado (2026-10-25):** Pendiente.
* **Nivel:** imprescindible (los documentos); la página del portal, deseable.
* **Depende de:** pasos 1 a 8, porque los documentos describen lo que quedó construido. Como solo toca `docs/governance/`, puede correr en una sesión paralela cuando los pasos 1 a 8 estén terminados.
* **Objetivo:** que los tres documentos de `docs/governance/` reflejen lo decidido en EPIC-5, lo desplegado en EPIC-6 y el portal de EPIC-7, sin texto de la especificación anterior (Delora como propuesta, entropía 0.65, 768 dimensiones, paridad dialectal sintética, "priorizar incidencias").

**Lenguaje:** los documentos están fuera de `docs/backlog/`, así que describen con palabras y no citan códigos del backlog. Los ids de fila de la FMEA (`F-01`…) son propios de ese documento y se pueden usar en él; en la Data Card y la Model Card, una fila se nombra por su tema y se enlaza.

## 1. Model Card (`docs/governance/model_card.md`, hoy v0.1 del 2026-10-22)

* **Versión 0.2.** Mantener lo que ya está al día: RoBERTuito ajustado con la plata de Gemini, calibrado con temperatura (1.68), métricas en el oro *test* y validación HITL de los temas por día.
* **Agregar lo de producción:**
  * registro en Vertex Model Registry con alias para promover y regresar;
  * carga de los pesos fp16 en fp32 en el delta de 1 vCPU;
  * reentrenamiento con la receta de los experimentos desde el modelo base (no desde el vigente), una semilla, con la plata reciente de Gemini (tope de $2) y las revisiones HITL que no son de la muestra de monitoreo;
  * temperatura y curva de cobertura y riesgo de cada candidato contra el oro *dev*;
  * *re-scoring* del histórico antes de promover;
  * regla de promoción (diferencias pareadas de κ y macro-F1 con *bootstrap*; si alguna queda significativamente peor, solo con promoción forzada y motivo);
  * monitoreo trimestral del κ con piso de 0.89 y avisos de corrección y de acuerdo con Gemini;
  * disparo manual por defecto.
* **Uso en el portal:** revisión humana por cobertura (90 % por defecto), casos de la muestra a ciegas, la explicación por oclusión (con dirección) solo en el Explorador y nunca en la revisión, y el *gap* en estrellas con PPI.
* **Límites:** revisar los 12. El límite sobre variantes regionales se redacta como "no se evaluó el desempeño por variante regional del español", sin mencionar el corpus sintético de la especificación anterior. Agregar: la explicación dice qué palabras movieron la predicción, no la causa técnica del fallo.
* **Citas:** por ahora, los reportes de `docs/analytics/`; el paso 12 cambia los enlaces por los capítulos de la tesis.

## 2. Data Card (`docs/governance/data_card.md`, hoy borrador 0.3)

* **Versión 0.4** (y corregir en `docs/backlog/epic_5.md` la mención "v0.2").
* **§2:** las familias con la taxonomía `v2.1` (11 familias y las marcas `u` y `s`), no la v1.
* **§4:** unificar la tasa de nombres con la FMEA y la Model Card (1 300 reseñas y ~0.4 %).
* **§5:** quitar "priorizar incidencias"; el uso es describir y priorizar por volumen de negativas por familia, sin detección de incidentes.
* **§8:** retirar los pendientes ya resueltos (una palabra, conteos `v1`, guía de aspectos, tópicos, backfill).
* **Agregar:**
  * las cifras de la carga del histórico (filas de predicciones, textos únicos, familias, embeddings) y su corte;
  * las tablas de producción y su regla de solo inserción;
  * quién accede a qué en el portal: los cuatro roles, IAP, las cuentas de `up.edu.mx`, `bbva.com` y Gmail, y que el lector nunca recibe texto;
  * la sanitización con Cloud DLP de los comentarios y las notas del portal;
  * que las consultas de búsqueda no se guardan;
  * los registros de auditoría de acceso a datos de BigQuery.

## 3. FMEA (`docs/governance/ethical_fmea_matrix.md`)

* **Introducción y sección "Pendiente":** reescribir. Ya no hay filas por añadir de EPIC-5 a EPIC-7: se cierran aquí.
* **F-15** (el Explorador amplía quién lee reseñas): calificar S, O, D y RPN con los controles del paso 6 (rol analista, sin descarga de texto, consultas no registradas, auditoría). Partida: RPN 50.
* **F-19** (leer un pico de temas como un incidente): calificar con los controles del paso 3 (aviso en el panel del día y en la pestaña por versión, sin umbrales, participación habitual al lado). Partida: RPN 84.
* **F-17 y F-18:** quitar "incidente" donde ya no aplica.
* ***Label Noise Bias*:** el título deja de decir "propuesta, no validada": está confirmado con el oro *test* (RPN 60).
* **Filas nuevas del portal:**

| Id | Modo de falla | Control |
| :--- | :--- | :--- |
| F-22 | El comentario del revisor o la nota de una alerta trae datos personales | Sanitización con Cloud DLP antes de guardar, con *fail-closed*; aviso en pantalla |
| F-23 | Una cuenta externa (`bbva.com`, `up.edu.mx`) entra con más permisos de los que necesita, o sigue entrando después de dejar el proyecto | IAP por correo, mapa de roles cifrado y versionado en Pulumi, revisión del mapa antes de la presentación y al cerrar |
| F-24 | La explicación por palabras se lee como la causa del fallo | Texto fijo bajo la explicación; solo en el Explorador; sin ella en la revisión |
| F-25 | Una consulta de búsqueda semántica trae datos personales | No se guarda ni se registra; viaja solo dentro de GCP |

  Calificar cada una (S, O, D, RPN) con el criterio de la matriz.

## 4. Página del portal (deseable)

`/gobernanza`, rol lector: los tres documentos renderizados al construir (`import … from "../../../../docs/governance/model_card.md?raw"` y `react-markdown` con `remark-gfm`), con un índice lateral, los límites declarados arriba (la licencia no comercial de los modelos de `pysentimiento`, la tasa de nombres que la sanitización no detecta, el corpus en un dataset privado de Kaggle) y la fecha y el commit. El `.dockerignore` suma `docs/governance/`.

## Terminado cuando

* [ ] Los tres documentos reflejan lo decidido y lo construido, y `grep -i -E "delora|0\.65|768|paridad dialectal|incidencias"` en `docs/governance/{data_card,model_card,ethical_fmea_matrix}.md` solo encuentra menciones históricas explícitas (Delora como resultado negativo).
* [ ] F-15, F-19 y F-22 a F-25 están calificadas.
* [ ] (Deseable) `/gobernanza` muestra los tres documentos.

## Avance

_(Se llena al ejecutar.)_
