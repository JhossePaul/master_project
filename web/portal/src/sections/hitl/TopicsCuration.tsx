import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import {
  type TopicCurationIn,
  type TopicOut,
  useCurateTopic,
  useTopicExamples,
  useTopicVersion,
  useTopicVersions,
} from "@/api/hitl";
import { Callout } from "@/components/Callout";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { KeyboardHint } from "@/components/KeyboardHint";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate, formatInt } from "@/lib/format";
import { cn } from "@/lib/utils";
import { FAMILY_GROUPS, FAMILY_TEXT, type Family } from "./families";

type Audience = TopicCurationIn["audience"];

const AUDIENCES: [Audience, string][] = [
  ["producto", "Producto"],
  ["ingenieria", "Ingeniería"],
  ["sin_valor", "Sin valor"],
];

const AUDIENCE_LABEL = Object.fromEntries(AUDIENCES) as Record<
  Audience,
  string
>;

const SHORTCUTS = [
  { keys: "J", action: "Tópico siguiente" },
  { keys: "K", action: "Tópico anterior" },
  { keys: "Ctrl+Enter", action: "Guardar y pasar al siguiente" },
];

function isTextEntry(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    target.matches(
      "textarea, select, input:not([type=radio]):not([type=checkbox])",
    )
  );
}

function Examples({ version, topicId }: { version: string; topicId: number }) {
  const examples = useTopicExamples(version, topicId);
  if (examples.isPending) return <Skeleton className="h-24" />;
  if (examples.isError)
    return (
      <ErrorState error={examples.error} onRetry={() => examples.refetch()} />
    );
  if (examples.data.examples.length === 0)
    return (
      <p className="text-sm text-text-muted">
        Este tópico no tiene ejemplos disponibles.
      </p>
    );
  return (
    <ul className="grid gap-2">
      {examples.data.examples.map((example) => (
        <li
          key={example.text}
          lang="es"
          className="whitespace-pre-wrap rounded-md border border-border bg-surface p-3 font-serif text-base leading-normal"
        >
          {example.text}
        </li>
      ))}
    </ul>
  );
}

function PreviousPair({ topic }: { topic: TopicOut }) {
  const previous = topic.previous;
  if (!previous)
    return (
      <p className="text-sm text-text-muted">
        Sin tópico anterior emparejado: no hay nada que confirmar.
      </p>
    );
  const curation = previous.curation;
  return (
    <div className="grid gap-1 text-sm">
      <p>
        Tópico anterior {previous.topic_id} · similitud del centroide{" "}
        <span className="tabular">
          {previous.centroid_similarity.toFixed(2)}
        </span>
      </p>
      {curation ? (
        <p className="text-text-muted">
          {curation.curated_name} · {AUDIENCE_LABEL[curation.audience]}
          {curation.families.length > 0
            ? ` · ${curation.families.join(", ")}`
            : ""}
        </p>
      ) : (
        <p className="text-text-muted">El anterior no tiene curaduría.</p>
      )}
    </div>
  );
}

interface FormState {
  name: string;
  coherence: number | null;
  audience: Audience | null;
  families: ReadonlySet<Family>;
  isNew: boolean;
  confirmed: boolean;
}

function initial(topic: TopicOut): FormState {
  const decision = topic.decision;
  if (decision)
    return {
      name: decision.curated_name,
      coherence: decision.coherence_1_5,
      audience: decision.audience,
      families: new Set(decision.families as Family[]),
      isNew: decision.is_new_theme,
      confirmed: decision.mapping_confirmed,
    };
  // Sin decisión, se propone lo que dijo el curador del tópico anterior.
  const previous = topic.previous?.curation;
  return {
    name: previous?.curated_name ?? "",
    coherence: null,
    audience: previous?.audience ?? null,
    families: new Set((previous?.families ?? []) as Family[]),
    isNew: topic.previous === null,
    confirmed: topic.previous !== null,
  };
}

function TopicForm({
  topic,
  busy,
  onSave,
}: {
  topic: TopicOut;
  busy: boolean;
  onSave: (body: TopicCurationIn) => void;
}) {
  const [form, setForm] = useState<FormState>(() => initial(topic));
  const [error, setError] = useState<string | null>(null);
  const paired = topic.previous !== null;

  const submit = () => {
    if (form.name.trim() === "")
      return setError("Escribe el nombre del tópico.");
    if (form.coherence === null)
      return setError("Elige la coherencia de 1 a 5.");
    if (form.audience === null) return setError("Elige la audiencia.");
    setError(null);
    onSave({
      curated_name: form.name.trim(),
      coherence_1_5: form.coherence,
      audience: form.audience,
      families: [...form.families],
      is_new_theme: form.isNew,
      mapping_confirmed: paired && form.confirmed,
    });
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Enter" && event.ctrlKey) {
        event.preventDefault();
        submit();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const toggle = (family: Family) =>
    setForm((f) => {
      const families = new Set(f.families);
      if (!families.delete(family)) families.add(family);
      return { ...f, families };
    });

  return (
    <form
      className="grid gap-5"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="grid gap-1">
        <Label htmlFor="topic-name">Nombre</Label>
        <Input
          id="topic-name"
          value={form.name}
          maxLength={80}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
        />
      </div>
      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-semibold">
          Coherencia (1 a 5)
        </legend>
        <div className="flex flex-wrap gap-2">
          {[1, 2, 3, 4, 5].map((n) => (
            <label
              key={n}
              className={cn(
                "flex size-10 cursor-pointer items-center justify-center rounded-md border text-base font-semibold has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2",
                form.coherence === n
                  ? "border-brand bg-brand text-on-brand"
                  : "border-border-strong bg-surface hover:bg-neutral-100",
              )}
            >
              <input
                type="radio"
                name="coherence"
                checked={form.coherence === n}
                onChange={() => setForm({ ...form, coherence: n })}
                className="sr-only"
              />
              {n}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-semibold">Audiencia</legend>
        <div className="flex flex-wrap gap-2">
          {AUDIENCES.map(([value, label]) => (
            <label
              key={value}
              className={cn(
                "flex h-10 cursor-pointer items-center rounded-md border px-4 text-sm font-semibold has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2",
                form.audience === value
                  ? "border-brand bg-brand text-on-brand"
                  : "border-border-strong bg-surface hover:bg-neutral-100",
              )}
            >
              <input
                type="radio"
                name="audience"
                checked={form.audience === value}
                onChange={() => setForm({ ...form, audience: value })}
                className="sr-only"
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="grid gap-3">
        <legend className="mb-1 text-sm font-semibold">
          Familias (en su orden de importancia, si hay varias)
        </legend>
        {FAMILY_GROUPS.map((group) => (
          <div key={group.title} className="grid gap-1">
            <p className="text-xs text-text-muted">{group.title}</p>
            {group.families.map((family) => (
              <label key={family} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.families.has(family)}
                  onChange={() => toggle(family)}
                  className="mt-0.5 size-4"
                />
                <span>
                  <strong>{family}</strong> · {FAMILY_TEXT[family].name}
                </span>
              </label>
            ))}
          </div>
        ))}
        <p className="text-xs text-text-muted">
          Sin familias quiere decir que el tópico mezcla temas o no tiene una.
        </p>
      </fieldset>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.isNew}
          onChange={(event) =>
            setForm({ ...form, isNew: event.target.checked })
          }
          className="mt-0.5 size-4"
        />
        Es un tema nuevo
      </label>
      {paired ? (
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.confirmed}
            onChange={(event) =>
              setForm({ ...form, confirmed: event.target.checked })
            }
            className="mt-0.5 size-4"
          />
          El emparejamiento con el tópico anterior es correcto
        </label>
      ) : null}
      {error ? (
        <div
          role="alert"
          className="rounded-md border border-danger/30 bg-danger-bg p-3 text-sm text-danger"
        >
          {error}
        </div>
      ) : null}
      <div>
        <Button type="submit" disabled={busy}>
          Guardar y seguir
        </Button>
      </div>
    </form>
  );
}

function VersionCuration({ version }: { version: string }) {
  const detail = useTopicVersion(version);
  const curate = useCurateTopic(version);
  const [onlyPending, setOnlyPending] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [activated, setActivated] = useState(false);

  const topics = detail.data?.topics;
  const visible = useMemo(
    () =>
      (topics ?? []).filter(
        (t) => !onlyPending || (t.previous !== null && t.decision === null),
      ),
    [topics, onlyPending],
  );
  const current =
    visible.find((t) => t.topic_id === selected) ?? visible[0] ?? null;

  const move = (delta: number) => {
    if (!current || visible.length === 0) return;
    const i = visible.findIndex((t) => t.topic_id === current.topic_id);
    const next = visible[(i + delta + visible.length) % visible.length];
    if (next) setSelected(next.topic_id);
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (isTextEntry(event.target)) return;
      if (event.altKey || event.metaKey || event.ctrlKey) return;
      const lower = event.key.toLowerCase();
      if (lower === "j") move(1);
      else if (lower === "k") move(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (detail.isPending) return <Skeleton className="h-64" />;
  if (detail.isError)
    return <ErrorState error={detail.error} onRetry={() => detail.refetch()} />;

  const save = (topic: TopicOut, body: TopicCurationIn) => {
    // El siguiente pendiente después de este, antes de que cambie la lista.
    const after = detail.data.topics.filter(
      (t) =>
        t.topic_id !== topic.topic_id &&
        t.previous !== null &&
        t.decision === null,
    );
    const next =
      after.find((t) => t.topic_id > topic.topic_id) ?? after[0] ?? null;
    curate.mutate(
      { topicId: topic.topic_id, body },
      {
        onSuccess: (result) => {
          toast.success("Guardado");
          if (result.completed && !detail.data.is_current) setActivated(true);
          if (next) setSelected(next.topic_id);
        },
        onError: (error) =>
          toast.error(
            error instanceof ApiError
              ? error.message
              : "No se pudo guardar la curaduría.",
          ),
      },
    );
  };

  return (
    <div className="grid gap-4">
      {activated ? (
        <Callout variant="info" title="La versión quedó completa">
          Todos los tópicos emparejados tienen una decisión: la versión pasa a
          ser la vigente y el histórico se re-asigna.
        </Callout>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={onlyPending}
            onChange={(event) => setOnlyPending(event.target.checked)}
            className="size-4"
          />
          Solo pendientes
        </label>
        <span className="tabular text-sm text-text-muted">
          {formatInt(detail.data.decided)} de {formatInt(detail.data.paired)}{" "}
          emparejados decididos
        </span>
      </div>
      {current === null ? (
        <EmptyState
          title="No quedan tópicos pendientes"
          description="Todos los tópicos emparejados de esta versión tienen una decisión."
        />
      ) : (
        <div className="grid gap-6 xl:grid-cols-12">
          <nav
            aria-label="Tópicos de la versión"
            className="max-h-[70vh] overflow-y-auto rounded-md border border-border bg-surface xl:col-span-3"
          >
            <ul>
              {visible.map((topic) => (
                <li key={topic.topic_id}>
                  <button
                    type="button"
                    aria-current={
                      topic.topic_id === current.topic_id ? "true" : undefined
                    }
                    onClick={() => setSelected(topic.topic_id)}
                    className={cn(
                      "flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-neutral-100",
                      topic.topic_id === current.topic_id && "bg-neutral-100",
                    )}
                  >
                    <span className="truncate">
                      {topic.topic_id} · {topic.terms.slice(0, 3).join(", ")}
                    </span>
                    <span className="text-xs text-text-muted">
                      {topic.decision
                        ? "decidido"
                        : topic.previous
                          ? "pendiente"
                          : "nuevo"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>
          <section
            aria-label="Ficha del tópico"
            key={current.topic_id}
            className="grid content-start gap-5 xl:col-span-9"
          >
            <div>
              <h2 className="text-lg font-semibold">
                Tópico {current.topic_id}
              </h2>
              <p className="text-sm">{current.terms.join(" · ")}</p>
              <p className="tabular text-sm text-text-muted">
                {formatInt(current.size)} cláusulas asignadas
              </p>
            </div>
            <PreviousPair topic={current} />
            <div className="grid gap-2">
              <h3 className="text-sm font-semibold">Ejemplos</h3>
              <Examples version={version} topicId={current.topic_id} />
            </div>
            <TopicForm
              topic={current}
              busy={curate.isPending}
              onSave={(body) => save(current, body)}
            />
            <div className="flex gap-3">
              <Button variant="secondary" size="sm" onClick={() => move(-1)}>
                Anterior
              </Button>
              <Button variant="secondary" size="sm" onClick={() => move(1)}>
                Siguiente
              </Button>
            </div>
            <KeyboardHint shortcuts={SHORTCUTS} />
          </section>
        </div>
      )}
    </div>
  );
}

export default function TopicsCuration() {
  const versions = useTopicVersions();
  const [chosen, setChosen] = useState<string | null>(null);

  if (versions.isPending) return <Skeleton className="h-48" />;
  if (versions.isError)
    return (
      <ErrorState error={versions.error} onRetry={() => versions.refetch()} />
    );
  const all = versions.data.versions;
  const pending = all.filter((v) => v.decided < v.paired);
  const active = chosen ?? pending[0]?.topic_model_version ?? null;

  return (
    <div className="grid gap-6">
      <h1 className="font-serif text-3xl font-semibold">
        Curaduría de tópicos
      </h1>
      {pending.length === 0 ? (
        <Callout variant="info" title="No hay versiones por decidir">
          La versión vigente no tiene tópicos pendientes. Aun así puedes volver
          a curar uno: la última decisión gana.
        </Callout>
      ) : (
        <Callout
          variant="info"
          title="Al decidir el último, la versión se activa"
        >
          Cuando todos los tópicos emparejados tengan una decisión, la versión
          pasa a ser la vigente y el histórico se re-asigna.
        </Callout>
      )}
      <ul className="grid gap-2 md:grid-cols-2">
        {all.map((v) => (
          <li key={v.topic_model_version}>
            <button
              type="button"
              aria-pressed={v.topic_model_version === active}
              onClick={() => setChosen(v.topic_model_version)}
              className={cn(
                "w-full rounded-md border p-3 text-left text-sm",
                v.topic_model_version === active
                  ? "border-brand bg-neutral-100"
                  : "border-border bg-surface hover:bg-neutral-100",
              )}
            >
              <span className="block font-semibold">
                {v.topic_model_version}
                {v.is_current ? " · vigente" : ""}
              </span>
              <span className="block text-text-muted">
                Ajustada el {formatDate(v.fitted_at)} ·{" "}
                <span className="tabular">
                  {formatInt(v.decided)} de {formatInt(v.paired)}
                </span>{" "}
                decididos
              </span>
            </button>
          </li>
        ))}
      </ul>
      {active ? (
        <VersionCuration key={active} version={active} />
      ) : (
        <EmptyState
          title="Todavía no hay versiones de tópicos"
          description="La primera versión aparece después del primer ajuste."
        />
      )}
    </div>
  );
}
