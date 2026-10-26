import { formatDate } from "@/lib/format";

export interface ProvenanceProps {
  model?: string | null;
  policy?: string | null;
  prompt?: string | null;
  gold?: string | null;
  /** Fecha ISO del último dato. */
  dataUntil?: string | null;
  note?: string;
}

export function Provenance({
  model,
  policy,
  prompt,
  gold,
  dataUntil,
  note,
}: ProvenanceProps) {
  const parts = [
    model && `Modelo ${model}`,
    policy && `política ${policy}`,
    prompt && `prompt ${prompt}`,
    gold && `oro ${gold}`,
    dataUntil && `datos al ${formatDate(dataUntil)}`,
    note,
  ].filter(Boolean);
  if (parts.length === 0) return null;
  return <p className="text-xs text-text-muted">{parts.join(" · ")}</p>;
}
