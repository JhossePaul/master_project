import {
  CheckCircle2,
  CircleDashed,
  Loader,
  OctagonAlert,
  RotateCcw,
  TriangleAlert,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";

const STATUSES = {
  ok: { label: "ok", variant: "ok", icon: CheckCircle2 },
  aviso: { label: "aviso", variant: "warning", icon: TriangleAlert },
  reentrenar: { label: "reentrenar", variant: "danger", icon: RotateCcw },
  rechazado: { label: "rechazado", variant: "danger", icon: XCircle },
  abierta: { label: "abierta", variant: "danger", icon: OctagonAlert },
  confirmada: { label: "confirmada", variant: "warning", icon: CheckCircle2 },
  descartada: { label: "descartada", variant: "ok", icon: CircleDashed },
  en_curso: { label: "en curso", variant: "info", icon: Loader },
  fallo: { label: "falló", variant: "danger", icon: XCircle },
} as const;

export type Status = keyof typeof STATUSES;

export function StatusPill({
  status,
  label,
}: {
  status: Status;
  label?: string;
}) {
  const { label: text, variant, icon: Icon } = STATUSES[status];
  return (
    <Badge variant={variant}>
      <Icon aria-hidden="true" />
      {label ?? text}
    </Badge>
  );
}
