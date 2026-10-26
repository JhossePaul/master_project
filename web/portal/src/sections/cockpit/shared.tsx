import { ArrowUpRight } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import type { MonthlyKpi } from "@/api/kpis";
import { Button } from "@/components/ui/button";
import { BANK_IDS, BANKS, type BankId, bankLabel } from "@/config/banks";

/** Orden y color de las familias de aspectos (tokens de tokens.css). */
export const FAMILY_ORDER = [
  "AC",
  "FA",
  "LE",
  "TR",
  "DI",
  "PR",
  "AT",
  "DV",
  "UX",
  "CO",
  "OT",
] as const;

export const FAMILY_COLORS: Record<string, string> = {
  AC: "--color-green-300",
  FA: "--color-green-500",
  LE: "--color-green-700",
  TR: "--color-green-900",
  DI: "--color-gold-200",
  PR: "--color-gold-400",
  AT: "--color-gold-600",
  DV: "--color-gold-800",
  UX: "--color-neutral-400",
  CO: "--color-neutral-600",
  OT: "--color-neutral-800",
  u: "--color-sent-neg",
};

export const FAMILY_NAMES: Record<string, string> = {
  AC: "Acceso y autenticación",
  FA: "Falla general de la app",
  LE: "Lentitud general",
  TR: "Transferencias y pagos",
  DI: "Dinero y cargos",
  PR: "Productos y cuentas",
  AT: "Atención",
  DV: "Diseño visual",
  UX: "Usabilidad y cambios de funciones",
  CO: "Compatibilidad y actualización",
  OT: "Sin familia",
  u: "Mención de actualización",
};

export function familyName(code: string): string {
  return FAMILY_NAMES[code] ?? code;
}

export interface ExplorerFilters {
  banks: BankId[];
  from: string;
  to: string;
  familia?: string | null;
  sentimiento?: string | null;
}

/** Dirección del Explorador con los filtros que el bloque tiene fijados. */
export function explorerUrl(f: ExplorerFilters): string {
  const params = new URLSearchParams();
  if (f.banks.length > 0 && f.banks.length < BANK_IDS.length)
    params.set("bancos", f.banks.join(","));
  params.set("desde", f.from);
  params.set("hasta", f.to);
  if (f.familia) params.set("familia", f.familia);
  if (f.sentimiento) params.set("sentimiento", f.sentimiento);
  return `/explorador?${params.toString()}`;
}

export function OpenInExplorer({ filters }: { filters: ExplorerFilters }) {
  return (
    <Button asChild variant="ghost" size="sm">
      <Link to={explorerUrl(filters)}>
        Abrir en el Explorador
        <ArrowUpRight aria-hidden="true" />
      </Link>
    </Button>
  );
}

/** Selector de un banco entre los filtrados (botones, no un menú). */
export function BankPicker({
  banks,
  value,
  onChange,
  label = "Banco",
}: {
  banks: BankId[];
  value: BankId;
  onChange: (bank: BankId) => void;
  label?: string;
}) {
  return (
    <fieldset className="flex flex-wrap items-center gap-1 border-0 p-0">
      <legend className="sr-only">{label}</legend>
      {banks.map((id) => (
        <Button
          key={id}
          size="sm"
          variant={id === value ? "primary" : "secondary"}
          aria-pressed={id === value}
          onClick={() => onChange(id)}
        >
          <span
            aria-hidden="true"
            className="size-2.5 rounded-full"
            style={{ background: `var(${BANKS[id].colorVar})` }}
          />
          {bankLabel(id)}
        </Button>
      ))}
    </fieldset>
  );
}

/** "2026-09" como fecha UTC. */
export function monthDate(period: string): Date {
  return new Date(`${period}-01T00:00:00Z`);
}

export function isoOf(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** Estimaciones de un mes por (banco, métrica). */
export function byKey(rows: MonthlyKpi[]): Map<string, MonthlyKpi> {
  return new Map(rows.map((r) => [`${r.bank_id}|${r.period}|${r.metric}`, r]));
}

export function LoadingBlock() {
  return (
    <div
      className="h-64 animate-pulse rounded-md bg-neutral-100"
      aria-busy="true"
    />
  );
}

const FALLBACK_WIDTH = 640;

/**
 * Ancho del contenedor para gráficas SVG a tamaño natural. Usa una referencia
 * por función: el contenedor suele aparecer cuando ya llegaron los datos, y
 * una referencia normal solo se mediría al montar el componente.
 */
export function useWidth() {
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!element) return;
    setWidth(element.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return { ref: setElement, width: width > 0 ? width : FALLBACK_WIDTH };
}
