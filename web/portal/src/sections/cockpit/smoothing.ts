export type SeriesMetric = "neg" | "gap" | "neg45";

export interface DailyLike {
  dia: string;
  predichas: number;
  neg: number;
  neg_4_5: number;
  gap_crudo: number | null;
}

/** Ventanas del suavizado, en días (1 = sin suavizar). */
export const WINDOWS = [1, 7, 14, 28] as const;
export type SmoothingWindow = (typeof WINDOWS)[number];
export const MAX_WINDOW = 28;

/** "2026-10-26" desplazado ``n`` días. */
export function dayShift(iso: string, n: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + n);
  return date.toISOString().slice(0, 10);
}

function parts(row: DailyLike, metric: SeriesMetric): [number, number] {
  if (metric === "neg") return [row.neg, row.predichas];
  if (metric === "neg45") return [row.neg_4_5, row.predichas];
  return row.gap_crudo === null
    ? [0, 0]
    : [row.gap_crudo * row.predichas, row.predichas];
}

/**
 * Valor de cada día con una ventana que termina en él: suma del numerador
 * entre suma del denominador (el promedio pesa cada día por sus reseñas
 * predichas; promediar proporciones diarias sesgaría los días con poco
 * volumen). ``rows`` es de un solo banco y viene en orden de fecha.
 */
export function rolling(
  rows: DailyLike[],
  window: number,
  metric: SeriesMetric,
): { dia: string; value: number | null }[] {
  return rows.map((row) => {
    const from = dayShift(row.dia, -(window - 1));
    let num = 0;
    let den = 0;
    for (const other of rows) {
      if (other.dia < from || other.dia > row.dia) continue;
      const [n, d] = parts(other, metric);
      num += n;
      den += d;
    }
    return { dia: row.dia, value: den > 0 ? num / den : null };
  });
}
