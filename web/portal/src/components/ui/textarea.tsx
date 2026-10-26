import type * as React from "react";
import { cn } from "@/lib/utils";

export function Textarea({
  className,
  ...props
}: React.ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(
        "min-h-20 w-full rounded-sm border border-border-strong bg-surface px-3 py-2 text-sm text-text placeholder:text-neutral-500 disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
