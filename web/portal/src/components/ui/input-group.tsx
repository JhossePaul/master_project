import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Campo con su unidad dentro, como un *input group*: el sufijo comparte el
 * borde con el campo. Pasa `unitId` al campo (`aria-describedby`) para que la
 * unidad también la lean los lectores de pantalla.
 */
export function InputGroup({
  suffix,
  unitId,
  className,
  children,
}: {
  suffix?: string;
  unitId?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex h-9 items-stretch overflow-hidden rounded-sm border border-border-strong bg-surface focus-within:outline-2 focus-within:outline-offset-1 focus-within:outline-focus has-[:disabled]:opacity-50 has-[[aria-invalid=true]]:border-danger",
        "[&_input]:h-full [&_input]:min-w-0 [&_input]:rounded-none [&_input]:border-0 [&_input]:focus-visible:outline-none",
        className,
      )}
    >
      {children}
      {suffix ? (
        <span
          id={unitId}
          className="flex shrink-0 items-center border-l border-border bg-surface-muted px-2.5 text-sm text-text-muted"
        >
          {suffix}
        </span>
      ) : null}
    </div>
  );
}
