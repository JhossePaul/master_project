import type { ReactNode } from "react";
import { MethodBadge } from "@/components/MethodBadge";
import { Provenance, type ProvenanceProps } from "@/components/Provenance";
import { Card } from "@/components/ui/card";

export interface KpiCardProps {
  label: ReactNode;
  value: string;
  /** Intervalo ya formateado, p. ej. "[11.0, 13.6]". */
  interval?: string;
  method?: "ppi" | "raw";
  /** Cambio contra el periodo anterior. */
  delta?: ReactNode;
  sparkline?: ReactNode;
  provenance?: ProvenanceProps;
}

export function KpiCard({
  label,
  value,
  interval,
  method,
  delta,
  sparkline,
  provenance,
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
      className="overflow-hidden border-t-4 p-5"
      style={colorVar ? { borderTopColor: `var(${colorVar})` } : undefined}
    >
      {children}
    </Card>
  );
}
