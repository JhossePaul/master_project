import { formatPct } from "@/lib/format";
import { FAMILY_NAMES } from "@/sections/cockpit/shared";

export interface DriftSeries {
  label: string;
  /** Estadístico del umbral: `z` (robusto, contra los 12 meses previos) o `psi`. */
  kind: "z" | "psi";
  format: (value: number) => string;
}

const ONE_DECIMAL = new Intl.NumberFormat("es-MX", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const THREE_DECIMALS = new Intl.NumberFormat("es-MX", {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
});

const pct = (value: number) => formatPct(value);
const FAMILY_PREFIX = "family_";

/** Nombre en lenguaje común de cada serie que mide el monitor de deriva. */
const SERIES: Record<string, DriftSeries> = {
  mean_words: {
    label: "Palabras por reseña",
    kind: "z",
    format: (v) => ONE_DECIMAL.format(v),
  },
  single_word_share: {
    label: "Proporción de reseñas de una palabra",
    kind: "z",
    format: pct,
  },
  over_60_words_share: {
    label: "Proporción de reseñas de más de 60 palabras",
    kind: "z",
    format: pct,
  },
  not_predicted_share: {
    label: "Proporción de reseñas que el modelo no clasifica",
    kind: "z",
    format: pct,
  },
  out_of_vocabulary_share: {
    label: "Proporción de palabras fuera del vocabulario de entrenamiento",
    kind: "z",
    format: pct,
  },
  neg_share: { label: "Proporción de negativas", kind: "z", format: pct },
  flag_update_share: {
    label: "Proporción de menciones de actualización",
    kind: "z",
    format: pct,
  },
  length_distribution: {
    label: "Distribución de la longitud de las reseñas",
    kind: "psi",
    format: (v) => THREE_DECIMALS.format(v),
  },
  topic_noise_share: {
    label: "Proporción de cláusulas sin tópico",
    kind: "z",
    format: pct,
  },
  topic_unaligned_share: {
    label: "Proporción de negativas sin familia curada",
    kind: "z",
    format: pct,
  },
};

export function driftSeries(series: string): DriftSeries {
  const known = SERIES[series];
  if (known) return known;
  if (series.startsWith(FAMILY_PREFIX)) {
    const code = series.slice(FAMILY_PREFIX.length);
    return {
      label: `Familia: ${FAMILY_NAMES[code] ?? code}`,
      kind: "z",
      format: pct,
    };
  }
  return { label: series, kind: "z", format: (v) => ONE_DECIMAL.format(v) };
}

/** El umbral como se lee: "z ≥ 4" o "PSI ≥ 0.25". */
export function formatThreshold(series: string, threshold: number): string {
  const number = new Intl.NumberFormat("es-MX", {
    maximumFractionDigits: 2,
  }).format(threshold);
  return driftSeries(series).kind === "psi"
    ? `PSI ≥ ${number}`
    : `z ≥ ${number}`;
}
