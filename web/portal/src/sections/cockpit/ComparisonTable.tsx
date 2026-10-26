import { scaleLinear } from "d3-scale";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { useState } from "react";
import { type BankCard, useCards } from "@/api/kpis";
import type { components } from "@/api/schema";
import { ChartFrame } from "@/components/ChartFrame";
import { ErrorState } from "@/components/ErrorState";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { BANKS, type BankId, bankLabel } from "@/config/banks";
import { formatInt, formatMonth } from "@/lib/format";
import { KPIS, type Kpi, KpiButtons, useKpi } from "./kpi";
import { LoadingBlock } from "./shared";

type Estimate = components["schemas"]["Estimate"];
type Compare = "year" | "month";
type Sort = "bank" | "actual";

const DUMBBELL_WIDTH = 280;
const ROW_HEIGHT = 40;

function pick(card: BankCard, kpi: Kpi): Estimate | null {
  return kpi === "neg"
    ? card.neg
    : kpi === "gap"
      ? card.gap_estrellas
      : card.quejas_4_5;
}

function pickPrev(
  card: BankCard,
  kpi: Kpi,
  compare: Compare,
): { period: string; estimate: Estimate | null } | null {
  const prev = compare === "year" ? card.previous_year : card.previous_month;
  if (!prev) return null;
  const estimate =
    kpi === "neg"
      ? prev.neg
      : kpi === "gap"
        ? prev.gap_estrellas
        : prev.quejas_4_5;
  return { period: prev.period, estimate };
}

function Value({
  est,
  kpi,
  note,
}: {
  est: Estimate | null;
  kpi: Kpi;
  note?: string;
}) {
  if (!est) return <span className="text-text-muted">—</span>;
  const spec = KPIS[kpi];
  return (
    <div className="tabular">
      <p className="text-lg font-bold leading-6">{spec.format(est.estimate)}</p>
      <p className="text-xs text-text-muted">
        {spec.interval(est.ci_low, est.ci_high)}
        {note ? ` · ${note}` : ""}
      </p>
    </div>
  );
}

function Delta({
  now,
  before,
  kpi,
}: {
  now: Estimate | null;
  before: Estimate | null;
  kpi: Kpi;
}) {
  if (!now || !before) return <span className="text-text-muted">—</span>;
  const diff = now.estimate - before.estimate;
  const Icon = Math.abs(diff) < 0.0005 ? Minus : diff > 0 ? ArrowUp : ArrowDown;
  return (
    <span className="tabular inline-flex items-center gap-1 font-semibold">
      <Icon className="size-4" aria-hidden="true" />
      {KPIS[kpi].diff(diff)}
    </span>
  );
}

interface Row {
  card: BankCard;
  now: Estimate | null;
  before: Estimate | null;
  beforePeriod: string | null;
}

/** Referencia → actual de un banco, con el rango de cada estimación. */
function Dumbbell({
  row,
  kpi,
  ticks,
  scale,
}: {
  row: Row;
  kpi: Kpi;
  ticks: number[];
  scale: (value: number) => number;
}) {
  const color = `var(${BANKS[row.card.bank_id as BankId]?.colorVar})`;
  const cy = ROW_HEIGHT / 2;
  const spec = KPIS[kpi];
  const whisker = (est: Estimate | null, opacity: number) =>
    est && est.ci_low != null && est.ci_high != null ? (
      <g stroke={color} opacity={opacity} strokeWidth={1.5}>
        <line x1={scale(est.ci_low)} x2={scale(est.ci_high)} y1={cy} y2={cy} />
        <line
          x1={scale(est.ci_low)}
          x2={scale(est.ci_low)}
          y1={cy - 4}
          y2={cy + 4}
        />
        <line
          x1={scale(est.ci_high)}
          x2={scale(est.ci_high)}
          y1={cy - 4}
          y2={cy + 4}
        />
      </g>
    ) : null;
  return (
    <svg
      width={DUMBBELL_WIDTH}
      height={ROW_HEIGHT}
      role="img"
      aria-label={`${bankLabel(row.card.bank_id)}: ${spec.format(row.before?.estimate)} a ${spec.format(row.now?.estimate)}`}
    >
      {ticks.map((t) => (
        <line
          key={t}
          x1={scale(t)}
          x2={scale(t)}
          y1={0}
          y2={ROW_HEIGHT}
          stroke="var(--color-neutral-200)"
        />
      ))}
      {row.before && row.now ? (
        <line
          x1={scale(row.before.estimate)}
          x2={scale(row.now.estimate)}
          y1={cy}
          y2={cy}
          stroke={color}
          strokeWidth={3}
        />
      ) : null}
      {whisker(row.before, 0.35)}
      {whisker(row.now, 0.6)}
      {row.before ? (
        <circle
          cx={scale(row.before.estimate)}
          cy={cy}
          r={5}
          fill="var(--color-surface)"
          stroke={color}
          strokeWidth={2}
        >
          <title>{`Referencia: ${spec.format(row.before.estimate)}`}</title>
        </circle>
      ) : null}
      {row.now ? (
        <circle cx={scale(row.now.estimate)} cy={cy} r={5.5} fill={color}>
          <title>{`Actual: ${spec.format(row.now.estimate)}`}</title>
        </circle>
      ) : null}
    </svg>
  );
}

export function ComparisonTable({
  banks,
  period,
}: {
  banks: BankId[];
  period: string | null;
}) {
  const [kpi] = useKpi();
  const [compare, setCompare] = useState<Compare>("year");
  const [sort, setSort] = useState<Sort>("bank");
  const cards = useCards(banks, period);
  if (cards.isPending) return <LoadingBlock />;
  if (cards.isError)
    return <ErrorState error={cards.error} onRetry={() => cards.refetch()} />;

  const spec = KPIS[kpi];
  const target = cards.data
    .map((c) => c.period)
    .filter(Boolean)
    .sort()
    .at(-1);
  const rows: Row[] = cards.data.map((card) => {
    const prev = pickPrev(card, kpi, compare);
    return {
      card,
      now: pick(card, kpi),
      before: prev?.estimate ?? null,
      beforePeriod: prev?.period ?? null,
    };
  });
  if (sort === "actual")
    rows.sort(
      (a, b) => (b.now?.estimate ?? -Infinity) - (a.now?.estimate ?? -Infinity),
    );
  const values = rows.flatMap((r) =>
    [r.now, r.before].flatMap((e) =>
      e ? [e.ci_low ?? e.estimate, e.ci_high ?? e.estimate] : [],
    ),
  );
  const lo = Math.min(...values, 0);
  const hi = Math.max(...values, 0.01);
  const pad = (hi - lo) * 0.06;
  const scale = scaleLinear()
    .domain([lo - pad, hi + pad])
    .range([8, DUMBBELL_WIDTH - 8]);
  const ticks = scale.ticks(4);
  const reference = rows.find((r) => r.beforePeriod)?.beforePeriod;
  const first = cards.data.find((c) => c.model_version);
  return (
    <ChartFrame
      kicker="Comparación entre bancos"
      title={spec.label}
      subtitle={
        reference && target
          ? `Comparando ${formatMonth(target)} vs ${formatMonth(reference)}`
          : undefined
      }
      method="ppi"
      howToRead={
        <p>
          Cada renglón es un banco. El punto vacío es el valor de referencia y
          el lleno, el actual; las barras son el rango de cada estimación. Si
          las barras se traslapan, el cambio no se distingue del ruido de la
          muestra. La flecha solo indica la dirección del cambio.
        </p>
      }
      provenance={{
        model: first?.model_version,
        gold: first?.gold_version,
        note: target ? `mes actual ${formatMonth(target)}` : undefined,
      }}
      data={{
        columns: ["Banco", "Referencia", "Actual", "Diferencia"],
        rows: rows.map((r) => [
          bankLabel(r.card.bank_id),
          spec.format(r.before?.estimate),
          spec.format(r.now?.estimate),
          r.now && r.before
            ? spec.diff(r.now.estimate - r.before.estimate)
            : null,
        ]),
      }}
    >
      <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2">
        <KpiButtons />
        <fieldset className="m-0 flex flex-wrap items-center gap-1 border-0 p-0">
          <legend className="sr-only">Comparar con</legend>
          <span className="text-sm text-text-muted">Comparar con:</span>
          {(
            [
              ["year", "Mismo mes del año anterior"],
              ["month", "Mes anterior"],
            ] as const
          ).map(([key, label]) => (
            <Button
              key={key}
              size="sm"
              variant={compare === key ? "primary" : "secondary"}
              aria-pressed={compare === key}
              onClick={() => setCompare(key)}
            >
              {label}
            </Button>
          ))}
        </fieldset>
        <fieldset className="m-0 flex flex-wrap items-center gap-1 border-0 p-0">
          <legend className="sr-only">Orden</legend>
          <span className="text-sm text-text-muted">Ordenar por:</span>
          {(
            [
              ["bank", "Banco"],
              ["actual", "Valor actual"],
            ] as const
          ).map(([key, label]) => (
            <Button
              key={key}
              size="sm"
              variant={sort === key ? "primary" : "secondary"}
              aria-pressed={sort === key}
              onClick={() => setSort(key)}
            >
              {label}
            </Button>
          ))}
        </fieldset>
      </div>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Banco</TableHead>
              <TableHead scope="col">Referencia</TableHead>
              <TableHead scope="col">Actual</TableHead>
              <TableHead scope="col">Diferencia</TableHead>
              <TableHead scope="col">
                <span className="block">Comparación</span>
                <svg width={DUMBBELL_WIDTH} height={16} aria-hidden="true">
                  <title>Escala</title>
                  {ticks.map((t) => (
                    <text
                      key={t}
                      x={scale(t)}
                      y={12}
                      textAnchor="middle"
                      fontSize={11}
                      fontWeight={400}
                      fill="var(--color-neutral-700)"
                    >
                      {spec.tick(t)}
                    </text>
                  ))}
                </svg>
              </TableHead>
              <TableHead scope="col">Alertas abiertas</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => {
              const style = BANKS[r.card.bank_id as BankId];
              return (
                <TableRow key={r.card.bank_id}>
                  <TableCell className="whitespace-nowrap font-semibold">
                    <span
                      aria-hidden="true"
                      className="mr-2 inline-block size-2.5 rounded-full"
                      style={{ background: `var(${style?.colorVar})` }}
                    />
                    {bankLabel(r.card.bank_id)}
                  </TableCell>
                  <TableCell>
                    <Value
                      est={r.before}
                      kpi={kpi}
                      note={
                        r.beforePeriod ? formatMonth(r.beforePeriod) : undefined
                      }
                    />
                  </TableCell>
                  <TableCell>
                    <Value
                      est={r.now}
                      kpi={kpi}
                      note={
                        r.card.period && r.card.period !== target
                          ? formatMonth(r.card.period)
                          : undefined
                      }
                    />
                  </TableCell>
                  <TableCell>
                    <Delta now={r.now} before={r.before} kpi={kpi} />
                  </TableCell>
                  <TableCell>
                    <Dumbbell row={r} kpi={kpi} ticks={ticks} scale={scale} />
                  </TableCell>
                  <TableCell>
                    <span className="tabular inline-flex items-center gap-2">
                      {formatInt(r.card.open_alerts)}
                      {r.card.open_alerts > 0 ? (
                        <StatusPill status="abierta" />
                      ) : null}
                    </span>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </ChartFrame>
  );
}
