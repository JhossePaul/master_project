import { Info } from "lucide-react";
import type { ReactNode } from "react";
import { MethodBadge } from "@/components/MethodBadge";
import { Provenance, type ProvenanceProps } from "@/components/Provenance";
import { Card } from "@/components/ui/card";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

export interface KpiCardProps {
  label: ReactNode;
  value: string;
  /** Rango ya escrito en palabras, p. ej. "entre 11.0 % y 13.6 %". */
  interval?: string;
  method?: "ppi" | "raw";
  /** Cambio contra el periodo anterior. */
  delta?: ReactNode;
  sparkline?: ReactNode;
  provenance?: ProvenanceProps;
  /** Procedencia dentro de un "Cómo se calculó" desplegable (vistas ejecutivas). */
  collapsedProvenance?: { provenance: ProvenanceProps; explanation: ReactNode };
}

export function KpiCard({
  label,
  value,
  interval,
  method,
  delta,
  sparkline,
  provenance,
  collapsedProvenance,
}: KpiCardProps) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-text-muted">{label}</p>
        {method ? <MethodBadge method={method} /> : null}
      </div>
      <p className="tabular text-4xl font-bold leading-10 text-text">{value}</p>
      {interval ? (
        <p className="tabular text-sm text-text-muted">{interval}</p>
      ) : null}
      {delta ? <div className="text-sm">{delta}</div> : null}
      {sparkline}
      {provenance ? <Provenance {...provenance} /> : null}
      {collapsedProvenance ? (
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              className="relative z-10 flex w-fit items-center gap-1 text-xs font-semibold text-green-600"
            >
              <Info className="size-3" aria-hidden="true" />
              Cómo se calculó
            </button>
          </PopoverTrigger>
          <PopoverContent>
            <div className="mb-2">{collapsedProvenance.explanation}</div>
            <Provenance {...collapsedProvenance.provenance} />
          </PopoverContent>
        </Popover>
      ) : null}
    </div>
  );
}

/** Tarjeta con filete superior de color, para las que se pueden pulsar. */
export function KpiCardFrame({
  colorVar,
  children,
}: {
  colorVar?: string;
  children: ReactNode;
}) {
  return (
    <Card
      className="relative overflow-hidden border-t-4 p-5 hover:border-x-green-200 hover:shadow-sm"
      style={colorVar ? { borderTopColor: `var(${colorVar})` } : undefined}
    >
      {children}
    </Card>
  );
}
