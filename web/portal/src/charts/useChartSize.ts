import { type RefObject, useEffect, useState } from "react";

export interface ChartSize {
  width: number;
  height: number;
}

/** Ancho y alto del contenedor, actualizados con ResizeObserver. */
export function useChartSize(ref: RefObject<HTMLElement | null>): ChartSize {
  const [size, setSize] = useState<ChartSize>({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setSize({ width: el.clientWidth, height: el.clientHeight });
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry)
        setSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}
