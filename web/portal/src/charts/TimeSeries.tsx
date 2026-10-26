import Dygraph, { type dygraphs } from "dygraphs";
import { useEffect, useRef } from "react";
import { cssVar } from "@/charts/color";

export interface TimeSeriesItem {
  id: string;
  label: string;
  colorVar: string;
  dash?: number[];
  /** Línea de fondo: más fina y translúcida. */
  faint?: boolean;
  points: [Date, number | null][];
}

export interface TimeSeriesProps {
  series: TimeSeriesItem[];
  bands?: { from: Date; to: Date; colorVar: string }[];
  markers?: { at: Date; label: string }[];
  valueFormatter: (value: number) => string;
  height: number;
  selectedDate?: Date | null;
  onSelectDate?: (date: Date) => void;
  onRangeChange?: (from: Date, to: Date) => void;
}

/** ``#rrggbb`` con transparencia. */
function withAlpha(color: string, alpha: number): string {
  const hex = /^#([0-9a-f]{6})$/i.exec(color)?.[1];
  if (!hex) return color;
  const n = Number.parseInt(hex, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

/** Envoltorio de dygraphs para series diarias largas. */
export function TimeSeries({
  series,
  bands = [],
  markers = [],
  valueFormatter,
  height,
  selectedDate = null,
  onSelectDate,
  onRangeChange,
}: TimeSeriesProps) {
  const ref = useRef<HTMLDivElement>(null);
  const legend = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onSelectDate, onRangeChange });
  callbacks.current = { onSelectDate, onRangeChange };

  useEffect(() => {
    const el = ref.current;
    if (!el || series.length === 0) return;
    const times = [
      ...new Set(series.flatMap((s) => s.points.map(([d]) => d.getTime()))),
    ].sort((a, b) => a - b);
    const lookup = series.map(
      (s) => new Map(s.points.map(([d, v]) => [d.getTime(), v])),
    );
    const data = times.map((t) => [
      new Date(t),
      ...lookup.map((m) => m.get(t) ?? null),
    ]);
    const options: dygraphs.Options = {
      labels: ["día (UTC)", ...series.map((s) => s.label)],
      colors: series.map((s) =>
        s.faint ? withAlpha(cssVar(s.colorVar), 0.35) : cssVar(s.colorVar),
      ),
      // La leyenda y los valores al pasar el cursor van en su franja, no
      // encima del eje.
      labelsDiv: legend.current ?? undefined,
      labelsSeparateLines: false,
      legend: "onmouseover",
      height,
      strokeWidth: 1.5,
      axisLabelFontSize: 12,
      gridLineColor: cssVar("--color-neutral-200"),
      axisLineColor: cssVar("--color-neutral-400"),
      connectSeparatedPoints: false,
      axes: {
        y: {
          valueFormatter: (v: number) => valueFormatter(v),
          axisLabelFormatter: (v) => valueFormatter(v as number),
        },
      },
      // Solo cuando la persona arrastra para acercar, no en cada redibujo.
      zoomCallback: (min: number, max: number) =>
        callbacks.current.onRangeChange?.(new Date(min), new Date(max)),
      underlayCallback: (ctx, area, g) => {
        for (const band of bands) {
          const left = g.toDomXCoord(band.from.getTime());
          const right = g.toDomXCoord(band.to.getTime());
          ctx.fillStyle = cssVar(band.colorVar);
          ctx.fillRect(left, area.y, Math.max(right - left, 1), area.h);
        }
        if (selectedDate) {
          const left = g.toDomXCoord(selectedDate.getTime());
          ctx.fillStyle = cssVar("--color-gold-100");
          ctx.fillRect(left - 3, area.y, 6, area.h);
        }
      },
      clickCallback: (_event, x) =>
        callbacks.current.onSelectDate?.(new Date(x)),
    };
    for (const s of series) {
      const own: Record<string, unknown> = {};
      if (s.dash?.length) own.strokePattern = s.dash;
      if (s.faint) own.strokeWidth = 0.8;
      if (Object.keys(own).length > 0)
        (options as Record<string, unknown>)[s.label] = own;
    }
    const graph = new Dygraph(el, data, options);
    graph.ready(() => {
      graph.setAnnotations(
        markers.map((m) => ({
          series: series[0]?.label ?? "",
          x: m.at.getTime(),
          shortText: "v",
          text: m.label,
          cssClass: "dygraph-annotation",
        })),
      );
    });
    return () => graph.destroy();
  }, [series, bands, markers, valueFormatter, height, selectedDate]);

  return (
    <div>
      <ul
        aria-hidden="true"
        className="mb-2 flex flex-wrap gap-x-5 gap-y-1 text-sm font-semibold"
      >
        {series
          .filter((s) => !s.faint)
          .map((s) => (
            <li
              key={s.id}
              className="flex items-center gap-2"
              style={{ color: `var(${s.colorVar})` }}
            >
              <svg width="28" height="8" aria-hidden="true">
                <line
                  x1="0"
                  x2="28"
                  y1="4"
                  y2="4"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeDasharray={s.dash?.join(" ") || undefined}
                />
              </svg>
              {s.label}
            </li>
          ))}
      </ul>
      <div
        ref={legend}
        aria-hidden="true"
        className="tabular mb-1 min-h-7 rounded-sm bg-surface-muted px-2 py-1 text-sm empty:before:text-text-muted empty:before:content-['Pasa_el_cursor_sobre_la_gráfica_para_ver_los_valores']"
      />
      <div
        ref={ref}
        role="img"
        aria-label={`Serie de tiempo: ${series.map((s) => s.label).join(", ")}`}
      />
    </div>
  );
}
