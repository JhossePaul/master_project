export interface GlossaryEntry {
  term: string;
  short: string;
  long?: string;
  /** Reporte de docs/analytics que respalda la definición, cuando existe. */
  link?: string;
}

const CALIBRATION = "docs/analytics/calibration/calibration_report.md";
const SCALE = "docs/analytics/scale/scale_report.md";
const TOPICS = "docs/analytics/topics/topics_report.md";
const GOLD = "docs/analytics/labeling/gold_v1_report.md";
const SILVER = "docs/analytics/labeling/silver_v0_report.md";
const MODELS = "docs/analytics/sentiment/sentiment_models_v0_report.md";

export const GLOSSARY = {
  ppi: {
    term: "PPI",
    short:
      "Estimación que corrige la proporción cruda con una muestra revisada por personas; trae su intervalo de confianza.",
    long: "Usa pocas reseñas revisadas a mano para medir cuánto se equivoca el modelo y descontar ese error en todas las demás.",
    link: CALIBRATION,
  },
  proporcion_cruda: {
    term: "proporción cruda",
    short:
      "Lo que predice el modelo, contado tal cual y sin corregir su error.",
    link: CALIBRATION,
  },
  gap_estrellas: {
    term: "brecha en estrellas",
    short:
      "Diferencia entre las estrellas que dio la persona y las que sugiere el tono de su texto; negativo significa que el texto es peor que la calificación.",
    link: CALIBRATION,
  },
  cobertura: {
    term: "cobertura",
    short:
      "Proporción de reseñas que el modelo resuelve solo, sin mandarlas a revisión humana.",
    link: CALIBRATION,
  },
  umbral_confianza: {
    term: "umbral de confianza",
    short:
      "Confianza mínima con la que el modelo se queda con su predicción; por debajo, el caso va a revisión.",
    link: CALIBRATION,
  },
  kappa: {
    term: "κ (kappa)",
    short:
      "Acuerdo entre dos juicios descontando el azar: 0 es azar y 1 es acuerdo total.",
    link: GOLD,
  },
  deriva: {
    term: "deriva",
    short:
      "Cambio en lo que el modelo ve (textos, longitudes, proporciones) frente a su línea base; avisa que conviene revisarlo.",
    link: SCALE,
  },
  z_robusto: {
    term: "z robusto",
    short:
      "Distancia a la mediana medida en desviaciones robustas; resiste valores extremos. Desde 4 se abre una alerta.",
    link: SCALE,
  },
  psi: {
    term: "PSI",
    short:
      "Índice de estabilidad de población: compara dos distribuciones; valores altos indican que cambiaron.",
    link: SCALE,
  },
  hitl: {
    term: "HITL",
    short:
      "Revisión con una persona en el circuito: el revisor confirma o corrige lo que predijo el modelo.",
    link: CALIBRATION,
  },
  modo_ciego: {
    term: "modo ciego",
    short:
      "La persona ve la reseña sin la predicción del modelo, para que no se anclen en ella; mide al modelo.",
    link: CALIBRATION,
  },
  modo_asistido: {
    term: "modo asistido",
    short:
      "La persona ve la propuesta del modelo y solo la acepta o la cambia; es más rápido.",
    link: CALIBRATION,
  },
  muestra_monitoreo: {
    term: "muestra de monitoreo",
    short:
      "Reseñas elegidas al azar y revisadas a ciegas cada periodo para medir cómo va el modelo.",
    link: SCALE,
  },
  familia_aspectos: {
    term: "familia de aspectos",
    short:
      "Grupo grande de temas de las quejas (por ejemplo, acceso o pagos) en que se clasifican las reseñas negativas.",
    link: "docs/analytics/eda/eda_aspects_guideline.md",
  },
  marca_u: {
    term: "marca de actualización (u)",
    short: "Señala que la queja habla de una actualización reciente de la app.",
    link: "docs/analytics/eda/eda_aspects_guideline.md",
  },
  marca_s: {
    term: "marca de seguridad (s)",
    short: "Señala que la queja habla de seguridad o fraude.",
    link: "docs/analytics/eda/eda_aspects_guideline.md",
  },
  topico: {
    term: "tópico",
    short:
      "Tema que aparece de forma repetida en las reseñas, hallado por agrupación de textos parecidos.",
    link: TOPICS,
  },
  topico_util: {
    term: "tópico útil",
    short:
      "Tópico con un tema claro y suficientes reseñas para describirlo; los demás se tratan como ruido.",
    link: TOPICS,
  },
  oclusion: {
    term: "oclusión",
    short:
      "Explicación que tapa una palabra a la vez para ver cuánto cambia la predicción; no es la causa técnica del fallo.",
    link: "docs/analytics/scale/explain_cost_v0_metrics.json",
  },
  temperatura: {
    term: "temperatura",
    short:
      "Ajuste que hace que la confianza del modelo se parezca a su acierto real.",
    link: CALIBRATION,
  },
  ece: {
    term: "ECE",
    short:
      "Error de calibración esperado: qué tanto se aleja la confianza del modelo de su acierto real. Menor es mejor.",
    link: CALIBRATION,
  },
  aurc: {
    term: "AURC",
    short:
      "Área bajo la curva riesgo-cobertura: error medio si el modelo se abstiene en los casos dudosos. Menor es mejor.",
    link: CALIBRATION,
  },
  plata: {
    term: "plata",
    short:
      "Etiquetas que pone Gemini a gran escala; sirven para entrenar, pero no son verdad revisada por personas.",
    link: SILVER,
  },
  oro: {
    term: "oro",
    short:
      "Etiquetas revisadas por personas con una guía; son la referencia para medir al modelo.",
    link: GOLD,
  },
  rescoring: {
    term: "re-scoring",
    short: "Volver a predecir el histórico con una versión nueva del modelo.",
    link: SCALE,
  },
  promocion: {
    term: "promoción",
    short:
      "Dejar una versión del modelo como la vigente, después de pasar sus criterios de aceptación.",
    link: MODELS,
  },
  rollback: {
    term: "rollback",
    short: "Volver a una versión anterior del modelo cuando la nueva falla.",
    link: MODELS,
  },
} as const satisfies Record<string, GlossaryEntry>;

export type TermId = keyof typeof GLOSSARY;

export function glossaryEntry(id: TermId): GlossaryEntry {
  return GLOSSARY[id];
}
