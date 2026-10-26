import { useRef, useState } from "react";
import { formatInt, formatMonth } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface MonthBar {
  key: string; // AAAA-MM
  n: number;
}

function lastDay(month: string): string {
  const [year, m] = month.split("-").map(Number) as [number, number];
  return new Date(Date.UTC(year, m, 0)).toISOString().slice(0, 10);
}

/** Reseñas por mes: pulsar un mes o arrastrar varios fija `desde` y `hasta`. */
export function MonthChart({
  bars,
  from,
  to,
  onSelect,
}: {
  bars: MonthBar[];
  from: string;
  to: string;
  onSelect: (from: string, to: string) => void;
}) {
  const [drag, setDrag] = useState<{ a: number; b: number } | null>(null);
  const dragging = useRef(false);
  const max = Math.max(1, ...bars.map((b) => b.n));

  function finish(range: { a: number; b: number } | null) {
    dragging.current = false;
    setDrag(null);
    if (!range) return;
    const lo = Math.min(range.a, range.b);
    const hi = Math.max(range.a, range.b);
    const first = bars[lo];
    const last = bars[hi];
    if (first && last) onSelect(`${first.key}-01`, lastDay(last.key));
  }

  const inRange = (i: number) =>
    drag
      ? i >= Math.min(drag.a, drag.b) && i <= Math.max(drag.a, drag.b)
      : false;
  const inFilter = (key: string) =>
    `${key}-01` <= to && lastDay(key) >= from && !drag;

  return (
    <section aria-label="Reseñas por mes" className="min-w-0">
      <h3 className="mb-1 text-sm font-semibold">Reseñas por mes</h3>
      {bars.length === 0 ? (
        <p className="text-sm text-text-muted">Sin datos con estos filtros.</p>
      ) : (
        <ul
          className="flex h-28 items-end gap-0.5"
          onPointerUp={() => dragging.current && finish(drag)}
          onPointerLeave={() => dragging.current && finish(drag)}
        >
          {bars.map((bar, i) => (
            <li key={bar.key} className="flex h-full min-w-0 flex-1 items-end">
              <button
                type="button"
                aria-label={`${formatMonth(`${bar.key}-01`)}: ${formatInt(bar.n)} reseñas`}
                aria-pressed={inFilter(bar.key)}
                onPointerDown={() => {
                  dragging.current = true;
                  setDrag({ a: i, b: i });
                }}
                onPointerEnter={() =>
                  dragging.current && setDrag((d) => (d ? { ...d, b: i } : d))
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(`${bar.key}-01`, lastDay(bar.key));
                  }
                }}
                className={cn(
                  "w-full rounded-t-sm bg-green-300 hover:bg-green-400",
                  inFilter(bar.key) && "bg-green-500",
                  inRange(i) && "bg-gold-400",
                )}
                style={{ height: `${Math.max((bar.n / max) * 100, 3)}%` }}
              />
            </li>
          ))}
        </ul>
      )}
      {bars.length > 0 ? (
        <p className="mt-1 flex justify-between text-xs text-text-muted">
          <span>{formatMonth(`${bars[0]?.key}-01`)}</span>
          <span>{formatMonth(`${bars[bars.length - 1]?.key}-01`)}</span>
        </p>
      ) : null}
      <p className="text-xs text-text-muted">
        Pulsa un mes o arrastra para elegir un rango.
      </p>
    </section>
  );
}
