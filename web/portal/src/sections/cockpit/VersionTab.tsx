import { scaleBand, scaleLinear } from "d3-scale";
import { useMemo, useRef, useState } from "react";
import {
  type SentimentFilter,
  useVersionDaily,
  useVersions,
  type VersionDailyResponse,
} from "@/api/kpis";
import { Axis, GridLines } from "@/charts/primitives";
import { Callout } from "@/components/Callout";
import { ChartFrame } from "@/components/ChartFrame";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { BankId } from "@/config/banks";
import { formatDate, formatInt, formatPct, formatPctRange } from "@/lib/format";
import { BankPicker, familyName, LoadingBlock, useWidth } from "./shared";

const HEIGHT = 300;
const M = { top: 10, right: 8, bottom: 30, left: 48 };
const OTHER = "OTRAS";

/** Colores por orden de aparición: versiones vecinas contrastan entre sí. */
export const VERSION_COLORS = [
  "--color-green-700",
  "--color-gold-400",
  "--color-green-300",
  "--color-neutral-700",
  "--color-gold-700",
  "--color-green-500",
  "--color-sent-neg",
  "--color-gold-200",
] as const;
const OTHER_COLOR = "--color-neutral-300";

const SENTIMENTS: { key: SentimentFilter; label: string }[] = [
  { key: "ALL", label: "Todas" },
  { key: "NEG", label: "Negativas" },
  { key: "NEU", label: "Neutras" },
  { key: "POS", label: "Positivas" },
];

export function releaseColor(release: string, index: number): string {
  return release === OTHER
    ? OTHER_COLOR
    : (VERSION_COLORS[index % VERSION_COLORS.length] as string);
}

function shortDay(iso: string): string {
  return new Date(`${iso}T00:00:00Z`)
    .toLocaleDateString("es-MX", {
      day: "numeric",
      month: "short",
      timeZone: "UTC",
    })
    .replace(/\./g, "");
}

function Stacked({
  data,
  width,
}: {
  data: VersionDailyResponse;
  width: number;
}) {
  const colors = new Map(
    data.releases.map((r, i) => [r.release, releaseColor(r.release, i)]),
  );
  const days = data.days.map((d) => d.dia);
  const x = scaleBand<string>()
    .domain(days)
    .range([0, width - M.left - M.right])
    .padding(0.1);
  const totals = data.days.map((d) =>
    Object.values(d.counts).reduce((a, b) => a + b, 0),
  );
  const y = scaleLinear()
    .domain([0, Math.max(1, ...totals)])
    .range([HEIGHT - M.top - M.bottom, 0]);
  const step = Math.ceil(days.length / Math.max(2, Math.floor(width / 80)));
  const firstDay = days[0];
  const [hover, setHover] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);

  function move(event: React.MouseEvent<SVGSVGElement>) {
    const left = event.currentTarget.getBoundingClientRect().left;
    const offset = event.clientX - left - M.left;
    const index = Math.floor(
      (offset / (width - M.left - M.right)) * days.length,
    );
    setHover(index >= 0 && index < days.length ? index : null);
  }

  const point = hover === null ? null : data.days[hover];
  const tipLeft =
    hover === null
      ? 0
      : Math.min(
          M.left + (x(days[hover] as string) ?? 0) + x.bandwidth() + 8,
          Math.max(width - 230, 0),
        );
  return (
    <div ref={box} className="relative">
      <svg
        width={width}
        height={HEIGHT}
        role="img"
        aria-label="Reseñas por día y versión de la app"
        onMouseMove={move}
        onMouseLeave={() => setHover(null)}
      >
        <g transform={`translate(${M.left},${M.top})`}>
          <GridLines scale={y} width={width - M.left - M.right} />
          <Axis
            scale={y}
            orientation="left"
            length={HEIGHT - M.top - M.bottom}
            format={(v) => formatInt(v as number)}
          />
          {data.days.map((d) => {
            let acc = 0;
            return (
              <g key={d.dia} transform={`translate(${x(d.dia)},0)`}>
                {data.releases.map((r) => {
                  const n = d.counts[r.release] ?? 0;
                  if (n === 0) return null;
                  const top = y(acc + n);
                  const h = y(acc) - top;
                  acc += n;
                  return (
                    <rect
                      key={r.release}
                      y={top}
                      width={x.bandwidth()}
                      height={Math.max(h, 0)}
                      fill={`var(${colors.get(r.release)})`}
                    >
                      <title>{`${formatDate(d.dia)} · ${r.release}: ${formatInt(n)}`}</title>
                    </rect>
                  );
                })}
              </g>
            );
          })}
          {/* Despliegues: la primera vez que aparece cada versión del rango. */}
          {data.releases
            .filter((r) => r.release !== OTHER && r.first_day !== firstDay)
            .map((r) => (
              <line
                key={r.release}
                x1={x(r.first_day) ?? 0}
                x2={x(r.first_day) ?? 0}
                y1={0}
                y2={HEIGHT - M.top - M.bottom}
                stroke="var(--color-neutral-900)"
                strokeDasharray="2 3"
                opacity={0.6}
              />
            ))}
          {days.map((d, i) =>
            i % step === 0 ? (
              <text
                key={d}
                x={(x(d) ?? 0) + x.bandwidth() / 2}
                y={HEIGHT - M.top - M.bottom + 18}
                textAnchor="middle"
                fontSize={11}
                fill="var(--color-neutral-700)"
              >
                {shortDay(d)}
              </text>
            ) : null,
          )}
          {hover !== null ? (
            <rect
              x={(x(days[hover] as string) ?? 0) - 1}
              y={0}
              width={x.bandwidth() + 2}
              height={HEIGHT - M.top - M.bottom}
              fill="none"
              stroke="var(--color-neutral-950)"
              strokeWidth={1}
              pointerEvents="none"
            />
          ) : null}
        </g>
      </svg>
      {point ? (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute top-2 z-10 w-56 rounded-md border border-border bg-surface p-2 text-xs shadow-sm"
          style={{ left: tipLeft }}
        >
          <p className="font-semibold">{formatDate(point.dia)}</p>
          <p className="tabular text-text-muted">
            {formatInt(Object.values(point.counts).reduce((a, b) => a + b, 0))}{" "}
            reseñas
          </p>
          <ul className="mt-1 grid gap-0.5">
            {data.releases
              .filter((r) => (point.counts[r.release] ?? 0) > 0)
              .map((r) => (
                <li key={r.release} className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="size-2 shrink-0 rounded-full"
                    style={{ background: `var(${colors.get(r.release)})` }}
                  />
                  <span className="flex-1">
                    {r.release === OTHER ? "Otras o sin versión" : r.release}
                  </span>
                  <span className="tabular">
                    {formatInt(point.counts[r.release])}
                  </span>
                </li>
              ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function VersionTab({
  banks,
  bank,
  onBank,
  from,
  to,
}: {
  banks: BankId[];
  bank: BankId;
  onBank: (bank: BankId) => void;
  from: string;
  to: string;
}) {
  const [sentiment, setSentiment] = useState<SentimentFilter>("ALL");
  const { ref, width } = useWidth();
  const daily = useVersionDaily(bank, from, to, sentiment);
  const versions = useVersions(bank);
  const active = useMemo(
    () =>
      (versions.data?.rows ?? []).filter(
        (r) => r.release !== OTHER && r.last_seen >= from && r.first_seen <= to,
      ),
    [versions.data, from, to],
  );
  const label = SENTIMENTS.find((s) => s.key === sentiment)?.label ?? "";
  return (
    <div className="grid gap-6">
      <h2 className="font-serif text-2xl font-semibold text-green-800">
        Comparación entre versiones de la app
      </h2>
      <Callout variant="info">
        Descriptivo: no hay pruebas de cambio de nivel entre versiones. Las
        versiones se comparan dentro de un banco porque cada banco numera las
        suyas de otra manera.
      </Callout>
      {versions.data ? (
        <p className="text-sm text-text-muted">
          El{" "}
          <span className="tabular">{formatPct(versions.data.coverage)}</span>{" "}
          de las reseñas tiene versión reconocida.
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <BankPicker
          banks={banks}
          value={bank}
          onChange={onBank}
          label="Banco de la vista por versión"
        />
        <fieldset className="m-0 flex flex-wrap items-center gap-1 border-0 p-0">
          <legend className="sr-only">Sentimiento</legend>
          <span className="text-sm text-text-muted">Reseñas:</span>
          {SENTIMENTS.map(({ key, label: text }) => (
            <Button
              key={key}
              size="sm"
              variant={key === sentiment ? "primary" : "secondary"}
              aria-pressed={key === sentiment}
              onClick={() => setSentiment(key)}
            >
              {text}
            </Button>
          ))}
        </fieldset>
      </div>
      <ChartFrame
        kicker="Por versión"
        title="Reseñas por día y versión de la app"
        subtitle={`${label} · del ${formatDate(from)} al ${formatDate(to)}`}
        method="raw"
        howToRead={
          <p>
            Cada barra es un día y cada color, una versión de la app: donde un
            color releva a otro hubo un despliegue (las líneas punteadas marcan
            la primera vez que aparece cada versión). Se muestran las 8
            versiones con más reseñas del rango; el resto y las reseñas sin
            versión reconocida van en gris. Cambia el sentimiento para ver solo
            las negativas, por ejemplo.
          </p>
        }
        provenance={{ note: "conteo del modelo, sin ajustar" }}
        data={{
          columns: ["Día", "Versión", "Reseñas"],
          rows: (daily.data?.days ?? []).flatMap((d) =>
            Object.entries(d.counts).map(([release, n]) => [d.dia, release, n]),
          ),
        }}
      >
        {daily.isPending ? <LoadingBlock /> : null}
        {daily.isError ? (
          <ErrorState error={daily.error} onRetry={() => daily.refetch()} />
        ) : null}
        {daily.data ? (
          daily.data.days.length === 0 ? (
            <p className="text-sm text-text-muted">
              No hay reseñas de ese tipo en el rango.
            </p>
          ) : (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_15rem]">
              <div ref={ref} className="min-w-0">
                <Stacked data={daily.data} width={width} />
              </div>
              <ul className="grid content-start gap-1" aria-label="Versiones">
                {daily.data.releases.map((r, i) => (
                  <li
                    key={r.release}
                    className="flex items-center gap-2 text-sm"
                  >
                    <span
                      aria-hidden="true"
                      className="size-2.5 shrink-0 rounded-full"
                      style={{
                        background: `var(${releaseColor(r.release, i)})`,
                      }}
                    />
                    <span className="flex-1">
                      {r.release === OTHER ? "Otras o sin versión" : r.release}
                    </span>
                    <span className="tabular text-xs text-text-muted">
                      {r.release === OTHER
                        ? formatInt(r.filas)
                        : `desde ${shortDay(r.first_day)} · ${formatInt(r.filas)}`}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )
        ) : null}
      </ChartFrame>
      <section aria-label="Tabla de versiones" className="grid gap-2">
        <h3 className="font-serif text-xl font-semibold">
          Versiones activas en el rango
        </h3>
        {versions.data?.median_neg_share != null ? (
          <p className="text-sm text-text-muted">
            Mediana del banco entre todas sus versiones:{" "}
            <span className="tabular">
              {formatPct(versions.data.median_neg_share)}
            </span>{" "}
            de negativas y{" "}
            <span className="tabular">
              {formatPct(versions.data.median_u_share)}
            </span>{" "}
            de ellas hablan de una actualización. Las cifras de la tabla son de
            toda la vida de cada versión.
          </p>
        ) : null}
        {versions.isPending ? <LoadingBlock /> : null}
        {versions.isError ? (
          <ErrorState
            error={versions.error}
            onRetry={() => versions.refetch()}
          />
        ) : null}
        {versions.data ? (
          <div className="max-h-96 overflow-auto rounded-sm border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Versión</TableHead>
                  <TableHead scope="col">Fechas</TableHead>
                  <TableHead scope="col">Reseñas</TableHead>
                  <TableHead scope="col">Negativas</TableHead>
                  <TableHead scope="col">
                    Relacionada con una actualización
                  </TableHead>
                  <TableHead scope="col">Familias principales</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {active.map((r) => (
                  <TableRow key={r.release}>
                    <TableCell>{r.release}</TableCell>
                    <TableCell>
                      {formatDate(r.first_seen)} – {formatDate(r.last_seen)}
                    </TableCell>
                    <TableCell className="tabular">
                      {formatInt(r.filas)}
                    </TableCell>
                    <TableCell className="tabular">
                      {formatPct(r.neg_share)} (
                      {formatPctRange(r.neg_ci_low, r.neg_ci_high)})
                    </TableCell>
                    <TableCell className="tabular">
                      {formatPct(r.u_share)}
                    </TableCell>
                    <TableCell>
                      {Object.entries(r.families)
                        .slice(0, 3)
                        .map(
                          ([code, share]) =>
                            `${familyName(code)} ${formatPct(share, 0)}`,
                        )
                        .join(" · ") || "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
