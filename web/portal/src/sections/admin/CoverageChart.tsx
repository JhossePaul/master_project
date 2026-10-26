import { scaleLinear } from "d3-scale";
import { area } from "d3-shape";
import { useRef } from "react";
import type { CoverageCurveResponse, CoveragePoint } from "@/api/admin";
import { Axis, DEFAULT_MARGIN, GridLines } from "@/charts/primitives";
import { useChartSize } from "@/charts/useChartSize";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatInt, formatPct } from "@/lib/format";

const HEIGHT = 300;
const MARGIN = { ...DEFAULT_MARGIN, right: 24, bottom: 40 };

/** Primer punto de la curva con cobertura ≥ la pedida (como `point_for`). */
export function pointFor(
  points: CoveragePoint[],
  coverage: number,
): CoveragePoint | null {
  return points.find((p) => p.coverage >= coverage - 1e-9) ?? null;
}

function Diamond({ x, y, fill, label }: DiamondProps) {
  return (
    <path
      d="M0,-8 L8,0 L0,8 L-8,0 Z"
      transform={`translate(${x},${y})`}
      fill={fill}
      stroke="var(--color-neutral-0)"
      strokeWidth={1.5}
    >
      <title>{label}</title>
    </path>
  );
}

interface DiamondProps {
  x: number;
  y: number;
  fill: string;
  label: string;
}

export function CoverageChart({
  data,
  proposed,
}: {
  data: CoverageCurveResponse;
  /** Cobertura que se está moviendo en el formulario. */
  proposed: number | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const { width } = useChartSize(ref);
  const points = data.curve.points;
  const w = Math.max((width || 640) - MARGIN.left - MARGIN.right, 120);
  const h = HEIGHT - MARGIN.top - MARGIN.bottom;
  const coverages = points.map((p) => p.coverage);
  const x = scaleLinear()
    .domain([Math.min(...coverages) - 0.01, Math.max(...coverages) + 0.01])
    .range([0, w]);
  const top = Math.max(...points.map((p) => p.risk_ci_high ?? p.risk), 0.01);
  const y = scaleLinear()
    .domain([0, top * 1.1])
    .range([h, 0])
    .nice();
  const band = area<CoveragePoint>()
    .x((p) => x(p.coverage))
    .y0((p) => y(p.risk_ci_low ?? p.risk))
    .y1((p) => y(p.risk_ci_high ?? p.risk))(points);
  const line = points
    .map((p, i) => `${i ? "L" : "M"}${x(p.coverage)},${y(p.risk)}`)
    .join(" ");
  const current = data.current_point;
  const moved = proposed === null ? null : pointFor(points, proposed);
  const showProposed = moved !== null && moved.coverage !== current?.coverage;
  const median = data.median_seconds;

  return (
    <div className="grid gap-4">
      <div ref={ref} className="w-full">
        <svg
          width={width || 640}
          height={HEIGHT}
          role="img"
          aria-label="Curva de cobertura y error esperado entre lo aceptado"
        >
          <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
            <GridLines scale={y} width={w} />
            <path
              d={band ?? undefined}
              fill="var(--color-green-200)"
              opacity={0.6}
            />
            <path
              d={line}
              fill="none"
              stroke="var(--color-green-600)"
              strokeWidth={2}
            />
            {points.map((p) => (
              <circle
                key={p.coverage}
                cx={x(p.coverage)}
                cy={y(p.risk)}
                r={3}
                fill="var(--color-green-600)"
              />
            ))}
            <g transform={`translate(0,${h})`}>
              <Axis
                scale={x}
                orientation="bottom"
                length={w}
                format={(v) => formatPct(Number(v), 0)}
                label="Cobertura"
              />
            </g>
            <Axis
              scale={y}
              orientation="left"
              length={h}
              format={(v) => formatPct(Number(v), 1)}
            />
            {current ? (
              <Diamond
                x={x(current.coverage)}
                y={y(current.risk)}
                fill="var(--color-gold-400)"
                label={`Vigente: ${formatPct(current.coverage, 0)}`}
              />
            ) : null}
            {showProposed && moved ? (
              <Diamond
                x={x(moved.coverage)}
                y={y(moved.risk)}
                fill="var(--color-brand)"
                label={`Propuesto: ${formatPct(moved.coverage, 0)}`}
              />
            ) : null}
          </g>
        </svg>
        <p className="text-xs text-text-muted">
          <span className="text-gold-700">◆ Vigente</span>
          {showProposed ? (
            <span className="ml-3 text-brand-strong">◆ Propuesto</span>
          ) : null}
          <span className="ml-3">
            Eje vertical: error esperado entre lo aceptado, con su intervalo.
          </span>
        </p>
      </div>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Cobertura</TableHead>
              <TableHead scope="col">Error esperado</TableHead>
              <TableHead scope="col">Errores atrapados</TableHead>
              <TableHead scope="col">Revisiones por semana</TableHead>
              <TableHead scope="col">Minutos por semana (curva)</TableHead>
              <TableHead scope="col">
                Minutos por semana (medidos, n = {formatInt(data.timed_n)})
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {points.map((p) => (
              <TableRow
                key={p.coverage}
                className={
                  p.coverage === current?.coverage ? "bg-gold-100" : undefined
                }
              >
                <TableCell>{formatPct(p.coverage, 0)}</TableCell>
                <TableCell>{formatPct(p.risk, 1)}</TableCell>
                <TableCell>{formatPct(p.errors_caught, 0)}</TableCell>
                <TableCell>
                  {formatInt(Math.round(p.reviews_per_week))}
                </TableCell>
                <TableCell>
                  {formatInt(Math.round(p.minutes_per_week))}
                </TableCell>
                <TableCell>
                  {median === null || median === undefined
                    ? "—"
                    : formatInt(Math.round((p.reviews_per_week * median) / 60))}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
