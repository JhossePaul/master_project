import { scaleLinear, scalePoint } from "d3-scale";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { type TopicMonth, useTopics } from "@/api/kpis";
import { Axis, GridLines, Line } from "@/charts/primitives";
import { ChartFrame } from "@/components/ChartFrame";
import { ErrorState } from "@/components/ErrorState";
import { GlossaryTerm } from "@/components/GlossaryTerm";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { BANKS, type BankId, bankLabel } from "@/config/banks";
import { formatInt, formatMonth, formatPct } from "@/lib/format";
import { familyName, LoadingBlock, OpenInExplorer, useWidth } from "./shared";

const PAGE_SIZE = 6;
const WINDOW_MONTHS = 24;
const HEIGHT = 150;
const M = { top: 8, right: 8, bottom: 22, left: 40 };
const AUDIENCE_LABEL: Record<string, string> = {
  producto: "Producto",
  ingenieria: "Ingeniería",
};

interface Group {
  head: TopicMonth;
  rows: TopicMonth[];
  total: number;
}

/** Un tópico: la parte de las negativas de cada mes, una línea por banco. */
function Panel({
  group,
  banks,
  periods,
  dim,
}: {
  group: Group;
  banks: BankId[];
  periods: string[];
  dim: boolean;
}) {
  const { ref, width } = useWidth();
  const x = scalePoint<string>()
    .domain(periods)
    .range([0, Math.max(width - M.left - M.right, 10)]);
  const top = Math.max(
    0.01,
    ...group.rows.filter((r) => periods.includes(r.period)).map((r) => r.share),
  );
  const y = scaleLinear()
    .domain([0, top])
    .range([HEIGHT - M.top - M.bottom, 0])
    .nice(3);
  const head = group.head;
  return (
    <li
      className={`grid min-w-0 content-start gap-2 rounded-md border border-border p-3 ${dim ? "opacity-40" : ""}`}
    >
      <div>
        <p className="flex items-start gap-2 font-semibold leading-5">
          <Badge
            variant={head.audience === "producto" ? "brand" : "neutral"}
            className="mt-0.5 shrink-0"
          >
            {AUDIENCE_LABEL[head.audience] ?? head.audience}
          </Badge>
          <span className="line-clamp-2">{head.nombre}</span>
        </p>
        <p className="mt-1 flex flex-wrap items-center gap-1 text-xs text-text-muted">
          <span>Familias:</span>
          {head.families.length === 0 ? (
            <span>sin familia asociada</span>
          ) : (
            <>
              {head.families.slice(0, 2).map((f) => (
                <Badge key={f} variant="neutral">
                  {familyName(f)}
                </Badge>
              ))}
              {head.families.length > 2 ? (
                <span title={head.families.slice(2).map(familyName).join(", ")}>
                  +{head.families.length - 2}
                </span>
              ) : null}
            </>
          )}
        </p>
        <p className="tabular mt-1 text-xs text-text-muted">
          {formatInt(group.total)} reseñas en el periodo
        </p>
      </div>
      <div ref={ref} className="min-w-0">
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={`${head.nombre}: parte de las negativas por mes`}
        >
          <g transform={`translate(${M.left},${M.top})`}>
            <GridLines
              scale={y}
              width={Math.max(width - M.left - M.right, 10)}
            />
            <Axis
              scale={y}
              orientation="left"
              length={HEIGHT - M.top - M.bottom}
              format={(v) => formatPct(v as number, 0)}
            />
            {[...new Set([periods[0], periods.at(-1)])].map((p) =>
              p ? (
                <text
                  key={p}
                  x={x(p) ?? 0}
                  y={HEIGHT - M.top - M.bottom + 16}
                  textAnchor={p === periods[0] ? "start" : "end"}
                  fontSize={11}
                  fill="var(--color-neutral-700)"
                >
                  {formatMonth(p)}
                </text>
              ) : null,
            )}
            {banks.map((bank) => {
              const own = group.rows.filter(
                (r) => r.bank_id === bank && periods.includes(r.period),
              );
              return (
                <g key={bank}>
                  <Line
                    points={own.map((r) => ({
                      x: x(r.period) ?? 0,
                      y: r.share,
                    }))}
                    x={scaleLinear().domain([0, 1]).range([0, 1])}
                    y={y}
                    colorVar={BANKS[bank].colorVar}
                    dash={BANKS[bank].dash}
                    strokeWidth={1.75}
                  />
                  {own.map((r) => (
                    <circle
                      key={r.period}
                      cx={x(r.period) ?? 0}
                      cy={y(r.share)}
                      r={6}
                      fill="transparent"
                    >
                      <title>{`${bankLabel(bank)} · ${formatMonth(r.period)}: ${formatPct(r.share)}`}</title>
                    </circle>
                  ))}
                </g>
              );
            })}
          </g>
        </svg>
      </div>
    </li>
  );
}

export function TopicsBlock({
  banks,
  familias,
  from,
  to,
}: {
  banks: BankId[];
  familias: string[];
  from: string;
  to: string;
}) {
  const topics = useTopics(banks);
  const key = banks.join(",");
  const [selected, setSelected] = useState<BankId[]>(banks);
  const [page, setPage] = useState(0);
  // Si cambia el filtro global, los bancos de este bloque vuelven a ser esos.
  // biome-ignore lint/correctness/useExhaustiveDependencies: `key` resume `banks`.
  useEffect(() => {
    setSelected(banks);
    setPage(0);
  }, [key]);

  const shown = useMemo(
    () => banks.filter((b) => selected.includes(b)),
    [banks, selected],
  );
  const periods = useMemo(
    () =>
      [...new Set((topics.data ?? []).map((t) => t.period))]
        .sort()
        .slice(-WINDOW_MONTHS),
    [topics.data],
  );
  const groups = useMemo(() => {
    const byTopic = new Map<number, TopicMonth[]>();
    for (const t of topics.data ?? []) {
      if (!shown.includes(t.bank_id as BankId)) continue;
      byTopic.set(t.topic_id, [...(byTopic.get(t.topic_id) ?? []), t]);
    }
    return [...byTopic.values()]
      .map((rows) => ({
        head: rows[0] as TopicMonth,
        rows,
        total: rows
          .filter((r) => periods.includes(r.period))
          .reduce((s, r) => s + r.filas, 0),
      }))
      .sort((a, b) => b.total - a.total);
  }, [topics.data, shown, periods]);

  if (topics.isPending) return <LoadingBlock />;
  if (topics.isError)
    return <ErrorState error={topics.error} onRetry={() => topics.refetch()} />;

  const pages = Math.max(1, Math.ceil(groups.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const visible = groups.slice(
    current * PAGE_SIZE,
    current * PAGE_SIZE + PAGE_SIZE,
  );
  const go = (next: number) => setPage(Math.min(Math.max(next, 0), pages - 1));

  function toggle(bank: BankId) {
    setSelected((now) =>
      now.includes(bank)
        ? now.length > 1
          ? now.filter((b) => b !== bank)
          : now
        : [...now, bank],
    );
    setPage(0);
  }

  return (
    <ChartFrame
      kicker="Tópicos vigentes"
      title="De qué hablan las negativas"
      subtitle="Solo tópicos útiles para producto o ingeniería, por volumen"
      method="raw"
      actions={
        <OpenInExplorer
          filters={{
            banks: shown,
            from,
            to,
            familia: familias.join(",") || null,
            sentimiento: "NEG",
          }}
        />
      }
      howToRead={
        <p>
          Un <GlossaryTerm id="topico_util">tópico útil</GlossaryTerm> agrupa
          reseñas que hablan de lo mismo y que un curador marcó como relevantes.
          Cada panel es un tópico y cada línea, un banco: qué parte de sus
          reseñas negativas de cada mes cae en ese tópico. Cada panel tiene su
          propia escala; compara los bancos dentro del panel.
        </p>
      }
      provenance={{
        note: groups[0]
          ? `tópicos ${groups[0].head.topic_model_version}`
          : undefined,
      }}
      data={{
        columns: ["Tópico", "Audiencia", "Familias", "Reseñas"],
        rows: groups.map((g) => [
          g.head.nombre,
          AUDIENCE_LABEL[g.head.audience] ?? g.head.audience,
          g.head.families.map(familyName).join(", "),
          g.total,
        ]),
      }}
    >
      <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2">
        <fieldset className="m-0 flex flex-wrap items-center gap-1 border-0 p-0">
          <legend className="sr-only">Bancos de los tópicos</legend>
          <span className="text-sm text-text-muted">Tópicos de:</span>
          {banks.map((id) => (
            <Button
              key={id}
              size="sm"
              variant={selected.includes(id) ? "primary" : "secondary"}
              aria-pressed={selected.includes(id)}
              onClick={() => toggle(id)}
            >
              <span
                aria-hidden="true"
                className="size-2.5 rounded-full"
                style={{ background: `var(${BANKS[id].colorVar})` }}
              />
              {bankLabel(id)}
            </Button>
          ))}
        </fieldset>
      </div>
      {groups.length === 0 ? (
        <p className="text-sm text-text-muted">
          Los bancos elegidos no tienen tópicos útiles en la versión vigente.
        </p>
      ) : (
        <section
          aria-label="Tópicos"
          onKeyDown={(e) => {
            if (e.key === "ArrowRight") go(current + 1);
            if (e.key === "ArrowLeft") go(current - 1);
          }}
          className="grid gap-3 rounded-md outline-offset-2"
        >
          <ol className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {visible.map((g) => (
              <Panel
                key={g.head.topic_id}
                group={g}
                banks={shown}
                periods={periods}
                dim={
                  familias.length > 0 &&
                  !g.head.families.some((f) => familias.includes(f))
                }
              />
            ))}
          </ol>
          <div className="flex items-center justify-center gap-3">
            <Button
              size="sm"
              variant="secondary"
              aria-label="Tópicos anteriores"
              aria-disabled={current === 0}
              className={current === 0 ? "opacity-50" : undefined}
              onClick={() => go(current - 1)}
            >
              <ChevronLeft aria-hidden="true" />
            </Button>
            <span className="tabular text-sm text-text-muted">
              {current * PAGE_SIZE + 1}–
              {Math.min((current + 1) * PAGE_SIZE, groups.length)} de{" "}
              {groups.length} tópicos
            </span>
            <Button
              size="sm"
              variant="secondary"
              aria-label="Tópicos siguientes"
              aria-disabled={current >= pages - 1}
              className={current >= pages - 1 ? "opacity-50" : undefined}
              onClick={() => go(current + 1)}
            >
              <ChevronRight aria-hidden="true" />
            </Button>
          </div>
        </section>
      )}
    </ChartFrame>
  );
}
