import { extent } from "d3-array";
import { scaleLinear, scaleTime } from "d3-scale";
import { type MonthlyKpi, useMonthly } from "@/api/kpis";
import { Axis, GridLines, Line, Points } from "@/charts/primitives";
import { ChartFrame } from "@/components/ChartFrame";
import { ErrorState } from "@/components/ErrorState";
import { BANKS, type BankId, bankLabel } from "@/config/banks";
import {
  formatMonth,
  formatPct,
  formatPctInterval,
  formatStars,
  formatStarsInterval,
} from "@/lib/format";
import { LoadingBlock, monthDate, OpenInExplorer } from "./shared";

const W = 300;
const H = 150;
const M = { top: 10, right: 10, bottom: 24, left: 44 };

type Metric = "neg" | "gap_estrellas";

const SPEC: Record<
  Metric,
  {
    title: string;
    format: (v: number) => string;
    interval: (lo?: number | null, hi?: number | null) => string;
  }
> = {
  neg: {
    title: "Reseñas negativas por mes",
    format: (v) => formatPct(v),
    interval: formatPctInterval,
  },
  gap_estrellas: {
    title: "Brecha en estrellas por mes",
    format: (v) => formatStars(v),
    interval: formatStarsInterval,
  },
};

function MiniChart({
  bank,
  rows,
  domain,
  metric,
}: {
  bank: BankId;
  rows: MonthlyKpi[];
  domain: [number, number];
  metric: Metric;
}) {
  const spec = SPEC[metric];
  const colorVar = BANKS[bank].colorVar;
  const dates = rows.map((r) => monthDate(r.period));
  const [d0, d1] = extent(dates) as [Date, Date];
  const x = scaleTime()
    .domain([d0 ?? new Date(), d1 ?? new Date()])
    .range([0, W - M.left - M.right]);
  const y = scaleLinear()
    .domain(domain)
    .range([H - M.top - M.bottom, 0]);
  const raw = rows
    .filter((r) => r.raw)
    .map((r) => ({ x: monthDate(r.period), y: r.raw?.estimate ?? null }));
  const ppi = rows
    .filter((r) => r.ppi)
    .map((r) => ({
      x: monthDate(r.period),
      y: r.ppi?.estimate as number,
      lo: r.ppi?.ci_low,
      hi: r.ppi?.ci_high,
      label: `${formatMonth(r.period)}: ${spec.format(r.ppi?.estimate as number)} ${spec.interval(r.ppi?.ci_low, r.ppi?.ci_high)}`,
    }));
  return (
    <figure className="m-0">
      <figcaption className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <span
          aria-hidden="true"
          className="size-2.5 rounded-full"
          style={{ background: `var(${colorVar})` }}
        />
        {bankLabel(bank)}
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label={`${spec.title}, ${bankLabel(bank)}`}
      >
        <g transform={`translate(${M.left},${M.top})`}>
          <GridLines scale={y} width={W - M.left - M.right} />
          <Axis
            scale={y}
            orientation="left"
            length={H - M.top - M.bottom}
            format={(v) => spec.format(v as number)}
          />
          <g transform={`translate(0,${H - M.top - M.bottom})`}>
            <Axis
              scale={x}
              orientation="bottom"
              length={W - M.left - M.right}
              format={(v) => formatMonth(v as Date)}
            />
          </g>
          <g opacity={0.45}>
            <Line
              points={raw}
              x={x}
              y={y}
              colorVar={colorVar}
              strokeWidth={1}
            />
          </g>
          <Points points={ppi} x={x} y={y} colorVar={colorVar} radius={3} />
        </g>
      </svg>
    </figure>
  );
}

function MonthlyChart({
  metric,
  banks,
  rows,
  from,
  to,
}: {
  metric: Metric;
  banks: BankId[];
  rows: MonthlyKpi[];
  from: string;
  to: string;
}) {
  const spec = SPEC[metric];
  const mine = rows.filter((r) => r.metric === metric);
  const values = mine.flatMap((r) =>
    [r.ppi?.ci_low, r.ppi?.ci_high, r.ppi?.estimate, r.raw?.estimate].filter(
      (v): v is number => typeof v === "number",
    ),
  );
  const domain: [number, number] = [
    Math.min(0, ...values),
    Math.max(...values, 0.01),
  ];
  if (metric === "gap_estrellas") domain[1] = Math.max(0, domain[1]);
  const model = mine.find((r) => r.ppi)?.model_version;
  return (
    <ChartFrame
      kicker="Mensual"
      title={spec.title}
      subtitle="Mismo eje en todos los bancos"
      method="ppi"
      actions={<OpenInExplorer filters={{ banks, from, to }} />}
      howToRead={
        <p>
          Los puntos con barra son la estimación con revisión humana y su rango;
          la línea tenue es lo que predice el modelo sin ajustar. Si la barra de
          un mes no toca a la del otro, la diferencia es más que ruido.
        </p>
      }
      provenance={{ model, note: "estimación mensual del monitor semanal" }}
      data={{
        columns: [
          "Mes",
          "Banco",
          "Con revisión humana",
          "Rango",
          "Solo modelo",
        ],
        rows: mine.map((r) => [
          r.period,
          bankLabel(r.bank_id),
          r.ppi ? spec.format(r.ppi.estimate) : null,
          r.ppi ? spec.interval(r.ppi.ci_low, r.ppi.ci_high) : null,
          r.raw ? spec.format(r.raw.estimate) : null,
        ]),
      }}
    >
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {banks.map((bank) => (
          <MiniChart
            key={bank}
            bank={bank}
            rows={mine.filter((r) => r.bank_id === bank)}
            domain={domain}
            metric={metric}
          />
        ))}
      </div>
    </ChartFrame>
  );
}

export function MonthlyBlock({
  banks,
  from,
  to,
}: {
  banks: BankId[];
  from: string;
  to: string;
}) {
  const monthly = useMonthly(banks);
  if (monthly.isPending) return <LoadingBlock />;
  if (monthly.isError)
    return (
      <ErrorState error={monthly.error} onRetry={() => monthly.refetch()} />
    );
  return (
    <div className="grid gap-6">
      {(["neg", "gap_estrellas"] as const).map((metric) => (
        <MonthlyChart
          key={metric}
          metric={metric}
          banks={banks}
          rows={monthly.data}
          from={from}
          to={to}
        />
      ))}
    </div>
  );
}
