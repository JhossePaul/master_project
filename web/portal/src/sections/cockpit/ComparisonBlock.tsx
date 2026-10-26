import { scaleBand, scaleLinear } from "d3-scale";
import { useMemo } from "react";
import { useMonthly } from "@/api/kpis";
import { ChartFrame } from "@/components/ChartFrame";
import { ErrorState } from "@/components/ErrorState";
import { BANKS, type BankId, bankLabel } from "@/config/banks";
import {
  formatMonth,
  formatPct,
  formatPctRange,
  formatStars,
  formatStarsRange,
} from "@/lib/format";
import { LoadingBlock, OpenInExplorer } from "./shared";

const W = 560;
const ROW = 34;
const M = { top: 8, right: 16, bottom: 28, left: 110 };

type Metric = "neg" | "gap_estrellas";
const SPEC = {
  neg: { title: "Reseñas negativas", format: formatPct, range: formatPctRange },
  gap_estrellas: {
    title: "Brecha en estrellas",
    format: formatStars,
    range: formatStarsRange,
  },
} as const;

export function months(
  rows: { period: string; ppi?: unknown; metric: string }[],
): string[] {
  return [
    ...new Set(
      rows.filter((r) => r.ppi && r.metric === "neg").map((r) => r.period),
    ),
  ].sort();
}

function Dots({
  metric,
  banks,
  period,
  from,
  to,
}: {
  metric: Metric;
  banks: BankId[];
  period: string | null;
  from: string;
  to: string;
}) {
  const monthly = useMonthly(banks);
  const spec = SPEC[metric];
  const rows = useMemo(() => {
    const data = monthly.data ?? [];
    const target = period ?? months(data).at(-1) ?? null;
    return {
      target,
      list: data
        .filter((r) => r.metric === metric && r.period === target && r.ppi)
        .sort((a, b) => (b.ppi?.estimate ?? 0) - (a.ppi?.estimate ?? 0)),
    };
  }, [monthly.data, metric, period]);

  if (monthly.isPending) return <LoadingBlock />;
  if (monthly.isError)
    return (
      <ErrorState error={monthly.error} onRetry={() => monthly.refetch()} />
    );
  const values = rows.list.flatMap((r) => [
    r.ppi?.ci_low ?? r.ppi?.estimate ?? 0,
    r.ppi?.ci_high ?? r.ppi?.estimate ?? 0,
  ]);
  const lo = Math.min(0, ...values);
  const hi = Math.max(0.01, ...values);
  const pad = (hi - lo) * 0.08;
  const x = scaleLinear()
    .domain([lo - pad, hi + pad])
    .range([0, W - M.left - M.right]);
  const height = M.top + M.bottom + ROW * rows.list.length;
  const y = scaleBand<string>()
    .domain(rows.list.map((r) => r.bank_id))
    .range([0, ROW * rows.list.length]);
  return (
    <ChartFrame
      kicker="Comparación"
      title={spec.title}
      subtitle={rows.target ? formatMonth(rows.target) : undefined}
      method="ppi"
      actions={<OpenInExplorer filters={{ banks, from, to }} />}
      howToRead={
        <p>
          Cada renglón es un banco, ordenado de más a menos. El punto es la
          estimación con revisión humana y la barra, su rango: si dos barras se
          traslapan, no se puede decir que un banco esté por encima del otro.
        </p>
      }
      provenance={{
        model: rows.list[0]?.model_version,
        note: "estimación mensual del monitor semanal",
      }}
      data={{
        columns: ["Banco", "Estimación", "Rango"],
        rows: rows.list.map((r) => [
          bankLabel(r.bank_id),
          spec.format(r.ppi?.estimate),
          spec.range(r.ppi?.ci_low, r.ppi?.ci_high),
        ]),
      }}
    >
      {rows.list.length === 0 ? (
        <p className="text-sm text-text-muted">
          Sin estimaciones con revisión humana para ese mes.
        </p>
      ) : (
        <svg
          viewBox={`0 0 ${W} ${height}`}
          className="w-full max-w-3xl"
          role="img"
          aria-label={`${spec.title} por banco`}
        >
          <g transform={`translate(${M.left},${M.top})`}>
            {x.ticks(5).map((t) => (
              <g key={t} transform={`translate(${x(t)},0)`}>
                <line
                  y2={ROW * rows.list.length}
                  stroke="var(--color-neutral-200)"
                />
                <text
                  y={ROW * rows.list.length + 18}
                  textAnchor="middle"
                  fontSize={12}
                  fill="var(--color-neutral-700)"
                  className="tabular"
                >
                  {spec.format(t)}
                </text>
              </g>
            ))}
            {rows.list.map((r) => {
              const cy = (y(r.bank_id) ?? 0) + ROW / 2;
              const color = `var(${BANKS[r.bank_id as BankId].colorVar})`;
              return (
                <g key={r.bank_id}>
                  <text
                    x={-8}
                    y={cy}
                    dy="0.32em"
                    textAnchor="end"
                    fontSize={13}
                    fill="var(--color-neutral-900)"
                  >
                    {bankLabel(r.bank_id)}
                  </text>
                  {r.ppi?.ci_low != null && r.ppi.ci_high != null ? (
                    <line
                      x1={x(r.ppi.ci_low)}
                      x2={x(r.ppi.ci_high)}
                      y1={cy}
                      y2={cy}
                      stroke={color}
                      strokeWidth={2}
                    />
                  ) : null}
                  <circle
                    cx={x(r.ppi?.estimate ?? 0)}
                    cy={cy}
                    r={5}
                    fill={color}
                  >
                    <title>
                      {`${bankLabel(r.bank_id)}: ${spec.format(r.ppi?.estimate)} ${spec.range(r.ppi?.ci_low, r.ppi?.ci_high)}`}
                    </title>
                  </circle>
                </g>
              );
            })}
          </g>
        </svg>
      )}
    </ChartFrame>
  );
}

export function ComparisonBlock({
  banks,
  period,
  from,
  to,
}: {
  banks: BankId[];
  period: string | null;
  from: string;
  to: string;
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {(["gap_estrellas", "neg"] as const).map((metric) => (
        <Dots
          key={metric}
          metric={metric}
          banks={banks}
          period={period}
          from={from}
          to={to}
        />
      ))}
    </div>
  );
}
