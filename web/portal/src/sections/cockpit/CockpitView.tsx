import { useMonthly } from "@/api/kpis";
import type { BankId } from "@/config/banks";
import { isBankId } from "@/config/banks";
import { useGlobalFilters } from "@/filters/useGlobalFilters";
import { CardsBlock } from "./CardsBlock";
import { months } from "./ComparisonBlock";
import { MatrixBlock } from "./MatrixBlock";
import { MonthPicker } from "./MonthPicker";
import { BANK, MONTH, useParam } from "./params";
import { BankPicker } from "./shared";

/** Cockpit: la comparación entre bancos y la matriz estrellas × texto. */
export default function CockpitView() {
  const [filters] = useGlobalFilters();
  const banks = filters.banks;
  const [focus, setFocus] = useParam("banco", BANK);
  const [mes, setMes] = useParam("mes", MONTH);
  const monthly = useMonthly(banks);
  const detail: BankId =
    focus && isBankId(focus) && banks.includes(focus)
      ? focus
      : (banks[0] as BankId);
  const common = { from: filters.from, to: filters.to };
  return (
    <div className="flex flex-col gap-8">
      <h1 className="sr-only">Cockpit</h1>
      <CardsBlock banks={banks} />
      <section aria-label="Estrellas por texto" className="grid gap-4">
        <div className="flex flex-wrap items-center gap-4">
          {banks.length > 1 ? (
            <BankPicker
              banks={banks}
              value={detail}
              onChange={setFocus}
              label="Banco de la matriz"
            />
          ) : null}
          <MonthPicker
            options={months(monthly.data ?? [])}
            value={mes}
            onChange={setMes}
          />
        </div>
        <MatrixBlock bank={detail} period={mes} {...common} />
      </section>
    </div>
  );
}
