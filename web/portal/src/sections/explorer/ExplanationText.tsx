import type { Explanation } from "@/api/reviews";
import {
  alpha,
  backgroundOf,
  type Probabilities,
  read,
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
  const steps = [0.25, 0.6, 1];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-muted">
      <span>Empuja hacia NEG</span>
      <span className="flex gap-0.5" aria-hidden="true">
        {[...steps].reverse().map((s) => (
          <span
            key={`n${s}`}
            className="size-4 rounded-sm"
            style={{ background: `rgba(178, 58, 46, ${alpha(s, 1)})` }}
          />
        ))}
        <span className="size-4 rounded-sm border border-border" />
        {steps.map((s) => (
          <span
            key={`p${s}`}
            className="size-4 rounded-sm"
            style={{ background: `rgba(0, 104, 94, ${alpha(s, 1)})` }}
          />
        ))}
      </span>
      <span>Empuja hacia POS</span>
      <span>
        Más intenso = movió más la predicción, respecto de la palabra que más la
        movió en este texto. Sin color: casi no la movió.
      </span>
    </div>
  );
}

export function ExplanationText({
  text,
  explanation,
  probabilities,
}: {
  text: string;
  explanation: Explanation;
  /** Probabilidades calibradas del texto completo (de la fila). */
  probabilities?: Probabilities;
}) {
  const directed = explanation.method === "occlusion_v2";
  const reading = read(explanation.attributions, probabilities);
  const index = new Map(explanation.attributions.map((a, i) => [a, i]));
  const top = directed
    ? topWords(text, explanation.attributions, reading)
    : null;
  return (
    <div className="grid gap-3">
      <p
        lang="es"
        className="whitespace-pre-wrap font-serif text-base leading-8"
        data-testid="texto-explicado"
      >
        {segments(text, explanation.attributions).map((s, i) => {
          const a = s.attribution;
          if (!a)
            // biome-ignore lint/suspicious/noArrayIndexKey: posiciones fijas del texto.
            return <span key={i}>{s.text}</span>;
          const at = index.get(a) ?? 0;
          const value = reading.scores[at] ?? null;
          const background = backgroundOf(a, reading, at);
          return (
            <mark
              // biome-ignore lint/suspicious/noArrayIndexKey: posiciones fijas del texto.
              key={i}
              title={tip(a)}
              data-direction={
                value === null
                  ? "v1"
                  : background === undefined
                    ? "none"
                    : value < 0
                      ? "neg"
                      : "pos"
              }
              className="rounded-sm bg-transparent text-inherit"
              style={background ? { background } : undefined}
            >
              {s.text}
            </mark>
          );
        })}
      </p>
      {directed ? <Legend /> : null}
      {top ? (
        reading.flat ? (
          <p className="text-sm">
            Ninguna palabra mueve la predicción de forma apreciable: la
            predicción es muy segura y no depende de una palabra en concreto.
          </p>
        ) : (
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
        )
      ) : (
        <p className="text-sm text-warning" role="note">
          {V1_NOTE}
        </p>
      )}
      <p className="text-xs text-text-muted">{FIXED_NOTE}</p>
    </div>
  );
}
