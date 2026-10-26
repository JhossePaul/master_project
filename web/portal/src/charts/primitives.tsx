import type { ScaleLinear, ScaleTime } from "d3-scale";
import { line as d3line } from "d3-shape";
import type { ReactNode } from "react";

type XScale = ScaleLinear<number, number> | ScaleTime<number, number>;
type YScale = ScaleLinear<number, number>;

export interface Margin {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export const DEFAULT_MARGIN: Margin = {
  top: 12,
  right: 72,
  bottom: 28,
  left: 44,
};

/** Eje inferior o izquierdo con las marcas de ``scale.ticks()``. */
export function Axis({
  scale,
  orientation,
  length,
  format,
  label,
}: {
  scale: XScale | YScale;
  orientation: "bottom" | "left";
  length: number;
  format: (value: number | Date) => string;
  label?: string;
}) {
  const ticks = (scale as YScale).ticks(
    orientation === "bottom" ? Math.max(2, Math.floor(length / 90)) : 5,
  );
  const position = (t: number | Date) => (scale as YScale)(t as number);
  return (
    <g fontSize={12} fill="var(--color-neutral-700)">
      {orientation === "bottom" ? (
        <>
          <line x1={0} x2={length} stroke="var(--color-neutral-400)" />
          {ticks.map((t) => (
            <g key={String(t)} transform={`translate(${position(t)},0)`}>
              <line y2={4} stroke="var(--color-neutral-400)" />
              <text y={18} textAnchor="middle" className="tabular">
                {format(t)}
              </text>
            </g>
          ))}
          {label ? (
            <text x={length} y={32} textAnchor="end">
              {label}
            </text>
          ) : null}
        </>
      ) : (
        <>
          <line y1={0} y2={length} stroke="var(--color-neutral-400)" />
          {ticks.map((t) => (
            <g key={String(t)} transform={`translate(0,${position(t)})`}>
              <line x2={-4} stroke="var(--color-neutral-400)" />
              <text x={-8} dy="0.32em" textAnchor="end" className="tabular">
                {format(t)}
              </text>
            </g>
          ))}
        </>
      )}
    </g>
  );
}

export function GridLines({ scale, width }: { scale: YScale; width: number }) {
  return (
    <g stroke="var(--color-neutral-200)">
      {scale.ticks(5).map((t) => (
        <line key={t} x1={0} x2={width} y1={scale(t)} y2={scale(t)} />
      ))}
    </g>
  );
}

export function Line({
  points,
  x,
  y,
  colorVar,
  dash = [],
  strokeWidth = 2,
}: {
  points: { x: number | Date; y: number | null }[];
  x: XScale;
  y: YScale;
  colorVar: string;
  dash?: number[];
  strokeWidth?: number;
}) {
  const path = d3line<{ x: number | Date; y: number | null }>()
    .defined((p) => p.y !== null)
    .x((p) => (x as YScale)(p.x as number))
    .y((p) => y(p.y as number))(points);
  return (
    <path
      d={path ?? undefined}
      fill="none"
      stroke={`var(${colorVar})`}
      strokeWidth={strokeWidth}
      strokeDasharray={dash.join(" ") || undefined}
    />
  );
}

/** Intervalo de confianza: banda del color de la serie al 18 %. */
export function Band({
  points,
  x,
  y,
  colorVar,
}: {
  points: { x: number | Date; lo: number; hi: number }[];
  x: XScale;
  y: YScale;
  colorVar: string;
}) {
  if (points.length === 0) return null;
  const px = (p: { x: number | Date }) => (x as YScale)(p.x as number);
  const upper = points.map((p) => `${px(p)},${y(p.hi)}`);
  const lower = [...points].reverse().map((p) => `${px(p)},${y(p.lo)}`);
  return (
    <polygon
      points={[...upper, ...lower].join(" ")}
      fill={`var(${colorVar})`}
      opacity={0.18}
    />
  );
}

/** Estimaciones puntuales con barra de error de 1 px. */
export function Points({
  points,
  x,
  y,
  colorVar,
  radius = 4,
}: {
  points: {
    x: number | Date;
    y: number;
    lo?: number | null;
    hi?: number | null;
    label?: string;
  }[];
  x: XScale;
  y: YScale;
  colorVar: string;
  radius?: number;
}) {
  return (
    <g>
      {points.map((p) => {
        const cx = (x as YScale)(p.x as number);
        return (
          <g key={`${String(p.x)}-${p.y}`}>
            {p.lo != null && p.hi != null ? (
              <line
                x1={cx}
                x2={cx}
                y1={y(p.lo)}
                y2={y(p.hi)}
                stroke={`var(${colorVar})`}
                strokeWidth={1}
              />
            ) : null}
            <circle cx={cx} cy={y(p.y)} r={radius} fill={`var(${colorVar})`}>
              {p.label ? <title>{p.label}</title> : null}
            </circle>
          </g>
        );
      })}
    </g>
  );
}

/** Umbral o valor vigente: línea discontinua de 1.5 px en dorado, con etiqueta. */
export function ReferenceLine({
  y,
  width,
  label,
  scale,
}: {
  y: number;
  width: number;
  label: string;
  scale: YScale;
}) {
  const py = scale(y);
  return (
    <g>
      <line
        x1={0}
        x2={width}
        y1={py}
        y2={py}
        stroke="var(--color-gold-600)"
        strokeWidth={1.5}
        strokeDasharray="6 4"
      />
      <text
        x={width}
        y={py - 4}
        textAnchor="end"
        fontSize={12}
        fill="var(--color-gold-700)"
      >
        {label}
      </text>
    </g>
  );
}

/** Líneas verticales punteadas con la versión arriba. */
export function VersionMarkers({
  markers,
  x,
  height,
}: {
  markers: { at: number | Date; label: string }[];
  x: XScale;
  height: number;
}) {
  return (
    <g>
      {markers.map((m) => {
        const px = (x as YScale)(m.at as number);
        return (
          <g key={m.label} transform={`translate(${px},0)`}>
            <line
              y2={height}
              stroke="var(--color-neutral-500)"
              strokeDasharray="2 3"
            />
            <text
              y={-2}
              textAnchor="middle"
              fontSize={11}
              fill="var(--color-neutral-700)"
            >
              {m.label}
            </text>
          </g>
        );
      })}
    </g>
  );
}

/** Leyenda con etiquetas directas, al final de cada línea. */
export function Legend({
  items,
  y,
  x,
}: {
  items: { label: string; colorVar: string; last: number | null }[];
  y: YScale;
  x: number;
}): ReactNode {
  return (
    <g fontSize={12}>
      {items.map((item) =>
        item.last === null ? null : (
          <text
            key={item.label}
            x={x + 6}
            y={y(item.last)}
            dy="0.32em"
            fill={`var(${item.colorVar})`}
            fontWeight={600}
          >
            {item.label}
          </text>
        ),
      )}
    </g>
  );
}
