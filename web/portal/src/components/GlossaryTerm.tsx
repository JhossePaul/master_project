import type { ReactNode } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { GLOSSARY, type TermId } from "@/config/glossary";

/** Término subrayado con puntos que abre su definición. */
export function GlossaryTerm({
  id,
  children,
}: {
  id: TermId;
  children?: ReactNode;
}) {
  const entry = GLOSSARY[id];
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="cursor-help underline decoration-dotted decoration-neutral-500 underline-offset-4"
        >
          {children ?? entry.term}
        </button>
      </PopoverTrigger>
      <PopoverContent>
        <p className="font-semibold">{entry.term}</p>
        <p className="mt-1">{entry.short}</p>
        {"long" in entry ? (
          <p className="mt-2 text-text-muted">{entry.long}</p>
        ) : null}
        {"link" in entry ? (
          <p className="mt-2 text-xs text-text-muted">
            Respaldo: <code className="font-mono">{entry.link}</code>
          </p>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
