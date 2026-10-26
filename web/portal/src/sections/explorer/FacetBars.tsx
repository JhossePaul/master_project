import { formatInt } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface FacetItem {
  key: string;
  label: string;
  n: number;
  /** Variable CSS del color de la barra. */
  colorVar?: string;
}

/** Barras horizontales; cada una es un botón que agrega o quita su filtro. */
export function FacetBars({
  title,
  items,
  selected,
  onToggle,
}: {
  title: string;
  items: FacetItem[];
  selected: ReadonlySet<string>;
  onToggle: (key: string) => void;
}) {
  const max = Math.max(1, ...items.map((i) => i.n));
  return (
    <section aria-label={title} className="min-w-0">
      <h3 className="mb-1 text-sm font-semibold">{title}</h3>
      {items.length === 0 ? (
        <p className="text-sm text-text-muted">Sin datos con estos filtros.</p>
      ) : (
        <ul className="grid gap-1">
          {items.map((item) => {
            const active = selected.has(item.key);
            return (
              <li key={item.key}>
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => onToggle(item.key)}
                  className={cn(
                    "grid w-full grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-2 rounded-sm px-1 py-0.5 text-left text-xs hover:bg-neutral-100",
                    active && "bg-green-50 ring-1 ring-green-400",
                  )}
                >
                  <span className="truncate">{item.label}</span>
                  <span
                    className="h-3 rounded-sm"
                    style={{
                      width: `${Math.max((item.n / max) * 100, 2)}%`,
                      background: `var(${item.colorVar ?? "--color-green-500"})`,
                    }}
                    aria-hidden="true"
                  />
                  <span className="tabular text-text-muted">
                    {formatInt(item.n)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
