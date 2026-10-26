import type { AlertRow, AlertStatus } from "@/api/alerts";
import { StatusPill } from "@/components/StatusPill";
import { BANKS, type BankId, bankLabel } from "@/config/banks";

export function AlertStatusPill({ status }: { status: AlertStatus }) {
  const pill = {
    open: "abierta",
    confirmed: "confirmada",
    dismissed: "descartada",
  } as const;
  return <StatusPill status={pill[status]} />;
}

export function BankDot({ bank }: { bank: string }) {
  const style = BANKS[bank as BankId];
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className="inline-block size-2.5 rounded-full"
        style={{ background: `var(${style?.colorVar ?? "--color-bank-all"})` }}
      />
      {bankLabel(bank)}
    </span>
  );
}

const DAY_MS = 86_400_000;

export function daysSince(value: string, now: number = Date.now()): number {
  return Math.max(0, Math.floor((now - new Date(value).getTime()) / DAY_MS));
}

export function formatCoverage(value: number): string {
  return new Intl.NumberFormat("es-MX", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/** Estado de la subida de revisión de la alerta, en una frase corta. */
export function boostSummary(boost: AlertRow["boost"]): string {
  if (!boost) return "Sin subida";
  if (boost.active)
    return `Activa (cobertura ${formatCoverage(boost.coverage)})`;
  return "Terminada";
}
