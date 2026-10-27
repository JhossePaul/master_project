import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import {
  type HitlCase,
  nextCase,
  type QueueTask,
  type ReviewOut,
  releaseCase,
  releaseOnExit,
  skipCase,
} from "@/api/hitl";

/**
 * Motor de una cola de revisión: tomar el caso, precargar el siguiente
 * mientras se lee, guardar en segundo plano y no volver a mostrar lo ya
 * revisado. Es el mismo flujo que la pantalla de sentimiento (cuyas
 * esperas por caso se midieron en dev); lo reutilizan las colas nuevas.
 */

export type Phase =
  | { kind: "loading" }
  | { kind: "case"; item: HitlCase }
  | { kind: "empty" }
  | { kind: "conflict" }
  | { kind: "error"; error: unknown };

interface Draft {
  reviewId: string;
}

/** Una revisión enviada que el servidor no aceptó. */
export interface Failed<D> {
  item: HitlCase;
  draft: D;
  message: string;
}

type Outcome = { ok: true; item: HitlCase | null } | { ok: false };

interface Ahead {
  for: string;
  outcome: Promise<Outcome>;
  held: HitlCase | null;
}

// Los que se recuerdan para no repetirlos (el servidor acepta hasta 60).
const MAX_DONE = 40;

export interface QueueOptions<D extends Draft> {
  task: QueueTask;
  /** El borrador de un caso nuevo (con su `reviewId`). */
  blank: (item: HitlCase) => D;
  /** `null` si se puede guardar; si no, lo que falta. */
  validate: (draft: D) => string | null;
  persist: (item: HitlCase, draft: D, claimNext: boolean) => Promise<ReviewOut>;
  /** Mensaje del 502 (DLP caído) en el formulario. */
  sanitizeMessage: string;
}

export function useCaseQueue<D extends Draft>(options: QueueOptions<D>) {
  const { task, blank, validate, persist, sanitizeMessage } = options;
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [seen, setSeen] = useState(0);
  const [draft, setDraft] = useState<D | null>(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(0);
  const [failed, setFailed] = useState<Failed<D> | null>(null);
  const openItem = useRef<string | null>(null);
  const ahead = useRef<Ahead | null>(null);
  const inFlight = useRef<Set<Promise<unknown>>>(new Set());
  const mounted = useRef(true);
  const done = useRef<string[]>([]);
  const markDone = useCallback((id: string) => {
    done.current = [...done.current.filter((x) => x !== id), id].slice(
      -MAX_DONE,
    );
  }, []);

  const prefetch = useCallback(
    (current: HitlCase) => {
      const entry: Ahead = {
        for: current.item_id,
        held: null,
        outcome: Promise.resolve({ ok: false }),
      };
      entry.outcome = nextCase([current.item_id, ...done.current], task).then(
        (item): Outcome => {
          entry.held = item;
          return { ok: true, item };
        },
        (): Outcome => ({ ok: false }),
      );
      ahead.current = entry;
    },
    [task],
  );

  const fill = useCallback(
    (item: HitlCase, restored?: D) => {
      openItem.current = item.item_id;
      setDraft(restored ?? blank(item));
      setFormError(null);
      setPhase({ kind: "case", item });
    },
    [blank],
  );

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
      const item = await nextCase(done.current, task);
      if (item) show(item);
      else setPhase({ kind: "empty" });
    } catch (error) {
      setPhase({ kind: "error", error });
    }
  }, [show, task]);

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

  const fail = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 409) {
        openItem.current = null;
        setPhase({ kind: "conflict" });
      } else if (error instanceof ApiError && error.status === 502) {
        setFormError(sanitizeMessage);
      } else {
        setFormError(
          error instanceof ApiError
            ? error.message
            : "No se pudo completar la acción.",
        );
      }
    },
    [sanitizeMessage],
  );

  const submitInBackground = useCallback(
    (item: HitlCase, saved: D) => {
      setPending((n) => n + 1);
      const job = persist(item, saved, false)
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
            draft: saved,
            message:
              error instanceof ApiError && error.status === 502
                ? "No se pudo sanitizar el comentario."
                : error instanceof ApiError
                  ? error.message
                  : "No se pudo enviar.",
          });
        })
        .finally(() => {
          inFlight.current.delete(job);
          setPending((n) => n - 1);
        });
      inFlight.current.add(job);
    },
    [persist],
  );

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
    if (phase.kind !== "case" || busy || draft === null) return;
    const missing = validate(draft);
    if (missing) {
      setFormError(missing);
      return;
    }
    const item = phase.item;
    const pre = ahead.current;
    const out = pre && pre.for === item.item_id ? await pre.outcome : null;
    if (out?.ok) {
      openItem.current = null;
      markDone(item.item_id);
      submitInBackground(item, draft);
      await advance(out.item);
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      const saved = await persist(item, draft, true);
      markDone(item.item_id);
      openItem.current = null;
      toast.success("Guardado");
      setBusy(false);
      if (saved.next) show(saved.next);
      else await load();
    } catch (error) {
      setBusy(false);
      fail(error);
    }
  }, [
    phase,
    busy,
    draft,
    validate,
    persist,
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

  return {
    phase,
    seen,
    draft,
    setDraft,
    busy,
    formError,
    pending,
    failed,
    dismissFailed: () => setFailed(null),
    load,
    save,
    skip,
    restore,
    leave,
  };
}
