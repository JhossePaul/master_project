import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const COPY = {
  ppi: {
    label: "PPI",
    variant: "brand",
    hint: "Estimación corregida con una muestra revisada por personas; trae su intervalo de confianza.",
  },
  raw: {
    label: "crudo",
    variant: "neutral",
    hint: "Proporción sin corregir: cuenta lo que predice el modelo, con su error incluido.",
  },
} as const;

export function MethodBadge({ method }: { method: "ppi" | "raw" }) {
  const { label, variant, hint } = COPY[method];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" className="rounded-full">
          <Badge variant={variant}>{label}</Badge>
        </button>
      </TooltipTrigger>
      <TooltipContent>{hint}</TooltipContent>
    </Tooltip>
  );
}
