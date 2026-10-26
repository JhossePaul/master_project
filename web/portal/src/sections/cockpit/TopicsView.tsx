import { useExplorerContext } from "@/components/ExplorerLink";
import type { BankId } from "@/config/banks";
import { isBankId } from "@/config/banks";
import { useGlobalFilters } from "@/filters/useGlobalFilters";
import { FamiliesBlock } from "./FamiliesBlock";
import { BANK, useListParam, useParam } from "./params";
import { BankPicker, FAMILY_ORDER } from "./shared";
import { TopicsBlock } from "./TopicsBlock";

/** Tópicos: familias de las negativas y tópicos vigentes. */
export default function TopicsView() {
  const [filters] = useGlobalFilters();
  const banks = filters.banks;
  const [familias, setFamilias] = useListParam("familia", FAMILY_ORDER);
  const [focus, setFocus] = useParam("banco", BANK);
  const detail: BankId =
    focus && isBankId(focus) && banks.includes(focus)
      ? focus
      : (banks[0] as BankId);
  useExplorerContext({ familia: familias, sentimiento: "NEG" });
  const common = { from: filters.from, to: filters.to };
  return (
    <div className="flex flex-col gap-8">
      <h1 className="sr-only">Tópicos</h1>
      {banks.length > 1 ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-text-muted">Familias de:</span>
          <BankPicker
            banks={banks}
            value={detail}
            onChange={setFocus}
            label="Banco de las familias"
          />
        </div>
      ) : null}
      <FamiliesBlock
        banks={banks}
        bank={detail}
        familias={familias}
        onFamilias={setFamilias}
        {...common}
      />
      <TopicsBlock banks={banks} familias={familias} {...common} />
    </div>
  );
}
