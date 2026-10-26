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
import { formatInt, formatMonth, formatPct } from "@/lib/format";
import {
  FAMILY_COLORS,
  FAMILY_ORDER,
  familyName,
  LoadingBlock,
  OpenInExplorer,
  useWidth,
} from "./shared";

const WINDOW_MONTHS = 24;
const HEIGHT = 260;
const M = { top: 30, right: 8, bottom: 28, left: 48 };
const MARK_LABEL = "Relacionada con una actualización";

export function zFill(z: number | null): string {
  if (z === null) return "var(--color-neutral-100)";
  const strength = Math.min(Math.abs(z) / 4, 1) * 70;
  const token = z >= 0 ? "--color-sent-neg" : "--color-sent-pos";
  return `color-mix(in srgb, var(${token}) ${strength}%, var(--color-neutral-0))`;
}

function Stacked({
  rows,
  periods,
  familias,
  changes,
  width,
}: {
  rows: FamilyMonth[];
  periods: string[];
  familias: string[];
  changes: { prompt_version: string; first_labeled_at: string }[];
  width: number;
}) {
  const count = (p: string, f: string) =>
    rows.find((r) => r.period === p && r.family === f)?.neg_count ?? 0;
  // Con selección solo se apilan las familias elegidas: el resto desaparece
  // y la escala se ajusta a lo que queda.
  const codes = FAMILY_ORDER.filter(
    (f) => familias.length === 0 || familias.includes(f),
  );
  const totals = periods.map((p) =>
    codes.reduce((sum, f) => sum + count(p, f), 0),
  );
  const x = scaleBand<string>()
    .domain(periods)
    .range([0, width - M.left - M.right])
    .padding(0.15);
  const y = scaleLinear()
    .domain([0, Math.max(1, ...totals)])
    .range([HEIGHT - M.top - M.bottom, 0]);
  const marks = changes
    .map((c) => ({
      label: c.prompt_version,
      period: c.first_labeled_at.slice(0, 7),
    }))
    .filter((c) => periods.includes(c.period));
  const step = Math.ceil(periods.length / Math.max(2, Math.floor(width / 70)));
  return (
    <svg
      width={width}
      height={HEIGHT}
      role="img"
      aria-label="Negativas por familia y mes"
    >
      <g transform={`translate(${M.left},${M.top})`}>
        <GridLines scale={y} width={width - M.left - M.right} />
        <Axis
          scale={y}
          orientation="left"
          length={HEIGHT - M.top - M.bottom}
          format={(v) => formatInt(v as number)}
        />
        {periods.map((p) => {
          let acc = 0;
          return (
            <g key={p} transform={`translate(${x(p)},0)`}>
              {codes.map((f) => {
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
                  >
                    <title>{`${formatMonth(p)} · ${familyName(f)}: ${formatInt(n)}`}</title>
                  </rect>
                );
              })}
            </g>
          );
        })}
        {periods.map((p, i) =>
          i % step === 0 ? (
            <text
              key={p}
              x={(x(p) ?? 0) + x.bandwidth() / 2}
              y={HEIGHT - M.top - M.bottom + 18}
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
              y1={-6}
              y2={HEIGHT - M.top - M.bottom}
              stroke="var(--color-neutral-900)"
              strokeDasharray="2 3"
            />
            <text x={4} y={-12} fontSize={11} fill="var(--color-neutral-700)">
              {m.label}
            </text>
          </g>
        ))}
      </g>
    </svg>
  );
}

function Heat({
  rows,
  periods,
  familias,
  width,
}: {
  rows: FamilyMonth[];
  periods: string[];
  familias: string[];
  width: number;
}) {
  const cell = (p: string, f: string) =>
    rows.find((r) => r.period === p && r.family === f);
  const left = 240;
  const cw = Math.max(
    16,
    Math.floor((width - left) / Math.max(periods.length, 1)),
  );
  const ch = 26;
  const gap = 12;
  const codes = [...FAMILY_ORDER, "u"] as const;
  const rowY = (i: number) =>
    22 + i * ch + (i === FAMILY_ORDER.length ? gap : 0);
  const labelEvery = Math.ceil(
    periods.length / Math.max(2, Math.floor((cw * periods.length) / 60)),
  );
  return (
    <div className="overflow-x-auto">
      <svg
        width={left + cw * periods.length}
        height={rowY(codes.length) + 8}
        role="img"
        aria-label="Anomalía de cada familia por mes"
      >
        {periods.map((p, i) =>
          i % labelEvery === 0 ? (
            <text
              key={p}
              x={left + cw * i + cw / 2}
              y={14}
              textAnchor="middle"
              fontSize={11}
              fill="var(--color-neutral-700)"
            >
              {formatMonth(p)}
            </text>
          ) : null,
        )}
        {codes.map((f, r) => (
          <g key={f} transform={`translate(0,${rowY(r)})`}>
            <text
              x={left - 8}
              y={ch / 2}
              dy="0.32em"
              textAnchor="end"
              fontSize={12}
              fontWeight={familias.includes(f) ? 700 : 400}
              fill="var(--color-neutral-900)"
            >
              {f === "u" ? MARK_LABEL : familyName(f)}
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
                  opacity={
                    familias.length > 0 && !familias.includes(f) ? 0.4 : 1
                  }
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
    </div>
  );
}

function ZLegend() {
  const steps = [-4, -2, 0, 2, 4];
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-text-muted">
      <span>z robusto:</span>
      <span>menos de lo habitual</span>
      <span className="flex" aria-hidden="true">
        {steps.map((z) => (
          <span
            key={z}
            className="h-4 w-8 border border-border"
            style={{ background: zFill(z) }}
          />
        ))}
      </span>
      <span>más de lo habitual</span>
      <span>
        (−4 a +4; un valor fuera de ese rango se pinta igual de intenso)
      </span>
    </div>
  );
}

function MarkU({
  rows,
  periods,
  width,
}: {
  rows: FamilyMonth[];
  periods: string[];
  width: number;
}) {
  const h = 110;
  const m = { top: 8, right: 8, bottom: 22, left: 48 };
  const values = periods.map(
    (p) => rows.find((r) => r.period === p && r.family === "u")?.share ?? 0,
  );
  const x = scaleBand<string>()
    .domain(periods)
    .range([0, width - m.left - m.right])
    .padding(0.15);
  const y = scaleLinear()
    .domain([0, Math.max(0.05, ...values)])
    .range([h - m.top - m.bottom, 0]);
  const step = Math.ceil(periods.length / Math.max(2, Math.floor(width / 70)));
  return (
    <figure className="m-0">
      <figcaption className="mb-1 text-sm font-semibold">
        <GlossaryTerm id="marca_u">{MARK_LABEL}</GlossaryTerm>{" "}
        <span className="font-normal text-text-muted">
          (parte de las negativas de cada mes)
        </span>
      </figcaption>
      <svg
        width={width}
        height={h}
        role="img"
        aria-label="Negativas relacionadas con una actualización, por mes"
      >
        <g transform={`translate(${m.left},${m.top})`}>
          <GridLines scale={y} width={width - m.left - m.right} />
          <Axis
            scale={y}
            orientation="left"
            length={h - m.top - m.bottom}
            format={(v) => formatPct(v as number, 0)}
          />
          {periods.map((p, i) => (
            <g key={p}>
              <rect
                x={x(p)}
                y={y(values[i] ?? 0)}
                width={x.bandwidth()}
                height={h - m.top - m.bottom - y(values[i] ?? 0)}
                fill={`var(${FAMILY_COLORS.u})`}
              >
                <title>{`${formatMonth(p)}: ${formatPct(values[i])}`}</title>
              </rect>
              {i % step === 0 ? (
                <text
                  x={(x(p) ?? 0) + x.bandwidth() / 2}
                  y={h - m.top - m.bottom + 15}
                  textAnchor="middle"
                  fontSize={11}
                  fill="var(--color-neutral-700)"
                >
                  {formatMonth(p)}
                </text>
              ) : null}
            </g>
          ))}
        </g>
      </svg>
    </figure>
  );
}

export function FamiliesBlock({
  banks,
  bank,
  familias,
  onFamilias,
  from,
  to,
}: {
  banks: BankId[];
  bank: BankId;
  familias: string[];
  onFamilias: (codes: string[]) => void;
  from: string;
  to: string;
}) {
  const families = useFamilies(banks);
  const [view, setView] = useState<"nivel" | "anomalia">("nivel");
  const { ref, width } = useWidth();
  const rows = useMemo(
    () => (families.data?.series ?? []).filter((r) => r.bank_id === bank),
    [families.data, bank],
  );
  const periods = useMemo(
    () => [...new Set(rows.map((r) => r.period))].sort().slice(-WINDOW_MONTHS),
    [rows],
  );
  if (families.isPending) return <LoadingBlock />;
  if (families.isError)
    return (
      <ErrorState error={families.error} onRetry={() => families.refetch()} />
    );
  const shown = rows.filter((r) => periods.includes(r.period));
  const unflagged = shown.some((r) => r.z !== null && r.threshold === null);
  const last = periods.at(-1);
  const prompt = families.data.prompt_changes.at(-1)?.prompt_version;
  return (
    <ChartFrame
      kicker="Familias"
      title={
        view === "nivel"
          ? "Negativas por familia y mes"
          : "Qué familias se salen de lo habitual"
      }
      subtitle={`Últimos ${WINDOW_MONTHS} meses`}
      method="raw"
      actions={
        <OpenInExplorer
          filters={{
            banks: [bank],
            from,
            to,
            familia: familias.join(",") || null,
            sentimiento: "NEG",
          }}
        />
      }
      howToRead={
        <p>
          Las <GlossaryTerm id="familia_aspectos">familias</GlossaryTerm> son
          los temas de las reseñas negativas. En "Nivel" cada barra suma las
          negativas del mes. En "Anomalía" el color indica cuánto se aleja el
          mes de lo habitual (z robusto del monitor); si hubiera umbral, el
          borde marcaría los meses que lo pasan. Elige una o varias familias: en
          "Nivel" solo se apilan esas; en "Anomalía" se resaltan.
        </p>
      }
      provenance={{
        prompt,
        note: "conteo del modelo, sin ajustar",
      }}
      data={{
        columns: ["Mes", "Familia", "Negativas", "Participación", "z"],
        rows: shown.map((r) => [
          r.period,
          r.family === "u" ? MARK_LABEL : familyName(r.family),
          r.neg_count,
          `${(r.share * 100).toFixed(1)} %`,
          r.z === null ? null : r.z.toFixed(1),
        ]),
      }}
    >
      <div className="mb-3">
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
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_15rem]">
        <div ref={ref} className="min-w-0">
          {view === "nivel" ? (
            <>
              <Stacked
                rows={shown}
                periods={periods}
                familias={familias}
                changes={families.data.prompt_changes}
                width={width}
              />
              <p className="mt-2 text-sm text-text-muted">
                Las familias de cada tramo vienen del prompt con el que se
                etiquetaron.
              </p>
            </>
          ) : (
            <>
              <Heat
                rows={shown}
                periods={periods}
                familias={familias}
                width={width}
              />
              <ZLegend />
              {unflagged ? (
                <div className="mt-2">
                  <Callout variant="info">
                    Estas series aún no tienen umbral: se muestra cuánto se
                    aleja cada mes de lo habitual, sin marcar alertas.
                  </Callout>
                </div>
              ) : null}
            </>
          )}
        </div>
        <fieldset className="m-0 grid content-start gap-1 border-0 p-0">
          <legend className="mb-1 text-sm font-semibold">
            Familias a mostrar
          </legend>
          {FAMILY_ORDER.map((f) => (
            <button
              key={f}
              type="button"
              aria-pressed={familias.includes(f)}
              onClick={() =>
                onFamilias(
                  familias.includes(f)
                    ? familias.filter((x) => x !== f)
                    : [...familias, f],
                )
              }
              className="flex items-center gap-2 rounded-sm border border-transparent px-2 py-1 text-left text-sm hover:bg-neutral-100 aria-pressed:border-brand aria-pressed:bg-green-100"
            >
              <span
                aria-hidden="true"
                className="size-2.5 shrink-0 rounded-full"
                style={{ background: `var(${FAMILY_COLORS[f]})` }}
              />
              <span className="flex-1">{familyName(f)}</span>
              {last ? (
                <span className="tabular text-xs text-text-muted">
                  {formatInt(
                    rows.find((r) => r.period === last && r.family === f)
                      ?.neg_count ?? 0,
                  )}
                </span>
              ) : null}
            </button>
          ))}
          {familias.length > 0 ? (
            <Button
              size="sm"
              variant="ghost"
              className="mt-1 justify-start"
              onClick={() => onFamilias([])}
            >
              Quitar la selección
            </Button>
          ) : null}
        </fieldset>
      </div>
      <div className="mt-6 border-t border-border pt-4">
        <MarkU rows={shown} periods={periods} width={width} />
      </div>
    </ChartFrame>
  );
}
