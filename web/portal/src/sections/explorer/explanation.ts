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

/** Hacia dónde empuja la palabra: positivo = POS, negativo = NEG. */
export function direction(a: Attribution): number | null {
  if (a.d_neg == null || a.d_pos == null) return null;
  return a.d_pos - a.d_neg;
}

const MAX_ALPHA = 0.75;
// Un cambio de 0.5 en la diferencia ya es la intensidad máxima.
const FULL_SCALE = 0.5;

export function alpha(value: number): number {
  return Math.min(Math.abs(value) / FULL_SCALE, 1) * MAX_ALPHA;
}

/** Fondo de la palabra: ladrillo hacia NEG, verde hacia POS (v2). */
export function backgroundOf(a: Attribution): string | undefined {
  const d = direction(a);
  if (d === null) {
    // ``occlusion_v1``: una sola dirección, la de la clase predicha.
    if (a.weight == null || a.weight <= 0) return undefined;
    return `rgba(133, 125, 114, ${alpha(a.weight)})`;
  }
  const a1 = alpha(d);
  if (a1 < 0.04) return undefined;
  return d < 0 ? `rgba(178, 58, 46, ${a1})` : `rgba(0, 104, 94, ${a1})`;
}

export interface TopWords {
  toNeg: string[];
  toPos: string[];
}

/** Las palabras que más empujan hacia cada lado (solo `occlusion_v2`). */
export function topWords(
  text: string,
  attributions: Attribution[],
  n = 3,
): TopWords {
  const scored = attributions
    .map((a) => ({ word: text.slice(a.start, a.end), d: direction(a) }))
    .filter((x): x is { word: string; d: number } => x.d !== null);
  const unique = (xs: { word: string }[]) => [
    ...new Set(xs.map((x) => x.word)),
  ];
  return {
    toNeg: unique(
      scored
        .filter((x) => x.d < 0)
        .sort((a, b) => a.d - b.d)
        .slice(0, n * 2),
    ).slice(0, n),
    toPos: unique(
      scored
        .filter((x) => x.d > 0)
        .sort((a, b) => b.d - a.d)
        .slice(0, n * 2),
    ).slice(0, n),
  };
}
