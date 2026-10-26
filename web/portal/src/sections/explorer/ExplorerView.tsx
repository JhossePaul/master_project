import { Download, X } from "lucide-react";
import { useMemo } from "react";
import {
  type Facets,
  type ReviewRow,
  type SortKey,
  useFacets,
  useReviewPage,
  useSearch,
} from "@/api/reviews";
import { Callout } from "@/components/Callout";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { BANK_IDS, type BankId, bankLabel } from "@/config/banks";
import { useGlobalFilters } from "@/filters/useGlobalFilters";
import { formatDate, formatInt } from "@/lib/format";
import { FAMILY_NAMES, FAMILY_ORDER } from "@/sections/cockpit/shared";
import { FacetBars, type FacetItem } from "@/sections/explorer/FacetBars";
import { MonthChart } from "@/sections/explorer/MonthChart";
import { useExplorerState } from "@/sections/explorer/params";
import { ResultsTable } from "@/sections/explorer/ResultsTable";
import { ReviewPanel } from "@/sections/explorer/ReviewPanel";
import { SearchBar } from "@/sections/explorer/SearchBar";

const SENTIMENT_COLORS: Record<string, string> = {
  NEG: "--color-sent-neg",
  NEU: "--color-sent-neu",
  POS: "--color-sent-pos",
};
const SORTS: { value: SortKey; label: string }[] = [
  { value: "fecha_desc", label: "Más recientes" },
  { value: "confidence_asc", label: "Menor confianza" },
  { value: "estrellas_asc", label: "Menos estrellas" },
];
const YES_NO: Record<string, string> = { si: "Sí", no: "No" };

/** CSV de los agregados de las gráficas; nunca texto de reseñas. */
export function facetsCsv(facets: Facets): string {
  const lines = ["dimension,clave,etiqueta,reseñas"];
  const groups: [string, Facets["by_bank"]][] = [
    ["banco", facets.by_bank],
    ["mes", facets.by_month],
    ["sentimiento", facets.by_sentiment],
    ["estrellas", facets.by_stars],
    ["familia", facets.by_family],
    ["actualizacion", facets.by_flag_update],
    ["seguridad", facets.by_flag_security],
    ["topico", facets.by_topic],
    ["revision_humana", facets.by_hitl],
  ];
  for (const [dim, items] of groups)
    for (const i of items)
      lines.push([dim, i.key, JSON.stringify(i.label ?? ""), i.n].join(","));
  return lines.join("\n");
}

function downloadCsv(facets: Facets) {
  const blob = new Blob([facetsCsv(facets)], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "agregados-explorador.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function toggled<T>(list: T[], value: T): T[] {
  return list.includes(value)
    ? list.filter((x) => x !== value)
    : [...list, value];
}

export default function ExplorerView() {
  const [global, updateGlobal] = useGlobalFilters();
  const { state, query, patch, clear } = useExplorerState();
  const facets = useFacets(query);
  const page = useReviewPage(query, state.page, state.sort);
  const search = useSearch();
  const searching = !search.isIdle;

  const open = (row: ReviewRow) =>
    patch({ ficha: `${row.bank_id}:${row.id_resena}` });
  const [fichaBank, fichaId] = state.ficha?.split(":") ?? [null, null];

  const chips = useMemo(() => {
    const out: { label: string; remove: () => void }[] = [];
    for (const s of state.sentiment)
      out.push({
        label: `Sentimiento ${s}`,
        remove: () =>
          patch({ sentiment: state.sentiment.filter((x) => x !== s) }),
      });
    for (const n of state.stars)
      out.push({
        label: `${n} ★`,
        remove: () => patch({ stars: state.stars.filter((x) => x !== n) }),
      });
    for (const f of state.families)
      out.push({
        label: FAMILY_NAMES[f] ?? f,
        remove: () =>
          patch({ families: state.families.filter((x) => x !== f) }),
      });
    if (state.u !== null)
      out.push({
        label: state.u
          ? "Relacionada con una actualización"
          : "Sin actualización",
        remove: () => patch({ u: null }),
      });
    if (state.s !== null)
      out.push({
        label: state.s ? "Con marca de seguridad" : "Sin marca de seguridad",
        remove: () => patch({ s: null }),
      });
    if (state.topic !== null)
      out.push({
        label: `Tópico ${state.topic}`,
        remove: () => patch({ topic: null }),
      });
    if (state.hitl !== null)
      out.push({
        label: state.hitl ? "Con revisión humana" : "Sin revisión humana",
        remove: () => patch({ hitl: null }),
      });
    if (state.version)
      out.push({
        label: `Versión ${state.version}`,
        remove: () => patch({ version: null }),
      });
    return out;
  }, [state, patch]);

  const f = facets.data;
  const flagItems = (items: Facets["by_hitl"], names: [string, string]) =>
    items.map(
      (i): FacetItem => ({
        key: i.key,
        n: i.n,
        label: i.key === "si" ? names[0] : names[1],
      }),
    );

  return (
    <div className="grid gap-5">
      <header className="grid gap-2">
        <h1 className="font-serif text-3xl font-semibold">
          Explorador de reseñas
        </h1>
        <Callout variant="info">
          Muestra texto sanitizado de reseñas, solo para análisis dentro del
          portal: no se descarga ni se comparte.
        </Callout>
      </header>

      <SearchBar
        busy={search.isPending}
        onSearch={(q) =>
          search.mutate({ query: q, banks: global.banks, k: 20 })
        }
      />

      {chips.length > 0 ? (
        <ul
          className="flex flex-wrap items-center gap-2"
          aria-label="Filtros activos"
        >
          {chips.map((chip) => (
            <li key={chip.label}>
              <button
                type="button"
                onClick={chip.remove}
                aria-label={`Quitar el filtro ${chip.label}`}
                className="inline-flex items-center gap-1 rounded-full border border-green-300 bg-green-50 px-2.5 py-1 text-xs"
              >
                {chip.label}
                <X className="size-3" aria-hidden="true" />
              </button>
            </li>
          ))}
          <li>
            <Button variant="ghost" size="sm" onClick={clear}>
              Quitar todos
            </Button>
          </li>
        </ul>
      ) : null}

      {searching ? (
        <SearchResults
          pending={search.isPending}
          data={search.data}
          error={search.error}
          selected={state.ficha}
          onOpen={open}
          onBack={() => search.reset()}
        />
      ) : (
        <>
          <Card className="grid gap-5 p-5">
            <div className="flex items-start justify-between gap-3">
              <h2 className="font-serif text-xl font-semibold">
                Resumen con los filtros actuales
              </h2>
              {f ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => downloadCsv(f)}
                >
                  <Download aria-hidden="true" />
                  Descargar agregados (CSV)
                </Button>
              ) : null}
            </div>
            {facets.isError ? (
              <ErrorState
                error={facets.error}
                onRetry={() => facets.refetch()}
              />
            ) : f ? (
              <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
                <MonthChart
                  bars={f.by_month.map((m) => ({ key: m.key, n: m.n }))}
                  from={global.from}
                  to={global.to}
                  onSelect={(from, to) => updateGlobal({ from, to })}
                />
                <FacetBars
                  title="Por banco"
                  items={f.by_bank.map((b) => ({
                    key: b.key,
                    n: b.n,
                    label: bankLabel(b.key),
                    colorVar: `--color-bank-${b.key.toLowerCase()}`,
                  }))}
                  selected={
                    new Set(
                      global.banks.length < BANK_IDS.length ? global.banks : [],
                    )
                  }
                  onToggle={(key) => {
                    const id = key as BankId;
                    const only = global.banks.length === BANK_IDS.length;
                    // Desde "todos", elegir uno deja solo ese; luego suma o quita.
                    const next = only ? [id] : toggled(global.banks, id);
                    if (next.length > 0)
                      updateGlobal({
                        banks: BANK_IDS.filter((b) => next.includes(b)),
                      });
                  }}
                />
                <FacetBars
                  title="Por sentimiento"
                  items={f.by_sentiment.map((s) => ({
                    key: s.key,
                    n: s.n,
                    label: s.key === "NO_PREDICTED" ? "Sin predicción" : s.key,
                    colorVar: SENTIMENT_COLORS[s.key],
                  }))}
                  selected={new Set(state.sentiment)}
                  onToggle={(key) =>
                    patch({ sentiment: toggled(state.sentiment, key) })
                  }
                />
                <FacetBars
                  title="Por estrellas"
                  items={f.by_stars.map((s) => ({
                    key: s.key,
                    n: s.n,
                    label: `${s.key} ★`,
                  }))}
                  selected={new Set(state.stars.map(String))}
                  onToggle={(key) =>
                    patch({ stars: toggled(state.stars, Number(key)) })
                  }
                />
                <FacetBars
                  title="Por familia"
                  items={[...f.by_family]
                    .sort(
                      (a, b) =>
                        FAMILY_ORDER.indexOf(a.key as never) -
                        FAMILY_ORDER.indexOf(b.key as never),
                    )
                    .map((s) => ({
                      key: s.key,
                      n: s.n,
                      label: FAMILY_NAMES[s.key] ?? s.key,
                    }))}
                  selected={new Set(state.families)}
                  onToggle={(key) =>
                    patch({ families: toggled(state.families, key) })
                  }
                />
                <FacetBars
                  title="Marca: actualización"
                  items={flagItems(f.by_flag_update, [
                    "Relacionada con una actualización",
                    "Sin actualización",
                  ])}
                  selected={
                    new Set(state.u === null ? [] : [state.u ? "si" : "no"])
                  }
                  onToggle={(key) =>
                    patch({
                      u: state.u === (key === "si") ? null : key === "si",
                    })
                  }
                />
                <FacetBars
                  title="Marca: seguridad"
                  items={flagItems(f.by_flag_security, [
                    "Con marca de seguridad",
                    "Sin marca de seguridad",
                  ])}
                  selected={
                    new Set(state.s === null ? [] : [state.s ? "si" : "no"])
                  }
                  onToggle={(key) =>
                    patch({
                      s: state.s === (key === "si") ? null : key === "si",
                    })
                  }
                />
                <FacetBars
                  title="Por tópico (los 20 principales)"
                  items={f.by_topic.map((t) => ({
                    key: t.key,
                    n: t.n,
                    label: t.label ?? `Tópico ${t.key}`,
                  }))}
                  selected={
                    new Set(state.topic === null ? [] : [String(state.topic)])
                  }
                  onToggle={(key) =>
                    patch({
                      topic: state.topic === Number(key) ? null : Number(key),
                    })
                  }
                />
                <FacetBars
                  title="Revisión humana"
                  items={f.by_hitl.map((i) => ({
                    key: i.key,
                    n: i.n,
                    label: YES_NO[i.key] ?? i.key,
                  }))}
                  selected={
                    new Set(
                      state.hitl === null ? [] : [state.hitl ? "si" : "no"],
                    )
                  }
                  onToggle={(key) =>
                    patch({
                      hitl: state.hitl === (key === "si") ? null : key === "si",
                    })
                  }
                />
              </div>
            ) : (
              <Skeleton className="h-40" />
            )}
          </Card>

          {page.isError ? (
            <ErrorState error={page.error} onRetry={() => page.refetch()} />
          ) : page.data ? (
            <section aria-label="Reseñas" className="grid gap-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm">
                  <strong className="tabular">
                    {formatInt(page.data.total)}
                  </strong>{" "}
                  reseñas del {formatDate(page.data.window_applied.date_from)}{" "}
                  al {formatDate(page.data.window_applied.date_to)}
                </p>
                <label className="flex items-center gap-2 text-sm">
                  Ordenar por
                  <select
                    className="h-8 rounded-sm border border-border-strong bg-surface px-2"
                    value={state.sort}
                    onChange={(e) => patch({ sort: e.target.value as SortKey })}
                  >
                    {SORTS.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {page.data.window_applied.clipped ? (
                <Callout variant="warning">
                  El Explorador abarca los últimos{" "}
                  {page.data.window_applied.months} meses: el rango se recortó.
                </Callout>
              ) : null}
              {page.data.rows.length === 0 ? (
                <EmptyState
                  title="Ninguna reseña con estos filtros"
                  description="Quita algún filtro o amplía el periodo."
                />
              ) : (
                <ResultsTable
                  rows={page.data.rows}
                  onOpen={open}
                  selected={state.ficha}
                />
              )}
              <Pager
                page={page.data.page}
                size={page.data.page_size}
                total={page.data.total}
                onPage={(p) => patch({ page: p })}
              />
            </section>
          ) : (
            <Skeleton className="h-64" />
          )}
        </>
      )}

      {fichaBank && fichaId ? (
        <ReviewPanel
          bank={fichaBank}
          id={fichaId}
          onClose={() => patch({ ficha: null })}
        />
      ) : null}
    </div>
  );
}

function Pager({
  page,
  size,
  total,
  onPage,
}: {
  page: number;
  size: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <nav
      aria-label="Paginación"
      className="flex items-center justify-end gap-3 text-sm"
    >
      <Button
        variant="secondary"
        size="sm"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
      >
        Anterior
      </Button>
      <span className="tabular">
        Página {page} de {formatInt(pages)}
      </span>
      <Button
        variant="secondary"
        size="sm"
        disabled={page >= pages}
        onClick={() => onPage(page + 1)}
      >
        Siguiente
      </Button>
    </nav>
  );
}

function SearchResults({
  pending,
  data,
  error,
  selected,
  onOpen,
  onBack,
}: {
  pending: boolean;
  data: ReturnType<typeof useSearch>["data"];
  error: unknown;
  selected: string | null;
  onOpen: (row: ReviewRow) => void;
  onBack: () => void;
}) {
  return (
    <section aria-label="Resultados de la búsqueda" className="grid gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-serif text-xl font-semibold">
          Resultados de la búsqueda
        </h2>
        <Button variant="secondary" size="sm" onClick={onBack}>
          Volver a la tabla
        </Button>
      </div>
      {pending ? (
        <>
          <p className="text-sm text-text-muted" role="status">
            Buscando… puede tardar hasta un minuto si el servicio estaba en
            reposo.
          </p>
          <Skeleton className="h-40" />
        </>
      ) : null}
      {error ? <ErrorState error={error} onRetry={onBack} /> : null}
      {data ? (
        data.hits.length === 0 ? (
          <EmptyState
            title="Sin coincidencias"
            description={`Se buscó en los últimos ${data.months_searched} meses.`}
          />
        ) : (
          <>
            <p className="text-xs text-text-muted">
              Los últimos {data.months_searched} meses · modelo de lenguaje{" "}
              {data.embedding_model} · distancia coseno: 0 es idéntico.
            </p>
            <ResultsTable
              rows={data.hits.map((h) => h.example)}
              onOpen={onOpen}
              selected={selected}
              leading={[
                {
                  header: "Distancia",
                  cell: (_, i) => (
                    <span className="tabular">
                      {(data.hits[i]?.distance ?? 0).toFixed(3)}
                    </span>
                  ),
                },
              ]}
              extra={[
                {
                  header: "Reseñas iguales",
                  cell: (_, i) => formatInt(data.hits[i]?.n_reviews ?? 0),
                },
              ]}
            />
          </>
        )
      ) : null}
    </section>
  );
}
