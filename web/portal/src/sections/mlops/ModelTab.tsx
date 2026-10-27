import { extent } from "d3-array";
import { scaleLinear } from "d3-scale";
import { useRef } from "react";
import {
  type ContextSeries,
  type QualitySeries,
  useMlopsCurve,
  useQuality,
  useTopicsContext,
} from "@/api/mlops";
import { Axis, DEFAULT_MARGIN, GridLines, Line } from "@/charts/primitives";
import { useChartSize } from "@/charts/useChartSize";
import { Callout } from "@/components/Callout";
import { ChartFrame } from "@/components/ChartFrame";
import { ErrorState } from "@/components/ErrorState";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { BANKS, type BankId, bankLabel } from "@/config/banks";
import { driftSeries } from "@/config/driftSeries";
import { formatDate, formatInt, formatPct } from "@/lib/format";
import { CoverageChart } from "@/sections/admin/CoverageChart";
import { QualityPill, SeriesChart, SIGNAL_ORDER, SIGNALS } from "./shared";

function interval(
  format: (v: number) => string,
  lo: number | null,
  hi: number | null,
): string | null {
  return lo === null || hi === null ? null : `[${format(lo)}, ${format(hi)}]`;
}

function SignalCard({ series }: { series: QualitySeries }) {
  const info = SIGNALS[series.signal];
  const last = series.points.at(-1);
  const threshold = last?.threshold ?? null;
  const bound = info.kind === "floor" ? "piso" : "tope";
  return (
    <Card className="grid min-w-0 content-start gap-3 p-5">
      <header className="flex items-start justify-between gap-3">
        <h2 className="font-serif text-lg font-semibold">{info.title}</h2>
        {last ? <QualityPill status={last.status} /> : null}
      </header>
      {last ? (
        <>
          <p className="flex flex-wrap items-baseline gap-x-3">
            <span className="tabular text-3xl font-semibold">
              {info.format(last.value)}
            </span>
            <span className="tabular text-sm text-text-muted">
              {interval(info.format, last.ci_low, last.ci_high)}
              {interval(info.format, last.ci_low, last.ci_high) ? " · " : ""}n ={" "}
              {formatInt(last.n)} · {last.period}
            </span>
          </p>
          <p className="text-sm">
            {threshold === null ? (
              "Sin umbral"
            ) : (
              <>
                Umbral vigente ({bound}):{" "}
                <strong className="tabular">{info.format(threshold)}</strong>
              </>
            )}
            {last.llm_model ? (
              <span className="text-text-muted">
                {" "}
                · {last.llm_model}, prompt {last.prompt_version}
              </span>
            ) : last.model_version ? (
              <span className="text-text-muted">
                {" "}
                · modelo {last.model_version}
              </span>
            ) : null}
          </p>
          <SeriesChart
            label={`${info.title}: serie por periodo con su umbral`}
            points={series.points.map((p) => ({
              label: p.period,
              value: p.value,
              lo: p.ci_low,
              hi: p.ci_high,
            }))}
            threshold={threshold}
            thresholdLabel={threshold === null ? undefined : bound}
            format={info.format}
          />
        </>
      ) : (
        <p className="text-sm text-text-muted">
          El monitor todavía no mide esta señal.
        </p>
      )}
      <p className="text-xs text-text-muted">{info.help}</p>
    </Card>
  );
}

const MARGIN = { ...DEFAULT_MARGIN, right: 16 };
const CHART_HEIGHT = 180;

/** Una línea por banco, mes a mes. */
function BankLines({ series }: { series: ContextSeries }) {
  const box = useRef<HTMLDivElement>(null);
  const { width: measured } = useChartSize(box);
  const width = measured || 520;
  const innerW = Math.max(width - MARGIN.left - MARGIN.right, 10);
  const innerH = CHART_HEIGHT - MARGIN.top - MARGIN.bottom;
  const periods = [...new Set(series.cells.map((c) => c.period))].sort();
  const [lo = 0, hi = 1] = extent(series.cells.map((c) => c.value));
  const x = scaleLinear()
    .domain([0, Math.max(periods.length - 1, 1)])
    .range([0, innerW]);
  const y = scaleLinear()
    .domain([Math.min(lo, 0), hi])
    .nice()
    .range([innerH, 0]);
  const banks = [...new Set(series.cells.map((c) => c.bank_id))];
  const info = driftSeries(series.metric);
  return (
    <div ref={box} className="w-full">
      <svg
        role="img"
        aria-label={`${info.label} por banco y mes`}
        width={width}
        height={CHART_HEIGHT}
        className="block"
      >
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          <GridLines scale={y} width={innerW} />
          <g transform={`translate(0,${innerH})`}>
            <Axis
              scale={x}
              orientation="bottom"
              length={innerW}
              format={(v) =>
                Number.isInteger(Number(v)) ? (periods[Number(v)] ?? "") : ""
              }
            />
          </g>
          <Axis
            scale={y}
            orientation="left"
            length={innerH}
            format={(v) => info.format(Number(v))}
          />
          {banks.map((bank) => {
            const style = BANKS[bank as BankId];
            const byPeriod = new Map(
              series.cells
                .filter((c) => c.bank_id === bank)
                .map((c) => [c.period, c.value]),
            );
            return (
              <Line
                key={bank}
                points={periods.map((p, i) => ({
                  x: i,
                  y: byPeriod.get(p) ?? null,
                }))}
                x={x}
                y={y}
                colorVar={style?.colorVar ?? "--color-bank-all"}
                dash={style?.dash}
                strokeWidth={1.5}
              />
            );
          })}
        </g>
      </svg>
    </div>
  );
}

function TopicsContext() {
  const context = useTopicsContext();
  if (context.isPending) return <Skeleton className="h-64 w-full" />;
  if (context.isError)
    return <ErrorState error={context.error} onRetry={context.refetch} />;
  const { topics, families } = context.data;
  const banks = [
    ...new Set(families.flatMap((s) => s.cells.map((c) => c.bank_id))),
  ].sort();
  const lastPeriod = families
    .flatMap((s) => s.cells.map((c) => c.period))
    .sort()
    .at(-1);
  return (
    <div className="grid gap-4">
      <Callout title="Contexto, sin umbral">
        Contexto, sin umbral: se acumulan para fijar uno con evidencia.
      </Callout>
      <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
        {topics.map((series) => (
          <ChartFrame
            key={series.metric}
            kicker="Tópicos"
            title={driftSeries(series.metric).label}
            provenance={{ note: "Una línea por banco, mes a mes" }}
          >
            <BankLines series={series} />
          </ChartFrame>
        ))}
      </div>
      {families.length > 0 ? (
        <Card className="grid gap-2 p-5">
          <h2 className="font-serif text-lg font-semibold">
            Familias y marca u del último mes
            {lastPeriod ? ` (${lastPeriod})` : ""}
          </h2>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Serie</TableHead>
                {banks.map((b) => (
                  <TableHead key={b} scope="col">
                    {bankLabel(b)}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {families.map((series) => (
                <TableRow key={series.metric}>
                  <TableCell>{driftSeries(series.metric).label}</TableCell>
                  {banks.map((b) => {
                    const cell = series.cells.find(
                      (c) => c.bank_id === b && c.period === lastPeriod,
                    );
                    return (
                      <TableCell key={b} className="tabular">
                        {cell ? formatPct(cell.value) : "—"}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      ) : null}
    </div>
  );
}

export default function ModelTab() {
  const quality = useQuality();
  const curve = useMlopsCurve();
  if (quality.isError)
    return <ErrorState error={quality.error} onRetry={quality.refetch} />;
  const bySignal = new Map(quality.data?.signals.map((s) => [s.signal, s]));
  return (
    <div className="grid gap-6">
      <section aria-label="Señales del monitor" className="grid gap-4">
        {quality.isPending ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {SIGNAL_ORDER.map((signal) => (
              <SignalCard
                key={signal}
                series={bySignal.get(signal) ?? { signal, points: [] }}
              />
            ))}
          </div>
        )}
      </section>
      <section aria-label="Curva de cobertura y riesgo" className="grid gap-3">
        {curve.isPending ? (
          <Skeleton className="h-64 w-full" />
        ) : curve.isError ? (
          <ErrorState error={curve.error} onRetry={curve.refetch} />
        ) : (
          <ChartFrame
            kicker="Curva vigente"
            title="Cobertura y riesgo del modelo promovido"
            subtitle="Solo lectura: el apetito de riesgo se cambia en Administración."
            provenance={{
              model: curve.data.curve.model_version,
              note: `calculada el ${formatDate(curve.data.curve.computed_at)}`,
            }}
          >
            <CoverageChart data={curve.data} proposed={null} />
          </ChartFrame>
        )}
      </section>
      <section aria-label="Tópicos" className="grid gap-3">
        <h2 className="font-serif text-xl font-semibold">Tópicos</h2>
        <TopicsContext />
      </section>
    </div>
  );
}
