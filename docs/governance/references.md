# Referencias y soporte bibliográfico

Documento de gobernanza que consolida la bibliografía del caso de uso
(`caso_de_uso_formato`, v1.0, 2026-09-30) con la literatura añadida para
sustentar las decisiones técnicas de EPIC-4 a EPIC-7. Está pensado para
alimentar la **Model Card**, la **Data Card** y la **Matriz Ethical FMEA**.

## Convenciones

**Nivel de verificación** (columna *Verif.*). Las entradas no son equivalentes;
no citar como leído lo que solo se vio como resumen.

| Marca | Significado |
| :---: | :--- |
| ✔ | Texto del paper leído (total o parcial, se indica) |
| ◐ | Solo resumen, metadatos o ficha del editor, obtenidos por búsqueda web. Abrir el paper antes de citar cifras |
| ✖ | No localizado o entrada incompleta. Requiere acción del autor del caso de uso |
| +M | Sufijo: la afirmación que el proyecto usa se **midió en este corpus** (EPIC-5). No sustituye la lectura del paper |

**Origen** (columna *Fuente*): `CU` = ya citada en el caso de uso; `Nueva` =
añadida en esta revisión.

---

## 1. Ruido de etiquetas: la base del método (EPIC-5)

El problema central es que las estrellas son una etiqueta ruidosa del
sentimiento del texto. Esta sección sustenta tanto el problema como el método.

### 1.1 El fenómeno: estrellas incongruentes con el texto

| Referencia | Fuente | Verif. | Qué aporta | Uso en el proyecto |
| :--- | :---: | :---: | :--- | :--- |
| Abaliyan et al. (2026). [*Fault of Our Stars: Behavioral Drivers of Rating–Sentiment Incongruence*](https://arxiv.org/pdf/2606.25518). arXiv 2606.25518 | CU | ◐ | Define patrones de incongruencia entre calificación y texto, entre ellos *Obligatory 5-Star*. Reporta 18.6 % de incongruencia en 16,156 reseñas de atracciones turísticas de Sri Lanka | Origen del término *Obligatory 5-Star* y del concepto LNB. **Ver correcciones C1 y C4** (el 28.3 % se reemplaza por lo medido en este corpus) |
| Gantayat y Mohapatra (2017; autoría según la ficha de IBM Research, verificar). [*Fault in your stars: An Analysis of Android App Reviews*](https://arxiv.org/pdf/1708.04968). arXiv 1708.04968 | Nueva | ◐ | Con 8,600 reseñas leídas a mano de 10 apps Android, ~20 % de las calificaciones no coincide con el texto; el rango estimado va de 16 % a 26 % según la app | Evidencia en **apps móviles** (el anterior es turismo). Respalda el problema con un dominio más cercano |
| Molla et al. (2026). [*A Multi-Model Approach to English-Bangla Sentiment Classification of Government Mobile Banking App Reviews*](https://arxiv.org/pdf/2604.13057). arXiv 2604.13057 | CU | ◐ +M | Reseñas de apps bancarias de Google Play. Compara etiquetas por estrellas contra un clasificador XLM-R y obtiene acuerdo moderado (κ = 0.459). Los modelos clásicos igualan o superan a los transformers en datos pequeños | Evidencia de ruido en **apps bancarias**. También una advertencia: un baseline clásico (TF-IDF + SVM/RF) debe estar en la escalera de modelos de EPIC-5. **Verificado en este corpus (5.4, fase A):** un clásico compite. M1 (TF-IDF + LR entrenado con la plata) logra κ 0.91 contra el oro *dev* (n = 199); Gemini, 0.94; la diferencia no es significativa (IC 95 % [−0.01, 0.08]). [Reporte](../analytics/sentiment/sentiment_models_v0_report.md) |
| *Beyond Stars: Bridging the Gap Between Ratings and Review Sentiment with LLM* (2025). [arXiv 2509.20953](https://arxiv.org/pdf/2509.20953) | Nueva | ◐ | Mide la brecha entre estrellas y sentimiento del texto en escala 1–5 y la reporta como diferencia absoluta | Precedente del *Satisfaction Gap* (`tnss_numeric_calibrated − estrellas`) |

### 1.2 El método: Delora y su base teórica

| Referencia | Fuente | Verif. | Qué aporta | Uso en el proyecto |
| :--- | :---: | :---: | :--- | :--- |
| Yuan, Chen y Zhang (2025). [*Weed Out, Then Harvest: Dual Low-Rank Adaptation is an Effective Noisy Label Detector for Noise-Robust Learning*](https://aclanthology.org/2025.findings-acl.792/). Findings of ACL 2025; [arXiv 2510.10208](https://arxiv.org/abs/2510.10208) | CU (citada como "Yuan et al., 2024") | ✔ (lectura del HTML, 100 000 de 103 009 caracteres) | **Es el origen de "Delora".** Dos LoRA: la *limpia* minimiza la entropía cruzada sobre las etiquetas observadas y la *ruidosa* actúa como umbral aprendible por muestra. Una muestra es limpia si la LoRA limpia ajusta mejor su etiqueta que la ruidosa. Con las muestras seleccionadas se entrena el clasificador. **Ver sección 1.3** | Fundamento de `model.py`, `train.py` y del KPI de eficacia de desacoplamiento. **Ver corrección C2** |
| Steele (2026). [*Why LoRA Resists Label Noise: A Theoretical Framework for Noise-Robust Parameter-Efficient Fine-Tuning*](https://arxiv.org/abs/2602.00084). arXiv 2602.00084 | Nueva | ◐ | Argumenta que un LoRA de rango *r* no puede memorizar todas las asignaciones de etiquetas, que existe un rango óptimo según la tasa de ruido y que los patrones limpios se aprenden antes que los ruidosos | Justifica por qué un LoRA de rango bajo ayuda frente a ruido y por qué el rango es un hiperparámetro a seleccionar |
| Hu et al. (2022). [*LoRA: Low-Rank Adaptation of Large Language Models*](https://arxiv.org/pdf/2106.09685). ICLR 2022 | Nueva | ◐ | Define LoRA; está en la biblioteca `peft` | Base de `model.py` |
| Bini, Girrbach y Akata (2025). [*DeLoRA: Decoupling Angles and Strength in Low-Rank Adaptation*](https://arxiv.org/abs/2503.18225). ICLR 2025 | Nueva | ✔ (páginas 1–9 de 18) | Variante de LoRA: normaliza la actualización y la escala con un λ aprendible; más robusta al learning rate y al entrenamiento largo. En RoBERTa-base/GLUE promedia 85.6 frente a 84.7 de LoRA. **No trata ruido de etiquetas** | Variante opcional del adaptador. **Colisión de nombre con Delora de Yuan (C3)** |
| Xu et al. (2025). [*Dual LoRA: Enhancing LoRA with Magnitude and Direction Updates*](https://arxiv.org/abs/2512.03402). arXiv 2512.03402 | Nueva | ✔ (fuente LaTeX completa) | Divide la actualización en grupo de magnitud (`ReLU(BA)`) y de dirección (`Sign(DC)`, con *straight-through estimator*). Requiere *warm-up* y cuesta hasta ~5 % más memoria y tiempo. **No trata ruido de etiquetas** | No se adopta: requiere código propio y la mejora es pequeña. Conservar solo como contexto. **Mismo riesgo de nombre (C3)** |

### 1.3 Divergencias entre el paper de Delora y la especificación anterior (`epic_5_deployment.md`, hoy anexo de `epic_6.md`)

La especificación actual no sigue el método publicado. Hay que decidir de forma
explícita si se adapta o se reemplaza.

| Aspecto | Delora (Yuan et al., 2025) | Especificación anterior (anexo de `epic_6.md`) |
| :--- | :--- | :--- |
| Función | **Detector de muestras ruidosas** en una primera etapa; la clasificación final se entrena aparte con las muestras seleccionadas | Un único modelo con dos ramas en el forward |
| Rama ruidosa | Umbral aprendible por muestra, sin entradas extra | Condicionada a `estrellas` con un módulo de transición |
| Criterio limpio/ruidosa | Pérdida de la LoRA limpia menor que la de la ruidosa (Eq. 3) | `is_obligatory_5_star_bias = estrellas >= 4 and tnss_score == NEG` |
| Regularización | Dinámica: τ₁(t)=t^h₁ y τ₂(t)=t^−h₂ sobre el cambio de parámetros entre épocas | Pérdida conjunta con "regularización de separación" sin definir |
| Entrenamiento del detector | Positivos con pseudo-etiqueta de GPT-4o coincidente con la etiqueta observada; negativos con etiqueta volteada aleatoriamente | No existe |
| Etapa 2 | Las muestras descartadas se re-etiquetan con un LLM y se entrenan con *reversed cross-entropy* | No existe |
| Modelo base | Llama-3.1-8B-Instruct, LoRA r=32 en `query` y `value` | RoBERTuito (~110 M) |
| Necesita conjunto limpio | Los hiperparámetros se eligen con un conjunto de desarrollo limpio | "Conjunto de evaluación curado" sin definir cómo se obtiene |

Consecuencias a decidir en la reescritura de EPIC-5:

- **Viabilidad de cómputo.** El paper no valida el método en modelos tipo RoBERTa. Un modelo de 8 B no cabe en Cloud Run CPU en Free Tier.
- **Dependencia de un LLM externo** para pseudo-etiquetas y re-etiquetado. Aunque el texto ya pasó por DLP, hay que validarlo con la Norma de Gobierno de Datos de BBVA antes de enviarlo fuera del perímetro.
- **Errores del paper (verificados contra el HTML de arXiv 2510.10208, 2026-10-20).**
  - **Eq. 5:** p_c = e^{CE_c} / (e^{CE_c} + e^{CE_n}) = σ(CE_c − CE_n). Da más probabilidad de limpia cuanto peor ajusta la LoRA limpia, lo que contradice la Eq. 3 y la frase del propio paper ("p_c > 0.5" equivale a la Eq. 3). La implementación usa σ(CE_n − CE_c).
  - **Eq. 6:** L_Detector = (1/N_p) Σ ℓ_nll(p_c, y) + ℓ_nll(1 − p_c, y^n). Tiene tres problemas:
    1. arrastra el signo de la Eq. 5, así que minimizarla tal cual entrena al detector al revés;
    2. aplica una NLL multiclase a una probabilidad escalar;
    3. no indica que el segundo p_c se evalúa en la etiqueta volteada y^n; leída literalmente, la pérdida es degenerada.
  - Lo que el paper pretende, y lo que se implementa, es la BCE estándar: −log p_c(x, y) − log(1 − p_c(x, y^n)) sobre D_p.
  - El detector logra 0.93 de precisión contra la plata fuera de muestra, lo que es consistente con el signo corregido.
  - Detalle en la [competencia de modelos](../analytics/sentiment/sentiment_models_v0_report.md), sección 12, "Errores del paper en las Eq. 5 y 6".
- **Hiperparámetros h₁ y h₂** sensibles a la tasa de ruido, sin valor por defecto. Requieren búsqueda, lo que justifica la fase de experimentación.

### 1.4 Técnicas complementarias de ruido de etiquetas

| Referencia | Fuente | Verif. | Qué aporta | Uso en el proyecto |
| :--- | :---: | :---: | :--- | :--- |
| Song et al. (2023). [*Learning from Noisy Labels with Deep Neural Networks: A Survey*](https://arxiv.org/pdf/2007.08199). IEEE TNNLS 34(11) | Nueva | ◐ | Taxonomía y comparación de métodos. Las versiones de arXiv difieren (46 a 62 métodos); citar la publicada | Marco general y justificación de la elección de método |
| Sukhbaatar et al. (2015). [*Training Convolutional Networks with Noisy Labels*](https://arxiv.org/pdf/1406.2080). ICLR Workshop | Nueva | ◐ | Capa de ruido entre softmax y pérdida, con matriz Q aprendida | Alternativa documentada a la selección de muestras: corrección con matriz de transición |
| Patrini et al. (2017). [*Making Deep Neural Networks Robust to Label Noise: A Loss Correction Approach*](https://arxiv.org/pdf/1609.03683). CVPR 2017 | Nueva | ◐ | Corrección *forward* (multiplicar por T) y *backward*, con garantías; *forward* domina en sus experimentos | Baseline de comparación para Delora |
| *Is BERT Robust to Label Noise? A Study on Learning with Noisy Labels in Text Classification* (2022). [arXiv 2204.09371](https://arxiv.org/pdf/2204.09371) | Nueva | ◐ | Estudio en texto con BERT; incluye un baseline con matriz de ruido tras las predicciones | Baseline más cercano en texto |
| *NoisyAG-News: A Benchmark for Addressing Instance-Dependent Noise in Text Classification* (2024). [arXiv 2407.06579](https://arxiv.org/abs/2407.06579) | Nueva | ◐ | El ruido real en texto depende de la instancia y los modelos preentrenados lo manejan peor que el ruido sintético | Limitación a declarar: el ruido de estrellas no es uniforme |
| Northcutt, Jiang y Chuang (2021). [*Confident Learning: Estimating Uncertainty in Dataset Labels*](https://jair.org/index.php/jair/article/view/12125). JAIR 70 | Nueva | ◐ | Estima la distribución conjunta entre etiqueta observada y verdadera; biblioteca `cleanlab`. Mejoró sentimiento en Amazon Reviews | Detector de ruido alternativo y barato para contrastar con Delora |
| Gao et al. (2024). [*Revisiting the Role of Label Smoothing in Enhanced Text Sentiment Classification*](https://arxiv.org/pdf/2312.06522). arXiv 2312.06522 | CU | ◐ | Analiza *label smoothing* con TextCNN, BERT y RoBERTa en ocho datasets | Baseline barato para la escalera de modelos. **Ver corrección C1** |

---

## 2. Modelo base y dominio lingüístico

| Referencia | Fuente | Verif. | Qué aporta | Uso en el proyecto |
| :--- | :---: | :---: | :--- | :--- |
| Pérez et al. (2022). [*RoBERTuito: a pre-trained language model for social media text in Spanish*](https://arxiv.org/abs/2111.09453). LREC 2022 | Nueva | ◐ +M | RoBERTa entrenado con más de 500 M de tuits en español; evaluado en sentimiento (TASS 2020), odio, emoción e ironía | Candidato M2 con `pysentimiento/robertuito-sentiment-analysis`. **Limitación:** preentrenado con tuits, no con reseñas de apps. **Medido (5.4, fase A):** sin ajuste da κ 0.47 en el oro *dev*, peor que las estrellas (0.69). Manda los elogios breves a `NEU` y sigue el esquema de TASS, no la guía v2; en textos de 11–30 palabras llega a κ 0.82. Motiva M4 (ajuste con la plata) |
| Pérez et al. (2021, rev. 2024). [*pysentimiento: A Python Toolkit for Opinion Mining and Social NLP tasks*](https://arxiv.org/abs/2106.09462). arXiv 2106.09462 | Nueva | ◐ | Biblioteca sobre `transformers` con analizadores de sentimiento, odio, ironía y emoción; en español usa RoBERTuito y BETO ajustados con TASS | Implementa M2 en 5.4. **Licencia:** la biblioteca y sus modelos son solo para uso no comercial e investigación, y heredan la licencia de TASS. Cabe en una tesis, no en un uso comercial. Confirmar el texto exacto en el repositorio y en la ficha de cada modelo antes de citarlo |
| BETO ajustado para sentimiento: [`finiteautomata/beto-sentiment-analysis`](https://huggingface.co/finiteautomata/beto-sentiment-analysis), de `pysentimiento`. Modelo base BETO (Cañete et al., 2020; ficha sin verificar) | Nueva | ◐ +M | BERT en español ajustado con TASS 2020 (tuits); mismas etiquetas `NEG`/`NEU`/`POS` y misma licencia no comercial de `pysentimiento` | Candidato M2. **Medido (5.4, fase A):** sin ajuste da κ 0.58 en el oro *dev*, por debajo de las estrellas (0.69); en textos de 11–30 palabras, κ 0.78 |

---

## 3. Calibración, incertidumbre y HITL

| Referencia | Fuente | Verif. | Qué aporta | Uso en el proyecto |
| :--- | :---: | :---: | :--- | :--- |
| Guo et al. (2017). [*On Calibration of Modern Neural Networks*](https://proceedings.mlr.press/v70/guo17a.html). ICML 2017 | Nueva | ◐ | Las redes modernas están mal calibradas; *temperature scaling* lo corrige con un parámetro sin alterar la exactitud | Calibrar probabilidades antes de calcular `prediction_entropy` y fijar el umbral 0.65 |
| Raji et al. (2020). *Closing the AI accountability gap: Defining an end-to-end framework for internal algorithmic auditing*. FAT* 2020 | CU | ✖ (entrada truncada, sin enlace) | Marco de auditoría interna de extremo a extremo | Soporte del protocolo HITL y de la Matriz Ethical FMEA |

Hueco: no hay una referencia de clasificación con rechazo o *selective
prediction* que justifique formalmente enviar a revisión humana las predicciones
de alta entropía. Ver sección 8.

---

## 4. Evaluación con pocas etiquetas humanas

| Referencia | Fuente | Verif. | Qué aporta | Uso en el proyecto |
| :--- | :---: | :---: | :--- | :--- |
| Angelopoulos et al. (2023). [*Prediction-Powered Inference*](https://arxiv.org/pdf/2301.09633). arXiv 2301.09633 | Nueva | ◐ | Combina un conjunto pequeño con etiqueta humana y muchas predicciones de un modelo para obtener intervalos de confianza válidos. La búsqueda no confirmó la revista; verificar antes de citar como *Science* | Reportar KPIs con intervalos usando 600–1000 etiquetas manuales más un conjunto grande etiquetado por LLM |
| Gilardi, Alizadeh y Kubli (2023). [*ChatGPT outperforms crowd-workers for text-annotation tasks*](https://pmc.ncbi.nlm.nih.gov/articles/PMC10372638). PNAS | Nueva | ◐ | Exactitud y acuerdo superiores a crowdworkers a una fracción del costo. Resultados en inglés con tuits y noticias; los autores limitan la generalización | Respalda el pre-etiquetado con LLM del conjunto de oro. Declarar la limitación de idioma |

---

## 5. Explicabilidad (EPIC-7)

| Referencia | Fuente | Verif. | Qué aporta | Uso en el proyecto |
| :--- | :---: | :---: | :--- | :--- |
| Lundberg y Lee (2017). [*A unified approach to interpreting model predictions*](https://arxiv.org/pdf/1705.07874). NeurIPS 30 | CU | ◐ | SHAP: atribuciones aditivas con propiedades teóricas únicas | Mapas de atribución en `explainability.py` |
| Ribeiro, Singh y Guestrin (2016). [*"Why Should I Trust You?": Explaining the Predictions of Any Classifier*](https://arxiv.org/pdf/1602.04938). KDD 2016 | Nueva | ◐ | LIME: explicaciones locales para cualquier clasificador | Alternativa ligera a SHAP, compatible con 1 vCPU / 1 GiB |
| Dhurandhar et al. (2018). *Explanations based on the missing: Towards contrastive explanations with pertinent negatives*. NeurIPS 31 | CU | ✖ (sin enlace verificado) | Explicaciones contrastivas con negativos pertinentes | Respalda la "atribución contrastiva" de EPIC-7 |

---

## 6. Gobernanza, documentación y privacidad

| Referencia | Fuente | Verif. | Qué aporta | Uso en el proyecto |
| :--- | :---: | :---: | :--- | :--- |
| Mitchell et al. (2019). [*Model Cards for Model Reporting*](https://research.google/pubs/model-cards-for-model-reporting/). FAT* 2019 | CU | ◐ | Formato de documentación del modelo | `docs/governance/model_card.md` |
| Gebru et al. (2021). *Datasheets for datasets*. CACM 64(12). DOI 10.1145/3458723 | CU | ✖ (sin enlace verificado) | Formato de documentación de datasets | `docs/governance/data_card.md` |
| Hutchinson et al. (2021). *Towards accountability for machine learning datasets: Practices from software engineering and infrastructure*. FAccT 2021 | CU | ✖ | Ciclo de vida y responsabilidad sobre datasets | `data_card.md` |
| Goldsteen et al. (2023). *AI privacy toolkit*. SoftwareX 22, 101352. DOI 10.1016/j.softx.2023.101352 | CU | ✖ | Herramientas de privacidad para IA | Respaldo de la sanitización PII (EPIC-4) |
| Gama et al. (2014). [*A Survey on Concept Drift Adaptation*](https://researchportal.ip-paris.fr/en/publications/a-survey-on-concept-drift-adaptation/). ACM Computing Surveys 46(4) | Nueva | ◐ | Marco de detección y adaptación a deriva conceptual | `drift_monitor.py` |
| BBVA (2024). *Norma de Gobierno de Modelos de Analítica Avanzada* (NCDATA0001_18, v6.0) | CU | n/a (interna) | Requisitos de gobierno de modelos y auditoría por QA independiente | Gate de promoción del modelo, Fallback Plan |
| BBVA (2025). *Norma Data Governance Grupo BBVA* (N.º 0000010007, v006) | CU | n/a (interna) | TDS, roles SLO y Data Owner, linaje | Diseño del TDS y de la Data Card |
| INAI (2019). *Introducción a la Ley General de Protección de Datos Personales en Posesión de Sujetos Obligados*; INAI (2013), *…en Posesión de los Particulares* | CU | n/a | Marco mexicano de protección de datos | Cumplimiento LFPDPPP; minimización de datos |
| ISO/IEC 29134:2023. *Guidelines for privacy impact assessment* | CU | n/a | Evaluación de impacto en privacidad | Evaluación de impacto de EPIC-4 |
| Tabassi (2023). *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*, NIST AI 100-1 | CU (entrada ausente en el export) | ◐ identificación probable | Gestión del riesgo algorítmico | Matriz Ethical FMEA |
| Agarwal y Agarwal (2023). *A seven-layer model with checklists for standardising fairness assessment throughout the AI lifecycle*. AI and Ethics 4(2). DOI 10.1007/s43681-023-00266-9 | CU | ✖ | Listas de verificación de equidad en el ciclo de vida | Insumo para la Ethical FMEA |
| Floridi (2022). *capAI: A procedure for conducting conformity assessment of AI systems in line with the EU AI Act*. DOI 10.2139/ssrn.4064091 | CU | ✖ | Procedimiento de evaluación de conformidad | Contexto regulatorio opcional |

---

## 7. Contexto ético general (no soporta decisiones técnicas)

Estas referencias del caso de uso enmarcan la sección de ética. Pueden
permanecer en el documento académico, pero no sustentan ninguna decisión de
ingeniería y **no son necesarias** para Model Card, Data Card ni EPIC-5/6.

Bietti (2020); Cervantes et al. (2020); Fjeld et al. (2020); Floridi y Taddeo
(2016); Floridi et al. (2018); Huang et al. (2022); Peters, Calvo y Ryan
(2020); OECD (2019); Harvard Law School Cyberlaw Clinic (2020); Future of
Privacy Forum (2018); García Ricci (2017); Argüelles Toache y Amaro Rosales
(2022); CNBV (2020); IA Responsable (2025).

El Galicia Agonizante (2025), *Sistema de detección de incidencias y priorización
de backlog* (proyecto de titulación, Universidad Panamericana), es el
antecedente directo del caso y la fuente de los KPIs financieros y operativos.
Es interno; no se verificó.

---

## 8. Correcciones necesarias a las citas del caso de uso

| ID | Hallazgo | Acción |
| :---: | :--- | :--- |
| **C1** | Tres entradas llevan identificadores de arXiv de relleno (`2403.00000`, `2401.00000`, `2601.00000`), que no corresponden a ningún paper. Los identificadores reales localizados: Abaliyan et al. → **2606.25518**; Gao et al. → **2312.06522**; Molla et al. → **2604.13057** | Corregir las entradas. El ID de Abaliyan sugiere 2026, no 2024. La búsqueda dio el primer autor como "Abaiyan"; verificar la ortografía en el PDF |
| **C2** | "Yuan et al. (2024)" es **Yuan, Chen y Zhang (2025)**, Findings of ACL 2025 (arXiv 2510.10208, octubre de 2025) | Corregir año y venue en el caso de uso |
| **C3** | "Dual LoRA" y "DeLoRA" se usan en el proyecto para el método de Yuan et al., pero existen otros dos papers con esos nombres (Xu et al.; Bini et al.) que son técnicas distintas de LoRA | Escribir "Delora (Yuan et al., 2025)" y no citar los otros como fundamento. Considerar un nombre que evite la confusión |
| **C4** | El caso de uso afirma que "hasta un 28.3 % de los usuarios otorga 5 estrellas por hábito" citando a Abaliyan. Lo que se vio del paper es **18.6 % de incongruencia total** en reseñas de turismo, con *Obligatory 5-Star* como parte de ellas. **Resuelta con medición propia (5.3):** el 28.3 % no se verificó y no se usa | Reemplazar el 28.3 % por lo medido en las cinco apps (estimación poblacional): estrellas distintas del texto en **9.9 %** (oro, EE 1.7) y **10.9 %** (plata); incongruencia en los extremos (1–2★ con `POS` o 4–5★ con `NEG`) en **4.7 %** (oro, EE 1.3) y **5.0 %** (plata). Fuentes: [oro](../analytics/labeling/gold_v0_r2_report.md) y [plata](../analytics/labeling/silver_v0_report.md). Abaliyan queda solo como origen del término |
| **C5** | El caso de uso reporta 6,140,799 calificaciones pero **788,341 reseñas textuales** para BBVA. Las cifras de volumen que se usaron en la discusión de cómputo (6.17 M para BBVA) coinciden con las calificaciones | Confirmar cuántas reseñas con texto hay por banco. Cambia la estimación de costo de inferencia |
| **C6** | El caso de uso lista *Paridad Dialectal* como KPI (cita Molla et al., 2026) | Si se descarta por alcance, registrarlo como cambio de alcance y como limitación en la Model Card |

## 9. Entradas truncadas o no localizadas

La exportación del caso de uso a Markdown corta la lista de referencias en
"Raji et al. (2020)". Faltan al menos las entradas de la S a la Z. Se citan en
el texto, pero no tienen ficha completa:

| Cita en el texto | Estado | Dónde se usa |
| :--- | :--- | :--- |
| Yang et al. (2021) | ✖ No localizado | ABSA y reducción del MTTD. La búsqueda no devolvió un paper que coincida con ABSA para detección de incidencias |
| Zuhir et al. (2025) | ✖ No localizado | Citado como respaldo del problema, la justificación, la explicabilidad y la brecha de satisfacción |
| Wührl et al. (2026) | ✖ No localizado | Explicabilidad y HITL |
| Youm (2020) | ✖ Ausente | Privacidad por diseño |
| GAO (2021) | ✖ Ausente; probablemente el marco de rendición de cuentas de IA del GAO. Verificar | Protocolo HITL, gobierno |
| Shah y Dubaria (2019); WBCOM (2023) | ✖ Ausentes | Cifrado y perímetro de seguridad |

**Acción:** pasar la lista completa (por ejemplo desde el `.docx` original) para
completar esta tabla. Zuhir (2025) y Yang (2021) son críticas, porque sustentan
varias afirmaciones técnicas del caso de uso.

## 10. Huecos de literatura

- **ABSA para apps bancarias en español.** La búsqueda no encontró un survey ni un dataset. Hay trabajo en inglés, indonesio y un estudio de pagos P2P en España ([Financial Innovation](https://riuma.uma.es/entities/publication/2fce7a10-b5ed-42d5-b55c-30993d5e6702)) de modelado de aspectos latentes, no ABSA estricto. Los ocho tópicos de `ABSATopic` son una taxonomía propia y debe declararse así.
- **Clasificación con rechazo (*selective prediction*)** para justificar el umbral de entropía de HITL.
- **Recuperación semántica con filtros por aspecto** y **PSI/JSD** para drift de datos. Aún no se buscaron.
- **Delora aplicado a un encoder tipo RoBERTa** y a etiquetas derivadas de estrellas. El paper solo evalúa Llama-3.1-8B y datasets de texto con ruido sintético o real distinto; este proyecto es una aplicación no validada.

## 11. Dónde citar cada cosa

| Documento | Referencias a usar |
| :--- | :--- |
| `model_card.md` | Mitchell (2019); Yuan (2025); Guo (2017); Angelopoulos (2023); Pérez (2022); licencia de `pysentimiento` (sección 2) si entra uno de sus modelos; límites de la sección 10 |
| `data_card.md` | Gebru (2021); Hutchinson (2021); Gantayat (2017), Abaliyan, Molla (evidencia de ruido); BBVA (2025) |
| `ethical_fmea_matrix.md` | Raji (2020); Tabassi (2023); Agarwal (2023); Goldsteen (2023); ISO 29134 |
| `epic_5.md` | Sección 1 completa; sección 3 (calibración); sección 4 (evaluación). En la competencia de modelos (5.4) Delora es un candidato, no el fundamento |
| `epic_6.md` | Gama (2014) (monitor de *drift*) |
| `epic_7.md` | Lundberg (2017); Ribeiro (2016); Dhurandhar (2018) |

## 12. Pendientes para la tesis (EPIC-7, 7.4)

La tesis del portal cita desde este documento y solo con entradas verificadas (decisión del autor, 2026-10-24). Faltan tres cosas.

**Entradas que describen el diseño anterior** y hay que actualizar a lo que se implementó:

- sección 1.2 y 1.3: Delora pasó a ser un **resultado negativo** (se probó y se descartó en la competencia de modelos), no el fundamento del método;
- sección 3: Guo et al. (2017) sustenta el *temperature scaling* de RoBERTuito y el umbral por probabilidad máxima calibrada, no la entropía ni el 0.65;
- sección 5: la explicación que se implementó es por oclusión, no SHAP ni LIME;
- sección 10: los ocho `ABSATopic` se reemplazaron por las 11 familias de aspectos con Gemini y los tópicos de BERTopic.

**Métodos usados sin referencia.** Las candidatas de abajo son puntos de partida para buscar; ninguna está verificada:

| Método usado | Candidatas a localizar y verificar |
| :--- | :--- |
| Clasificación con rechazo (curva de cobertura y riesgo, umbral HITL) | Chow (1970), *On optimum recognition error and reject tradeoff*; Geifman y El-Yaniv (2017), *Selective classification for deep neural networks* |
| PPI con ajuste de λ (PPI++) | Angelopoulos, Duchi y Zrnic (2023), *PPI++: Efficient prediction-powered inference*; confirmar la versión publicada del PPI original |
| Tópicos: BERTopic, UMAP, HDBSCAN | Grootendorst (2022), *BERTopic*; McInnes, Healy y Melville (2018), *UMAP*; Campello, Moulavi y Sander (2013), HDBSCAN |
| Embeddings de oraciones (MiniLM) | Reimers y Gurevych (2019), *Sentence-BERT*; Wang et al. (2020), *MiniLM* |
| Deriva: z robusta con MAD y PSI | Leys et al. (2013), sobre la desviación absoluta de la mediana; una referencia formal del PSI (por ejemplo, Yurdakul, 2018) |
| Acuerdo y bootstrap | Cohen (1960), κ; Efron y Tibshirani (1993), *An introduction to the bootstrap* |
| Explicación por oclusión en texto | Li, Monroe y Jurafsky (2016), *Understanding neural networks through representation erasure*; Zeiler y Fergus (2014) |
| Etiquetado con LLM (plata, familias) | La ficha técnica del modelo de Gemini usado; trabajos de anotación con LLM además de Gilardi et al. (2023) |
| MLOps y operación del modelo | Sculley et al. (2015), *Hidden technical debt in machine learning systems*; Kreuzberger, Kühl y Hirschl (2023), *MLOps: overview, definition, and architecture* |

**Entradas del caso de uso sin resolver:** las secciones 8 y 9 (C5, C6 y las citas truncadas). Zuhir (2025) y Yang (2021) siguen siendo críticas si la introducción conserva las afirmaciones que sustentan.
