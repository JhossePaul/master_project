import { type MatrixCell, useMatrix } from "@/api/kpis";
import { ChartFrame } from "@/components/ChartFrame";
import { ErrorState } from "@/components/ErrorState";
import type { BankId } from "@/config/banks";
import { formatMonth, formatPct, formatPctRange } from "@/lib/format";
import { LoadingBlock } from "./shared";

const CLASSES = ["NEG", "NEU", "POS"] as const;
const LABEL = { NEG: "negativo", NEU: "neutro", POS: "positivo" } as const;
const STARS = { NEG: "1–2 ★", NEU: "3 ★", POS: "4–5 ★" } as const;

export function MatrixBlock({
  bank,
  period,
}: {
  bank: BankId;
  period: string | null;
}) {
  const matrix = useMatrix(bank, period);
  if (matrix.isPending) return <LoadingBlock />;
  if (matrix.isError)
    return <ErrorState error={matrix.error} onRetry={() => matrix.refetch()} />;
  const cells = new Map<string, MatrixCell>(
    matrix.data.map((c) => [`${c.stars_class}|${c.text_class}`, c]),
  );
  const shown = matrix.data[0]?.period ?? period;
  return (
    <ChartFrame
      kicker="Estrellas × texto"
      title="Qué dicen las estrellas y qué dice el texto"
      subtitle={shown ? formatMonth(shown) : undefined}
      method="ppi"
      howToRead={
        <p>
          Cada reseña cae en una celda según sus estrellas (renglón) y el tono
          de su texto (columna). Las celdas con borde, estrellas altas con texto
          negativo o estrellas bajas con texto positivo, son las incongruencias
          que explican la brecha en estrellas.
        </p>
      }
      provenance={{
        note: "estimación mensual del monitor semanal",
      }}
      data={{
        columns: ["Estrellas", "Texto", "Con revisión humana", "Solo modelo"],
        rows: matrix.data.map((c) => [
          STARS[c.stars_class],
          LABEL[c.text_class],
          c.ppi ? formatPct(c.ppi.estimate) : null,
          c.raw ? formatPct(c.raw.estimate) : null,
        ]),
      }}
    >
      {matrix.data.length === 0 ? (
        <p className="text-sm text-text-muted">
          Sin estimaciones para este mes.
        </p>
      ) : (
        <table className="w-full max-w-2xl border-separate border-spacing-1 text-sm">
          <caption className="sr-only">
            Proporción de reseñas por estrellas y tono del texto
          </caption>
          <thead>
            <tr>
              <th scope="col" className="p-2 text-left text-text-muted">
                Estrellas ↓ / Texto →
              </th>
              {CLASSES.map((t) => (
                <th key={t} scope="col" className="p-2 text-center capitalize">
                  {LABEL[t]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {CLASSES.map((s) => (
              <tr key={s}>
                <th scope="row" className="p-2 text-left">
                  {STARS[s]}
                </th>
                {CLASSES.map((t) => {
                  const c = cells.get(`${s}|${t}`);
                  const extreme =
                    (s === "NEG" && t === "POS") ||
                    (s === "POS" && t === "NEG");
                  const value = c?.ppi?.estimate ?? c?.raw?.estimate ?? null;
                  return (
                    <td
                      key={t}
                      className={`rounded-sm p-2 text-center ${extreme ? "border-2 border-neutral-950" : "border border-border"}`}
                      style={{
                        background: `color-mix(in srgb, var(--color-green-300) ${Math.min((value ?? 0) * 100, 100) * 0.6}%, var(--color-neutral-0))`,
                      }}
                    >
                      <span className="tabular block text-lg font-bold">
                        {formatPct(value)}
                      </span>
                      {c?.ppi ? (
                        <span className="tabular block text-xs text-text-muted">
                          {formatPctRange(c.ppi.ci_low, c.ppi.ci_high)}
                        </span>
                      ) : null}
                      {extreme ? (
                        <span className="block text-xs font-semibold">
                          incongruencia
                        </span>
                      ) : null}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </ChartFrame>
  );
}
