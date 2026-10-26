# Guía visual del portal

> **Estado (2026-10-25): versión 0.1, para revisar por el autor.** Fija la marca, la paleta, la tipografía y los componentes del portal web (`web/portal/`). La implementación de los *tokens* vive en `web/portal/src/styles/tokens.css` y debe copiar los valores de este documento, no reinventarlos. Las preguntas abiertas están en el [cuestionario de diseño](../backlog/epic_7/design_questions.md); el stack técnico, en [`frontend_stack.md`](frontend_stack.md).

## 1. De dónde sale

La fuente es la **Guía de diseño institucional de la Universidad Panamericana** (un PDF de una página, revisado como imagen el 2026-10-25) y la [marca institucional](https://www.up.edu.mx/marca-institucional/). Lo que dice la guía y aplica aquí:

* **Cuatro colores de producto**, uno por unidad: azul `#002D72` (Preparatoria), vino `#8A1538` (Licenciatura), verde `#00685E` (Posgrados) y dorado `#BA9357` (Alumni e institucional). Cada uno tiene sus complementarios específicos, que son tonos del mismo color.
* **Complementarios generales:** dorado `#BA9357`, negro y blanco. Combinan con cualquier producto.
* **Regla:** un producto mantiene su color y **no se mezclan colores de un producto en otro**.
* **Tipografía:** Panamericana (serif) para títulos, encabezados y descriptores; Seravek (sans humanista) para cuerpo de texto y lectura extensa.
* **Elementos gráficos:** escudo (documentos oficiales y ceremoniales), marca madre (comunicación institucional), marca de producto (unidades y programas), textura de roble, *wordmark* "Panamericana" como fondo decorativo y el **tahalí** (franja diagonal que da dinamismo). Todos con los colores de la paleta.
* **Checklist de la guía:** tipografías institucionales, paleta correcta según el tipo de comunicación, logotipo adecuado (escudo, marca madre o producto), complementos sin exceso.

## 2. Cómo se aplica al portal

**El portal es un producto de Posgrados** (decisión del autor, 2026-10-25): una tesis de maestría. Por eso:

* **Color de marca:** el verde de Posgrados `#00685E` y sus tonos.
* **Acento:** el dorado `#BA9357` y sus tonos, que es complementario general.
* **Fondo y texto:** blanco, negro y grises cálidos (derivados del dorado para que armonicen).
* **No se usan como color de marca** el azul de Preparatoria ni el vino de Licenciatura. La paleta del EDA (`#002D72`, `#215347`, `#7A1A37`, `#B9975B`) queda en los notebooks y las figuras de los experimentos; el portal no la usa.
* **Tipografía:** Panamericana y Seravek son propietarias y no se usan. Se sustituyen por una superfamilia libre que reproduce el mismo contraste serif + sans humanista (sección 5).
* **Gráficas:** tienen su propia paleta de datos (sección 4). La regla de no mezclar productos aplica a la identidad (encabezado, navegación, botones, títulos), no a los colores que codifican datos, como los de cada banco o el sentimiento. Los colores de datos nunca se usan en la interfaz.

## 3. Paleta de interfaz

Los valores marcados con ★ son los de la guía; los demás son tonos derivados para tener una escala completa. El contraste es contra blanco (WCAG 2.2: ≥ 4.5 para texto normal y ≥ 3 para texto grande y elementos gráficos).

### 3.1 Verde (marca)

| Token | Hex | Contraste | Uso |
| :--- | :--- | :---: | :--- |
| `green-50` | `#EEF6F4` | — | Fondo de selección y de fila activa |
| `green-100` | `#D3E9E5` | — | Fondo de etiqueta y de *hover* |
| `green-200` | `#A3D0C8` | — | Bordes de componentes activos |
| `green-300` | `#5FAEA3` | 2.6 | Solo decorativo |
| `green-400` | `#1F8A7E` | 4.2 | Íconos y elementos gráficos |
| `green-500` | `#00776C` | 5.45 | Enlaces sobre fondos claros |
| `green-600` ★ | `#00685E` | 6.68 | **Color de marca:** botón primario, navegación activa, foco, enlaces |
| `green-700` | `#00574F` | 8.48 | *Hover* del botón primario |
| `green-800` ★ | `#004940` | 10.36 | Títulos de sección, encabezado del portal |
| `green-900` ★ | `#00322A` | 14.1 | Fondo del encabezado y del *hero* de la landing |

### 3.2 Dorado (acento)

| Token | Hex | Contraste | Uso |
| :--- | :--- | :---: | :--- |
| `gold-50` | `#F8F3EA` | — | Fondo de aviso suave y de la cita destacada |
| `gold-100` | `#EFE4D0` | — | Fondo del marcador "vigente" en tablas |
| `gold-200` | `#E0CBA6` | — | Separadores decorativos |
| `gold-300` | `#C9AC79` | — | Tahalí sobre fondo verde |
| `gold-400` ★ | `#BA9357` | 2.84 | **Acento:** filetes, tahalí, marcador del valor vigente en gráficas. **Nunca como texto** |
| `gold-500` | `#9C7B48` | 3.93 | Texto grande (≥ 24 px) |
| `gold-600` | `#846C48` | 4.98 | Texto en dorado (antetítulos, cifras destacadas) |
| `gold-700` | `#68553A` | 7.12 | Texto dorado pequeño |
| `gold-800` | `#524330` | 9.53 | Texto sobre `gold-50` |

Sobre `green-900`, el `gold-400` llega a 4.97: sirve como texto en el encabezado oscuro.

### 3.3 Neutros cálidos

| Token | Hex | Uso |
| :--- | :--- | :--- |
| `neutral-0` | `#FFFFFF` | Superficie de tarjetas y tablas |
| `neutral-25` | `#FBFAF7` | Fondo de la página |
| `neutral-50` | `#F6F4EF` | Fondo de zonas secundarias (barra de filtros, encabezado de tabla) |
| `neutral-100` | `#EDEAE3` | Fondo de *hover* neutro |
| `neutral-200` | `#DDD8CE` | Bordes de tarjeta y divisores |
| `neutral-300` | `#C4BDB0` | Bordes de controles |
| `neutral-400` | `#A39B8D` | Ejes y rejillas de gráficas |
| `neutral-500` | `#857D72` | Texto deshabilitado; solo texto grande (4.06) |
| `neutral-600` | `#6E675D` | Texto secundario (5.58) |
| `neutral-700` | `#514B43` | Etiquetas de ejes, texto de apoyo |
| `neutral-800` | `#36322D` | Antetítulos |
| `neutral-900` | `#211E1B` | **Texto principal** |
| `neutral-950` | `#141210` | Negro de la marca (títulos sobre fondo claro, logo en negro) |

### 3.4 Tokens semánticos

Los componentes usan estos nombres, no los de la escala.

| Token | Valor | Nota |
| :--- | :--- | :--- |
| `--color-bg` | `neutral-25` | |
| `--color-surface` | `neutral-0` | |
| `--color-surface-muted` | `neutral-50` | |
| `--color-border` | `neutral-200` | |
| `--color-border-strong` | `neutral-300` | |
| `--color-text` | `neutral-900` | |
| `--color-text-muted` | `neutral-600` | |
| `--color-brand` | `green-600` | |
| `--color-brand-hover` | `green-700` | |
| `--color-brand-strong` | `green-800` | |
| `--color-on-brand` | `neutral-0` | Texto sobre el verde |
| `--color-accent` | `gold-400` | Decorativo |
| `--color-accent-text` | `gold-600` | |
| `--color-focus` | `green-600` | Anillo de 2 px con 2 px de separación |
| `--color-ok` / `--color-ok-bg` | `green-700` / `green-50` | Estado `ok`, éxito, alerta descartada |
| `--color-warning` / `--color-warning-bg` | `#8A5A00` / `#FFF3D6` | Estado `warning`; contraste 5.37 |
| `--color-danger` / `--color-danger-bg` | `#A12C2C` / `#FBE9E7` | Estado `retrain` o `rejected`, error, alerta abierta; contraste 6.15 |
| `--color-info` / `--color-info-bg` | `neutral-700` / `neutral-100` | Avisos neutros ("es una descripción, no un diagnóstico") |

Ningún estado se comunica solo con el color: cada uno lleva su ícono y su texto (`ok`, `aviso`, `reentrenar`).

## 4. Paleta de datos

Se usa solo dentro de gráficas, tablas de datos y la explicación por palabras. Cada gráfica codifica **una sola cosa con color** (o bancos, o sentimiento), así que el rojo de un banco y el del sentimiento negativo nunca conviven en la misma gráfica.

### 4.1 Bancos

Decisión del autor (2026-10-24): cada banco lleva un seudónimo fijo y su color representativo, iguales en todo el portal. Los seudónimos se eligieron por color (cuestionario, pregunta `D-03`): Banco Azul (BBVA), Banco Verde (AZTECA), Banco Rojo (SANTANDER), Banco Morado (NUBANK) y Banco Gris (BANORTE). Se simplificaron el 2026-10-26: el nombre del color es más directo que un sinónimo. El mapa vive en un solo archivo (`web/portal/src/config/banks.ts`), indexado por `bank_id`.

| `bank_id` | Color | Hex | Contraste | Trazo de respaldo |
| :--- | :--- | :--- | :---: | :--- |
| `BBVA` | Azul | `#1F64B0` | 5.99 | Continuo |
| `AZTECA` | Verde | `#3E8E2F` | 4.11 | Guiones largos |
| `SANTANDER` | Rojo | `#D0261C` | 5.28 | Punteado |
| `NUBANK` | Morado | `#7B2FC9` | 6.79 | Guion y punto |
| `BANORTE` | Gris | `#6A6867` | 5.54 | Guiones cortos |
| Los cinco juntos | Casi negro | `neutral-950` | 18.69 | Continuo, más grueso |

* El rojo y el verde se confunden con deuteranopía: toda gráfica de líneas por banco lleva la **etiqueta directa** al final de cada línea y el trazo de respaldo de la tabla.
* El verde de AZTECA es amarillento a propósito, para no confundirse con el verde azulado de la marca.

### 4.2 Sentimiento

| Valor | Hex | Nota |
| :--- | :--- | :--- |
| `NEG` | `#B23A2E` (ladrillo) | Contraste 5.94. Distinto del vino de Licenciatura; el cuestionario (`C-02`) pregunta si se prefiere el vino |
| `NEU` | `#857D72` | Gris cálido |
| `POS` | `#00685E` | El verde de la marca |
| `NO_PREDICTED` | `neutral-300` con rayado diagonal | Reseñas que no se predicen; nunca se mezclan con `NEU` |

### 4.3 Escalas

* **Secuencial** (matriz 3 × 3, mapas de calor, volumen): de `green-50` a `green-900`, en 7 pasos.
* **Divergente** (*gap* en estrellas, z de deriva, explicación por palabras): ladrillo `#B23A2E` ← `neutral-50` → verde `#00685E`, simétrica alrededor de 0.
* **Explicación por palabras:** el fondo de cada palabra toma el color de la clase hacia la que empuja (ladrillo hacia `NEG`, verde hacia `POS`), con opacidad proporcional al peso (de 0 a 0.45). Debajo va la escala con su rango numérico y el texto "qué palabras movieron la predicción del modelo; no es la causa técnica del fallo".

### 4.4 Marcas de referencia en las gráficas

| Elemento | Estilo |
| :--- | :--- |
| Umbral vigente (z ≥ 4, piso de κ, cobertura objetivo) | Línea discontinua de 1.5 px en `gold-600`, con su etiqueta |
| Punto vigente de una curva (cobertura de la política) | Rombo `gold-400` con borde `neutral-950` |
| Intervalo de confianza | Banda del color de la serie al 18 % de opacidad; en puntos, barra de error de 1 px |
| Cambio de versión (prompt, modelo, tópicos) | Línea vertical punteada `neutral-500` con la versión arriba |
| Día o periodo seleccionado | Banda `gold-100` detrás de los datos |
| Ejes y rejilla | `neutral-400` para el eje y `neutral-200` para la rejilla; sin borde de marco |

Las proporciones crudas se dibujan como línea, las estimaciones con PPI como punto con su intervalo, y cada gráfica lleva su insignia de método (sección 7).

## 5. Tipografía

**Superfamilia Source** (Adobe, licencia SIL Open Font License), servida desde el propio portal con los paquetes `@fontsource-variable`, sin llamadas a Google Fonts ni a otro CDN.

| Rol | Familia | Sustituye a | Por qué |
| :--- | :--- | :--- | :--- |
| Títulos y lectura larga (la tesis) | **Source Serif 4** (variable, con tamaños ópticos) | Panamericana | Serif de transición, sobria, pensada para pantalla y para texto académico largo |
| Interfaz, tablas y cuerpo general | **Source Sans 3** (variable) | Seravek | Sans humanista como Seravek; cifras tabulares para KPIs y tablas |
| Versiones, ids, hashes, código | **Source Code Pro** | — | Monoespaciada de la misma familia |

Las tres se diseñaron para convivir y cubren todo el español (ñ, acentos, ¿ ¡ « »). Respaldo: `Georgia, serif`, `system-ui, sans-serif` y `ui-monospace, monospace`.

### 5.1 Escala

Base de 16 px; razón aproximada de 1.25.

| Token | Tamaño | Interlineado | Uso |
| :--- | :--- | :--- | :--- |
| `text-xs` | 12 px | 16 px | Procedencia, notas de gráfica, insignias |
| `text-sm` | 14 px | 20 px | Tablas, etiquetas de controles, ejes |
| `text-base` | 16 px | 24 px | Cuerpo de la interfaz |
| `text-lg` | 18 px | 30 px | Cuerpo de la tesis (serif, 1.7 de interlineado) |
| `text-xl` | 20 px | 28 px | Títulos de tarjeta (serif 600) |
| `text-2xl` | 24 px | 32 px | Títulos de sección (serif 600, `green-800`) |
| `text-3xl` | 30 px | 36 px | Título de página (serif 600) |
| `text-4xl` | 36 px | 40 px | Cifra principal de un KPI (sans 600, cifras tabulares) |
| `text-5xl` | 48 px | 1 | Título de la landing y de cada capítulo de la tesis (serif 600) |

* **Antetítulo** (como el "ELEGIR / PALETA DE COLOR" de la guía): sans 600, 12–13 px, mayúsculas, espaciado de 0.08 em, en `neutral-800`; debajo, el título en serif.
* **Pesos:** 400 y 600; 700 solo en la cifra de un KPI. Sin itálicas falsas.
* **Medida:** la tesis y la ayuda no pasan de 68 caracteres por línea; la interfaz no tiene límite.
* **Cifras:** `font-variant-numeric: tabular-nums` en tablas, KPIs y ejes.
* **Términos en inglés** de uso común (*drift*, *coverage*, *gold labels*): en cursiva la primera vez en cada página, con su entrada en el glosario.
* **Fórmulas:** MathJax con su fuente por defecto (New Computer Modern); el cuestionario (`T-03`) pregunta si se cambia.

## 6. Elementos gráficos de la marca

| Elemento | Uso en el portal |
| :--- | :--- |
| **Marca de producto de Posgrados** | En el encabezado (versión en blanco sobre `green-900`) y en la portada de la tesis. Requiere el archivo oficial en SVG (cuestionario, `B-01`); mientras no esté, el encabezado lleva solo el nombre del portal en Source Serif 4 |
| **Escudo** | No se usa en el portal: la guía lo reserva para documentos oficiales y ceremoniales |
| **Tahalí** | Una franja diagonal en `gold-400` en el *hero* de la landing y en la portada de cada capítulo de la tesis, como componente SVG (`<Tahali />`). Nunca tapa datos ni texto |
| **Textura de roble y *wordmark*** | Solo como fondo muy tenue (opacidad ≤ 0.08) del *hero* de la landing, y solo con el archivo oficial. No se redibujan |
| **Fotografía** | No hay: el portal es de datos |

## 7. Procedencia, método y estado

Es el principio "cada número con su procedencia" hecho componente. Toda cifra y toda gráfica llevan:

* **Línea de procedencia** (`<Provenance />`, `text-xs`, `neutral-600`) al pie: `Modelo robertuito_sentiment_v1 · política risk_policy_v1 · prompt aspects_v2_1 · datos al 24 oct 2026`. Solo los campos que aplican.
* **Insignia de método** (`<MethodBadge />`): "Con revisión humana" (verde, con su rango; es la estimación PPI) o "Solo modelo" (gris; es la proporción cruda). Al pasar el cursor, una línea explica la diferencia sin juzgar la cifra "sin revisión" como mala, y el glosario enlaza los términos técnicos.
* **Estado** (`<StatusPill />`): `ok`, `aviso`, `reentrenar`, `rechazado`, `abierta`, `confirmada`, `descartada`, `en curso`, `falló`, con ícono y color semántico.
* **Aviso de descripción** (`<Callout variant="info">`) en las vistas de temas por día y por versión: "Describe lo que dicen las reseñas; no es un diagnóstico ni una detección de incidentes".

## 8. Composición

### 8.1 Estructura de la aplicación

* **Encabezado** (56 px, fondo `green-900`): marca o nombre del portal a la izquierda; a la derecha, la insignia del ambiente (`dev`), el enlace a gobernanza y el menú de usuario (correo y roles).
* **Navegación lateral** (240 px, plegable a 64 px con solo íconos), agrupada:
  * **Consultar:** Inicio, Cockpit.
  * **Investigar:** Explorador, Alertas.
  * **Revisar:** Revisión (HITL).
  * **Operar:** MLOps y AIOps.
  * **Configurar:** Administración.
  * **Documentación:** Reporte de la tesis, al final: lo consulta quien busca el trasfondo académico (decisión del autor, 2026-10-26).
  * Solo aparecen las secciones que permite el rol; la activa lleva una barra de 3 px en `green-600` y fondo `green-50`.
* **Barra de filtros globales** (fija bajo el encabezado, fondo `neutral-50`), en las secciones que la usan: bancos (selección múltiple), periodo (atajos y rango) y "Restablecer". Los filtros viven en la URL, así que se conservan al cambiar de sección y se pueden compartir.
* **Contenido:** ancho máximo de 1 440 px, márgenes de 32 px (24 px en pantallas medianas), rejilla de 12 columnas con 24 px de separación.

### 8.2 Superficies

* **Tarjetas:** fondo blanco, borde de 1 px `neutral-200`, radio de 8 px, sin sombra; las que se pueden pulsar ganan `shadow-sm` y borde `green-200` al pasar el cursor.
* **Espaciado:** múltiplos de 4 px (la escala por defecto de Tailwind).
* **Radios:** 4 px en controles, 8 px en tarjetas y diálogos, 999 px en insignias.
* **Movimiento:** transiciones de 150 ms, sin animar los datos al filtrar; con `prefers-reduced-motion`, ninguna.

### 8.3 Tamaños de pantalla

El portal se diseña para escritorio (≥ 1 280 px) y para proyectar en la presentación. Entre 1 024 y 1 279 px la navegación se pliega. Por debajo de 1 024 px, la landing, el reporte y las tarjetas del cockpit se leen en una columna; el HITL, el Explorador y la administración muestran un aviso de que piden una pantalla más ancha (cuestionario, `L-04`).

## 9. Componentes base

Se construyen una vez en `src/components/` y todas las secciones los reutilizan.

| Componente | Qué hace |
| :--- | :--- |
| `KpiCard` | Cifra principal, intervalo, cambio contra el periodo anterior, minigráfica, insignia de método y procedencia |
| `ChartFrame` | Marco de toda gráfica: antetítulo, título, subtítulo, "Cómo leerla" desplegable, la gráfica, "Ver datos" (tabla accesible con los mismos números), procedencia y acciones ("Abrir en el Explorador", "Descargar agregado") |
| `DataTable` | Tabla con orden, paginación del servidor, columnas fijas y filas virtualizadas |
| `FilterBar` | Filtros globales leídos y escritos en la URL |
| `ConfirmWithReason` | Diálogo de confirmación con motivo obligatorio (mínimo 10 caracteres); para cambios grandes pide escribir una palabra de confirmación |
| `StatusPill`, `MethodBadge`, `VersionChip`, `Provenance` | Sección 7 |
| `Callout` | Avisos `info`, `warning` y `danger` |
| `GlossaryTerm` | Término subrayado con puntos que abre su definición |
| `EmptyState`, `ErrorState`, `Skeleton` | Sin datos, error (con el id de la petición para buscarlo en los logs) y carga |
| `KeyboardHint` | Atajos visibles (HITL) |
| `Tahali` | Elemento gráfico de la marca (sección 6) |

## 10. Redacción y formatos

* **Idioma:** español, en segunda persona de cortesía implícita ("Elige un banco"), frases cortas, sin jerga del backlog: "RoBERTuito ajustado con la plata de Gemini", no códigos de decisión.
* **Números:** `Intl.NumberFormat('es-MX')`: punto decimal y coma de miles (`2,654,106`). Porcentajes con un decimal y espacio antes del signo (`12.3 %`); intervalos como `12.3 % [11.0, 13.6]`; κ y F1 con tres decimales.
* **Fechas:** `25 oct 2026`; meses `oct 2026`; horas con zona (`09:30 CDMX`). Los días de las series son días UTC, como los calcula BigQuery, y el eje lo dice (cuestionario, `L-05`).
* **Registros de lenguaje** (decisión del autor, 2026-10-26). Cada sección se escribe para su público (`audience` en `config/nav.ts`):

  | Registro | Secciones | Cómo se escribe |
  | :--- | :--- | :--- |
  | Ejecutivo | Inicio | Palabras comunes y sin siglas; cada cifra con su rango en palabras ("entre 16.5 % y 19.5 %"); la procedencia técnica va en un "Cómo se calculó" desplegable |
  | Analista y decisor | Cockpit, Explorador, Alertas, Revisión | Lenguaje común a la vista; el cómo se calculó y los términos técnicos van en tooltips y en un "Cómo se calculó" |
  | Académico | Reporte, Gobernanza | Términos precisos (PPI, κ, deriva) con su definición del glosario la primera vez |
  | Técnico | MLOps y AIOps, Administración | Términos técnicos sin traducir |

  Equivalencias para los registros no técnicos: ingesta → "reseñas nuevas"; delta → "análisis de reseñas"; monitor → "revisión del modelo"; deriva → "cambios"; intervalo → "rango"; HITL → "revisión"; *gap* → "brecha". Un término técnico nunca desaparece: se explica en el glosario.
* **Vacíos:** se dice qué falta y por qué ("Sin revisiones en este trimestre: la muestra de monitoreo tiene 0 de 300"), nunca un cero engañoso.

## 11. Accesibilidad

* WCAG 2.2 AA: contrastes de las tablas de arriba, foco visible en todo control y navegación completa con teclado.
* Ninguna información depende solo del color (íconos, texto, trazos de respaldo).
* Cada gráfica tiene su "Ver datos" con los mismos números en una tabla.
* Las pruebas del portal corren `axe` sobre cada página (ver la feature de pruebas del backlog).
