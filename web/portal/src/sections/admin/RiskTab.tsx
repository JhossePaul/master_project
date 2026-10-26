import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import {
  type FieldPath,
  type Resolver,
  type UseFormReturn,
  useForm,
} from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import {
  type Changes,
  previewRisk,
  type RiskPolicy,
  type RiskPreview,
  useCoverageCurve,
  useRiskPolicy,
  useSaveRisk,
} from "@/api/admin";
import { Callout } from "@/components/Callout";
import { ChartFrame } from "@/components/ChartFrame";
import { ConfirmWithReason } from "@/components/ConfirmWithReason";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { RISK_HELP, type RiskField } from "@/config/policyHelp";
import { formatDate, formatPct } from "@/lib/format";
import { CoverageChart } from "./CoverageChart";
import { HelpButton } from "./HelpButton";

const CONFIRM_WORD = "CONFIRMAR";

export interface RiskForm {
  hitl_target_coverage: number;
  hitl_weekly_cap: number | null;
  no_boost: boolean;
  drift_boost_coverage: number | null;
  drift_boost_days: number | null;
  drift_boost_weekly_cap: number | null;
  monitor_sample_size: number;
  monitor_frequency: string;
  no_agreement: boolean;
  human_agreement_sample_size: number | null;
  human_agreement_frequency: string | null;
  warn_correction_rate: number;
  warn_agreement_floor: number;
  agreement_sample_weekly: number;
  families_exact_floor: number;
  families_min_prevalence: number;
  retrain_kappa_floor: number;
  retrain_trigger: "manual" | "auto";
  topic_refit_trigger: "scheduled" | "manual";
  topic_refit_frequency: string;
}

type NumberKey = {
  [K in keyof RiskForm]: RiskForm[K] extends number | null ? K : never;
}[keyof RiskForm] &
  RiskField;

const REQUIRED = "Escribe un número";

function bounded(field: RiskField) {
  const help = RISK_HELP[field] as { min?: number; max?: number };
  let schema = z.number({ error: REQUIRED });
  if (help.min !== undefined)
    schema = schema.min(help.min, `Mínimo ${help.min}`);
  if (help.max !== undefined)
    schema = schema.max(help.max, `Máximo ${help.max}`);
  return schema;
}

const text = z.string().trim().min(1, "Escribe un valor");

export const riskSchema = z
  .object({
    hitl_target_coverage: bounded("hitl_target_coverage"),
    hitl_weekly_cap: bounded("hitl_weekly_cap").nullable(),
    no_boost: z.boolean(),
    drift_boost_coverage: bounded("drift_boost_coverage").nullable(),
    drift_boost_days: bounded("drift_boost_days").nullable(),
    drift_boost_weekly_cap: bounded("drift_boost_weekly_cap").nullable(),
    monitor_sample_size: bounded("monitor_sample_size"),
    monitor_frequency: text,
    no_agreement: z.boolean(),
    human_agreement_sample_size: bounded(
      "human_agreement_sample_size",
    ).nullable(),
    human_agreement_frequency: z.string().trim().nullable(),
    warn_correction_rate: bounded("warn_correction_rate"),
    warn_agreement_floor: bounded("warn_agreement_floor"),
    agreement_sample_weekly: bounded("agreement_sample_weekly"),
    families_exact_floor: bounded("families_exact_floor"),
    families_min_prevalence: bounded("families_min_prevalence"),
    retrain_kappa_floor: bounded("retrain_kappa_floor"),
    retrain_trigger: z.enum(["manual", "auto"]),
    topic_refit_trigger: z.enum(["scheduled", "manual"]),
    topic_refit_frequency: text,
  })
  .superRefine((v, ctx) => {
    if (!v.no_boost) {
      for (const key of [
        "drift_boost_coverage",
        "drift_boost_days",
        "drift_boost_weekly_cap",
      ] as const) {
        if (v[key] === null)
          ctx.addIssue({
            code: "custom",
            path: [key],
            message: "La subida se configura completa",
          });
      }
    }
    if (!v.no_agreement) {
      if (v.human_agreement_sample_size === null)
        ctx.addIssue({
          code: "custom",
          path: ["human_agreement_sample_size"],
          message: "La doble revisión se configura completa",
        });
      if (!v.human_agreement_frequency)
        ctx.addIssue({
          code: "custom",
          path: ["human_agreement_frequency"],
          message: "La doble revisión se configura completa",
        });
    }
  });

export function toForm(p: RiskPolicy): RiskForm {
  return {
    hitl_target_coverage: p.hitl_target_coverage,
    hitl_weekly_cap: p.hitl_weekly_cap ?? null,
    no_boost: p.drift_boost_coverage == null,
    drift_boost_coverage: p.drift_boost_coverage ?? null,
    drift_boost_days: p.drift_boost_days ?? null,
    drift_boost_weekly_cap: p.drift_boost_weekly_cap ?? null,
    monitor_sample_size: p.monitor_sample_size,
    monitor_frequency: p.monitor_frequency,
    no_agreement: p.human_agreement_sample_size == null,
    human_agreement_sample_size: p.human_agreement_sample_size ?? null,
    human_agreement_frequency: p.human_agreement_frequency ?? null,
    warn_correction_rate: p.warn_correction_rate,
    warn_agreement_floor: p.warn_agreement_floor,
    agreement_sample_weekly: p.agreement_sample_weekly,
    families_exact_floor: p.families_exact_floor,
    families_min_prevalence: p.families_min_prevalence,
    retrain_kappa_floor: p.retrain_kappa_floor,
    retrain_trigger: p.retrain_trigger ?? "manual",
    topic_refit_trigger: p.topic_refit_trigger ?? "scheduled",
    topic_refit_frequency: p.topic_refit_frequency,
  };
}

/** Solo los campos que cambian; un grupo apagado queda en nulo. */
export function toChanges(values: RiskForm, current: RiskPolicy): Changes {
  const next: Record<string, unknown> = {
    ...values,
    drift_boost_coverage: values.no_boost ? null : values.drift_boost_coverage,
    drift_boost_days: values.no_boost ? null : values.drift_boost_days,
    drift_boost_weekly_cap: values.no_boost
      ? null
      : values.drift_boost_weekly_cap,
    human_agreement_sample_size: values.no_agreement
      ? null
      : values.human_agreement_sample_size,
    human_agreement_frequency: values.no_agreement
      ? null
      : values.human_agreement_frequency?.trim() || null,
  };
  delete next.no_boost;
  delete next.no_agreement;
  const before = toForm(current) as unknown as Record<string, unknown>;
  const was: Record<string, unknown> = { ...before };
  delete was.no_boost;
  delete was.no_agreement;
  return Object.fromEntries(
    Object.entries(next).filter(([key, value]) => was[key] !== value),
  );
}

const toNumber = (v: unknown) =>
  v === "" || v === null || v === undefined ? null : Number(v);

function NumberField({
  form,
  name,
  disabled,
}: {
  form: UseFormReturn<RiskForm>;
  name: NumberKey;
  disabled?: boolean;
}) {
  const help = RISK_HELP[name] as {
    label: string;
    unit: string;
    min?: number;
    max?: number;
    step?: number;
  };
  const error = form.formState.errors[name]?.message;
  return (
    <div className="grid gap-1">
      <div className="flex items-center gap-2">
        <Label htmlFor={name}>{help.label}</Label>
        <HelpButton help={RISK_HELP[name]} />
      </div>
      <Input
        id={name}
        type="number"
        inputMode="decimal"
        min={help.min}
        max={help.max}
        step={help.step ?? "any"}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        {...form.register(name as FieldPath<RiskForm>, {
          setValueAs: toNumber,
        })}
      />
      {help.unit ? (
        <p className="text-xs text-text-muted">{help.unit}</p>
      ) : null}
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {String(error)}
        </p>
      ) : null}
    </div>
  );
}

function TextField({
  form,
  name,
  disabled,
}: {
  form: UseFormReturn<RiskForm>;
  name:
    | "monitor_frequency"
    | "human_agreement_frequency"
    | "topic_refit_frequency";
  disabled?: boolean;
}) {
  const help = RISK_HELP[name];
  const error = form.formState.errors[name]?.message;
  return (
    <div className="grid gap-1">
      <div className="flex items-center gap-2">
        <Label htmlFor={name}>{help.label}</Label>
        <HelpButton help={help} />
      </div>
      <Input
        id={name}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        {...form.register(name, {
          setValueAs: (v: string) => (v === "" ? null : v),
        })}
      />
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {String(error)}
        </p>
      ) : null}
    </div>
  );
}

function ChoiceField({
  form,
  name,
  options,
}: {
  form: UseFormReturn<RiskForm>;
  name: "retrain_trigger" | "topic_refit_trigger";
  options: [string, string][];
}) {
  const help = RISK_HELP[name];
  return (
    <div className="grid gap-1">
      <div className="flex items-center gap-2">
        <Label htmlFor={name}>{help.label}</Label>
        <HelpButton help={help} />
      </div>
      <select
        id={name}
        className="h-9 rounded-sm border border-border-strong bg-surface px-3 text-sm"
        {...form.register(name)}
      >
        {options.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
    </div>
  );
}

function Group({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <fieldset className="grid gap-4 rounded-md border border-border p-4 md:grid-cols-2">
      <legend className="px-2 font-serif text-lg font-semibold">{title}</legend>
      {children}
    </fieldset>
  );
}

function Toggle({
  form,
  name,
  label,
}: {
  form: UseFormReturn<RiskForm>;
  name: "no_boost" | "no_agreement";
  label: string;
}) {
  return (
    <label className="col-span-full flex items-center gap-2 text-sm">
      <input type="checkbox" {...form.register(name)} />
      {label}
    </label>
  );
}

function CoverageControl({ form }: { form: UseFormReturn<RiskForm> }) {
  const help = RISK_HELP.hitl_target_coverage;
  const value = form.watch("hitl_target_coverage");
  const error = form.formState.errors.hitl_target_coverage?.message;
  return (
    <div className="col-span-full grid gap-1">
      <div className="flex items-center gap-2">
        <Label htmlFor="hitl_target_coverage">{help.label}</Label>
        <HelpButton help={help} />
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <input
          type="range"
          aria-label="Cobertura objetivo (control deslizante)"
          min={help.min}
          max={help.max}
          step={help.step}
          value={Number.isFinite(value) ? value : help.min}
          onChange={(e) =>
            form.setValue("hitl_target_coverage", Number(e.target.value), {
              shouldDirty: true,
            })
          }
          className="min-w-48 flex-1"
        />
        <Input
          id="hitl_target_coverage"
          type="number"
          min={help.min}
          max={help.max}
          step={help.step}
          className="w-28"
          {...form.register("hitl_target_coverage", { setValueAs: toNumber })}
        />
        <span className="tabular text-sm text-text-muted">
          {Number.isFinite(value) ? formatPct(value, 0) : "—"} de las reseñas
          sin revisión
        </span>
      </div>
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {String(error)}
        </p>
      ) : null}
    </div>
  );
}

function PreviewPanel({ preview }: { preview: RiskPreview }) {
  return (
    <Card className="grid gap-3 p-4" aria-live="polite">
      <h3 className="font-serif text-lg font-semibold">Cambios propuestos</h3>
      {preview.errors.map((e) => (
        <Callout key={e} variant="danger">
          {e}
        </Callout>
      ))}
      {preview.warnings.map((w) => (
        <Callout key={w} variant="warning">
          {w}
        </Callout>
      ))}
      {preview.diff.length > 0 ? (
        <ul className="grid gap-1 text-sm">
          {preview.diff.map((d) => (
            <li key={d.field}>
              <code className="font-mono">{d.field}</code>:{" "}
              <span className="tabular">{String(d.before ?? "nulo")}</span> →{" "}
              <strong className="tabular">{String(d.after ?? "nulo")}</strong>
            </li>
          ))}
        </ul>
      ) : preview.errors.length === 0 ? (
        <p className="text-sm text-text-muted">Sin cambios.</p>
      ) : null}
    </Card>
  );
}

export default function RiskTab() {
  const policy = useRiskPolicy();
  const curve = useCoverageCurve();
  const save = useSaveRisk();
  const [preview, setPreview] = useState<RiskPreview | null>(null);
  const [checking, setChecking] = useState(false);
  const form = useForm<RiskForm>({
    resolver: zodResolver(riskSchema) as unknown as Resolver<RiskForm>,
  });
  const current = policy.data?.current;
  const version = current?.policy_version;
  // Al abrir y al guardar una versión nueva, el formulario vuelve a la vigente.
  // biome-ignore lint/correctness/useExhaustiveDependencies: solo cambia con la versión
  useEffect(() => {
    if (current) {
      form.reset(toForm(current));
      setPreview(null);
    }
  }, [version]);

  if (policy.isPending || curve.isPending) {
    return <Skeleton className="h-64 w-full" />;
  }
  if (policy.isError)
    return <ErrorState error={policy.error} onRetry={() => policy.refetch()} />;
  if (curve.isError)
    return <ErrorState error={curve.error} onRetry={() => curve.refetch()} />;

  const noBoost = form.watch("no_boost");
  const noAgreement = form.watch("no_agreement");
  const coverage = form.watch("hitl_target_coverage");
  const trigger = form.watch("retrain_trigger");
  const policyNow = policy.data.current;

  async function review(values: RiskForm) {
    setChecking(true);
    try {
      const changes = toChanges(values, policyNow);
      setPreview(await previewRisk(policyNow.policy_version, changes));
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "No se pudo revisar",
      );
    } finally {
      setChecking(false);
    }
  }

  const canSave =
    preview !== null &&
    preview.proposed !== null &&
    preview.errors.length === 0 &&
    preview.diff.length > 0;

  return (
    <div className="grid gap-6">
      <ChartFrame
        kicker="Apetito de riesgo"
        title="Cobertura y error esperado"
        subtitle={`Modelo ${curve.data.curve.model_version} · política vigente ${policyNow.policy_version}, desde ${formatDate(policyNow.valid_from)}`}
        howToRead={
          <p>
            Cada punto es una cobertura posible: la parte de las reseñas que se
            acepta sin revisión. Mientras más alta, menos revisión y más error
            entre lo aceptado. El rombo dorado es la cobertura vigente; al mover
            el control aparece el propuesto.
          </p>
        }
        provenance={{
          model: curve.data.curve.model_version,
          note: `calibración ${curve.data.curve.calibration_version}`,
        }}
        data={{
          columns: ["Cobertura", "Error esperado", "Revisiones por semana"],
          rows: curve.data.curve.points.map((p) => [
            formatPct(p.coverage, 0),
            formatPct(p.risk, 1),
            Math.round(p.reviews_per_week),
          ]),
        }}
      >
        <CoverageChart
          data={curve.data}
          proposed={Number.isFinite(coverage) ? coverage : null}
        />
      </ChartFrame>

      {curve.data.hitl_boosts_active.length > 0 ? (
        <Card className="p-4">
          <h3 className="mb-2 font-serif text-lg font-semibold">
            Subidas de revisión activas
          </h3>
          <ul className="grid gap-1 text-sm">
            {curve.data.hitl_boosts_active.map((b) => (
              <li key={b.boost_id}>
                <strong>{b.bank_id}</strong>
                {b.alert_id ? ` · alerta ${b.alert_id}` : ""} · cobertura{" "}
                {formatPct(b.coverage, 0)} · hasta {formatDate(b.ends_at)}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <form
        className="grid gap-5"
        onSubmit={form.handleSubmit(review)}
        noValidate
      >
        <Group title="Revisión humana">
          <CoverageControl form={form} />
          <NumberField form={form} name="hitl_weekly_cap" />
        </Group>
        <Group title="Reacción a la deriva">
          <Toggle
            form={form}
            name="no_boost"
            label="Sin subida automática de la revisión"
          />
          <NumberField
            form={form}
            name="drift_boost_coverage"
            disabled={noBoost}
          />
          <NumberField form={form} name="drift_boost_days" disabled={noBoost} />
          <NumberField
            form={form}
            name="drift_boost_weekly_cap"
            disabled={noBoost}
          />
        </Group>
        <Group title="Muestras">
          <NumberField form={form} name="monitor_sample_size" />
          <TextField form={form} name="monitor_frequency" />
          <Toggle form={form} name="no_agreement" label="Sin doble revisión" />
          <NumberField
            form={form}
            name="human_agreement_sample_size"
            disabled={noAgreement}
          />
          <TextField
            form={form}
            name="human_agreement_frequency"
            disabled={noAgreement}
          />
        </Group>
        <Group title="Avisos">
          <NumberField form={form} name="warn_correction_rate" />
          <NumberField form={form} name="warn_agreement_floor" />
          <NumberField form={form} name="agreement_sample_weekly" />
          <NumberField form={form} name="families_exact_floor" />
          <NumberField form={form} name="families_min_prevalence" />
        </Group>
        <Group title="Modelos">
          <NumberField form={form} name="retrain_kappa_floor" />
          <ChoiceField
            form={form}
            name="retrain_trigger"
            options={[
              ["manual", "Manual"],
              ["auto", "Automático"],
            ]}
          />
          {trigger === "auto" ? (
            <div className="col-span-full">
              <Callout variant="warning">
                En automático, el texto sale a Kaggle sin aprobación por
                corrida; cambiarlo es esa aprobación.
              </Callout>
            </div>
          ) : null}
          <ChoiceField
            form={form}
            name="topic_refit_trigger"
            options={[
              ["scheduled", "Programado"],
              ["manual", "Manual"],
            ]}
          />
          <TextField form={form} name="topic_refit_frequency" />
        </Group>

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="secondary" disabled={checking}>
            Revisar cambios
          </Button>
          <ConfirmWithReason
            title="Guardar una versión nueva"
            description="Se crea una versión nueva de la política con tu nombre y este motivo; la siguiente corrida la usa. Nada se edita ni se borra."
            confirmLabel="Guardar versión"
            requireWord={preview?.large_change ? CONFIRM_WORD : undefined}
            trigger={
              <Button type="button" disabled={!canSave}>
                Guardar…
              </Button>
            }
            onConfirm={(reason) => {
              if (!preview) return;
              save.mutate(
                {
                  base_version: policyNow.policy_version,
                  changes: toChanges(form.getValues(), policyNow),
                  reason,
                  confirm_word: preview.large_change ? CONFIRM_WORD : null,
                },
                {
                  onSuccess: (saved) =>
                    toast.success(`Versión ${saved.policy_version} guardada`),
                  onError: (error) => toast.error(error.message),
                },
              );
            }}
          />
        </div>
      </form>
      {preview ? <PreviewPanel preview={preview} /> : null}
    </div>
  );
}
