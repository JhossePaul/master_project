import { scaleBand, scaleLinear } from "d3-scale";
import { useMemo, useState } from "react";
import { type FamilyMonth, useFamilies } from "@/api/kpis";
import { Axis, GridLines } from "@/charts/primitives";
import { Callout } from "@/components/Callout";
import { ChartFrame } from "@/components/ChartFrame";
import { ErrorState } from "@/components/ErrorState";
import { GlossaryTerm } from "@/components/GlossaryTerm";
import { Button } from "@/components/ui/button";
import type { BankId } from "@/config/banks";
import { formatInt, formatMonth } from "@/lib/format";
import {
  FAMILY_COLORS,
  FAMILY_ORDER,
  familyName,
  LoadingBlock,
  OpenInExplorer,
} from "./shared";

const W = 640;
const H = 280;
const M = { top: 22, right: 12, bottom: 30, left: 48 };
const CODES = [...FAMILY_ORDER, "u"] as const;

export function zFill(z: number | null): string {
  if (z === null) return "var(--color-neutral-100)";
  const strength = Math.min(Math.abs(z) / 4, 1) * 70;
  const token = z >= 0 ? "--color-sent-neg" : "--color-sent-pos";
  return `color-mix(in srgb, var(${token}) ${strength}%, var(--color-neutral-0))`;
}

function Stacked({
  rows,
  familia,
  changes,
}: {
  rows: FamilyMonth[];
  familia: string | null;
  changes: { prompt_version: string; first_labeled_at: string }[];
}) {
  const periods = [...new Set(rows.map((r) => r.period))].sort();
  const count = (p: string, f: string) =>
    rows.find((r) => r.period === p && r.family === f)?.neg_count ?? 0;
  const totals = periods.map((p) =>
    FAMILY_ORDER.reduce((sum, f) => sum + count(p, f), 0),
  );
  const x = scaleBand<string>()
    .domain(periods)
    .range([0, W - M.left - M.right])
    .padding(0.2);
  const y = scaleLinear()
    .domain([0, Math.max(1, ...totals)])
    .range([H - M.top - M.bottom, 0]);
  const marks = changes
    .map((c) => ({
      label: c.prompt_version,
      period: c.first_labeled_at.slice(0, 7),
    }))
    .filter((c) => periods.includes(c.period));
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      role="img"
      aria-label="Negativas por familia y mes"
    >
      <g transform={`translate(${M.left},${M.top})`}>
        <GridLines scale={y} width={W - M.left - M.right} />
        <Axis
          scale={y}
          orientation="left"
          length={H - M.top - M.bottom}
          format={(v) => formatInt(v as number)}
        />
        {periods.map((p) => {
          let acc = 0;
          return (
            <g key={p} transform={`translate(${x(p)},0)`}>
              {FAMILY_ORDER.map((f) => {
                const n = count(p, f);
                const top = y(acc + n);
                const h = y(acc) - top;
                acc += n;
                return (
                  <rect
                    key={f}
                    y={top}
                    width={x.bandwidth()}
                    height={Math.max(h, 0)}
                    fill={`var(${FAMILY_COLORS[f]})`}
                    opacity={familia && familia !== f ? 0.25 : 1}
                  >
                    <title>{`${formatMonth(p)} · ${familyName(f)}: ${formatInt(n)}`}</title>
                  </rect>
                );
              })}
            </g>
          );
        })}
        {periods.map((p, i) =>
          i % Math.ceil(periods.length / 8) === 0 ? (
            <text
              key={p}
              x={(x(p) ?? 0) + x.bandwidth() / 2}
              y={H - M.top - M.bottom + 18}
              textAnchor="middle"
              fontSize={11}
              fill="var(--color-neutral-700)"
            >
              {formatMonth(p)}
            </text>
          ) : null,
        )}
        {marks.map((m) => (
          <g key={m.label} transform={`translate(${x(m.period) ?? 0},0)`}>
            <line
              y2={H - M.top - M.bottom}
              stroke="var(--color-neutral-900)"
              strokeDasharray="2 3"
            />
            <text y={-6} fontSize={11} fill="var(--color-neutral-700)">
              {m.label}
            </text>
          </g>
        ))}
        {familia === "u" || !familia ? (
          <polyline
            fill="none"
            stroke={`var(${FAMILY_COLORS.u})`}
            strokeWidth={2}
            strokeDasharray="4 3"
            points={periods
              .map(
                (p) => `${(x(p) ?? 0) + x.bandwidth() / 2},${y(count(p, "u"))}`,
              )
              .join(" ")}
          />
        ) : null}
      </g>
    </svg>
  );
}

function Heat({
  rows,
  familia,
}: {
  rows: FamilyMonth[];
  familia: string | null;
}) {
  const periods = [...new Set(rows.map((r) => r.period))].sort();
  const cell = (p: string, f: string) =>
    rows.find((r) => r.period === p && r.family === f);
  const cw = Math.max(18, Math.min(44, 560 / Math.max(periods.length, 1)));
  const ch = 24;
  const left = 150;
  return (
    <svg
      viewBox={`0 0 ${left + cw * periods.length + 10} ${ch * CODES.length + 40}`}
      className="w-full"
      role="img"
      aria-label="Anomalía de cada familia por mes"
    >
      {periods.map((p, i) => (
        <text
          key={p}
          x={left + cw * i + cw / 2}
          y={14}
          textAnchor="middle"
          fontSize={10}
          fill="var(--color-neutral-700)"
        >
          {i % Math.ceil(periods.length / 12) === 0 ? formatMonth(p) : ""}
        </text>
      ))}
      {CODES.map((f, r) => (
        <g key={f} transform={`translate(0,${24 + r * ch})`}>
          <text
            x={left - 8}
            y={ch / 2}
            dy="0.32em"
            textAnchor="end"
            fontSize={12}
            fontWeight={familia === f ? 700 : 400}
            fill="var(--color-neutral-900)"
          >
            {f === "u" ? "Marca u (actualización)" : familyName(f)}
          </text>
          {periods.map((p, i) => {
            const c = cell(p, f);
            const flagged =
              !!c &&
              c.z !== null &&
              c.threshold !== null &&
              (c.alert === true || c.z >= c.threshold);
            return (
              <rect
                key={p}
                x={left + cw * i + 1}
                y={1}
                width={cw - 2}
                height={ch - 2}
                fill={zFill(c?.z ?? null)}
                stroke={flagged ? "var(--color-neutral-950)" : "none"}
                strokeWidth={2}
                opacity={familia && familia !== f ? 0.4 : 1}
              >
                <title>
                  {c?.z != null
                    ? `${formatMonth(p)} · ${familyName(f)}: z = ${c.z.toFixed(1)}${c.threshold != null ? ` (umbral ${c.threshold})` : " (sin umbral)"}`
                    : `${formatMonth(p)} · ${familyName(f)}: sin z`}
                </title>
              </rect>
            );
          })}
        </g>
      ))}
    </svg>
  );
}

export function FamiliesBlock({
  banks,
  bank,
  familia,
  onFamilia,
  from,
  to,
}: {
  banks: BankId[];
  bank: BankId;
  familia: string | null;
  onFamilia: (code: string | null) => void;
  from: string;
  to: string;
}) {
  const families = useFamilies(banks);
  const [view, setView] = useState<"nivel" | "anomalia">("nivel");
  const rows = useMemo(
    () => (families.data?.series ?? []).filter((r) => r.bank_id === bank),
    [families.data, bank],
  );
  if (families.isPending) return <LoadingBlock />;
  if (families.isError)
    return (
      <ErrorState error={families.error} onRetry={() => families.refetch()} />
    );
  const unflagged = rows.some((r) => r.z !== null && r.threshold === null);
  return (
    <ChartFrame
      kicker="Familias"
      title={
        view === "nivel"
          ? "Negativas por familia y mes"
          : "Qué familias se salen de lo habitual"
      }
      method="raw"
      actions={
        <OpenInExplorer
          filters={{ banks: [bank], from, to, familia, sentimiento: "NEG" }}
        />
      }
      howToRead={
        <p>
          Las <GlossaryTerm id="familia_aspectos">familias</GlossaryTerm> son
          los temas de las reseñas negativas. En "Nivel" cada barra suma las
          negativas del mes; la línea punteada es la{" "}
          <GlossaryTerm id="marca_u">marca u</GlossaryTerm>. En "Anomalía" el
          color indica cuánto se aleja el mes de lo habitual y el borde marca
          los meses que pasan el umbral del monitor.
        </p>
      }
      provenance={{
        prompt: families.data.prompt_changes.at(-1)?.prompt_version,
        note: "conteo del modelo, sin ajustar",
      }}
      data={{
        columns: ["Mes", "Familia", "Negativas", "Participación", "z"],
        rows: rows.map((r) => [
          r.period,
          familyName(r.family),
          r.neg_count,
          `${(r.share * 100).toFixed(1)} %`,
          r.z === null ? null : r.z.toFixed(1),
        ]),
      }}
    >
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <fieldset className="m-0 flex gap-1 border-0 p-0">
          <legend className="sr-only">Vista</legend>
          {(
            [
              ["nivel", "Nivel"],
              ["anomalia", "Anomalía"],
            ] as const
          ).map(([key, label]) => (
            <Button
              key={key}
              size="sm"
              variant={view === key ? "primary" : "secondary"}
              aria-pressed={view === key}
              onClick={() => setView(key)}
            >
              {label}
            </Button>
          ))}
        </fieldset>
        <fieldset className="m-0 flex flex-wrap gap-1 border-0 p-0">
          <legend className="sr-only">Familia resaltada</legend>
          {CODES.map((f) => (
            <button
              key={f}
              type="button"
              aria-pressed={familia === f}
              onClick={() => onFamilia(familia === f ? null : f)}
              className="inline-flex items-center gap-1 rounded-full border border-border-strong px-2 py-0.5 text-xs aria-pressed:border-brand aria-pressed:bg-green-100"
            >
              <span
                aria-hidden="true"
                className="size-2 rounded-full"
                style={{ background: `var(${FAMILY_COLORS[f]})` }}
              />
              {f === "u" ? "u" : familyName(f)}
            </button>
          ))}
        </fieldset>
      </div>
      {view === "nivel" ? (
        <>
          <Stacked
            rows={rows}
            familia={familia}
            changes={families.data.prompt_changes}
          />
          <p className="mt-2 text-sm text-text-muted">
            Las familias de cada tramo vienen del prompt con el que se
            etiquetaron.
          </p>
        </>
      ) : (
        <>
          <Heat rows={rows} familia={familia} />
          {unflagged ? (
            <div className="mt-2">
              <Callout variant="info">
                Los meses anteriores a la política vigente no tienen umbral: se
                muestran sin borde.
              </Callout>
            </div>
          ) : null}
        </>
      )}
    </ChartFrame>
  );
}
