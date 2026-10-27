import { useState } from "react";
import { type DriftCell, useDrift } from "@/api/mlops";
import { ChartFrame } from "@/components/ChartFrame";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { bankLabel } from "@/config/banks";
import { driftSeries, formatThreshold } from "@/config/driftSeries";
import { formatMonth } from "@/lib/format";
import { DriftChart } from "@/sections/alerts/DriftChart";
import { useParam } from "@/sections/cockpit/params";

const SERIES_PARAM = /^[A-Za-z0-9_]{1,64}$/;
/** z a partir del cual un color está al máximo. */
const FULL_SCALE = 4;

/** El estadístico en la escala de z: el PSI se lleva a z con su umbral. */
export function signedScore(cell: DriftCell): number | null {
  if (cell.z !== null) return cell.z;
  if (cell.psi !== null && cell.threshold)
    return (cell.psi / cell.threshold) * FULL_SCALE;
  return null;
}

/** Escala divergente: verde bajo la línea base, rojo sobre ella. */
export function heatColor(score: number | null): string {
  if (score === null) return "var(--color-neutral-50)";
  const strength = Math.min(Math.abs(score) / FULL_SCALE, 1) * 70;
  const hue = score >= 0 ? "var(--color-danger)" : "var(--color-green-500)";
  return `color-mix(in srgb, ${hue} ${strength.toFixed(0)}%, var(--color-neutral-0))`;
}

function scoreText(cell: DriftCell): string {
  const score = signedScore(cell);
  return score === null ? "—" : score.toFixed(1);
}

function Heatmap({
  cells,
  banks,
  metric,
  picked,
  onPick,
}: {
  cells: DriftCell[];
  banks: string[];
  metric: string;
  picked: { bank: string; period: string } | null;
  onPick: (bank: string, period: string) => void;
}) {
  const periods = [...new Set(cells.map((c) => c.period))].sort();
  const byKey = new Map(cells.map((c) => [`${c.bank_id}|${c.period}`, c]));
  const kind = driftSeries(metric).kind === "psi" ? "PSI" : "z";
  return (
    <div className="overflow-x-auto">
      <table className="border-separate border-spacing-0.5 text-xs">
        <caption className="sr-only">
          {kind} por banco y mes de {driftSeries(metric).label}
        </caption>
        <thead>
          <tr>
            <td />
            {periods.map((p) => (
              <th
                key={p}
                scope="col"
                className="px-1 pb-1 text-center font-normal text-text-muted"
              >
                {formatMonth(p)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {banks.map((bank) => (
            <tr key={bank}>
              <th scope="row" className="pr-2 text-left font-semibold">
                {bankLabel(bank)}
              </th>
              {periods.map((period) => {
                const cell = byKey.get(`${bank}|${period}`);
                if (!cell) return <td key={period} />;
                const selected =
                  picked?.bank === bank && picked.period === period;
                return (
                  <td key={period} className="p-0">
                    <button
                      type="button"
                      aria-pressed={selected}
                      aria-label={`${bankLabel(bank)}, ${formatMonth(period)}: ${kind} ${scoreText(cell)}${cell.alert ? ", supera el umbral" : ""}`}
                      onClick={() => onPick(bank, period)}
                      className="tabular flex h-8 w-11 items-center justify-center rounded-sm text-[11px] text-neutral-900 outline-offset-2"
                      style={{
                        background: heatColor(signedScore(cell)),
                        border: cell.alert
                          ? "2px solid var(--color-gold-600)"
                          : selected
                            ? "2px solid var(--color-neutral-900)"
                            : "1px solid transparent",
                      }}
                    >
                      {scoreText(cell)}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CellSeries({
  cells,
  bank,
  period,
  metric,
}: {
  cells: DriftCell[];
  bank: string;
  period: string;
  metric: string;
}) {
  const info = driftSeries(metric);
  const series = cells
    .filter((c) => c.bank_id === bank)
    .sort((a, b) => a.period.localeCompare(b.period));
  const threshold = series.find((c) => c.threshold !== null)?.threshold ?? null;
  const isZ = info.kind === "z";
  const provenance = { note: `${bankLabel(bank)}, 24 meses` };
  return (
    <div className="grid gap-4">
      <ChartFrame
        kicker="Serie del banco"
        title={`${info.label} de ${bankLabel(bank)}`}
        subtitle={
          threshold === null
            ? "Esta serie no tiene umbral"
            : `Umbral vigente: ${formatThreshold(metric, threshold)}`
        }
        provenance={provenance}
      >
        <DriftChart
          label={`${info.label} de ${bankLabel(bank)}, 24 meses, con el mes elegido resaltado`}
          points={series.map((c) => ({
            period: c.period,
            value: c.value,
            baseline: c.baseline,
          }))}
          highlight={period}
          colorVar="--color-brand"
          format={info.format}
          showBaseline={isZ}
          thresholds={
            !isZ && threshold !== null
              ? [
                  {
                    value: threshold,
                    label: formatThreshold(metric, threshold),
                  },
                ]
              : []
          }
        />
      </ChartFrame>
      {isZ && threshold !== null ? (
        <ChartFrame
          kicker="Cuánto se aleja"
          title="z por mes"
          provenance={provenance}
        >
          <DriftChart
            label={`z mensual de ${info.label} de ${bankLabel(bank)}, con el umbral`}
            points={series.map((c) => ({ period: c.period, value: c.z }))}
            highlight={period}
            colorVar="--color-brand"
            format={(v) => v.toFixed(1)}
            thresholds={[
              { value: threshold, label: formatThreshold(metric, threshold) },
              { value: -threshold, label: `z ≤ −${threshold}` },
            ]}
          />
        </ChartFrame>
      ) : null}
    </div>
  );
}

export default function DriftTab() {
  const [serie, setSerie] = useParam("serie", SERIES_PARAM);
  const [picked, setPicked] = useState<{ bank: string; period: string } | null>(
    null,
  );
  const drift = useDrift(serie);
  if (drift.isError)
    return <ErrorState error={drift.error} onRetry={drift.refetch} />;
  if (drift.isPending) return <Skeleton className="h-64 w-full" />;
  const { metric, series, banks, cells } = drift.data;
  if (series.length === 0)
    return (
      <EmptyState
        title="Todavía no hay series de deriva"
        description="El monitor semanal las escribe en cuanto mide el primer mes cerrado."
      />
    );
  const alerts = cells.filter((c) => c.alert).length;
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-2">
        <Label htmlFor="mlops-series">Serie</Label>
        <select
          id="mlops-series"
          value={metric}
          onChange={(e) => {
            setPicked(null);
            setSerie(e.target.value);
          }}
          className="h-9 rounded-sm border border-border-strong bg-surface px-3 text-sm"
        >
          {series.map((s) => (
            <option key={s} value={s}>
              {driftSeries(s).label}
            </option>
          ))}
        </select>
      </div>
      <ChartFrame
        kicker="Deriva"
        title={driftSeries(metric).label}
        subtitle={`${alerts === 0 ? "Ningún mes" : `${alerts} ${alerts === 1 ? "mes" : "meses"}`} supera el umbral en estos 24 meses`}
        howToRead="Cada celda es el z del mes contra los 12 meses previos del banco (PSI para la longitud, llevado a la misma escala). Rojo: sobre la línea base; verde: bajo ella. El borde dorado marca los meses que superan el umbral. Pulsa una celda para ver la serie del banco."
        provenance={{ note: "Una alerta dice que algo cambió, no por qué" }}
      >
        <Heatmap
          cells={cells}
          banks={banks}
          metric={metric}
          picked={picked}
          onPick={(bank, period) => setPicked({ bank, period })}
        />
        <p className="mt-3 flex items-center gap-2 text-xs text-text-muted">
          <span aria-hidden="true">−4</span>
          <span
            aria-hidden="true"
            className="h-3 w-40 rounded-sm"
            style={{
              background: `linear-gradient(to right, ${heatColor(-4)}, ${heatColor(0)}, ${heatColor(4)})`,
            }}
          />
          <span aria-hidden="true">+4</span>
          <span>z</span>
        </p>
      </ChartFrame>
      {picked ? (
        <CellSeries
          cells={cells}
          bank={picked.bank}
          period={picked.period}
          metric={metric}
        />
      ) : null}
    </div>
  );
}
