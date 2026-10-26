# Paso 12. Feature 7.4: Reporte de la tesis

* **Estado (2026-10-25):** Pendiente. **Prioridad mínima** (decisión del autor, 2026-10-25): va después de cerrar el portal funcional, para que los tokens se gasten primero en funcionalidad. Es lo primero que se recorta si el tiempo no alcanza.
* **Nivel:** imprescindible en el mapa original del portal; por decisión del autor, último en el orden.
* **Depende de:** paso 11 y los insumos del autor de la sección 1.
* **Objetivo:** la tesis redactada, publicada como sección del portal con un submenú por capítulo. Cuenta una historia en lenguaje humano y académico. **No es una copia de los reportes de `docs/analytics/`:** esos reportes son la evidencia de la experimentación, se conservan como histórico y la tesis los usa como fuente de cifras. Es una **foto versionada** (fecha y commit) que no cambia con la operación diaria.

## Decisiones del autor

**Del 2026-10-24:**

* **Estructura:**
  1. Introducción.
  2. Antecedentes.
  3. Análisis, técnico en el sentido académico:
     1. metodología;
     2. resultados, negativos y positivos (Delora descartado, la detección de incidentes que no se alcanzó, la inestabilidad de los tópicos entre semillas, junto con los que funcionaron);
     3. discusión;
     4. conclusiones.
  4. Despliegue y operativización:
     1. sistema de extracción y sanitización (EPIC-2 a EPIC-4);
     2. sistema de MLOps y AIOps (EPIC-6 y EPIC-7).
  5. Referencias.
* **Aporte:** se reformula, porque el *Incident Analyzer* no se alcanzó. La formulación nueva la fija el autor antes de redactar la introducción.
* **Gráficas:** se generan de los JSON de métricas, nunca transcritas, con D3 (y dygraphs donde convenga, por ejemplo para series largas). Cada gráfica trae "cómo leerla" e intervalo cuando corresponde.
* **Idioma:** español, con los términos técnicos en inglés donde son los de uso común (*gold* y *silver labels*, *temperature scaling*, *coverage*, *drift*…). Un glosario fija cada término una vez.
* **Datos:** solo resultados analíticos (agregados, métricas, intervalos); nunca datos crudos ni texto de reseñas. Los ejemplos, sintéticos.
* **Bancos anonimizados:** seudónimo fijo por banco, conservando su color representativo (azul BBVA, verde Azteca, rojo Santander, morado Nu, negro Banorte), igual en todo el portal.
* **Contexto:** la maestría la patrocinó BBVA, que recibe los beneficios del trabajo. Se declara en la introducción.
* **Referencias:** las de [`references.md`](../../governance/references.md), que hay que completar (huecos en su sección 12). La tesis cita solo entradas verificadas.
* **Relación con otras features:** la Model Card y la Data Card citan la tesis; las ayudas de Administración pueden enlazar su capítulo.

**Del 2026-10-25:**

* **Redacción:** la sesión de ejecución redacta un borrador de cada capítulo a partir de los reportes y las métricas; el autor lo revisa y reescribe.
* **Sin PDF:** la tesis vive solo en el portal.
* **Prioridad mínima** (arriba).

## 1. Insumos del autor antes de redactar

| # | Insumo | Bloquea |
| :-: | :--- | :--- |
| 1 | El aporte reformulado (2 o 3 frases) y las preguntas de investigación | Introducción y conclusiones |
| 2 | El título de la tesis, el nombre del programa, el autor, el asesor y el año | Portada |
| 3 | Los seudónimos de los bancos (pregunta `D-03`) | Todas las gráficas |
| 4 | Cómo se declara el patrocinio de BBVA sin romper la anonimización (pregunta `P-02`) | Introducción |
| 5 | Estilo de citas (recomendado APA 7, pregunta `P-03`) | Referencias |
| 6 | Aprobar el índice detallado de cada capítulo (sección 4, paso 1) | Cada capítulo |

## 2. Dónde vive

* **Texto:** `docs/thesis/`, un archivo MDX por sección:

```
docs/thesis/
├── thesis.json                      # título, autor, asesor, programa, versión publicada, fecha
├── 00_portada.mdx
├── 01_introduccion.mdx
├── 02_antecedentes.mdx
├── 03_analisis/
│   ├── 01_metodologia.mdx
│   ├── 02_resultados.mdx
│   ├── 03_discusion.mdx
│   └── 04_conclusiones.mdx
├── 04_despliegue/
│   ├── 01_extraccion_y_sanitizacion.mdx
│   └── 02_mlops_y_aiops.mdx
├── 05_referencias.mdx               # generado de references.json
├── glosario.mdx
├── references.json                  # entradas verificadas: id, tipo, autores, año, título, fuente, doi/url, verified: true
└── data/                            # agregados exportados de BigQuery para la tesis (sección 3.2)
```

* **Versión:** publicar una versión es un tag de git `tesis-v<n>` y la actualización de `thesis.json`; el portal muestra "Versión 1 · 15 nov 2026 · commit abc1234". La operación diaria no la cambia: las gráficas leen archivos versionados, nunca la API.

## 3. Construcción

### 3.1 Canal de MDX (`web/hitl-portal/`)

* Dependencias: `@mdx-js/rollup`, `remark-gfm`, `remark-math`, `rehype-mathjax` (fórmulas a SVG al construir), `rehype-slug`, `rehype-autolink-headings`, `mermaid` (cargado de forma perezosa) y `react-markdown` si no estaba.
* `vite.config.ts`: el plugin de MDX con esos *plugins*, el alias `@thesis` → `../../docs/thesis` y `server.fs.allow` para leer fuera del proyecto.
* **Componentes que el MDX puede usar** (`src/sections/report/mdx/`):
  * `<Figure id="…" />`: busca la figura en el registro, la numera por capítulo ("Figura 3.4") y la dibuja en un `ChartFrame` con su leyenda, "Cómo leerla", la fuente (ruta del JSON) y el intervalo;
  * `<Cite id="guo2017" />`: "(Guo et al., 2017)", con enlace a referencias; falla al construir si el id no existe o no está `verified`;
  * `<Term id="ppi" />`: el término con su definición del glosario;
  * los bloques de código `mermaid` se dibujan con `<Mermaid>`;
  * `<Callout>`.
* **Registro de figuras** (`src/sections/report/figures/index.ts`): `id → { component, caption, source, howToRead }`. Cada figura es un componente que importa su JSON (`import data from "@analytics/sentiment/sentiment_models_test_metrics.json"`) y usa las primitivas de `src/charts/`. Los bancos siempre pasan por `bankLabel()`.

### 3.2 Agregados para la tesis

Los JSON de `docs/analytics/` no traen series mensuales ni diarias por banco. `tools/export_thesis_aggregates.py` (con aprobación del autor para correr consultas; costo estimado < $0.10) exporta de BigQuery a `docs/thesis/data/`, **solo agregados**:

* proporción de `NEG` y *gap* crudo por banco y mes;
* *gap* en estrellas con PPI por banco y mes (de `kpi_estimates`);
* volumen y elegibilidad por banco y mes;
* medianas por versión.

Cada archivo lleva la fecha de corte y la consulta que lo produjo. Ningún archivo tiene ids de reseña ni texto.

### 3.3 Sección del portal (`/reporte`)

* Índice lateral por capítulo y sección, y la versión y la fecha arriba.
* Lectura en Source Serif 4 a 18 px, interlineado de 1.7, 68 caracteres por línea.
* Figuras a todo el ancho de la columna; notas al margen en pantallas anchas.
* Navegación anterior y siguiente al pie de cada capítulo.

## 4. Redacción

1. **Índice detallado primero:** por cada capítulo, sus secciones con 2 o 3 líneas de contenido, las figuras y tablas que lleva y sus fuentes. El autor lo aprueba antes de redactar.
2. **Un capítulo por vez**, en el orden 3 (análisis), 4 (despliegue), 2 (antecedentes), 1 (introducción) y conclusiones: la introducción se escribe al final, cuando el aporte está claro.
3. **Fuentes por capítulo:**

| Capítulo | Fuentes |
| :--- | :--- |
| 1. Introducción | El aporte del autor, [`epics.md`](../epics.md), la [historia de los resultados](../../analytics/README.md) |
| 2. Antecedentes | [`references.md`](../../governance/references.md) (solo entradas verificadas) |
| 3.1 Metodología | Reportes de EDA, [reglas de elegibilidad](../../analytics/eda/eligibility_rules.md), oro y plata (`labeling/`), [protocolo de modelos](../../analytics/sentiment/sentiment_models_protocol.md), diseño de calibración, de tópicos y de escala |
| 3.2 Resultados | El [registro de decisión](../../analytics/decision_record.md) y los reportes de cada etapa, con sus JSON |
| 3.3 Discusión y 3.4 Conclusiones | Límites de la Model Card, trabajo futuro (detección de incidentes) |
| 4.1 Extracción y sanitización | [`epic_2.md`](../epic_2.md) a [`epic_4.md`](../epic_4.md), [contrato de ingesta](../../contracts/ingestion_v2.md), [despliegue](../../operations/deployment.md) |
| 4.2 MLOps y AIOps | [`epic_6.md`](../epic_6.md), [contrato v3](../../contracts/analytics_outputs_v3.md), esta épica y el portal |

4. **Lenguaje común:** la tesis no cita códigos del backlog (`M4`, `P8-9`, `D12`); los describe ("RoBERTuito ajustado con la plata de Gemini").
5. **Figuras candidatas**, de los JSON que existen:
   * escalera de modelos con κ e IC;
   * matriz de confusión en el *test*;
   * diagrama de confiabilidad antes y después de la temperatura;
   * curva de cobertura y riesgo;
   * ancho del intervalo con PPI frente a solo oro;
   * *gap* por banco;
   * elegibilidad por banco;
   * prevalencia y κ de las familias;
   * índices temporales;
   * tasas de alerta de deriva por banco;
   * costos y *benchmarks*;
   * validación HITL;
   * comparación de ventanas de la señal de incidentes;
   * diagramas de arquitectura en Mermaid.
6. **Referencias:** completar la sección 12 de `references.md` (verificar las candidatas de rechazo selectivo, PPI++, BERTopic, UMAP, HDBSCAN, Sentence-BERT y MiniLM, z robusto y PSI, Cohen, Efron y Tibshirani, oclusión, anotación con LLM y MLOps; resolver C5, C6, Zuhir 2025 y Yang 2021) y pasar las verificadas a `references.json`.

## 5. Pruebas

* Al construir: cada `<Figure>` y `<Cite>` existe; cada cita está verificada.
* `tools/check_thesis.py` (en CI): ningún nombre real de banco en `docs/thesis/` fuera de la declaración de patrocinio aprobada; ningún archivo de `docs/thesis/data/` tiene columnas `id_resena`, `texto*` ni `text_key`.
* `axe` sin violaciones en `/reporte`.

## Terminado cuando

* [ ] Los cinco capítulos están publicados en el portal con su versión (fecha y commit).
* [ ] Cada cifra y gráfica sale de su JSON; no aparece ningún banco por su nombre ni ningún texto de reseña.
* [ ] Cada referencia citada está verificada en `references.md` y en `references.json`.
* [ ] La Model Card y la Data Card enlazan los capítulos de la tesis (paso 10).

## Avance

_(Se llena al ejecutar.)_
