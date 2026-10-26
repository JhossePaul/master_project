import Dygraph, { type dygraphs } from "dygraphs";
import { useEffect, useRef } from "react";
import { cssVar } from "@/charts/color";

export interface TimeSeriesItem {
  id: string;
  label: string;
  colorVar: string;
  dash?: number[];
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
      colors: series.map((s) => cssVar(s.colorVar)),
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
      drawCallback: (g, initial) => {
        if (initial) return;
        const [from, to] = g.xAxisRange();
        callbacks.current.onRangeChange?.(new Date(from), new Date(to));
      },
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
    series.forEach((s, i) => {
      if (s.dash?.length) {
        (options as Record<string, unknown>)[s.label] = {
          strokePattern: s.dash,
        };
      }
      void i;
    });
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
    <div
      ref={ref}
      role="img"
      aria-label={`Serie de tiempo: ${series.map((s) => s.label).join(", ")}`}
    />
  );
}
