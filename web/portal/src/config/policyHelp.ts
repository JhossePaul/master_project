/** Ayuda de cada parámetro de la política de riesgo y de la de deriva. */
export interface PolicyHelp {
  label: string;
  /** Texto corto de la unidad ("%", "casos por semana"…); vacío si no aplica. */
  unit: string;
  means: string;
  /** De dónde sale el valor vigente. */
  evidence: string;
  /** Reporte de docs/analytics que lo respalda, cuando existe. */
  link?: string;
  up: string;
  down: string;
  min?: number;
  max?: number;
  step?: number;
}

const CALIBRATION = "docs/analytics/calibration/calibration_report.md";
const SCALE = "docs/analytics/scale/scale_report.md";
const GOLD = "docs/analytics/labeling/gold_v1_report.md";

export const RISK_HELP = {
  hitl_target_coverage: {
    label: "Cobertura objetivo",
    unit: "%",
    means:
      "Qué parte de las reseñas se acepta sin revisión humana. El resto, las que el modelo ve menos seguras, pasa a la cola de revisión.",
    evidence:
      "Con 90 % de cobertura se revisan unos 350 textos por semana y el error entre lo aceptado es de 0.4 %.",
    link: CALIBRATION,
    up: "Menos revisión y más error entre lo aceptado.",
    down: "Más revisión (más minutos) y menos error.",
    min: 0.8,
    max: 1,
    step: 0.01,
  },
  hitl_weekly_cap: {
    label: "Tope semanal de revisión",
    unit: "casos por semana",
    means:
      "Máximo de casos que entran a la cola en una semana. Sin tope, entran todos los que pide la cobertura.",
    evidence:
      "Sin evidencia en los experimentos. La semana real de los temas por día dio 387 casos con el umbral del 90 %.",
    up: "Se revisan más casos de la semana.",
    down: "Se revisan solo los primeros N casos de la semana.",
    min: 1,
    step: 1,
  },
  drift_boost_coverage: {
    label: "Cobertura durante una subida",
    unit: "%",
    means:
      "Cobertura que se usa en un banco mientras una alerta de deriva tiene la revisión subida.",
    evidence:
      "Sin evidencia; la curva da el costo de cada cobertura con el volumen del banco.",
    up: "Una alerta sube la revisión de ese banco.",
    down: "Una alerta sube menos la revisión.",
    min: 0.8,
    max: 1,
    step: 0.01,
  },
  drift_boost_days: {
    label: "Días de la subida",
    unit: "días",
    means: "Cuánto dura la revisión subida después de una alerta.",
    evidence: "Sin evidencia en los experimentos.",
    up: "La revisión extra dura más.",
    down: "La revisión extra termina antes.",
    min: 1,
    step: 1,
  },
  drift_boost_weekly_cap: {
    label: "Tope semanal de la subida",
    unit: "casos por semana",
    means: "Máximo de casos extra por semana mientras dura la subida.",
    evidence: "Sin evidencia en los experimentos.",
    up: "Se revisan más casos del banco con alerta.",
    down: "Se revisan menos casos extra.",
    min: 1,
    step: 1,
  },
  monitor_sample_size: {
    label: "Muestra de monitoreo",
    unit: "revisiones por periodo",
    means:
      "Reseñas que se revisan a ciegas cada periodo para medir si el modelo sigue acertando.",
    evidence:
      "Con 300 revisiones el κ detecta la caída al piso de reentrenamiento.",
    link: SCALE,
    up: "Más precisión en el κ y más minutos de revisión.",
    down: "Menos precisión en el κ.",
    min: 50,
    step: 10,
  },
  monitor_frequency: {
    label: "Frecuencia de la muestra",
    unit: "",
    means: "Cada cuánto se toma la muestra de monitoreo.",
    evidence: "Hoy es trimestral, con 300 revisiones por trimestre.",
    link: SCALE,
    up: "Se mide con más frecuencia.",
    down: "Se mide con menos frecuencia.",
  },
  retrain_kappa_floor: {
    label: "Piso de κ para reentrenar",
    unit: "κ",
    means:
      "Si el acuerdo (κ) de la muestra de monitoreo cae por debajo de este valor, se recomienda reentrenar.",
    evidence:
      "Percentil 5 del κ de un modelo sin cambios: así una caída por debajo casi no ocurre por azar.",
    link: SCALE,
    up: "Se reentrena antes.",
    down: "Se tolera más degradación.",
    min: 0.5,
    max: 1,
    step: 0.01,
  },
  retrain_trigger: {
    label: "Quién lanza el reentrenamiento",
    unit: "",
    means:
      "En manual, una persona lo lanza. En automático, el monitor lo lanza al medir que el κ cayó.",
    evidence:
      "Decisión del autor: en automático, el texto sale a Kaggle sin aprobación por corrida.",
    up: "—",
    down: "—",
  },
  topic_refit_frequency: {
    label: "Frecuencia del re-ajuste de tópicos",
    unit: "",
    means: "Cada cuánto se re-ajusta el modelo de tópicos si es programado.",
    evidence: "No hay un umbral con evidencia para re-ajustar tópicos.",
    up: "—",
    down: "—",
  },
  topic_refit_trigger: {
    label: "Quién lanza el re-ajuste de tópicos",
    unit: "",
    means:
      "Programado: según la frecuencia. Manual: solo cuando una persona lo pide.",
    evidence: "No hay un umbral con evidencia para re-ajustar tópicos.",
    up: "—",
    down: "—",
  },
  human_agreement_sample_size: {
    label: "Doble revisión",
    unit: "revisiones por periodo",
    means:
      "Casos que revisa una segunda persona para medir el acuerdo entre revisores. Sin esto no hay doble revisión.",
    evidence:
      "Sin evidencia; el oro tuvo un segundo anotador con κ de 0.81 a 0.87.",
    link: GOLD,
    up: "Más medición del acuerdo y más minutos.",
    down: "—",
    min: 10,
    step: 10,
  },
  human_agreement_frequency: {
    label: "Frecuencia de la doble revisión",
    unit: "",
    means: "Cada cuánto se toma la muestra de doble revisión.",
    evidence: "Sin evidencia en los experimentos.",
    link: GOLD,
    up: "Se mide más seguido.",
    down: "Se mide menos seguido.",
  },
  warn_correction_rate: {
    label: "Aviso por tasa de corrección",
    unit: "%",
    means:
      "Avisa si los revisores corrigen al modelo en más de esta proporción de los casos.",
    evidence: "Tasa de corrección de la cola en los experimentos (4 semanas).",
    up: "Avisa menos.",
    down: "Avisa más.",
    min: 0,
    max: 1,
    step: 0.01,
  },
  warn_agreement_floor: {
    label: "Aviso por acuerdo con Gemini",
    unit: "%",
    means:
      "Avisa si el acuerdo entre el modelo y Gemini en la muestra semanal baja de este valor.",
    evidence:
      "Acuerdo del modelo con Gemini en el análisis de escala; cuesta unos $0.02 por semana.",
    link: SCALE,
    up: "Avisa más.",
    down: "Avisa menos.",
    min: 0,
    max: 1,
    step: 0.01,
  },
  agreement_sample_weekly: {
    label: "Muestra semanal de acuerdo",
    unit: "textos por semana",
    means: "Textos que Gemini vuelve a clasificar cada semana para el aviso.",
    evidence: "500 textos por semana, unos $0.02.",
    link: SCALE,
    up: "Mide el acuerdo con más precisión.",
    down: "Mide con menos precisión.",
    min: 50,
    step: 50,
  },
  families_exact_floor: {
    label: "Piso de familias exactas",
    unit: "%",
    means:
      "Un cambio de prompt de familias se rechaza si acierta menos que esto en las reseñas anotadas.",
    evidence:
      "Revalidación de las familias con las 300 reseñas anotadas por el autor.",
    up: "Rechaza más cambios de prompt.",
    down: "Acepta más cambios de prompt.",
    min: 0,
    max: 1,
    step: 0.01,
  },
  families_min_prevalence: {
    label: "Prevalencia mínima de una familia",
    unit: "%",
    means:
      "Una familia con menos reseñas que esto no se considera en la revalidación.",
    evidence:
      "Revalidación de las familias con las 300 reseñas anotadas por el autor.",
    up: "Rechaza más cambios de prompt.",
    down: "Acepta más cambios de prompt.",
    min: 0,
    max: 1,
    step: 0.01,
  },
} as const satisfies Record<string, PolicyHelp>;

export type RiskField = keyof typeof RISK_HELP;

export const DRIFT_HELP = {
  thresholds: {
    label: "Umbral de alerta por serie",
    unit: "",
    means:
      "Una serie alerta cuando su z robusto (o su PSI, en la longitud) llega a este valor.",
    evidence:
      "Con z ≥ 4 y PSI ≥ 0.25, cada serie alertó de 0 a 1.4 meses al año por banco.",
    link: SCALE,
    up: "Menos alertas.",
    down: "Más alertas (z ≥ 3 daría unas 1.6 veces más).",
  },
  baseline_months: {
    label: "Meses de línea base",
    unit: "meses",
    means: "Meses anteriores que forman la línea base de cada serie.",
    evidence: "Línea base histórica del monitor: 12 meses.",
    link: SCALE,
    up: "Una línea base más estable, pero el banco entra más tarde.",
    down: "Una línea base más ruidosa.",
    min: 1,
    step: 1,
  },
  min_baseline_months: {
    label: "Meses mínimos de línea base",
    unit: "meses",
    means: "Mínimo de meses de historia para que una serie se mida.",
    evidence: "Línea base histórica del monitor: 6 meses.",
    link: SCALE,
    up: "Entra más tarde.",
    down: "Entra antes, con menos historia.",
    min: 1,
    step: 1,
  },
  min_rows_per_month: {
    label: "Reseñas mínimas por mes",
    unit: "reseñas",
    means: "Un mes con menos reseñas que esto no se evalúa.",
    evidence: "Línea base histórica del monitor: 200 reseñas.",
    link: SCALE,
    up: "Se descartan más meses de poco volumen.",
    down: "Entran meses más ruidosos.",
    min: 1,
    step: 10,
  },
  entry_months: {
    label: "Meses seguidos para entrar",
    unit: "meses",
    means:
      "Meses seguidos con el mínimo de reseñas antes de que el banco entre al monitor.",
    evidence: "Línea base histórica del monitor: 12 meses.",
    link: SCALE,
    up: "Entra más tarde, con una base más estable.",
    down: "Entran antes más bancos y meses.",
    min: 1,
    step: 1,
  },
} as const satisfies Record<string, PolicyHelp>;

export type DriftParam = Exclude<keyof typeof DRIFT_HELP, "thresholds">;
