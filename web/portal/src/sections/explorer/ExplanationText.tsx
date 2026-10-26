import type { Explanation } from "@/api/reviews";
import {
  alpha,
  backgroundOf,
  direction,
  segments,
  topWords,
} from "@/sections/explorer/explanation";

const FIXED_NOTE =
  "Indica qué palabras movieron la predicción del modelo; no es la causa técnica del fallo.";
const V1_NOTE =
  "Explicación anterior: solo mide cuánto sostiene cada palabra la clase predicha.";

function tip(a: Explanation["attributions"][number]): string | undefined {
  if (a.d_neg != null && a.d_neu != null && a.d_pos != null)
    return `NEG ${signed(a.d_neg)} · NEU ${signed(a.d_neu)} · POS ${signed(a.d_pos)}`;
  if (a.weight != null)
    return `Sostiene la clase predicha: ${signed(a.weight)}`;
  return undefined;
}

function signed(x: number): string {
  return `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(2)}`;
}

function Legend() {
  const steps = [0.1, 0.25, 0.5];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-muted">
      <span>Empuja hacia NEG</span>
      <span className="flex gap-0.5" aria-hidden="true">
        {[...steps].reverse().map((s) => (
          <span
            key={`n${s}`}
            className="size-4 rounded-sm"
            style={{ background: `rgba(178, 58, 46, ${alpha(s)})` }}
          />
        ))}
        <span className="size-4 rounded-sm border border-border" />
        {steps.map((s) => (
          <span
            key={`p${s}`}
            className="size-4 rounded-sm"
            style={{ background: `rgba(0, 104, 94, ${alpha(s)})` }}
          />
        ))}
      </span>
      <span>Empuja hacia POS</span>
      <span>Más intenso = movió más la predicción</span>
    </div>
  );
}

export function ExplanationText({
  text,
  explanation,
}: {
  text: string;
  explanation: Explanation;
}) {
  const directed = explanation.method === "occlusion_v2";
  const top = directed ? topWords(text, explanation.attributions) : null;
  return (
    <div className="grid gap-3">
      <p
        lang="es"
        className="whitespace-pre-wrap font-serif text-base leading-8"
        data-testid="texto-explicado"
      >
        {segments(text, explanation.attributions).map((s, i) =>
          s.attribution ? (
            <mark
              // biome-ignore lint/suspicious/noArrayIndexKey: posiciones fijas del texto.
              key={i}
              title={tip(s.attribution)}
              data-direction={
                direction(s.attribution) === null
                  ? "v1"
                  : (direction(s.attribution) as number) < 0
                    ? "neg"
                    : "pos"
              }
              className="rounded-sm text-inherit"
              style={{ background: backgroundOf(s.attribution) }}
            >
              {s.text}
            </mark>
          ) : (
            // biome-ignore lint/suspicious/noArrayIndexKey: posiciones fijas del texto.
            <span key={i}>{s.text}</span>
          ),
        )}
      </p>
      {directed ? <Legend /> : null}
      {top ? (
        <dl className="grid gap-1 text-sm sm:grid-cols-2">
          <div>
            <dt className="font-semibold">Más empujan hacia NEG</dt>
            <dd>{top.toNeg.length > 0 ? top.toNeg.join(", ") : "—"}</dd>
          </div>
          <div>
            <dt className="font-semibold">Más empujan hacia POS</dt>
            <dd>{top.toPos.length > 0 ? top.toPos.join(", ") : "—"}</dd>
          </div>
        </dl>
      ) : (
        <p className="text-sm text-warning" role="note">
          {V1_NOTE}
        </p>
      )}
      <p className="text-xs text-text-muted">{FIXED_NOTE}</p>
    </div>
  );
}
