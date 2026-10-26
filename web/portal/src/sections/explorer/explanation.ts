import type { Attribution } from "@/api/reviews";

export interface Segment {
  text: string;
  /** `null` si la palabra no tiene atribución (espacios y separadores). */
  attribution: Attribution | null;
}

/** Parte `text` en palabras con su atribución y los huecos entre ellas. */
export function segments(text: string, attributions: Attribution[]): Segment[] {
  const sorted = [...attributions].sort((a, b) => a.start - b.start);
  const out: Segment[] = [];
  let cursor = 0;
  for (const a of sorted) {
    if (a.start < cursor || a.end > text.length) continue;
    if (a.start > cursor)
      out.push({ text: text.slice(cursor, a.start), attribution: null });
    out.push({ text: text.slice(a.start, a.end), attribution: a });
    cursor = a.end;
  }
  if (cursor < text.length)
    out.push({ text: text.slice(cursor), attribution: null });
  return out;
}

export interface Probabilities {
  p_neg: number | null;
  p_pos: number | null;
}

const EPSILON = 1e-6;
// Menos de esto en log-odds (≈ 5 % de cambio relativo) es ruido.
const MIN_EFFECT = 0.05;
// Una palabra cuenta si llega al 15 % del mayor efecto del texto.
const MIN_SHARE = 0.15;
const MIN_ALPHA = 0.2;
const MAX_ALPHA = 0.75;

function clamp(p: number): number {
  return Math.min(Math.max(p, EPSILON), 1 - EPSILON);
}

/**
 * Hacia dónde empuja la palabra: positivo = POS, negativo = NEG.
 *
 * Se mide en log-odds de `POS` contra `NEG` con y sin la palabra. En
 * probabilidades, una predicción segura (99 %) casi no se mueve al quitar una
 * palabra y todo parece ruido; en log-odds cada palabra conserva su efecto.
 * Las probabilidades sin la palabra salen de las del texto y los cambios
 * guardados (`p − d`). Sin probabilidades base cae a `d_pos − d_neg`.
 */
export function score(a: Attribution, base?: Probabilities): number | null {
  if (a.d_neg == null || a.d_pos == null) return null;
  if (base?.p_neg == null || base.p_pos == null) return a.d_pos - a.d_neg;
  const full = Math.log(clamp(base.p_pos) / clamp(base.p_neg));
  const without = Math.log(
    clamp(base.p_pos - a.d_pos) / clamp(base.p_neg - a.d_neg),
  );
  return full - without;
}

export interface Reading {
  /** Efecto de cada atribución, en el mismo orden (`null` en v1). */
  scores: (number | null)[];
  /** Mayor efecto absoluto del texto. */
  max: number;
  /** Ninguna palabra mueve la predicción de forma apreciable. */
  flat: boolean;
}

export function read(
  attributions: Attribution[],
  base?: Probabilities,
): Reading {
  const scores = attributions.map((a) => score(a, base));
  const max = Math.max(0, ...scores.map((s) => (s === null ? 0 : Math.abs(s))));
  const directed = scores.some((s) => s !== null);
  return {
    scores,
    max,
    flat: directed && max < (base?.p_neg == null ? 0.002 : MIN_EFFECT),
  };
}

export function significant(value: number | null, reading: Reading): boolean {
  return (
    value !== null &&
    !reading.flat &&
    reading.max > 0 &&
    Math.abs(value) >= reading.max * MIN_SHARE
  );
}

/** Intensidad (opacidad) de una palabra respecto del mayor efecto. */
export function alpha(value: number, max: number): number {
  if (max <= 0) return 0;
  return (
    MIN_ALPHA + (MAX_ALPHA - MIN_ALPHA) * Math.min(Math.abs(value) / max, 1)
  );
}

/** Fondo de la palabra: ladrillo hacia NEG, verde hacia POS; sin efecto, ninguno. */
export function backgroundOf(
  a: Attribution,
  reading: Reading,
  index: number,
): string | undefined {
  const value = reading.scores[index] ?? null;
  if (value === null) {
    // ``occlusion_v1``: una sola dirección, la de la clase predicha.
    if (a.weight == null || a.weight <= 0) return undefined;
    return `rgba(133, 125, 114, ${alpha(a.weight, 0.5)})`;
  }
  if (!significant(value, reading)) return undefined;
  const opacity = alpha(value, reading.max).toFixed(2);
  return value < 0
    ? `rgba(178, 58, 46, ${opacity})`
    : `rgba(0, 104, 94, ${opacity})`;
}

export interface TopWords {
  toNeg: string[];
  toPos: string[];
}

/** Las palabras con efecto claro que más empujan hacia cada lado (v2). */
export function topWords(
  text: string,
  attributions: Attribution[],
  reading: Reading,
  n = 3,
): TopWords {
  const scored = attributions
    .map((a, i) => ({
      word: text.slice(a.start, a.end),
      d: reading.scores[i] ?? null,
    }))
    .filter(
      (x): x is { word: string; d: number } =>
        x.d !== null && significant(x.d, reading),
    );
  const unique = (xs: { word: string }[]) => [
    ...new Set(xs.map((x) => x.word)),
  ];
  return {
    toNeg: unique(
      scored.filter((x) => x.d < 0).sort((a, b) => a.d - b.d),
    ).slice(0, n),
    toPos: unique(
      scored.filter((x) => x.d > 0).sort((a, b) => b.d - a.d),
    ).slice(0, n),
  };
}
