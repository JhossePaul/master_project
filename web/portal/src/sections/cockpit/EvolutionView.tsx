import type { BankId } from "@/config/banks";
import { isBankId } from "@/config/banks";
import { useGlobalFilters } from "@/filters/useGlobalFilters";
import { KpiButtons } from "./kpi";
import { MonthlyBlock } from "./MonthlyBlock";
import { BANK, DAY, useParam } from "./params";
import { SeriesBlock } from "./SeriesBlock";
import { VersionTab } from "./VersionTab";

/** Evolución: serie diaria, mensual con PPI y por versión de la app. */
export default function EvolutionView() {
  const [filters, update] = useGlobalFilters();
  const banks = filters.banks;
  const [day, setDay] = useParam("dia", DAY);
  const [focus, setFocus] = useParam("banco", BANK);
  const versionBank: BankId =
    focus && isBankId(focus) && banks.includes(focus)
      ? focus
      : (banks[0] as BankId);
  const common = { from: filters.from, to: filters.to };
  return (
    <div className="flex flex-col gap-8">
      <h1 className="sr-only">Evolución</h1>
      {/* La medida solo gobierna la serie diaria y el mensual: el selector es
          fijo dentro de este grupo y se va al llegar a las versiones. */}
      <div className="grid gap-8">
        <div className="sticky top-[6.6rem] z-10 -mx-2 flex flex-wrap items-center gap-3 border-b border-border bg-bg px-2 py-2">
          <span className="text-sm font-semibold">Medida:</span>
          <KpiButtons />
          <span className="text-xs text-text-muted">
            Aplica a la serie diaria y a la mensual.
          </span>
        </div>
        <SeriesBlock
          banks={banks}
          {...common}
          day={day}
          familia={null}
          onDay={setDay}
          onRange={(from, to) => update({ from, to })}
        />
        <MonthlyBlock banks={banks} {...common} />
      </div>
      <VersionTab
        banks={banks}
        bank={versionBank}
        onBank={setFocus}
        {...common}
      />
    </div>
  );
}
