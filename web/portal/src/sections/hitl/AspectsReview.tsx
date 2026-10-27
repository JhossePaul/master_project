import { PanelRightClose, PanelRightOpen } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { type HitlCase, saveAspectsReview, useGuideline } from "@/api/hitl";
import { Callout } from "@/components/Callout";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { KeyboardHint } from "@/components/KeyboardHint";
import { Markdown } from "@/components/Markdown";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { FAMILY_GROUPS, FAMILY_TEXT, type Family } from "./families";
import { useCaseQueue } from "./useCaseQueue";

const SHORTCUTS = [
  { keys: "0", action: "Sin problema concreto" },
  { keys: "U", action: "Actualización" },
  { keys: "E", action: "Seguridad" },
  { keys: "Enter", action: "Guardar y seguir" },
  { keys: "S", action: "Saltar" },
  { keys: "G", action: "Mostrar u ocultar la guía" },
];

interface Draft {
  reviewId: string;
  none: boolean;
  families: ReadonlySet<Family>;
  update: boolean;
  security: boolean;
  comment: string;
}

// Funciones del módulo: `useCaseQueue` las usa como dependencias estables.
const blank = (): Draft => ({
  reviewId: crypto.randomUUID(),
  none: false,
  families: new Set(),
  update: false,
  security: false,
  comment: "",
});

const validate = (draft: Draft): string | null =>
  draft.none === draft.families.size > 0
    ? "Marca «Sin problema concreto» o al menos una familia, no ambas."
    : null;

const persist = (item: HitlCase, draft: Draft, claimNext: boolean) =>
  saveAspectsReview(item.item_id, {
    review_id: draft.reviewId,
    families: [...draft.families],
    flag_update: draft.update,
    flag_security: draft.security,
    comment: draft.comment.trim() || null,
    guideline_version: item.guideline_version,
    claim_next: claimNext,
  });

const SANITIZE =
  "No se pudo sanitizar el comentario y no se guardó nada. Tu formulario sigue aquí: reintenta o quita el comentario.";

function isTextEntry(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    target.matches(
      "textarea, select, input:not([type=radio]):not([type=checkbox])",
    )
  );
}

function Guide() {
  const guide = useGuideline("aspects");
  if (guide.isPending) return <Skeleton className="h-64" />;
  if (guide.isError)
    return <ErrorState error={guide.error} onRetry={() => guide.refetch()} />;
  return (
    <div>
      <p className="text-sm text-text-muted">
        Guía {guide.data.guideline_version} · vigente desde{" "}
        {formatDate(guide.data.valid_from)}
      </p>
      <Markdown>{guide.data.content}</Markdown>
    </div>
  );
}

export default function AspectsReview() {
  const navigate = useNavigate();
  const queue = useCaseQueue<Draft>({
    task: "aspects",
    blank,
    validate,
    persist,
    sanitizeMessage: SANITIZE,
  });
  const { phase, draft, setDraft, save, skip, leave, busy } = queue;
  const [guideOpen, setGuideOpen] = useState(true);

  useEffect(() => {
    if (phase.kind !== "case") return;
    const onKey = (event: KeyboardEvent) => {
      if (isTextEntry(event.target)) {
        if (event.key === "Enter" && event.ctrlKey) {
          event.preventDefault();
          void save();
        }
        return;
      }
      if (event.altKey || event.metaKey || event.ctrlKey) return;
      const lower = event.key.toLowerCase();
      if (event.key === "0") {
        setDraft((d) => (d ? { ...d, none: !d.none, families: new Set() } : d));
      } else if (lower === "u") {
        setDraft((d) => (d ? { ...d, update: !d.update } : d));
      } else if (lower === "e") {
        setDraft((d) => (d ? { ...d, security: !d.security } : d));
      } else if (lower === "g") setGuideOpen((open) => !open);
      else if (lower === "s") void skip();
      else if (event.key === "Enter") {
        if (event.target instanceof HTMLButtonElement) return;
        event.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase.kind, save, skip, setDraft]);

  if (phase.kind === "loading" || (phase.kind === "case" && draft === null)) {
    return (
      <div className="grid gap-4" aria-busy="true">
        <Skeleton className="h-8 w-96" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (phase.kind === "error") {
    return <ErrorState error={phase.error} onRetry={() => void queue.load()} />;
  }
  if (phase.kind === "empty") {
    return (
      <EmptyState
        title="No quedan casos pendientes en esta cola"
        description="El administrador crea las muestras de aspectos desde Administración."
        action={
          <Button variant="secondary" onClick={() => navigate("/hitl")}>
            Volver a la revisión
          </Button>
        }
      />
    );
  }
  if (phase.kind === "conflict") {
    return (
      <div className="grid gap-4">
        <Callout variant="warning" title="El caso volvió a la cola">
          Tardaste más de 15 minutos o alguien más lo tomó. No se guardó nada.
        </Callout>
        <div>
          <Button onClick={() => void queue.load()}>Pedir el siguiente</Button>
        </div>
      </div>
    );
  }
  if (draft === null) return null;

  const { item } = phase;
  const toggleFamily = (family: Family) =>
    setDraft((d) => {
      if (!d) return d;
      const families = new Set(d.families);
      if (!families.delete(family)) families.add(family);
      // Elegir una familia desmarca «Sin problema concreto».
      return { ...d, families, none: false };
    });
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-base font-semibold">
          Caso {queue.seen} de esta sesión · guía {item.guideline_version} ·
          modo a ciegas
          {queue.pending > 0 ? (
            <span className="ml-3 font-normal text-text-muted" role="status">
              Guardando{" "}
              {queue.pending === 1
                ? "una revisión"
                : `${queue.pending} revisiones`}
              …
            </span>
          ) : null}
        </h1>
        <Button
          variant="ghost"
          size="sm"
          aria-expanded={guideOpen}
          onClick={() => setGuideOpen((open) => !open)}
        >
          {guideOpen ? (
            <PanelRightClose aria-hidden="true" />
          ) : (
            <PanelRightOpen aria-hidden="true" />
          )}
          {guideOpen ? "Ocultar la guía" : "Mostrar la guía"}
        </Button>
      </div>
      {queue.failed ? (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-md border border-danger/30 bg-danger-bg p-3 text-sm text-danger"
        >
          <span>
            No se guardó la revisión del caso anterior: {queue.failed.message}
          </span>
          <Button size="sm" variant="secondary" onClick={queue.restore}>
            Volver a ese caso
          </Button>
          <Button size="sm" variant="ghost" onClick={queue.dismissFailed}>
            Descartar
          </Button>
        </div>
      ) : null}
      <div className="grid gap-6 xl:grid-cols-12">
        <section
          aria-label="Caso"
          className={cn(
            "grid content-start gap-5",
            guideOpen ? "xl:col-span-8" : "xl:col-span-12",
          )}
        >
          <p className="text-sm">
            Esta reseña es <strong>negativa</strong>. ¿Sobre qué problemas
            concretos se queja?
          </p>
          <div
            lang="es"
            className="whitespace-pre-wrap rounded-md border border-border bg-surface p-5 font-serif text-[20px] leading-[1.5]"
          >
            {item.text}
          </div>
          <form
            className="grid gap-5"
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <label className="flex items-start gap-2 text-sm font-semibold">
              <input
                type="checkbox"
                checked={draft.none}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    none: event.target.checked,
                    // «Sin problema concreto» excluye las familias.
                    families: event.target.checked ? new Set() : draft.families,
                  })
                }
                className="mt-0.5 size-4"
              />
              <span>
                Sin problema concreto
                <span className="block text-xs font-normal text-text-muted">
                  Solo valora mal, no dice qué falla.
                </span>
              </span>
            </label>
            {FAMILY_GROUPS.map((group) => (
              <fieldset key={group.title} className="grid gap-2">
                <legend className="mb-1 text-sm font-semibold">
                  {group.title}
                </legend>
                {group.families.map((family) => (
                  <label
                    key={family}
                    className="flex items-start gap-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={draft.families.has(family)}
                      onChange={() => toggleFamily(family)}
                      className="mt-0.5 size-4"
                    />
                    <span>
                      <strong>{family}</strong> · {FAMILY_TEXT[family].name}
                      <span className="block text-xs text-text-muted">
                        {FAMILY_TEXT[family].help}
                      </span>
                    </span>
                  </label>
                ))}
              </fieldset>
            ))}
            <fieldset className="grid gap-2">
              <legend className="mb-1 text-sm font-semibold">Marcas</legend>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={draft.update}
                  onChange={(event) =>
                    setDraft({ ...draft, update: event.target.checked })
                  }
                  className="mt-0.5 size-4"
                />
                <span>
                  <strong>u</strong> · Actualización
                  <span className="block text-xs text-text-muted">
                    Liga la queja a una actualización o versión nueva.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={draft.security}
                  onChange={(event) =>
                    setDraft({ ...draft, security: event.target.checked })
                  }
                  className="mt-0.5 size-4"
                />
                <span>
                  <strong>s</strong> · Seguridad
                  <span className="block text-xs text-text-muted">
                    Hackeo, fraude con la app, desconfianza, biometría como
                    seguridad, privacidad.
                  </span>
                </span>
              </label>
            </fieldset>
            <div className="grid gap-1">
              <Label htmlFor="comentario">Comentario (opcional)</Label>
              <Textarea
                id="comentario"
                value={draft.comment}
                maxLength={500}
                onChange={(event) =>
                  setDraft({ ...draft, comment: event.target.value })
                }
                aria-describedby="comentario-ayuda"
              />
              <p id="comentario-ayuda" className="text-xs text-text-muted">
                Dudas, ambigüedades o ideas para la guía. No copies el texto de
                la reseña; los nombres y datos personales se reemplazan antes de
                guardar.
              </p>
            </div>
            {queue.formError ? (
              <div
                role="alert"
                className="rounded-md border border-danger/30 bg-danger-bg p-3 text-sm text-danger"
              >
                {queue.formError}
              </div>
            ) : null}
            <div className="flex flex-wrap gap-3">
              <Button type="submit" disabled={busy}>
                Guardar y seguir
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={busy}
                onClick={() => void skip()}
              >
                Saltar
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={busy}
                onClick={() => void leave()}
              >
                Salir
              </Button>
            </div>
          </form>
          <KeyboardHint shortcuts={SHORTCUTS} />
        </section>
        {guideOpen ? (
          <aside
            aria-label="Guía de revisión"
            className="max-h-[80vh] overflow-y-auto rounded-md border border-border bg-surface p-4 xl:col-span-4"
          >
            <Guide />
          </aside>
        ) : null}
      </div>
    </div>
  );
}
