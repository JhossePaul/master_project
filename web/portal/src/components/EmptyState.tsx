import { Inbox } from "lucide-react";
import type { ReactNode } from "react";

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border-strong bg-surface p-10 text-center">
      <Inbox className="size-6 text-neutral-500" aria-hidden="true" />
      <p className="font-serif text-xl font-semibold">{title}</p>
      {description ? (
        <p className="max-w-prose text-sm text-text-muted">{description}</p>
      ) : null}
      {action}
    </div>
  );
}
