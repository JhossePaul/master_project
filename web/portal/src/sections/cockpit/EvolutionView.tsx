import type { BankId } from "@/config/banks";
import { isBankId } from "@/config/banks";
import { useGlobalFilters } from "@/filters/useGlobalFilters";
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
      <SeriesBlock
        banks={banks}
        {...common}
        day={day}
        familia={null}
        onDay={setDay}
        onRange={(from, to) => update({ from, to })}
      />
      <MonthlyBlock banks={banks} {...common} />
      <VersionTab
        banks={banks}
        bank={versionBank}
        onBank={setFocus}
        {...common}
      />
    </div>
  );
}
