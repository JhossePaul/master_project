import { CircleHelp } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import type { PolicyHelp } from "@/config/policyHelp";

/** Ícono junto a un campo: qué significa, de dónde sale y qué pasa al moverlo. */
export function HelpButton({ help }: { help: PolicyHelp }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Ayuda: ${help.label}`}
          className="rounded-full text-neutral-700 hover:text-brand"
        >
          <CircleHelp className="size-4" aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="grid w-80 gap-2 text-sm">
        <p className="font-semibold">{help.label}</p>
        <p>{help.means}</p>
        <p>
          <span className="font-semibold">De dónde sale. </span>
          {help.evidence}
          {help.link ? (
            <>
              {" "}
              <code className="font-mono text-xs">{help.link}</code>
            </>
          ) : null}
        </p>
        {help.up !== "—" ? (
          <p>
            <span className="font-semibold">Si sube. </span>
            {help.up}
          </p>
        ) : null}
        {help.down !== "—" ? (
          <p>
            <span className="font-semibold">Si baja. </span>
            {help.down}
          </p>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
