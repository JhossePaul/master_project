import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { BANK_IDS, BANKS, type BankId } from "@/config/banks";
import {
  defaultRange,
  isoDay,
  useGlobalFilters,
} from "@/filters/useGlobalFilters";

const SHORTCUTS: { label: string; days: number | null }[] = [
  { label: "30 días", days: 30 },
  { label: "90 días", days: 90 },
  { label: "12 meses", days: 365 },
  { label: "Todo", days: null },
];
const ALL_FROM = "2016-01-01";

function rangeFor(days: number | null): { from: string; to: string } {
  const today = new Date();
  if (days === null) return { from: ALL_FROM, to: isoDay(today) };
  const from = new Date(today);
  from.setUTCDate(from.getUTCDate() - days);
  return { from: isoDay(from), to: isoDay(today) };
}

export function FilterBar() {
  const [filters, update] = useGlobalFilters();

  function toggle(bank: BankId, checked: boolean) {
    const next = checked
      ? [...new Set([...filters.banks, bank])]
      : filters.banks.filter((b) => b !== bank);
    if (next.length > 0)
      update({ banks: BANK_IDS.filter((b) => next.includes(b)) });
  }

  return (
    <search
      aria-label="Filtros globales"
      className="flex flex-wrap items-center gap-3 border-b border-border bg-surface-muted px-8 py-2"
    >
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="secondary" size="sm">
            Bancos ({filters.banks.length} de {BANK_IDS.length})
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          {BANK_IDS.map((id) => (
            <DropdownMenuCheckboxItem
              key={id}
              checked={filters.banks.includes(id)}
              onCheckedChange={(checked) => toggle(id, checked === true)}
              onSelect={(e) => e.preventDefault()}
            >
              <span
                aria-hidden="true"
                className="size-2.5 rounded-full"
                style={{ background: `var(${BANKS[id].colorVar})` }}
              />
              {BANKS[id].label}
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <fieldset className="flex gap-1 border-0 p-0">
        <legend className="sr-only">Atajos de periodo</legend>
        {SHORTCUTS.map(({ label, days }) => (
          <Button
            key={label}
            variant="ghost"
            size="sm"
            onClick={() => update(rangeFor(days))}
          >
            {label}
          </Button>
        ))}
      </fieldset>
      <label className="flex items-center gap-1 text-sm" htmlFor="filtro-desde">
        Desde
        <Input
          id="filtro-desde"
          type="date"
          className="w-auto"
          value={filters.from}
          max={filters.to}
          onChange={(e) => e.target.value && update({ from: e.target.value })}
        />
      </label>
      <label className="flex items-center gap-1 text-sm" htmlFor="filtro-hasta">
        Hasta
        <Input
          id="filtro-hasta"
          type="date"
          className="w-auto"
          value={filters.to}
          min={filters.from}
          onChange={(e) => e.target.value && update({ to: e.target.value })}
        />
      </label>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => update({ banks: [...BANK_IDS], ...defaultRange() })}
      >
        <RotateCcw aria-hidden="true" />
        Restablecer
      </Button>
    </search>
  );
}
