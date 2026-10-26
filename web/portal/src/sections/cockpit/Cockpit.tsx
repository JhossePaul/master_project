import { useSearchParams } from "react-router";
import { useMonthly } from "@/api/kpis";
import { ErrorState } from "@/components/ErrorState";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BANK_IDS, type BankId, isBankId } from "@/config/banks";
import { useGlobalFilters } from "@/filters/useGlobalFilters";
import { formatMonth } from "@/lib/format";
import { CardsBlock } from "./CardsBlock";
import { ComparisonBlock, months } from "./ComparisonBlock";
import { FamiliesBlock } from "./FamiliesBlock";
import { MatrixBlock } from "./MatrixBlock";
import { MonthlyBlock } from "./MonthlyBlock";
import { SeriesBlock } from "./SeriesBlock";
import { BankPicker } from "./shared";
import { TopicsBlock } from "./TopicsBlock";
import { VersionTab } from "./VersionTab";

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const MONTH = /^\d{4}-\d{2}$/;
const FAMILY = /^[A-Za-z]{1,2}$/;

function useParam(name: string, valid: RegExp) {
  const [params, setParams] = useSearchParams();
  const raw = params.get(name);
  const value = raw && valid.test(raw) ? raw : null;
  const set = (next: string | null) =>
    setParams(
      (prev) => {
        const out = new URLSearchParams(prev);
        if (next) out.set(name, next);
        else out.delete(name);
        return out;
      },
      { replace: true },
    );
  return [value, set] as const;
}

function MonthPicker({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string | null;
  onChange: (m: string | null) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      Mes
      <select
        className="h-9 rounded-sm border border-border-strong bg-surface px-2"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">Último con revisión humana</option>
        {[...options].reverse().map((m) => (
          <option key={m} value={m}>
            {formatMonth(m)}
          </option>
        ))}
      </select>
    </label>
  );
}

function Daily({ banks }: { banks: BankId[] }) {
  const [filters, update] = useGlobalFilters();
  const [day, setDay] = useParam("dia", DAY);
  const [familia, setFamilia] = useParam("familia", FAMILY);
  const [focus, setFocus] = useParam("banco", /^[A-Z]+$/);
  const [mes, setMes] = useParam("mes", MONTH);
  const monthly = useMonthly(banks);
  const detail: BankId =
    focus && isBankId(focus) && banks.includes(focus)
      ? focus
      : (banks[0] as BankId);
  const options = months(monthly.data ?? []);
  const common = { from: filters.from, to: filters.to };
  return (
    <div className="flex flex-col gap-8">
      <CardsBlock banks={banks} />
      <SeriesBlock
        banks={banks}
        {...common}
        day={day}
        familia={familia}
        onDay={setDay}
        onRange={(from, to) => update({ from, to })}
      />
      <MonthlyBlock banks={banks} {...common} />
      <section aria-labelledby="detalle" className="grid gap-6">
        <div className="flex flex-wrap items-center gap-4">
          <h2
            id="detalle"
            className="font-serif text-2xl font-semibold text-green-800"
          >
            Detalle de un banco
          </h2>
          {banks.length > 1 ? (
            <BankPicker
              banks={banks}
              value={detail}
              onChange={(b) => setFocus(b)}
              label="Banco del detalle"
            />
          ) : null}
        </div>
        <FamiliesBlock
          banks={banks}
          bank={detail}
          familia={familia}
          onFamilia={setFamilia}
          {...common}
        />
        <TopicsBlock
          banks={banks}
          bank={detail}
          familia={familia}
          {...common}
        />
        <MatrixBlock bank={detail} period={mes} {...common} />
      </section>
      <section aria-labelledby="comparacion" className="grid gap-4">
        <div className="flex flex-wrap items-center gap-4">
          <h2
            id="comparacion"
            className="font-serif text-2xl font-semibold text-green-800"
          >
            Comparación entre bancos
          </h2>
          <MonthPicker options={options} value={mes} onChange={setMes} />
        </div>
        {monthly.isError ? (
          <ErrorState error={monthly.error} />
        ) : (
          <ComparisonBlock banks={banks} period={mes} {...common} />
        )}
      </section>
    </div>
  );
}

function ByVersion({ banks }: { banks: BankId[] }) {
  const [focus, setFocus] = useParam("banco", /^[A-Z]+$/);
  const bank: BankId =
    focus && isBankId(focus) ? focus : ((banks[0] ?? BANK_IDS[0]) as BankId);
  return (
    <div className="flex flex-col gap-4">
      <BankPicker
        banks={BANK_IDS}
        value={bank}
        onChange={setFocus}
        label="Banco de la vista por versión"
      />
      <VersionTab bank={bank} />
    </div>
  );
}

export default function Cockpit() {
  const [filters] = useGlobalFilters();
  const [params, setParams] = useSearchParams();
  const view = params.get("vista") === "version" ? "version" : "diario";
  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-serif text-3xl font-semibold">Cockpit</h1>
      <Tabs
        value={view}
        onValueChange={(next) =>
          setParams(
            (prev) => {
              const out = new URLSearchParams(prev);
              if (next === "version") out.set("vista", "version");
              else out.delete("vista");
              return out;
            },
            { replace: true },
          )
        }
      >
        <TabsList>
          <TabsTrigger value="diario">Diario</TabsTrigger>
          <TabsTrigger value="version">Por versión</TabsTrigger>
        </TabsList>
        <TabsContent value="diario" className="pt-6">
          <Daily banks={filters.banks} />
        </TabsContent>
        <TabsContent value="version" className="pt-6">
          <ByVersion banks={filters.banks} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
