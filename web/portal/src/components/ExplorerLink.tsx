import { ArrowUpRight } from "lucide-react";
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { BANK_IDS } from "@/config/banks";
import { useGlobalFilters } from "@/filters/useGlobalFilters";

/** Lo que una vista agrega a los filtros globales al abrir el Explorador. */
export interface ExplorerContext {
  from?: string;
  to?: string;
  /** Códigos de familia. */
  familia?: string[];
  sentimiento?: string;
}

interface Filters {
  banks: string[];
  from: string;
  to: string;
  familia?: string | null;
  sentimiento?: string | null;
}

/** Dirección del Explorador con los filtros fijados. */
export function explorerUrl(f: Filters): string {
  const params = new URLSearchParams();
  if (f.banks.length > 0 && f.banks.length < BANK_IDS.length)
    params.set("bancos", f.banks.join(","));
  params.set("desde", f.from);
  params.set("hasta", f.to);
  if (f.familia) params.set("familia", f.familia);
  if (f.sentimiento) params.set("sentimiento", f.sentimiento);
  return `/explorador?${params.toString()}`;
}

const Context = createContext<{
  value: ExplorerContext | null;
  set: (value: ExplorerContext | null) => void;
} | null>(null);

export function ExplorerProvider({ children }: { children: ReactNode }) {
  const [value, set] = useState<ExplorerContext | null>(null);
  const memo = useMemo(() => ({ value, set }), [value]);
  return <Context.Provider value={memo}>{children}</Context.Provider>;
}

/** La vista dice qué suma a los filtros globales; se limpia al salir. */
export function useExplorerContext(value: ExplorerContext | null) {
  const ctx = useContext(Context);
  const key = JSON.stringify(value);
  // biome-ignore lint/correctness/useExhaustiveDependencies: `key` resume `value`.
  useEffect(() => {
    ctx?.set(value);
    return () => ctx?.set(null);
  }, [key]);
}

export function ExplorerLink() {
  const [filters] = useGlobalFilters();
  const context = useContext(Context)?.value ?? null;
  const url = explorerUrl({
    banks: filters.banks,
    from: context?.from ?? filters.from,
    to: context?.to ?? filters.to,
    familia: context?.familia?.join(",") || null,
    sentimiento: context?.sentimiento ?? null,
  });
  return (
    <Button asChild variant="secondary" size="sm" className="ml-auto">
      <Link to={url}>
        Abrir en el Explorador
        <ArrowUpRight aria-hidden="true" />
      </Link>
    </Button>
  );
}
