import { extent } from "d3-array";
import { scaleLinear, scaleTime } from "d3-scale";
import { useRef } from "react";
import {
  Axis,
  DEFAULT_MARGIN,
  GridLines,
  Line,
  Points,
  ReferenceLine,
} from "@/charts/primitives";
import { useChartSize } from "@/charts/useChartSize";
import { formatMonth } from "@/lib/format";

export interface DriftPoint {
  period: string; // "2026-09"
  value: number | null;
  baseline?: number | null;
}

interface DriftChartProps {
  /** Describe la gráfica para lectores de pantalla. */
  label: string;
  points: DriftPoint[];
  /** Mes de la alerta: se resalta. */
  highlight: string;
  colorVar: string;
  format: (value: number) => string;
  /** Umbrales (líneas doradas discontinuas). */
  thresholds?: { value: number; label: string }[];
  showBaseline?: boolean;
  height?: number;
}

const FALLBACK_WIDTH = 640;

function monthDate(period: string): Date {
  return new Date(`${period}-01T00:00:00Z`);
}

export function DriftChart({
  label,
  points,
  highlight,
  colorVar,
  format,
  thresholds = [],
  showBaseline = false,
  height = 240,
}: DriftChartProps) {
  const box = useRef<HTMLDivElement>(null);
  const { width: measured } = useChartSize(box);
  const width = measured || FALLBACK_WIDTH;
  const m = DEFAULT_MARGIN;
  const innerW = Math.max(width - m.left - m.right, 10);
  const innerH = height - m.top - m.bottom;

  const dates = points.map((p) => monthDate(p.period));
  const numbers = [
    ...points.flatMap((p) => [p.value, showBaseline ? p.baseline : null]),
    ...thresholds.map((t) => t.value),
  ].filter((v): v is number => typeof v === "number");
  const [lo = 0, hi = 1] = extent(numbers);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.1;
  const x = scaleTime()
    .domain(extent(dates) as [Date, Date])
    .range([0, innerW]);
  const y = scaleLinear()
    .domain([lo - pad, hi + pad])
    .nice()
    .range([innerH, 0]);

  const marked = points.find((p) => p.period === highlight);
  const markedX = marked ? x(monthDate(marked.period)) : null;

  return (
    <div ref={box} className="w-full">
      <svg
        role="img"
        aria-label={label}
        width={width}
        height={height}
        className="block"
      >
        <g transform={`translate(${m.left},${m.top})`}>
          <GridLines scale={y} width={innerW} />
          {markedX !== null ? (
            <rect
              data-testid="alert-month"
              x={markedX - 10}
              y={0}
              width={20}
              height={innerH}
              fill="var(--color-gold-100)"
            />
          ) : null}
          <g transform={`translate(0,${innerH})`}>
            <Axis
              scale={x}
              orientation="bottom"
              length={innerW}
              format={(v) => formatMonth(v as Date)}
            />
          </g>
          <Axis
            scale={y}
            orientation="left"
            length={innerH}
            format={(v) => format(v as number)}
          />
          {showBaseline ? (
            <Line
              points={points.map((p) => ({
                x: monthDate(p.period),
                y: p.baseline ?? null,
              }))}
              x={x}
              y={y}
              colorVar="--color-neutral-600"
              dash={[4, 3]}
              strokeWidth={1.5}
            />
          ) : null}
          <Line
            points={points.map((p) => ({
              x: monthDate(p.period),
              y: p.value,
            }))}
            x={x}
            y={y}
            colorVar={colorVar}
          />
          <Points
            points={points
              .filter(
                (p): p is DriftPoint & { value: number } => p.value !== null,
              )
              .map((p) => ({
                x: monthDate(p.period),
                y: p.value,
                label: `${formatMonth(p.period)}: ${format(p.value)}`,
              }))}
            x={x}
            y={y}
            colorVar={colorVar}
            radius={2.5}
          />
          {marked && marked.value !== null ? (
            <Points
              points={[
                {
                  x: monthDate(marked.period),
                  y: marked.value,
                  label: `Mes de la alerta, ${formatMonth(marked.period)}: ${format(marked.value)}`,
                },
              ]}
              x={x}
              y={y}
              colorVar="--color-danger"
              radius={6}
            />
          ) : null}
          {thresholds.map((t) => (
            <ReferenceLine
              key={t.label}
              y={t.value}
              width={innerW}
              scale={y}
              label={t.label}
              labelOutside
            />
          ))}
        </g>
      </svg>
    </div>
  );
}
