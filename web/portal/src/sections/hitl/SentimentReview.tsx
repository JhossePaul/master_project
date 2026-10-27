import { PanelRightClose, PanelRightOpen } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import {
  type HitlCase,
  nextCase,
  releaseCase,
  releaseOnExit,
  saveReview,
  skipCase,
  useGuideline,
} from "@/api/hitl";
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

type Choice = "NEG" | "NEU" | "POS" | "NO_EVALUABLE";
type Flag = "menciona_falla" | "duda" | "nombre_persona";

const CHOICES: { value: Choice; label: string; key: string }[] = [
  { value: "NEG", label: "NEG", key: "1" },
  { value: "NEU", label: "NEU", key: "2" },
  { value: "POS", label: "POS", key: "3" },
  { value: "NO_EVALUABLE", label: "No evaluable", key: "0" },
];

const FLAGS: { value: Flag; label: string; key: string; help?: string }[] = [
  {
    value: "menciona_falla",
    label: "Menciona una falla concreta",
    key: "F",
    help: "Describe un problema de funcionamiento o de servicio, aunque ya esté resuelto.",
  },
  {
    value: "duda",
    label: "Tengo dudas con esta etiqueta",
    key: "D",
    help: "La decisión fue difícil: elige la mejor opción y marca esto. No uses NEU como refugio.",
  },
  {
    value: "nombre_persona",
    label: "Contiene nombre propio de una persona",
    key: "N",
    help: "Nombre o apellido de una persona escrito en el texto, aunque no sea del autor. No cuentan los tokens como [PERSON_NAME] ni los nombres de bancos o apps.",
  },
];

const SHORTCUTS = [
  { keys: "1 2 3", action: "NEG, NEU, POS" },
  { keys: "0", action: "No evaluable" },
  { keys: "F", action: "Falla concreta" },
  { keys: "D", action: "Tengo dudas" },
  { keys: "N", action: "Nombre propio" },
  { keys: "Enter", action: "Guardar y seguir" },
  { keys: "S", action: "Saltar" },
  { keys: "G", action: "Mostrar u ocultar la guía" },
];

type Phase =
  | { kind: "loading" }
  | { kind: "case"; item: HitlCase }
  | { kind: "empty" }
  | { kind: "conflict" }
  | { kind: "error"; error: unknown };

// Los que se recuerdan para no repetirlos (el servidor acepta hasta 60).
const MAX_DONE = 40;

const PROBABILITY: Record<"NEG" | "NEU" | "POS", "p_neg" | "p_neu" | "p_pos"> =
  { NEG: "p_neg", NEU: "p_neu", POS: "p_pos" };

function isTextEntry(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    target.matches(
      "textarea, select, input:not([type=radio]):not([type=checkbox])",
    )
  );
}

function Guide() {
  const guide = useGuideline("sentiment");
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

interface Draft {
  reviewId: string;
  choice: Choice | null;
  flags: ReadonlySet<Flag>;
  comment: string;
}

/** Una revisión enviada que el servidor no aceptó. */
interface Failed {
  item: HitlCase;
  draft: Draft;
  message: string;
}

type Outcome = { ok: true; item: HitlCase | null } | { ok: false };

/** El caso siguiente, ya pedido (y bloqueado) mientras se revisa el actual. */
interface Ahead {
  for: string;
  outcome: Promise<Outcome>;
  /** El caso bloqueado, en cuanto llega (para soltarlo al salir). */
  held: HitlCase | null;
}

function payload(item: HitlCase, draft: Draft, claimNext: boolean) {
  const noEvaluable = draft.choice === "NO_EVALUABLE";
  return {
    review_id: draft.reviewId,
    validated_label: noEvaluable
      ? null
      : (draft.choice as Exclude<Choice, "NO_EVALUABLE">),
    flags: [...draft.flags, ...(noEvaluable ? ["no_evaluable" as const] : [])],
    comment: draft.comment.trim() || null,
    guideline_version: item.guideline_version,
    claim_next: claimNext,
  };
}

export default function SentimentReview() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [seen, setSeen] = useState(0);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [flags, setFlags] = useState<ReadonlySet<Flag>>(new Set());
  const [comment, setComment] = useState("");
  const [reviewId, setReviewId] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [guideOpen, setGuideOpen] = useState(true);
  const [pending, setPending] = useState(0);
  const [failed, setFailed] = useState<Failed | null>(null);
  const openItem = useRef<string | null>(null);
  const ahead = useRef<Ahead | null>(null);
  const inFlight = useRef<Set<Promise<unknown>>>(new Set());
  const mounted = useRef(true);
  /**
   * Casos que ya guardé o salté en esta sesión. Mientras su guardado va en
   * camino siguen "abiertos" para el servidor, y la precarga los devolvería
   * (el caso recién revisado reaparecía como el siguiente).
   */
  const done = useRef<string[]>([]);
  const markDone = useCallback((id: string) => {
    done.current = [...done.current.filter((x) => x !== id), id].slice(
      -MAX_DONE,
    );
  }, []);

  /** Pide el caso que sigue mientras se lee el actual: guardar ya no espera. */
  const prefetch = useCallback((current: HitlCase) => {
    const entry: Ahead = {
      for: current.item_id,
      held: null,
      outcome: Promise.resolve({ ok: false }),
    };
    entry.outcome = nextCase([current.item_id, ...done.current]).then(
      (item): Outcome => {
        entry.held = item;
        return { ok: true, item };
      },
      (): Outcome => ({ ok: false }),
    );
    ahead.current = entry;
  }, []);

  const fill = useCallback((item: HitlCase, draft?: Draft) => {
    openItem.current = item.item_id;
    setChoice(
      draft ? draft.choice : item.proposal ? item.proposal.label : null,
    );
    setFlags(draft ? draft.flags : new Set());
    setComment(draft ? draft.comment : "");
    setReviewId(draft ? draft.reviewId : crypto.randomUUID());
    setFormError(null);
    setPhase({ kind: "case", item });
  }, []);

  const show = useCallback(
    (item: HitlCase) => {
      fill(item);
      setSeen((n) => n + 1);
      prefetch(item);
    },
    [fill, prefetch],
  );

  const load = useCallback(async () => {
    openItem.current = null;
    ahead.current = null;
    setPhase({ kind: "loading" });
    setFormError(null);
    try {
      const item = await nextCase(done.current);
      if (item) show(item);
      else setPhase({ kind: "empty" });
    } catch (error) {
      setPhase({ kind: "error", error });
    }
  }, [show]);

  useEffect(() => {
    void load();
  }, [load]);

  // Al salir de la pantalla o cerrar la pestaña, los casos abiertos (el actual
  // y el precargado) vuelven a la cola.
  useEffect(() => {
    mounted.current = true;
    const release = () => {
      if (openItem.current) releaseOnExit(openItem.current);
      const held = ahead.current?.held;
      if (held) releaseOnExit(held.item_id);
    };
    window.addEventListener("pagehide", release);
    return () => {
      mounted.current = false;
      window.removeEventListener("pagehide", release);
      release();
    };
  }, []);

  const fail = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 409) {
      openItem.current = null;
      setPhase({ kind: "conflict" });
    } else if (error instanceof ApiError && error.status === 502) {
      setFormError(
        "No se pudo sanitizar el comentario y no se guardó nada. Tu formulario sigue aquí: reintenta o quita el comentario.",
      );
    } else {
      setFormError(
        error instanceof ApiError
          ? error.message
          : "No se pudo completar la acción.",
      );
    }
  }, []);

  /** Envía la revisión sin bloquear la pantalla; si falla, avisa y la conserva. */
  const submitInBackground = useCallback((item: HitlCase, draft: Draft) => {
    setPending((n) => n + 1);
    const task = saveReview(item.item_id, payload(item, draft, false))
      .then(() => {
        if (mounted.current) toast.success("Guardado");
      })
      .catch((error: unknown) => {
        if (!mounted.current) return;
        if (error instanceof ApiError && error.status === 409) {
          toast.error(
            "Una revisión no se guardó: el caso volvió a la cola antes de enviarla.",
          );
          return;
        }
        setFailed({
          item,
          draft,
          message:
            error instanceof ApiError && error.status === 502
              ? "No se pudo sanitizar el comentario."
              : error instanceof ApiError
                ? error.message
                : "No se pudo enviar.",
        });
      })
      .finally(() => {
        inFlight.current.delete(task);
        setPending((n) => n - 1);
      });
    inFlight.current.add(task);
  }, []);

  const advance = useCallback(
    async (next: HitlCase | null) => {
      if (!mounted.current) return;
      if (next && done.current.includes(next.item_id)) {
        // Red de seguridad: nunca se vuelve a mostrar un caso ya revisado.
        await load();
        return;
      }
      if (next) show(next);
      else {
        openItem.current = null;
        ahead.current = null;
        setPhase({ kind: "empty" });
      }
    },
    [show, load],
  );

  const save = useCallback(async () => {
    if (phase.kind !== "case" || busy) return;
    if (choice === null) {
      setFormError("Elige un sentimiento antes de guardar.");
      return;
    }
    const item = phase.item;
    const draft: Draft = { reviewId, choice, flags, comment };
    const pre = ahead.current;
    const out = pre && pre.for === item.item_id ? await pre.outcome : null;
    if (out?.ok) {
      // El siguiente ya está pedido: se muestra de inmediato y el guardado
      // sigue en segundo plano.
      openItem.current = null;
      markDone(item.item_id);
      submitInBackground(item, draft);
      await advance(out.item);
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      const saved = await saveReview(item.item_id, payload(item, draft, true));
      markDone(item.item_id);
      openItem.current = null;
      toast.success("Guardado");
      setBusy(false);
      // La respuesta ya trae el siguiente caso; sin él se pregunta a la cola.
      if (saved.next) show(saved.next);
      else await load();
    } catch (error) {
      setBusy(false);
      fail(error);
    }
  }, [
    phase,
    busy,
    choice,
    flags,
    comment,
    reviewId,
    load,
    show,
    fail,
    advance,
    submitInBackground,
    markDone,
  ]);

  const skip = useCallback(async () => {
    if (phase.kind !== "case" || busy) return;
    const item = phase.item;
    const pre = ahead.current;
    const out = pre && pre.for === item.item_id ? await pre.outcome : null;
    if (out?.ok) {
      openItem.current = null;
      markDone(item.item_id);
      void skipCase(item.item_id).catch(() => {
        if (mounted.current) toast.error("No se pudo saltar el caso anterior.");
      });
      await advance(out.item);
      return;
    }
    setBusy(true);
    try {
      await skipCase(item.item_id);
      markDone(item.item_id);
      openItem.current = null;
      setBusy(false);
      await load();
    } catch (error) {
      setBusy(false);
      fail(error);
    }
  }, [phase, busy, load, fail, advance, markDone]);

  /** Vuelve al caso cuya revisión no se aceptó, con su formulario. */
  const restore = useCallback(() => {
    if (!failed) return;
    const current = phase.kind === "case" ? phase.item : null;
    // El caso que se estaba viendo pasa a ser el precargado: no se pierde.
    ahead.current = current
      ? {
          for: failed.item.item_id,
          held: current,
          outcome: Promise.resolve({ ok: true, item: current }),
        }
      : null;
    fill(failed.item, failed.draft);
    setFailed(null);
  }, [failed, phase, fill]);

  const leave = useCallback(async () => {
    await Promise.allSettled([...inFlight.current]);
    const id = openItem.current;
    openItem.current = null;
    const held = ahead.current?.held;
    ahead.current = null;
    await Promise.all(
      [id, held?.item_id]
        .filter((x): x is string => Boolean(x))
        .map((x) => releaseCase(x).catch(() => undefined)),
    );
    navigate("/hitl");
  }, [navigate]);

  const toggleFlag = useCallback((flag: Flag) => {
    setFlags((current) => {
      const next = new Set(current);
      if (!next.delete(flag)) next.add(flag);
      return next;
    });
  }, []);

  useEffect(() => {
    if (phase.kind !== "case") return;
    const onKey = (event: KeyboardEvent) => {
      const key = event.key;
      if (isTextEntry(event.target)) {
        if (key === "Enter" && event.ctrlKey) {
          event.preventDefault();
          void save();
        }
        return;
      }
      if (event.altKey || event.metaKey || event.ctrlKey) return;
      const lower = key.toLowerCase();
      const pick = CHOICES.find((c) => c.key === key);
      if (pick) setChoice(pick.value);
      else if (lower === "f") toggleFlag("menciona_falla");
      else if (lower === "d") toggleFlag("duda");
      else if (lower === "n") toggleFlag("nombre_persona");
      else if (lower === "g") setGuideOpen((open) => !open);
      else if (lower === "s") void skip();
      else if (key === "Enter") {
        // Sobre un botón, Enter ya lo activa.
        if (event.target instanceof HTMLButtonElement) return;
        event.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase.kind, save, skip, toggleFlag]);

  if (phase.kind === "loading") {
    return (
      <div className="grid gap-4" aria-busy="true">
        <Skeleton className="h-8 w-96" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (phase.kind === "error") {
    return <ErrorState error={phase.error} onRetry={() => void load()} />;
  }
  if (phase.kind === "empty") {
    return (
      <EmptyState
        title="No quedan casos pendientes en esta cola"
        description="Vuelve más tarde: cada día llegan casos nuevos."
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
          <Button onClick={() => void load()}>Pedir el siguiente</Button>
        </div>
      </div>
    );
  }

  const { item } = phase;
  const mode = item.display_mode === "blind" ? "a ciegas" : "asistido";
  const proposal = item.proposal;
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-base font-semibold">
          Caso {seen} de esta sesión · guía {item.guideline_version} · modo{" "}
          {mode}
          {pending > 0 ? (
            <span className="ml-3 font-normal text-text-muted" role="status">
              Guardando{" "}
              {pending === 1 ? "una revisión" : `${pending} revisiones`}…
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
      {failed ? (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-md border border-danger/30 bg-danger-bg p-3 text-sm text-danger"
        >
          <span>
            No se guardó la revisión del caso anterior: {failed.message}
          </span>
          <Button size="sm" variant="secondary" onClick={restore}>
            Volver a ese caso
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setFailed(null)}>
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
          <div
            lang="es"
            className="whitespace-pre-wrap rounded-md border border-border bg-surface p-5 font-serif text-[20px] leading-[1.5]"
          >
            {item.text}
          </div>
          {proposal ? (
            <p className="text-sm">
              El modelo propone <strong>{proposal.label}</strong> (
              {proposal[PROBABILITY[proposal.label]].toFixed(2)})
            </p>
          ) : null}
          <form
            className="grid gap-5"
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <fieldset className="grid gap-2">
              <legend className="mb-1 text-sm font-semibold">
                Sentimiento
              </legend>
              <div className="flex flex-wrap gap-3">
                {CHOICES.map(({ value, label }) => (
                  <label
                    key={value}
                    className={cn(
                      "flex h-12 min-w-24 cursor-pointer items-center justify-center rounded-md border px-5 text-base font-semibold has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2",
                      choice === value
                        ? "border-brand bg-brand text-on-brand"
                        : "border-border-strong bg-surface hover:bg-neutral-100",
                    )}
                  >
                    <input
                      type="radio"
                      name="sentimiento"
                      value={value}
                      checked={choice === value}
                      onChange={() => setChoice(value)}
                      className="sr-only"
                    />
                    {label}
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset className="grid gap-2">
              <legend className="mb-1 text-sm font-semibold">Marcas</legend>
              {FLAGS.map(({ value, label, help }) => (
                <label key={value} className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={flags.has(value)}
                    onChange={() => toggleFlag(value)}
                    className="mt-0.5 size-4"
                  />
                  <span>
                    {label}
                    {help ? (
                      <span className="block text-xs text-text-muted">
                        {help}
                      </span>
                    ) : null}
                  </span>
                </label>
              ))}
            </fieldset>
            <div className="grid gap-1">
              <Label htmlFor="comentario">Comentario (opcional)</Label>
              <Textarea
                id="comentario"
                value={comment}
                maxLength={500}
                onChange={(event) => setComment(event.target.value)}
                aria-describedby="comentario-ayuda"
              />
              <p id="comentario-ayuda" className="text-xs text-text-muted">
                No copies el texto de la reseña; los nombres y datos personales
                se reemplazan antes de guardar.
              </p>
            </div>
            {formError ? (
              <div
                role="alert"
                className="rounded-md border border-danger/30 bg-danger-bg p-3 text-sm text-danger"
              >
                {formError}
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
