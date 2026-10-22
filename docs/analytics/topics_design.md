# Plan de diseño de 5.5: tópicos y decisión sobre ABSA

> **Estado (2026-10-20): aprobado por el autor (`v1`).** Aún no implementado. Dueño: hilo "Tópicos". Código futuro en `experiments/analytics/src/voc_analytics/topics/`. Contexto: [feature 5.5 en `epic_5.md`](../backlog/epic_5.md), [EDA 5.2](eda_report.md#52-proporción-multi-aspecto-de-las-negativas), [EDA temporal](eda_temporal_report.md), [guía de aspectos `v1`](eda_aspects_guideline.md), [reglas de elegibilidad](eligibility_rules.md).
> * **Cambios contra el borrador (`v0`):** ajuste global de BERTopic con `topics_over_time` como vía principal; las 10 familias pasan de alternativa a referencia de evaluación y núcleo estable; `DS` se reemplaza por `DV`, `UX` y `FQ` más una marca `u` de actualización, con una prueba de separación con regla de decisión fijada de antemano; análisis por versión con normalización por banco; hipótesis temporales declaradas de antemano. Se tomó en cuenta una revisión externa (Gemini) que proponía tópicos dinámicos sin ABSA; se adoptaron sus puntos de ingeniería y se rechazó descartar la taxonomía (sección 4.4).

## 1. Qué hay que decidir

Una recomendación entre taxonomía fija (ABSA ligero), tópicos dinámicos o híbrido, con costo de operación, para Q2 (temas recurrentes y su cambio) y Q3 (detección rápida de incidentes nuevos). El piloto mide ambas vías sobre la misma muestra.

## 2. Evidencia de partida (5.2)

* 32 % (Gemini, cota inferior) a 44 % (autor) de las negativas es multi-aspecto; 51 % en las de 20 palabras o más. Un tópico por reseña asigna mal al menos un tercio.
  * **Salvedad:** la regla 3 de la guía `v1` suma `DS` cuando la queja culpa a una actualización, así que "desde la actualización no abre" cuenta como multi-aspecto siendo un solo problema con su causa (acceso + diseño es de los pares más comunes). La cifra puede estar inflada por definición; se recalcula con `aspects_v2` (sección 6).
* Las negativas de 1–5 palabras casi nunca son multi-aspecto (0–2 %), pero sí nombran un problema concreto: el 48–50 % de las de 2 palabras y el 77–81 % de las de 3 a 5; solo el 4 % de las de una palabra (`v1` / `v2`; [reporte](topics_report.md), §2.3; corregido el 2026-10-21). El 7.3 % de las `NEG` no tiene problema concreto.
* Familias: acceso 35 %, falla 26 %, diseño y actualizaciones 18 %, transferencias 15 %, lentitud 11 %, atención 9 %.
* `DS` es el código débil (κ 0.39); dinero y cargos 0.26; compatibilidad ≈ 0.
* `version_app = UNKNOWN` en el 8.8 % (H10); NUBANK publica una versión por semana y solo es elegible desde 2020 (`TNSS_TIME_OUTLIER`); la detección automática de idioma no es fiable (H8).

## 3. Alcance

**Dentro:** las negativas de la plata `silver_v0` (estratificada por banco × periodo, ponderada por 1 / π; el oro para validar), por banco, periodo y versión; tópicos dinámicos; aspectos con Gemini (`aspects_v2`); umbral de `TOPIC_TOO_SHORT`; señal de incidentes probada hacia atrás; recomendación.
**Fuera:** predecir sentimiento o asignar tópicos sobre el corpus completo (backfill: 5.7, 5.8 y EPIC-6, con un plan de implementación acordado), servir tópicos en producción, calibración (5.6), re-entrenar sentimiento (5.4), la guía de aspectos `v2` en sí (Datos y EDA, sección 6).

## 4. Enfoque

### 4.1 Unidad de análisis
Por cláusula u oración en reseñas largas y reseña completa en las cortas; como alternativa, la distribución de tópicos por reseña (`approximate_distribution`). Se elige la que mejor recupere el multi-aspecto de `aspects_v2`. Los resultados se reportan por reseña (un tópico cuenta una vez por reseña) para no inflar las largas.

### 4.2 Vía A: BERTopic dinámico (principal)
* **Ajuste global** sobre una muestra estratificada por banco × periodo (para que los tópicos chicos y antiguos no los absorban 2019+ ni BBVA), Da identificadores estables por construcción. La muestra de ajuste es la propia plata: 40 382 textos únicos `NEG` que representan ~706 000 filas. La asignación del corpus completo no es parte de 5.5.
* Embeddings (candidatos: el encoder de M4 RoBERTuito y `paraphrase-multilingual-MiniLM-L12-v2`, elegidos por coherencia y alineación con familias; **fase 1: MiniLM, porque RoBERTuito base colapsa**) → UMAP (5–10 dimensiones) → HDBSCAN → c-TF-IDF → nombre propuesto por Gemini en Vertex.
* **`topics_over_time`** por trimestre (y bimestre como sensibilidad) para la evolución de la representación y la frecuencia.
* **Robustez:** ajuste por ventana con emparejamiento de centroides, y varias semillas.
* En la tesis se nombra como BERTopic con `topics_over_time` (Grootendorst, 2022), no como el *Dynamic Topic Model* de Blei y Lafferty (2006).

### 4.3 Vía B: familias de aspectos con Gemini (referencia y núcleo)
Clasificación multi-etiqueta de cada reseña negativa en las familias de `aspects_v2` (sin extracción de spans ni polaridad por aspecto: la reseña ya es negativa). Dos usos:
1. **Referencia de evaluación** de la vía A: alineación tópico ↔ familia (pureza, NMI), validada con la codificación del autor.
2. **Núcleo estable** del híbrido: familias abstractas comparables en el tiempo (el llavero de 2015 y el soft-token de 2026 son ambos `AC`).

Costo medido: $0.17 por 2 × 1 434 textos; el costo a escala se estima antes de correrla.

### 4.4 Comparación y recomendación
Hipótesis a confirmar o refutar: **híbrido**, con las familias como núcleo y tópicos emergentes de la vía A (los que no se alinean con ninguna familia, o caen en `OT` o sin familia). Se descartó recomendar solo tópicos dinámicos de entrada porque:
* un tópico por reseña no representa el 32–44 % multi-aspecto;
* la coherencia de tópicos no es exactitud: sin las familias no hay referencia defendible;
* Q3 necesita series comparables en el tiempo para detectar regresiones por versión.

## 5. Reseñas cortas: `TOPIC_TOO_SHORT`
Barrer el umbral k (1–10 palabras) y medir por k: fracción con problema concreto (`aspects_v2` y oro), coherencia de los tópicos que las contienen, peso de los grupos genéricos ("pésima", "no sirve") y pérdida de cobertura. Hipótesis: k cerca de 5–6. **Refutada en la fase 1 (2026-10-21):** las cortas sí nombran problemas y excluirlas no mejora los tópicos; **Decisión del autor (2026-10-22): k = 1** ([reporte](topics_report.md), §4.3). Las excluidas se reportan como cobertura.

## 6. Decisión: reabrir 5.2 para reemplazar `DS` (aprobada)

**Aprobado por el autor (2026-10-20):** se reabre 5.2 en un *fork* de Datos y EDA para la guía de aspectos `v2` y el prompt `aspects_v2`. Este hilo fija los criterios y consume el resultado.

> **Resultado (2026-10-21): taxonomía final `v2.1`** ([EDA, sección 5.2.1](eda_report.md#521-guía-de-aspectos-v2-y-v21-reapertura-para-55)). Con `v2`, `DV` cumplió la regla y `UX` no (κ 0.55), y `FQ` se fusionó con `UX`. Como el bajo acuerdo de `UX` venía de su frontera con `CO`, `AC` y `PR`, y no de `DV`, el autor decidió (desviación documentada) mover la instalación y la actualización a `CO` y todo el token a `AC`, en lugar de fusionar `DV` con `UX`. Con `v2.1`, `UX` tiene κ 0.74 y `DV` κ 0.74; `DV` queda separado aunque su prevalencia es 1.8 %. Son 11 familias y dos marcas ortogonales: `u` (actualización, κ 0.70, usable como señal) y `s` (seguridad, no concluyente). Multi-aspecto: 24.7 % [22.6, 26.8]. Las subsecciones 6.1 a 6.4 quedan como registro del plan.

### 6.1 Códigos de prueba (guía `v2-draft`)

| Código | Familia | Ejemplo sintético |
| :---: | :--- | :--- |
| `DV` | Diseño visual: apariencia, colores, letra, "está fea", modo oscuro | "los colores nuevos están horribles" |
| `UX` | Usabilidad y recorrido: no encuentra algo, demasiados pasos, flujo confuso, navegación | "para pagar tengo que dar mil vueltas" |
| `FQ` | Funciones quitadas o cambiadas | "ya no puedo ver mis movimientos anteriores" |
| marca `u` | Problema atribuido a una actualización o cambio; ortogonal, como el elogio | "desde la actualización…" + la familia del problema |

* **Frontera `DV`/`UX`:** si se queja de cómo se ve, `DV`; de cómo se hace algo, `UX`. "Está bonita pero no encuentro nada" es `UX` con elogio concreto.
* La marca `u` reemplaza la regla 3 de `v1`: ya no suma una familia y no infla el multi-aspecto.
* **Hipótesis del autor:** el diseño visual y la experiencia de uso son temas distintos y su mezcla en `DS` explica el bajo acuerdo.

### 6.2 Protocolo
1. **Calibración (~30 textos):** el autor codifica y se afinan las definiciones antes de usar Gemini.
2. **Muestra (~300 textos):** ~150 enriquecidos con casos de diseño (`DS` de `aspects_v1` según Gemini o según el autor, y candidatos por palabras clave) y ~150 aleatorios de las negativas para estimar prevalencia; la parte enriquecida se pondera.
3. **Consistencia intra-anotador:** el autor recodifica a ciegas 50 textos tras una semana o más. Con un único anotador, primero hay que mostrar que él distingue `DV` de `UX` de forma estable.
4. **Evidencia sin etiquetas (este hilo):** si en la vía A los textos de diseño se separan solos en grupos visuales y de recorrido.

### 6.3 Regla de decisión (fijada antes de ver datos)
`DV` y `UX` quedan separados si se cumplen las cuatro:
* κ intra-autor ≥ 0.70 en cada uno;
* κ autor–Gemini ≥ 0.60 en cada uno;
* la confusión `DV`↔`UX` explica menos del 20 % de sus desacuerdos;
* cada uno aparece en al menos el 2 % de las negativas.

Si falla alguna, se fusionan, siempre que el código fusionado alcance κ ≥ 0.60. `FQ` se evalúa con los mismos criterios. Si la fusión se debe a baja prevalencia y no a falta de distinción, se reporta así. En todos los casos se recalcula la proporción multi-aspecto con `u` aparte; si baja mucho, la segmentación por cláusula pesa menos en la decisión.

### 6.4 Mientras tanto
La vía A no depende de la guía y arranca de inmediato. La vía B espera a `aspects_v2`.

## 7. Detección de incidentes y análisis por versión (Q3)

### 7.1 Versión
* Normalización **por banco** según su esquema (NUBANK publica semanalmente; `Major.Minor` no es comparable entre bancos); se excluyen `BETA`.
* Análisis por versión solo con ≥ 50 negativas; las demás se agrupan. Cobertura de `UNKNOWN` reportada (8.8 %).
* `version_app` ya es la versión instalada al escribir; no se imputa salvo en `UNKNOWN`.
* La comparación entre versiones consecutivas se hace contra una línea base temporal (tendencia, quincena, jueves en NUBANK; ver [EDA temporal](eda_temporal_report.md)), no solo versión n contra n−1.

### 7.2 Señal
Crecimiento anómalo de la proporción de un tópico o familia (con y sin marca `u`) por banco × versión y en ventana de 7 días contra su línea base móvil (z robusto o EWMA/Poisson sobre conteos). Prueba hacia atrás con los picos del EDA (BBVA 2024-07, 2025-10, 2025-11) y los días pico de SANTANDER y AZTECA con 5★ que esconden quejas, en dos escalones: (1) por mes y versión con la plata ponderada, sin costo; (2) solo si (1) no basta y con aprobación del autor, M4 en local (MPS) únicamente sobre esas ventanas con ~60 días de línea base (decenas de miles de textos, minutos). Los umbrales operativos se calibran en 5.7. Métricas: recall de picos conocidos, días de adelanto contra el pico de volumen de negativas, falsos positivos por banco-mes. Con pocos incidentes conocidos, el resultado es ilustrativo y se declara.

## 8. Hipótesis temporales declaradas de antemano
Se confirman o refutan con la vía A; no son premisas:
* H-T1: tópicos de token físico y apps separadas (wallet) concentrados antes de 2018 y en desaparición después.
* H-T2: biometría y onboarding digital crecen desde 2019.
* H-T3: NUBANK (desde 2020) tiene tópicos ausentes en los bancos tradicionales. La hipótesis de confusión con el portugués es improbable según H8 y se verifica antes de afirmarla.
* H-T4: la proporción de quejas con marca `u` sube en los días siguientes a una versión y baja con la versión de corrección.

## 9. Validación humana
Revisión del autor de los ~20 tópicos principales (coherencia 1–5, utilidad para producto, nombre aceptable) y mapeo contra las 8 `ABSATopic` hipotéticas y las familias `v2`. Muestra pequeña, definida de antemano.

## 10. Métricas

| Aspecto | Métrica |
| :--- | :--- |
| Calidad de tópicos | Coherencia (c_v/NPMI), diversidad, fracción de ruido de HDBSCAN, juicio del autor |
| Alineación con familias | Pureza y NMI tópico ↔ familia `aspects_v2`; tópicos sin familia (emergentes) |
| Estabilidad | ARI/NMI entre semillas; global contra por ventana |
| Cobertura | % de negativas elegibles asignadas; % cubierto por familias |
| Aspectos | κ por código contra el autor; κ intra-autor; multi-aspecto recalculado |
| Incidentes | Recall de picos, adelanto, falsos positivos |
| Costo | Tiempo de ajuste y asignación, USD de Gemini, horas de curaduría por corrida |

## 11. Entregables
1. `topics/`: muestra estratificada, embeddings, BERTopic global y por ventana, alineación con familias, barrido de `TOPIC_TOO_SHORT`, normalización de versiones, señal de incidentes.
2. `docs/analytics/topics_report.md` y `topics_metrics.json` (solo agregados y ejemplos sintéticos).
3. Sección 5.5 de `epic_5.md` con la recomendación y su costo de operación.
4. Nota de entrada para el registro de decisión (5.8).

## 12. Fases y dependencias

| Fase | Contenido | Depende de |
| :--- | :--- | :--- |
| 0 | Muestra estratificada de negativas elegibles; embeddings; normalización de versiones | Plata vigente |
| 1 | Vía A, piloto en 2 bancos; barrido de umbral corto | Fase 0 |
| 2 | Vía A en los 5 bancos, `topics_over_time`, hipótesis H-T1 a H-T3; señal hacia atrás | Fase 1 |
| 2b | Guía `v2` y `aspects_v2` (fork de Datos y EDA, sección 6) | Aprobado |
| 3 | Vía B con `aspects_v2`; alineación A ↔ B; H-T4 | 2, 2b |
| 4 | Validación humana, recomendación y reporte | 3 |

## 13. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| La entrada depende de `NEG` de la plata (Gemini), con error | Sensibilidad con el oro |
| La plata es gruesa por día y versión | Señal por mes y versión; ventanas puntuales con M4 local solo si hace falta |
| Grupos genéricos grandes ("pésima") | `TOPIC_TOO_SHORT` y reporte aparte de "sin problema concreto" |
| Ajuste global dominado por 2019+ y BBVA | Muestra estratificada para el ajuste; robustez por ventana |
| Privacidad (FMEA F-01: la sanitización no detecta nombres) | Gemini solo en Vertex dentro de GCP; nada fuera sin autorización y fila FMEA; en `docs/` solo agregados |
| Cómputo fuera de GCP | Todo en local (smoke test: 40 382 textos en 47 s con MiniLM y 119 s con RoBERTuito en MPS; BERTopic con 35 000 en 19 s; < 1.3 GB de RAM); F-13 cubre solo 5.4 |
| Inestabilidad de tópicos | Ajuste global, semillas múltiples, ancla en familias |
| `DV`/`UX` indistinguibles o raros | Regla de decisión 6.3; reportar el motivo de la fusión |
| Un solo anotador | Consistencia intra-autor; declarar la limitación |
| Pocos incidentes conocidos | Resultado ilustrativo; sin umbrales operativos |
| Alcance excesivo | Piloto en 2 bancos; criterios de parada por fase |

## 14. Decisiones del autor
* Cómputo en local, sin Kaggle (2026-10-20), tras el smoke test.
* 5.5 trabaja solo con la plata; no requiere backfill de sentimiento (2026-10-20).
* `TOPIC_TOO_SHORT` con k = 1: solo se excluyen las negativas de una palabra (2026-10-22; [reporte](topics_report.md), §4.3).
* Vía B a escala: codificar con `aspects_v2_1` las 40 382 negativas únicas de la plata, ~$3.80 en Vertex dentro de GCP (2026-10-22).
