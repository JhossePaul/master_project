# Model Card: M4 RoBERTuito para el sentimiento real de reseñas bancarias

* **Versión:** 0.1 (2026-10-22), al cerrar el registro de decisión de EPIC-5 (5.8). Se completa en EPIC-7 (7.11) con lo que agregue el despliegue (EPIC-6).
* **Formato:** sigue *Model Cards for Model Reporting* (Mitchell et al., 2019); ver [`references.md`](references.md).
* **Fuentes:**
  * [competencia de modelos y evaluación en el oro *test*](../analytics/sentiment/sentiment_models_v0_report.md) (secciones 12 a 15);
  * [calibración y HITL](../analytics/calibration/calibration_report.md);
  * [escala y monitoreo](../analytics/scale/scale_report.md);
  * [registro de decisión](../analytics/decision_record.md);
  * [Data Card](data_card.md) y [FMEA](ethical_fmea_matrix.md).

## 1. Detalles del modelo

| Campo | Valor |
| :--- | :--- |
| Nombre y versión | `M4_robertuito_s1_ppi` (semilla 1, la de producción; decisión del autor, 2026-10-22) |
| Tarea | Clasificar el sentimiento del **texto** de una reseña en `NEG`, `NEU` o `POS`, separado de las estrellas (Q1) |
| Arquitectura | `pysentimiento/robertuito-sentiment-analysis` (RoBERTa de 109 M de parámetros, preentrenado con tuits en español) con todos los pesos ajustados |
| Entrenamiento | Etiquetas de la plata: Gemini `gemini-3.6-flash` con `prompt_v3` sobre 63 415 textos únicos, sin `NA` ni reseñas del oro. 2 épocas, AdamW con lr 2e−5, lote 32 y fp16, en una T4 de Kaggle (~6 min). Época elegida con un 5 % de validación agrupada por texto |
| Entrada | `texto_sanitizado` con el preprocesamiento de `pysentimiento` y hasta 128 *tokens* (cubre el 99.8–99.9 % de los textos) |
| Calibración | *Temperature scaling* con T = 1.68, ajustada en el oro *dev* aleatorio (5.6). No cambia la clase predicha |
| Reglas previas | `eligibility_rules_v1`: las reseñas de una palabra cubiertas por el léxico se etiquetan por regla (`RULE_BASED`), sin el modelo; las vacías, sin contenido o fuera de rango se excluyen ([reglas](../analytics/eda/eligibility_rules.md)) |
| Pesos | fp16, 218 MB, fuera de git (`data/models/weights/`); registro en Vertex AI Model Registry en EPIC-6 (P7-3) |
| Autor | El autor del proyecto, como trabajo académico independiente de los bancos |
| Licencia | **Solo uso no comercial e investigación**, heredada del checkpoint de `pysentimiento` y de TASS (P8-2) |

## 2. Usos

* **Previstos:**
  * estimar el sentimiento real frente a las estrellas, por banco y periodo, con intervalos PPI (*Satisfaction Gap* en estrellas, P8-9);
  * marcar las reseñas negativas que entran a familias y tópicos (`TOPIC_NOT_NEGATIVE`);
  * ordenar la cola de revisión humana por confianza.
* **Fuera de alcance:**
  * uso comercial (licencia);
  * decisiones sobre una persona: el modelo describe reseñas públicas, no clientes;
  * otros idiomas, otras tiendas (el corpus es solo de Google Play) u otros dominios distintos de la banca móvil en México;
  * tomar la etiqueta de una sola reseña como verdad sin revisión, en los casos de baja confianza.

## 3. Métricas

**Oro *test*** (594 reseñas aleatorias, anotadas a ciegas; evaluado una sola vez en 5.8):

| Métrica | `s1` | Media de 3 semillas | M9 Gemini (referencia) |
| :--- | :---: | :---: | :---: |
| κ de Cohen (IC 95 %) | 0.929 (0.901–0.955) | 0.929 | 0.943 (0.917–0.966) |
| κ ponderado por diseño | 0.927 | 0.927 | 0.942 |
| F1 `NEG` / `NEU` / `POS` | 0.970 / 0.629 / 0.978 | — | 0.979 / 0.718 / 0.981 |
| Recall / precisión de `NEG` | 0.976 / 0.963 | 0.975 / 0.964 | 0.981 / 0.977 |
| ECE sin calibrar → calibrado | 0.029 → 0.014 | — | — |

* **M9 − M4 en κ:** +0.014 [−0.010, 0.037] con `s1`. No es significativo en ninguna semilla, y tampoco hay diferencia significativa en `NEG`. Por la regla aprobada, P8-1 eligió M4.
* **Contra las estrellas (M0):** κ 0.68 y recall de `NEG` 66 % en el *dev*. Las estrellas esconden una de cada tres quejas; M4 pierde el 2.4 % en el *test* (5 de 212).
* **Casos difíciles** (*dev* dirigido, n = 297): κ 0.63, contra 0.61 de Gemini.
* **Entre personas:** κ 0.81–0.87 con un segundo anotador (100 reseñas). Diferencias de ~0.02 entre los mejores modelos quedan por debajo de ese ruido.
* **Por banco:** contra la plata en `holdout_nuevo`, κ de 0.92 a 0.97 (corrida del Mac). No hay oro suficiente para medirlo contra humanos por banco.
* **Revisión humana** (curva de cobertura y riesgo de 5.6, oro *dev*): con 90 % de cobertura se revisa el ~10 % menos seguro (~350 textos por semana). El error entre lo que se acepta sin revisión es 0.42 % [0.03, 1.06], la revisión atrapa el 87 % de los errores y una de cada cuatro reseñas revisadas (24.9 %) necesita corrección.
* **Validación con una semana real** (5.9, 2026-10-23; revisión del autor a ciegas de la cola del 2026-10-05 al 11): con el umbral del 90 % del *dev*, la cobertura real fue 86.4 % (cola de 387 textos, no ~350). La tasa de corrección fue **18.3 % [14.6, 22.6]** en 356 evaluables, menor que la esperada; el 8.0 % de la cola fue no evaluable. Los errores se concentran en lo predicho `POS` (33 % corregido, casi siempre a `NEG`: elogios con una queja), y lo predicho `NEG` casi no se corrige (5 %). Revisar la cola tomó ~80 min activos (mediana de 7 s por reseña).

**Costo de operación** (5.7): T4 a ~4 000 textos/s (backfill de 1 429 675 textos únicos en ~6 min por semilla); Cloud Run de 1 vCPU y 2 GiB a 22.6 textos/s en fp32 (delta diario de ~500 textos en ~25 s). No cabe en 1 GiB.

## 4. Datos de evaluación y de entrenamiento

* **Oro:** 1 700 reseñas anotadas por el autor (400 de `gold_v0_r2` y 1 300 de `gold_v1`, con la guía de sentimiento `v2`, vigente `v2.2`), divididas en *dev* (799 aleatorias y 300 dirigidas; 794 y 297 evaluables) y *test* (601 aleatorias, 594 evaluables). Las aleatorias tienen pesos de diseño (1/π) para estimar la población.
* **Plata:** etiquetas de Gemini sobre una muestra estratificada del corpus; κ 0.93 contra el oro.
* Detalle en la [Data Card](data_card.md).

## 5. Límites y riesgos

Cada riesgo tiene su fila en la [FMEA](ethical_fmea_matrix.md) cuando aplica.

1. **Licencia no comercial** de `pysentimiento` (P8-2). El modelo sirve para la tesis; un uso comercial exige reentrenar desde un checkpoint sin esa restricción o usar M9 (F-16).
2. **`NEU` es la clase débil:** F1 de 0.63 contra 0.72 de Gemini. Casi todos sus errores van a `POS`. Afecta poco a Q1, que depende de `NEG`.
3. **Casos difíciles:** en el *dev* dirigido el error sigue en 17–23 % aun revisando el 20 %, y la confianza calibrada vale menos ahí (ECE 0.10–0.14). Una predicción incierta aceptada sin revisión puede priorizar mal (F-17).
4. **Aprende el criterio de Gemini,** incluidos sus sesgos: su techo práctico es el acuerdo de Gemini con el oro.
5. **Oro de un solo anotador principal** (el autor), con κ 0.81–0.87 contra un segundo anotador en 100 reseñas. Las métricas heredan su criterio (F-20).
6. **Familias y tópicos dependen de Gemini:** las 11 familias `aspects_v2_1` son etiquetas de Gemini, con κ de 0.55 a 0.86 contra el autor según la familia (F-18).
7. **Sin detección de incidentes:** la detección automática quedó fuera del alcance (decisión del autor, 2026-10-22). El dashboard muestra por día los temas de las negativas como descripción; un pico no es un incidente confirmado (F-19).
8. **`fecha` es la de la última edición** de la reseña, no la de creación. Las series pueden desplazar una queja al mes en que se editó.
9. **PII residual:** la sanitización es solo regex y no detecta nombres (F-01: 0 nombres en 1 300 reseñas anotadas, con una cota superior al 95 % de ~0.4 %).
10. **Corpus fuera de GCP:** el entrenamiento (F-13) y el backfill (F-14) se hicieron en Kaggle, con el riesgo aceptado por el autor.
11. **Paridad dialectal no evaluada:** la especificación original pedía comparar el español estándar con modismos mexicanos usando un corpus sintético. Se sacó del alcance, así que queda como limitación declarada.
12. **No es representativo de la clientela:** las reseñas públicas son una muestra autoseleccionada. El *gap* mide la brecha entre las estrellas y el texto de quienes escriben, no la satisfacción del total de clientes.

## 6. Monitoreo y ciclo de vida

* **κ de M4 cada trimestre** en una muestra humana a ciegas de 300 reseñas (`monitor_sample`). Si queda debajo de 0.89, se pide reentrenar (P7-10).
* **Avisos semanales** que no disparan solos: tasa de corrección de la cola HITL > 28 % y acuerdo M4–Gemini < 94 %, ambos en 4 semanas.
* **Deriva de entrada y de predicción** por banco, con la `drift_policy` de cada banco (P7-9).
* **Promoción y *re-scoring*:** al promover un modelo se re-predice todo el histórico en Kaggle, con `model_version` por predicción (P7-4).
