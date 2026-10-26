import { Button } from "@/components/ui/button";
import {
  formatPct,
  formatPctInterval,
  formatStars,
  formatStarsInterval,
} from "@/lib/format";
import { useParam } from "./params";

export type Kpi = "neg" | "gap" | "quejas";

export interface KpiSpec {
  label: string;
  /** Métrica de ``/kpis/monthly`` y celda de la tarjeta. */
  metric: string;
  format: (value: number | null | undefined) => string;
  interval: (lo?: number | null, hi?: number | null) => string;
  /** Diferencia entre dos estimaciones, con signo. */
  diff: (value: number) => string;
  /** Eje de las gráficas. */
  tick: (value: number) => string;
}

function signed(x: number, text: string): string {
  return `${x > 0 ? "+" : x < 0 ? "−" : ""}${text}`;
}

const PCT_DIFF = (x: number) =>
  signed(x, formatPct(Math.abs(x)).replace(" %", " pts"));

export const KPIS: Record<Kpi, KpiSpec> = {
  neg: {
    label: "Reseñas negativas",
    metric: "neg",
    format: (v) => formatPct(v),
    interval: formatPctInterval,
    diff: PCT_DIFF,
    tick: (v) => formatPct(v, 0),
  },
  gap: {
    label: "Brecha en estrellas",
    metric: "gap_estrellas",
    format: (v) => formatStars(v),
    interval: formatStarsInterval,
    diff: (x) => formatStars(x),
    tick: (v) => formatStars(v),
  },
  quejas: {
    label: "Quejas con 4–5 estrellas",
    metric: "estrellas_POS_texto_NEG",
    format: (v) => formatPct(v),
    interval: formatPctInterval,
    diff: PCT_DIFF,
    tick: (v) => formatPct(v, 0),
  },
};

export const KPI_ORDER: Kpi[] = ["neg", "gap", "quejas"];

/** El KPI elegido, compartido por toda la vista (``?kpi=``). */
export function useKpi() {
  const [value, set] = useParam("kpi", /^(neg|gap|quejas)$/);
  const kpi: Kpi = (value as Kpi | null) ?? "neg";
  return [kpi, (next: Kpi) => set(next === "neg" ? null : next)] as const;
}

/** Botones del KPI, ligados al estado compartido de la URL. */
export function KpiButtons() {
  const [kpi, setKpi] = useKpi();
  return (
    <fieldset className="m-0 flex flex-wrap gap-1 border-0 p-0">
      <legend className="sr-only">Medida</legend>
      {KPI_ORDER.map((key) => (
        <Button
          key={key}
          size="sm"
          variant={key === kpi ? "primary" : "secondary"}
          aria-pressed={key === kpi}
          onClick={() => setKpi(key)}
        >
          {KPIS[key].label}
        </Button>
      ))}
    </fieldset>
  );
}
