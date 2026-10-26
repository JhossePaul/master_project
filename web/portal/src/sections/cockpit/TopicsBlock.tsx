import { scaleLinear, scalePoint } from "d3-scale";
import { useMemo } from "react";
import { type TopicMonth, useTopics } from "@/api/kpis";
import { ChartFrame } from "@/components/ChartFrame";
import { ErrorState } from "@/components/ErrorState";
import { GlossaryTerm } from "@/components/GlossaryTerm";
import { Badge } from "@/components/ui/badge";
import { BANKS, type BankId } from "@/config/banks";
import { formatInt, formatPct } from "@/lib/format";
import { familyName, LoadingBlock, OpenInExplorer } from "./shared";

const TOP = 12;
const AUDIENCE_LABEL: Record<string, string> = {
  producto: "Producto",
  ingenieria: "Ingeniería",
};

function Spark({ rows, colorVar }: { rows: TopicMonth[]; colorVar: string }) {
  const sorted = [...rows].sort((a, b) => a.period.localeCompare(b.period));
  const x = scalePoint<string>()
    .domain(sorted.map((r) => r.period))
    .range([2, 118]);
  const y = scaleLinear()
    .domain([0, Math.max(0.01, ...sorted.map((r) => r.share))])
    .range([26, 2]);
  const points = sorted.map((r) => `${x(r.period)},${y(r.share)}`).join(" ");
  return (
    <svg viewBox="0 0 120 28" className="h-7 w-28" aria-hidden="true">
      <polyline
        fill="none"
        stroke={`var(${colorVar})`}
        strokeWidth={1.5}
        points={points}
      />
    </svg>
  );
}

export function TopicsBlock({
  banks,
  bank,
  familia,
  from,
  to,
}: {
  banks: BankId[];
  bank: BankId;
  familia: string | null;
  from: string;
  to: string;
}) {
  const topics = useTopics(banks);
  const groups = useMemo(() => {
    const byTopic = new Map<number, TopicMonth[]>();
    for (const t of topics.data ?? []) {
      if (t.bank_id !== bank) continue;
      byTopic.set(t.topic_id, [...(byTopic.get(t.topic_id) ?? []), t]);
    }
    return [...byTopic.values()]
      .map((rows) => ({
        head: rows[0] as TopicMonth,
        rows,
        total: rows.reduce((s, r) => s + r.filas, 0),
      }))
      .sort((a, b) => b.total - a.total)
      .slice(0, TOP);
  }, [topics.data, bank]);

  if (topics.isPending) return <LoadingBlock />;
  if (topics.isError)
    return <ErrorState error={topics.error} onRetry={() => topics.refetch()} />;
  return (
    <ChartFrame
      kicker="Tópicos vigentes"
      title="De qué hablan las negativas"
      subtitle="Solo tópicos útiles para producto o ingeniería"
      method="raw"
      actions={
        <OpenInExplorer
          filters={{ banks: [bank], from, to, familia, sentimiento: "NEG" }}
        />
      }
      howToRead={
        <p>
          Un <GlossaryTerm id="topico_util">tópico útil</GlossaryTerm> agrupa
          reseñas que hablan de lo mismo y que un curador marcó como relevantes.
          La minigráfica muestra qué parte de las negativas de cada mes cae en
          el tópico.
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
      {groups.length === 0 ? (
        <p className="text-sm text-text-muted">
          Este banco no tiene tópicos útiles en la versión vigente.
        </p>
      ) : (
        <ol className="grid gap-2">
          {groups.map((g) => {
            const dim = familia && !g.head.families.includes(familia);
            return (
              <li
                key={g.head.topic_id}
                className={`grid gap-2 rounded-sm border border-border p-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center ${dim ? "opacity-40" : ""}`}
              >
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 font-semibold">
                    <Badge
                      variant={
                        g.head.audience === "producto" ? "brand" : "neutral"
                      }
                    >
                      {AUDIENCE_LABEL[g.head.audience] ?? g.head.audience}
                    </Badge>
                    {g.head.nombre}
                  </p>
                  <p className="mt-1 flex flex-wrap items-center gap-1 text-xs text-text-muted">
                    <span>Familias:</span>
                    {g.head.families.length === 0 ? (
                      <span>sin familia asociada</span>
                    ) : (
                      <>
                        {g.head.families.slice(0, 3).map((f) => (
                          <Badge key={f} variant="neutral">
                            {familyName(f)}
                          </Badge>
                        ))}
                        {g.head.families.length > 3 ? (
                          <span
                            title={g.head.families
                              .slice(3)
                              .map(familyName)
                              .join(", ")}
                          >
                            +{g.head.families.length - 3}
                          </span>
                        ) : null}
                      </>
                    )}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <Spark rows={g.rows} colorVar={BANKS[bank].colorVar} />
                  <span className="tabular w-28 text-right text-sm">
                    {formatInt(g.total)} reseñas
                    <br />
                    <span className="text-text-muted">
                      {formatPct(g.rows.at(-1)?.share)} último mes
                    </span>
                  </span>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </ChartFrame>
  );
}
