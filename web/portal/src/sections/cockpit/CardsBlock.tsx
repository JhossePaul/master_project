import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { useState } from "react";
import { type BankCard, useCards } from "@/api/kpis";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { GlossaryTerm } from "@/components/GlossaryTerm";
import { KpiCard, KpiCardFrame } from "@/components/KpiCard";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { BANKS, type BankId, bankLabel } from "@/config/banks";
import {
  formatInt,
  formatMonth,
  formatPct,
  formatPctRange,
  formatStars,
  formatStarsRange,
} from "@/lib/format";
import { LoadingBlock } from "./shared";

type Estimate = components["schemas"]["Estimate"];

/** Cambio contra el mismo mes del año anterior, sin juzgar si es bueno o malo. */
export function Change({
  now,
  before,
  kind,
  period,
}: {
  now: Estimate | null;
  before: Estimate | null | undefined;
  kind: "pct" | "stars";
  period: string;
}) {
  if (!now || !before) return null;
  const diff = now.estimate - before.estimate;
  const Icon = Math.abs(diff) < 0.0005 ? Minus : diff > 0 ? ArrowUp : ArrowDown;
  const text =
    kind === "pct"
      ? `${diff >= 0 ? "+" : "−"}${formatPct(Math.abs(diff)).replace(" %", " pts")}`
      : formatStars(diff);
  return (
    <span className="inline-flex items-center gap-1 text-text-muted">
      <Icon className="size-3" aria-hidden="true" />
      <span className="tabular">{text}</span> frente a {formatMonth(period)}
    </span>
  );
}

type Compare = "year" | "month";

function BankCardView({ card, compare }: { card: BankCard; compare: Compare }) {
  const style = BANKS[card.bank_id as BankId];
  const prev = compare === "year" ? card.previous_year : card.previous_month;
  if (!card.period) {
    return (
      <KpiCardFrame colorVar={style?.colorVar}>
        <h3 className="mb-2 font-serif text-xl font-semibold">
          {bankLabel(card.bank_id)}
        </h3>
        <p className="text-sm text-text-muted">
          Sin cifra con revisión humana todavía.
        </p>
      </KpiCardFrame>
    );
  }
  return (
    <KpiCardFrame colorVar={style?.colorVar}>
      <div className="mb-3 flex items-start justify-between gap-2">
        <h3 className="font-serif text-xl font-semibold">
          {bankLabel(card.bank_id)}
        </h3>
        <span className="text-xs text-text-muted">
          {formatMonth(card.period)}
        </span>
      </div>
      <div className="grid gap-4">
        <KpiCard
          label={
            <GlossaryTerm id="gap_estrellas">Brecha en estrellas</GlossaryTerm>
          }
          value={formatStars(card.gap_estrellas?.estimate)}
          interval={formatStarsRange(
            card.gap_estrellas?.ci_low,
            card.gap_estrellas?.ci_high,
          )}
          method="ppi"
          delta={
            prev ? (
              <Change
                now={card.gap_estrellas}
                before={prev.gap_estrellas}
                kind="stars"
                period={prev.period}
              />
            ) : null
          }
        />
        <KpiCard
          label="Reseñas negativas"
          value={formatPct(card.neg?.estimate)}
          interval={formatPctRange(card.neg?.ci_low, card.neg?.ci_high)}
          method="ppi"
          delta={
            prev ? (
              <Change
                now={card.neg}
                before={prev.neg}
                kind="pct"
                period={prev.period}
              />
            ) : null
          }
        />
        <KpiCard
          label="Quejas con 4–5 estrellas"
          value={formatPct(card.quejas_4_5?.estimate)}
          interval={formatPctRange(
            card.quejas_4_5?.ci_low,
            card.quejas_4_5?.ci_high,
          )}
          method="ppi"
          delta={
            prev ? (
              <Change
                now={card.quejas_4_5}
                before={prev.quejas_4_5}
                kind="pct"
                period={prev.period}
              />
            ) : null
          }
          provenance={{
            model: card.model_version,
            gold: card.gold_version,
            note: `cifras de ${formatMonth(card.period)}`,
          }}
        />
        <p className="flex items-center gap-2 text-sm">
          Alertas abiertas:{" "}
          <span className="tabular font-semibold">
            {formatInt(card.open_alerts)}
          </span>
          {card.open_alerts > 0 ? <StatusPill status="abierta" /> : null}
        </p>
      </div>
    </KpiCardFrame>
  );
}

export function CardsBlock({ banks }: { banks: BankId[] }) {
  const cards = useCards(banks);
  const [compare, setCompare] = useState<Compare>("year");
  if (cards.isPending) return <LoadingBlock />;
  if (cards.isError)
    return <ErrorState error={cards.error} onRetry={() => cards.refetch()} />;
  return (
    <section
      id="resumen"
      aria-label="Último mes por banco"
      className="scroll-mt-40"
    >
      <h2 className="sr-only">Último mes por banco</h2>
      <fieldset className="m-0 mb-3 flex flex-wrap items-center gap-2 border-0 p-0">
        <legend className="sr-only">Comparar con</legend>
        <span className="text-sm text-text-muted">Comparar con:</span>
        {(
          [
            ["year", "Mismo mes del año anterior"],
            ["month", "Mes anterior"],
          ] as const
        ).map(([key, label]) => (
          <Button
            key={key}
            size="sm"
            variant={compare === key ? "primary" : "secondary"}
            aria-pressed={compare === key}
            onClick={() => setCompare(key)}
          >
            {label}
          </Button>
        ))}
      </fieldset>
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
        {cards.data.map((card) => (
          <BankCardView key={card.bank_id} card={card} compare={compare} />
        ))}
      </div>
    </section>
  );
}
