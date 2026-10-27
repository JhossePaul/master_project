import { extent } from "d3-array";
import { scaleLinear } from "d3-scale";
import { useRef } from "react";
import type { QualityPoint, QualitySeries } from "@/api/mlops";
import {
  Axis,
  DEFAULT_MARGIN,
  GridLines,
  Line,
  Points,
  ReferenceLine,
} from "@/charts/primitives";
import { useChartSize } from "@/charts/useChartSize";
import { type Status, StatusPill } from "@/components/StatusPill";
import { formatKappa, formatPct } from "@/lib/format";

export type Signal = QualitySeries["signal"];
export type QualityStatus = QualityPoint["status"];

export interface SignalInfo {
  title: string;
  /** `floor`: el estado baja si el valor cae bajo el umbral; `cap`: si lo pasa. */
  kind: "floor" | "cap";
  format: (value: number) => string;
  help: string;
}

export const SIGNALS: Record<Signal, SignalInfo> = {
  kappa_monitor: {
    title: "κ trimestral con la revisión humana",
    kind: "floor",
    format: formatKappa,
    help: "Acuerdo del modelo con la muestra de monitoreo que revisan personas. Bajo el piso, el monitor avisa que conviene reentrenar.",
  },
  correction_rate: {
    title: "Tasa de corrección de la cola (4 semanas)",
    kind: "cap",
    format: (v) => formatPct(v),
    help: "Qué parte de las reseñas de la cola de revisión corrigió una persona. Sobre el tope, el monitor da un aviso.",
  },
  gemini_agreement: {
    title: "Acuerdo con Gemini (4 semanas)",
    kind: "floor",
    format: (v) => formatPct(v),
    help: "Coincidencia del modelo con Gemini en una muestra semanal. Bajo el piso, el monitor da un aviso.",
  },
  families_validation: {
    title: "Revalidación de las familias",
    kind: "floor",
    format: (v) => formatPct(v),
    help: "Coincidencia exacta de las familias que asigna Gemini con el oro de aspectos. Bajo el piso, la versión del prompt se rechaza.",
  },
};

export const SIGNAL_ORDER: Signal[] = [
  "kappa_monitor",
  "correction_rate",
  "gemini_agreement",
  "families_validation",
];

const PILL: Record<QualityStatus, Status> = {
  ok: "ok",
  warning: "aviso",
  retrain: "reentrenar",
  rejected: "rechazado",
};

export function QualityPill({ status }: { status: QualityStatus }) {
  return <StatusPill status={PILL[status]} />;
}

export interface ChartPoint {
  label: string;
  value: number;
  lo?: number | null;
  hi?: number | null;
}

const FALLBACK_WIDTH = 520;

/** Serie por periodo (trimestre, mes…) con su umbral en línea discontinua dorada. */
export function SeriesChart({
  label,
  points,
  threshold,
  thresholdLabel,
  format,
  height = 160,
  colorVar = "--color-brand",
}: {
  label: string;
  points: ChartPoint[];
  threshold?: number | null;
  thresholdLabel?: string;
  format: (value: number) => string;
  height?: number;
  colorVar?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const { width: measured } = useChartSize(box);
  const width = measured || FALLBACK_WIDTH;
  const m = { ...DEFAULT_MARGIN, right: 64 };
  const innerW = Math.max(width - m.left - m.right, 10);
  const innerH = height - m.top - m.bottom;
  const numbers = [
    ...points.flatMap((p) => [p.value, p.lo, p.hi]),
    threshold,
  ].filter((v): v is number => typeof v === "number");
  const [lo = 0, hi = 1] = extent(numbers);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.15;
  const x = scaleLinear()
    .domain([0, Math.max(points.length - 1, 1)])
    .range([0, innerW]);
  const y = scaleLinear()
    .domain([lo - pad, hi + pad])
    .nice()
    .range([innerH, 0]);
  const at = (v: number | Date) => {
    const i = Number(v);
    return Number.isInteger(i) ? (points[i]?.label ?? "") : "";
  };
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
          <g transform={`translate(0,${innerH})`}>
            <Axis scale={x} orientation="bottom" length={innerW} format={at} />
          </g>
          <Axis
            scale={y}
            orientation="left"
            length={innerH}
            format={(v) => format(Number(v))}
          />
          <Line
            points={points.map((p, i) => ({ x: i, y: p.value }))}
            x={x}
            y={y}
            colorVar={colorVar}
          />
          <Points
            points={points.map((p, i) => ({
              x: i,
              y: p.value,
              lo: p.lo,
              hi: p.hi,
              label: `${p.label}: ${format(p.value)}`,
            }))}
            x={x}
            y={y}
            colorVar={colorVar}
            radius={3}
          />
          {typeof threshold === "number" ? (
            <ReferenceLine
              y={threshold}
              width={innerW}
              scale={y}
              label={thresholdLabel ?? format(threshold)}
              labelOutside
            />
          ) : null}
        </g>
      </svg>
    </div>
  );
}
