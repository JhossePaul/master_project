import { scaleLinear } from "d3-scale";
import { Info } from "lucide-react";
import { Link } from "react-router";
import type { components } from "@/api/schema";
import { MethodBadge } from "@/components/MethodBadge";
import { Provenance } from "@/components/Provenance";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { BANK_IDS, BANKS, type BankId, bankLabel } from "@/config/banks";
import {
  formatMonth,
  formatPct,
  formatPctRange,
  formatStars,
  formatStarsRange,
} from "@/lib/format";

type Headline = components["schemas"]["BankHeadline"];
type Estimate = components["schemas"]["Estimate"];

const PLOT_WIDTH = 150;
const ROW_HEIGHT = 36;

interface Metric {
  label: string;
  pick: (bank: Headline) => Estimate;
  format: (x: number) => string;
  range: (lo: number | null, hi: number | null) => string;
  tick: (x: number) => string;
}

const signed = (x: number) =>
  `${x < 0 ? "−" : x > 0 ? "+" : ""}${Math.abs(x).toFixed(1)}`;

const NEG: Metric = {
  label: "Reseñas negativas",
  pick: (b) => b.neg,
  format: (x) => formatPct(x),
  range: formatPctRange,
  tick: (x) => formatPct(x, 0),
};

const GAP: Metric = {
  label: "Brecha en estrellas",
  pick: (b) => b.gap_estrellas,
  format: (x) => formatStars(x),
  range: formatStarsRange,
  tick: signed,
};

function makeScale(banks: Headline[], metric: Metric) {
  const values = banks.flatMap((b) => {
    const e = metric.pick(b);
    return [e.ci_low ?? e.estimate, e.ci_high ?? e.estimate];
  });
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo) * 0.08 || 0.01;
  return scaleLinear()
    .domain([lo - pad, hi + pad])
    .range([8, PLOT_WIDTH - 8]);
}

type Scale = ReturnType<typeof makeScale>;

/** Punto con su rango sobre la escala compartida de la columna. */
function IntervalPlot({
  est,
  scale,
  colorVar,
  label,
}: {
  est: Estimate;
  scale: Scale;
  colorVar: string;
  label: string;
}) {
  const color = `var(${colorVar})`;
  const cy = ROW_HEIGHT / 2;
  return (
    <svg width={PLOT_WIDTH} height={ROW_HEIGHT} role="img" aria-label={label}>
      <title>{label}</title>
      {scale.ticks(3).map((t) => (
        <line
          key={t}
          x1={scale(t)}
          x2={scale(t)}
          y1={0}
          y2={ROW_HEIGHT}
          stroke="var(--color-neutral-200)"
        />
      ))}
      {est.ci_low != null && est.ci_high != null ? (
        <g stroke={color} strokeWidth={2}>
          <line
            x1={scale(est.ci_low)}
            x2={scale(est.ci_high)}
            y1={cy}
            y2={cy}
          />
          <line
            x1={scale(est.ci_low)}
            x2={scale(est.ci_low)}
            y1={cy - 5}
            y2={cy + 5}
          />
          <line
            x1={scale(est.ci_high)}
            x2={scale(est.ci_high)}
            y1={cy - 5}
            y2={cy + 5}
          />
        </g>
      ) : null}
      <circle cx={scale(est.estimate)} cy={cy} r={5} fill={color} />
    </svg>
  );
}

function ScaleHead({ metric, scale }: { metric: Metric; scale: Scale }) {
  return (
    <TableHead scope="col">
      <span className="sr-only">Rango de {metric.label.toLowerCase()}</span>
      <svg width={PLOT_WIDTH} height={16} aria-hidden="true">
        <title>Escala</title>
        {scale.ticks(3).map((t) => (
          <text
            key={t}
            x={scale(t)}
            y={12}
            textAnchor="middle"
            fontSize={11}
            fontWeight={400}
            fill="var(--color-neutral-700)"
          >
            {metric.tick(t)}
          </text>
        ))}
      </svg>
    </TableHead>
  );
}

function Value({ est, metric }: { est: Estimate; metric: Metric }) {
  return (
    <div className="tabular">
      <p className="text-lg font-bold leading-6">
        {metric.format(est.estimate)}
      </p>
      <p className="text-xs text-text-muted">
        {metric.range(est.ci_low, est.ci_high)}
        {est.method === "raw" ? " · Solo modelo" : ""}
      </p>
    </div>
  );
}

function BankRow({
  bank,
  scales,
  latest,
}: {
  bank: Headline;
  scales: [Scale, Scale];
  latest: string;
}) {
  const style = BANKS[bank.bank_id as BankId];
  const colorVar = style?.colorVar ?? "--color-neutral-700";
  const name = bankLabel(bank.bank_id);
  return (
    <TableRow className="relative hover:bg-surface-muted">
      <TableCell className="whitespace-nowrap font-semibold">
        <span
          aria-hidden="true"
          className="mr-2 inline-block size-2.5 rounded-full"
          style={{ background: `var(${colorVar})` }}
        />
        <Link
          to={{ pathname: "/cockpit", search: `?bancos=${bank.bank_id}` }}
          className="after:absolute after:inset-0"
        >
          {name}
        </Link>
        {bank.period !== latest ? (
          <span className="ml-2 text-xs font-normal text-text-muted">
            {formatMonth(bank.period)}
          </span>
        ) : null}
      </TableCell>
      {[NEG, GAP].map((metric, i) => {
        const est = metric.pick(bank);
        const scale = scales[i] as Scale;
        return [
          <TableCell key={`${metric.label}-v`}>
            <Value est={est} metric={metric} />
          </TableCell>,
          <TableCell key={`${metric.label}-p`}>
            <IntervalPlot
              est={est}
              scale={scale}
              colorVar={colorVar}
              label={`${name}, ${metric.label.toLowerCase()}: ${metric.format(est.estimate)}, ${metric.range(est.ci_low, est.ci_high)}`}
            />
          </TableCell>,
        ];
      })}
    </TableRow>
  );
}

export function BankSummary({ banks }: { banks: Headline[] }) {
  const byBank = new Map(banks.map((b) => [b.bank_id, b]));
  const shown = BANK_IDS.flatMap((id) => byBank.get(id) ?? []);
  const missing = BANK_IDS.filter((id) => !byBank.has(id));
  const latest =
    shown
      .map((b) => b.period)
      .sort()
      .at(-1) ?? "";
  const first = shown[0];
  const allPpi = shown.every(
    (b) => b.neg.method === "ppi" && b.gap_estrellas.method === "ppi",
  );
  const scales: [Scale, Scale] = [makeScale(shown, NEG), makeScale(shown, GAP)];
  return (
    <section aria-labelledby="bancos">
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1">
        <h2
          id="bancos"
          className="font-serif text-2xl font-semibold text-green-800"
        >
          Resumen
        </h2>
        {latest ? (
          <span className="text-sm text-text-muted">
            Cifras de {formatMonth(latest)}
          </span>
        ) : null}
        {shown.length > 0 && allPpi ? <MethodBadge method="ppi" /> : null}
        {first ? (
          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                className="flex items-center gap-1 text-xs font-semibold text-green-600"
              >
                <Info className="size-3" aria-hidden="true" />
                Cómo se calculó
              </button>
            </PopoverTrigger>
            <PopoverContent>
              <p className="mb-2 text-sm">
                Un modelo clasifica todas las reseñas y personas revisaron una
                muestra para ajustar el cálculo. Cada rango dice qué tan segura
                es la cifra.
              </p>
              <Provenance
                model={first.model_version}
                gold={first.gold_version}
              />
            </PopoverContent>
          </Popover>
        ) : null}
      </div>
      <div className="overflow-x-auto rounded-md border border-border bg-surface">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Banco</TableHead>
              <TableHead scope="col">{NEG.label}</TableHead>
              <ScaleHead metric={NEG} scale={scales[0]} />
              <TableHead scope="col">{GAP.label}</TableHead>
              <ScaleHead metric={GAP} scale={scales[1]} />
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((bank) => (
              <BankRow
                key={bank.bank_id}
                bank={bank}
                scales={scales}
                latest={latest}
              />
            ))}
            {missing.map((id) => (
              <TableRow key={id}>
                <TableCell className="whitespace-nowrap font-semibold">
                  <span
                    aria-hidden="true"
                    className="mr-2 inline-block size-2.5 rounded-full"
                    style={{ background: `var(${BANKS[id].colorVar})` }}
                  />
                  {bankLabel(id)}
                </TableCell>
                <TableCell colSpan={4} className="text-text-muted">
                  Sin cifra con revisión humana en un mes cerrado: aún no hay
                  suficientes reseñas revisadas.
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}
