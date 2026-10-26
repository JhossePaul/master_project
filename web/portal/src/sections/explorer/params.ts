import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";
import type { ReviewQuery, SortKey } from "@/api/reviews";
import { parseFilters } from "@/filters/useGlobalFilters";

/** Filtros propios del Explorador, además de bancos, desde y hasta. */
export interface ExplorerState {
  sentiment: string[];
  stars: number[];
  families: string[];
  u: boolean | null;
  s: boolean | null;
  topic: number | null;
  hitl: boolean | null;
  version: string | null;
  page: number;
  sort: SortKey;
  /** `BANCO:id_resena` de la ficha abierta. */
  ficha: string | null;
}

const SORTS: SortKey[] = ["fecha_desc", "confidence_asc", "estrellas_asc"];
const SENTIMENTS = ["NEG", "NEU", "POS", "NO_PREDICTED"];

function list(raw: string | null): string[] {
  return raw
    ? [
        ...new Set(
          raw
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
        ),
      ]
    : [];
}

function flag(raw: string | null): boolean | null {
  if (raw === "1") return true;
  if (raw === "0") return false;
  return null;
}

export function parseExplorer(params: URLSearchParams): ExplorerState {
  const topic = Number.parseInt(params.get("topico") ?? "", 10);
  const page = Number.parseInt(params.get("pagina") ?? "1", 10);
  const sort = params.get("orden") as SortKey | null;
  return {
    sentiment: list(params.get("sentimiento")).filter((s) =>
      SENTIMENTS.includes(s),
    ),
    stars: list(params.get("estrellas"))
      .map(Number)
      .filter((n) => Number.isInteger(n) && n >= 1 && n <= 5),
    families: list(params.get("familia")),
    u: flag(params.get("u")),
    s: flag(params.get("s")),
    topic: Number.isInteger(topic) && topic >= 0 ? topic : null,
    hitl: flag(params.get("hitl")),
    version: params.get("version") || null,
    page: Number.isInteger(page) && page >= 1 ? page : 1,
    sort: sort && SORTS.includes(sort) ? sort : "fecha_desc",
    ficha: params.get("ficha"),
  };
}

function toQuery(params: URLSearchParams, state: ExplorerState): ReviewQuery {
  const global = parseFilters(params);
  return {
    banks: global.banks,
    date_from: global.from,
    date_to: global.to,
    sentiment: state.sentiment,
    stars: state.stars,
    families: state.families,
    flag_update: state.u ?? undefined,
    flag_security: state.s ?? undefined,
    topic_id: state.topic ?? undefined,
    hitl_reviewed: state.hitl ?? undefined,
    version: state.version ?? undefined,
  };
}

const KEYS = {
  sentiment: "sentimiento",
  stars: "estrellas",
  families: "familia",
} as const;

export type Patch = Partial<ExplorerState>;

/** Estado del Explorador en la URL; todo cambio de filtro vuelve a la página 1. */
export function useExplorerState(): {
  state: ExplorerState;
  query: ReviewQuery;
  patch: (patch: Patch) => void;
  clear: () => void;
} {
  const [params, setParams] = useSearchParams();
  const state = useMemo(() => parseExplorer(params), [params]);
  const query = useMemo(() => toQuery(params, state), [params, state]);

  const patch = useCallback(
    (change: Patch) => {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          const merged = { ...parseExplorer(previous), ...change };
          for (const [field, key] of Object.entries(KEYS)) {
            const values = merged[field as keyof typeof KEYS] as (
              | string
              | number
            )[];
            if (values.length > 0) next.set(key, values.join(","));
            else next.delete(key);
          }
          for (const [field, key] of [
            ["u", "u"],
            ["s", "s"],
            ["hitl", "hitl"],
          ] as const) {
            const value = merged[field];
            if (value === null) next.delete(key);
            else next.set(key, value ? "1" : "0");
          }
          if (merged.topic === null) next.delete("topico");
          else next.set("topico", String(merged.topic));
          if (merged.version) next.set("version", merged.version);
          else next.delete("version");
          if (merged.sort === "fecha_desc") next.delete("orden");
          else next.set("orden", merged.sort);
          if (merged.ficha) next.set("ficha", merged.ficha);
          else next.delete("ficha");
          // Cambiar un filtro reinicia la paginación; cambiar de página no.
          const filtering = Object.keys(change).some(
            (k) => k !== "page" && k !== "ficha",
          );
          const page = filtering ? (change.page ?? 1) : merged.page;
          if (page > 1) next.set("pagina", String(page));
          else next.delete("pagina");
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const clear = useCallback(
    () =>
      patch({
        sentiment: [],
        stars: [],
        families: [],
        u: null,
        s: null,
        topic: null,
        hitl: null,
        version: null,
      }),
    [patch],
  );

  return { state, query, patch, clear };
}
