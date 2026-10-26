import { X } from "lucide-react";
import { useEffect } from "react";
import {
  type ReviewRow,
  useComputeExplanation,
  useReviewDetail,
  useStoredExplanation,
} from "@/api/reviews";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { VersionChip } from "@/components/VersionChip";
import { formatDate, formatPct } from "@/lib/format";
import { FAMILY_NAMES } from "@/sections/cockpit/shared";
import { ExplanationText } from "@/sections/explorer/ExplanationText";
import {
  BankDot,
  ProbabilityBar,
  SentimentBadge,
} from "@/sections/explorer/ResultsTable";

function Explanation({ row }: { row: ReviewRow }) {
  const stored = useStoredExplanation(row.text_key, row.model_version, true);
  const compute = useComputeExplanation();
  const explanation = compute.data ?? stored.data ?? null;
  if (stored.isPending) return <Skeleton className="h-24" />;
  if (explanation)
    return (
      <div className="grid gap-2">
        <p className="text-xs text-text-muted">
          Modelo <VersionChip version={explanation.model_version} /> ·{" "}
          {explanation.method} ·{" "}
          {explanation.source === "on_demand"
            ? "calculada bajo pedido"
            : "precalculada"}
        </p>
        <ExplanationText
          text={row.text}
          explanation={explanation}
          probabilities={row}
        />
      </div>
    );
  return (
    <div className="grid gap-2">
      {stored.isError ? (
        <ErrorState error={stored.error} onRetry={() => stored.refetch()} />
      ) : null}
      <div>
        <Button
          variant="secondary"
          size="sm"
          disabled={compute.isPending || !row.text}
          onClick={() => compute.mutate(row)}
        >
          {compute.isPending ? "Calculando…" : "Calcular explicación"}
        </Button>
      </div>
      <p className="text-xs text-text-muted">
        Puede tardar hasta un minuto si el servicio estaba en reposo.
      </p>
      {compute.isError ? (
        <ErrorState error={compute.error} onRetry={() => compute.mutate(row)} />
      ) : null}
    </div>
  );
}

/** Ficha lateral de una reseña con su texto, predicción y explicación. */
export function ReviewPanel({
  bank,
  id,
  onClose,
}: {
  bank: string;
  id: string;
  onClose: () => void;
}) {
  const detail = useReviewDetail(bank, id);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside
      aria-label="Ficha de la reseña"
      className="fixed inset-y-0 right-0 z-30 flex w-full max-w-xl flex-col gap-4 overflow-y-auto border-l border-border bg-surface p-5 shadow-lg"
    >
      <header className="flex items-start justify-between gap-3">
        <h2 className="font-serif text-xl font-semibold">Ficha de la reseña</h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Cerrar la ficha"
          onClick={onClose}
        >
          <X aria-hidden="true" />
        </Button>
      </header>
      {detail.isPending ? <Skeleton className="h-64" /> : null}
      {detail.isError ? (
        <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
      ) : null}
      {detail.data ? <Body detail={detail.data} /> : null}
    </aside>
  );
}

function Body({
  detail,
}: {
  detail: NonNullable<ReturnType<typeof useReviewDetail>["data"]>;
}) {
  const { row } = detail;
  return (
    <div className="grid gap-5">
      <section aria-label="Texto" className="grid gap-2">
        <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-text-muted">
          <BankDot id={row.bank_id} />
          <span>{formatDate(row.fecha)}</span>
          <span>Versión {row.version_app ?? "—"}</span>
          <span>{row.estrellas} ★</span>
        </p>
        <p
          lang="es"
          className="whitespace-pre-wrap rounded-md border border-border bg-surface-muted p-4 font-serif text-base leading-7"
        >
          {row.text ||
            "(texto no disponible: la reseña cambió desde la predicción)"}
        </p>
      </section>
      <section aria-label="Predicción" className="grid gap-2">
        <h3 className="font-semibold">Predicción</h3>
        <div className="flex flex-wrap items-center gap-3">
          <SentimentBadge value={row.sentiment} />
          <ProbabilityBar row={row} />
          {row.confidence != null ? (
            <span className="text-sm">
              Confianza {formatPct(row.confidence, 0)}
            </span>
          ) : null}
          {row.model_version ? (
            <VersionChip version={row.model_version} />
          ) : null}
        </div>
        {row.p_neg != null && row.p_neu != null && row.p_pos != null ? (
          <p className="tabular text-sm text-text-muted">
            NEG {formatPct(row.p_neg, 1)} · NEU {formatPct(row.p_neu, 1)} · POS{" "}
            {formatPct(row.p_pos, 1)} (calibradas)
          </p>
        ) : null}
      </section>
      <section aria-label="Aspectos y tópicos" className="grid gap-1 text-sm">
        <h3 className="font-semibold">Familias, marcas y tópicos</h3>
        <p>
          Familias:{" "}
          {row.families.length === 0
            ? "ninguna"
            : row.families.map((f) => FAMILY_NAMES[f] ?? f).join(", ")}
        </p>
        <p>
          Relacionada con una actualización:{" "}
          {row.flag_update == null ? "sin dato" : row.flag_update ? "sí" : "no"}
          {" · "}Seguridad:{" "}
          {row.flag_security == null
            ? "sin dato"
            : row.flag_security
              ? "sí"
              : "no"}
        </p>
        {detail.aspects_prompt_version ? (
          <p className="text-xs text-text-muted">
            Prompt <VersionChip version={detail.aspects_prompt_version} />
          </p>
        ) : null}
        <p>
          Tópicos:{" "}
          {row.topics.length === 0
            ? "ninguno"
            : row.topics
                .map((t) => t.name ?? `Tópico ${t.topic_id}`)
                .join(", ")}
        </p>
      </section>
      {detail.hitl_reviews.length > 0 ? (
        <section aria-label="Revisiones humanas" className="grid gap-1 text-sm">
          <h3 className="font-semibold">Revisiones humanas</h3>
          <ul className="grid gap-1">
            {detail.hitl_reviews.map((r) => (
              <li key={`${r.review_round}-${r.submitted_at}`}>
                Ronda {r.review_round}:{" "}
                {r.outcome === "confirmed" ? "confirmó" : "corrigió"}
                {r.validated_label
                  ? ` a ${r.validated_label}`
                  : " (no evaluable)"}
                {" · "}
                {formatDate(r.submitted_at)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section aria-label="Explicación" className="grid gap-2">
        <h3 className="font-semibold">Explicación por palabras</h3>
        <Explanation row={row} />
      </section>
    </div>
  );
}
