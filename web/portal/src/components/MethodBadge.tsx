import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const COPY = {
  ppi: {
    label: "Con revisión humana",
    variant: "brand",
    hint: "Personas revisaron una muestra de reseñas y con ella se ajustó el cálculo; por eso trae su rango. En términos técnicos: estimación PPI.",
  },
  raw: {
    label: "Solo modelo",
    variant: "neutral",
    hint: "Cuenta lo que predice el modelo, sin ajustarlo con revisión humana.",
  },
} as const;

export function MethodBadge({ method }: { method: "ppi" | "raw" }) {
  const { label, variant, hint } = COPY[method];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" className="relative z-10 rounded-full">
          <Badge variant={variant}>{label}</Badge>
        </button>
      </TooltipTrigger>
      <TooltipContent>{hint}</TooltipContent>
    </Tooltip>
  );
}
