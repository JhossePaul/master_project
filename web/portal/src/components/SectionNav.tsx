import { ChevronDown } from "lucide-react";
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const ACTIVE_OFFSET = 180;

export interface SectionItem {
  id: string;
  label: string;
}

interface SectionState {
  items: SectionItem[];
  active: string | null;
}

interface SectionContext extends SectionState {
  setState: (state: SectionState) => void;
}

const Context = createContext<SectionContext | null>(null);

/** Guarda las secciones de la pantalla para mostrarlas en la barra fija. */
export function SectionNavProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SectionState>({
    items: [],
    active: null,
  });
  const value = useMemo(() => ({ ...state, setState }), [state]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/**
 * Registra las secciones de la pantalla y marca la que está a la vista al
 * hacer scroll.
 */
export function useSectionNav(items: SectionItem[]) {
  const ctx = useContext(Context);
  const key = items.map((i) => i.id).join("|");
  // biome-ignore lint/correctness/useExhaustiveDependencies: `key` resume `items`.
  useEffect(() => {
    if (!ctx) return;
    const ids = key.split("|").filter(Boolean);
    const labels = new Map(items.map((i) => [i.id, i.label]));
    const list = ids.map((id) => ({ id, label: labels.get(id) ?? id }));
    ctx.setState({ items: list, active: ids[0] ?? null });
    // La sección a la vista es la última cuyo inicio ya pasó por debajo de
    // las barras fijas (unos 140 px).
    const onScroll = () => {
      let current = ids[0] ?? null;
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= ACTIVE_OFFSET) current = id;
      }
      ctx.setState({ items: list, active: current });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      ctx.setState({ items: [], active: null });
    };
  }, [key]);
}

/** Menú de la sección a la vista, con salto a las demás. */
export function SectionMenu() {
  const ctx = useContext(Context);
  if (!ctx || ctx.items.length === 0) return null;
  const current = ctx.items.find((i) => i.id === ctx.active) ?? ctx.items[0];
  return (
    <nav aria-label="Secciones de la pantalla" className="ml-auto">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="secondary" size="sm">
            <span className="text-text-muted">Sección:</span> {current?.label}
            <ChevronDown aria-hidden="true" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {ctx.items.map((item) => (
            <DropdownMenuItem
              key={item.id}
              onSelect={() =>
                document
                  .getElementById(item.id)
                  ?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
            >
              {item.label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </nav>
  );
}
