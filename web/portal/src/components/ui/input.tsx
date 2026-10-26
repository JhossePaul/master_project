import type * as React from "react";
import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "h-9 w-full rounded-sm border border-border-strong bg-surface px-3 text-sm text-text placeholder:text-neutral-500 disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
