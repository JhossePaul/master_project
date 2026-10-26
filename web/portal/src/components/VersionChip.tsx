import { cn } from "@/lib/utils";

export function VersionChip({
  version,
  className,
}: {
  version: string;
  className?: string;
}) {
  return (
    <code
      className={cn(
        "rounded-sm bg-neutral-100 px-1.5 py-0.5 font-mono text-xs text-neutral-800",
        className,
      )}
    >
      {version}
    </code>
  );
}
