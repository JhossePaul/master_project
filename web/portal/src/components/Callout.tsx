import { Info, OctagonAlert, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

const VARIANTS = {
  info: { icon: Info, box: "bg-info-bg text-info border-neutral-300" },
  warning: {
    icon: TriangleAlert,
    box: "bg-warning-bg text-warning border-warning/30",
  },
  danger: {
    icon: OctagonAlert,
    box: "bg-danger-bg text-danger border-danger/30",
  },
} as const;

export function Callout({
  variant = "info",
  title,
  children,
}: {
  variant?: keyof typeof VARIANTS;
  title?: string;
  children: ReactNode;
}) {
  const { icon: Icon, box } = VARIANTS[variant];
  return (
    <div
      role={variant === "info" ? "note" : "alert"}
      className={cn("flex gap-3 rounded-md border p-4 text-sm", box)}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div>
        {title ? <p className="font-semibold">{title}</p> : null}
        <div>{children}</div>
      </div>
    </div>
  );
}
