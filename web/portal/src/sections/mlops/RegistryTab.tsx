import { scaleLinear } from "d3-scale";
import { useId, useState } from "react";
import { toast } from "sonner";
import { useMe } from "@/api/me";
import {
  type Action,
  type ActionState,
  type CalibrationOut,
  type ModelOut,
  type PromotionCheckOut,
  type ReliabilityBin,
  useCalibration,
  useMlopsCurve,
  useModels,
  useRunAction,
} from "@/api/mlops";
import { hasRole } from "@/auth/roles";
import { Axis, DEFAULT_MARGIN, GridLines } from "@/charts/primitives";
import { Callout } from "@/components/Callout";
import { ChartFrame } from "@/components/ChartFrame";
import { ConfirmWithReason } from "@/components/ConfirmWithReason";
import { ErrorState } from "@/components/ErrorState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  formatDate,
  formatDateTime,
  formatKappa,
  formatPct,
} from "@/lib/format";
import { CoverageChart } from "@/sections/admin/CoverageChart";

const FORCE_WORD = "FORZAR";

type Verdict = PromotionCheckOut["verdict"];

const VERDICT: Record<
  Verdict,
  { label: string; variant: "ok" | "warning" | "danger" }
> = {
  better: { label: "mejor", variant: "ok" },
  tie: { label: "empate", variant: "warning" },
  worse: { label: "peor", variant: "danger" },
};

function signed(x: number, digits = 3): string {
  const text = Math.abs(x).toFixed(digits);
  return x < 0 ? `−${text}` : x > 0 ? `+${text}` : text;
}

// -- Línea de tiempo ------------------------------------------------------

interface TimelineEvent {
  version: string;
  label: string;
  at: string;
  actor: string | null;
  reason: string | null;
}

export function timeline(models: ModelOut[]): TimelineEvent[] {
  const events: TimelineEvent[] = [];
  for (const model of models) {
    let promoted = false;
    for (const step of model.history) {
      const label =
        step.status === "candidate"
          ? "Registrada como candidata"
          : step.status === "retired"
            ? "Retirada"
            : promoted
              ? "Rollback: vuelve a ser la vigente"
              : "Promovida";
      if (step.status === "promoted") promoted = true;
      events.push({
        version: model.model_version,
        label,
        at: step.at,
        actor: step.actor,
        reason: step.reason,
      });
    }
  }
  return events.sort((a, b) => b.at.localeCompare(a.at));
}

function Timeline({ models }: { models: ModelOut[] }) {
  const events = timeline(models);
  return (
    <ol className="grid gap-3 border-l-2 border-border pl-4">
      {events.map((e) => (
        <li key={`${e.version}|${e.at}|${e.label}`} className="text-sm">
          <p>
            <strong>{e.version}</strong> · {e.label}
          </p>
          <p className="text-text-muted">
            {formatDateTime(e.at)}
            {e.actor ? ` · ${e.actor}` : ""}
            {e.reason ? ` · ${e.reason}` : ""}
          </p>
        </li>
      ))}
    </ol>
  );
}

// -- Regla de promoción ---------------------------------------------------

const DOT_WIDTH = 200;
const DOT_RANGE = 0.06;

/** Una diferencia con su intervalo alrededor de 0 (línea vertical). */
function DiffDot({
  label,
  diff,
  lo,
  hi,
}: {
  label: string;
  diff: number;
  lo: number;
  hi: number;
}) {
  const range = Math.max(DOT_RANGE, Math.abs(lo), Math.abs(hi));
  const x = scaleLinear()
    .domain([-range, range])
    .range([8, DOT_WIDTH - 8]);
  return (
    <svg
      role="img"
      aria-label={`${label}: ${signed(diff)}, intervalo de ${signed(lo)} a ${signed(hi)}`}
      width={DOT_WIDTH}
      height={28}
    >
      <line
        x1={x(0)}
        x2={x(0)}
        y1={2}
        y2={26}
        stroke="var(--color-neutral-500)"
        strokeDasharray="2 3"
      />
      <line
        x1={x(lo)}
        x2={x(hi)}
        y1={14}
        y2={14}
        stroke="var(--color-neutral-700)"
        strokeWidth={2}
      />
      <circle cx={x(diff)} cy={14} r={5} fill="var(--color-brand)" />
    </svg>
  );
}

function CandidateRow({ model }: { model: ModelOut }) {
  const check = model.check;
  return (
    <TableRow>
      <TableCell className="font-semibold">{model.model_version}</TableCell>
      <TableCell className="tabular">{formatKappa(model.kappa_dev)}</TableCell>
      <TableCell>
        {check ? (
          <div className="grid gap-0.5">
            <DiffDot
              label={`Diferencia de κ de ${model.model_version}`}
              diff={check.kappa_diff}
              lo={check.kappa_ci_low}
              hi={check.kappa_ci_high}
            />
            <span className="tabular text-xs text-text-muted">
              {signed(check.kappa_diff)} [{signed(check.kappa_ci_low)},{" "}
              {signed(check.kappa_ci_high)}]
            </span>
          </div>
        ) : (
          <span className="text-sm text-text-muted">Sin re-scoring</span>
        )}
      </TableCell>
      <TableCell>
        {check ? (
          <div className="grid gap-0.5">
            <DiffDot
              label={`Diferencia de macro-F1 de ${model.model_version}`}
              diff={check.macro_f1_diff}
              lo={check.macro_f1_ci_low}
              hi={check.macro_f1_ci_high}
            />
            <span className="tabular text-xs text-text-muted">
              {signed(check.macro_f1_diff)} [{signed(check.macro_f1_ci_low)},{" "}
              {signed(check.macro_f1_ci_high)}]
            </span>
          </div>
        ) : null}
      </TableCell>
      <TableCell>
        {check ? (
          <Badge variant={VERDICT[check.verdict].variant}>
            {VERDICT[check.verdict].label}
          </Badge>
        ) : (
          "—"
        )}
      </TableCell>
    </TableRow>
  );
}

// -- Confiabilidad --------------------------------------------------------

const RELIABILITY_SIZE = 280;
const RELIABILITY_MARGIN = { ...DEFAULT_MARGIN, right: 12, bottom: 34 };

function ReliabilityDiagram({
  title,
  bins,
}: {
  title: string;
  bins: ReliabilityBin[];
}) {
  const m = RELIABILITY_MARGIN;
  const inner = RELIABILITY_SIZE - m.left - m.right;
  const height = RELIABILITY_SIZE - m.top - m.bottom;
  const x = scaleLinear().domain([0, 1]).range([0, inner]);
  const y = scaleLinear().domain([0, 1]).range([height, 0]);
  return (
    <figure className="grid gap-1">
      <svg
        role="img"
        aria-label={`${title}: acierto por cubeta de confianza`}
        width={RELIABILITY_SIZE}
        height={RELIABILITY_SIZE}
      >
        <g transform={`translate(${m.left},${m.top})`}>
          <GridLines scale={y} width={inner} />
          {bins.map((b) => (
            <rect
              key={b.low}
              x={x(b.low) + 1}
              y={y(b.accuracy)}
              width={Math.max(x(b.high) - x(b.low) - 2, 1)}
              height={height - y(b.accuracy)}
              fill="var(--color-green-300)"
            >
              <title>
                {`Confianza ${formatPct(b.low, 0)}–${formatPct(b.high, 0)}: acierto ${formatPct(b.accuracy)} (n = ${b.n})`}
              </title>
            </rect>
          ))}
          <line
            x1={x(0)}
            y1={y(0)}
            x2={x(1)}
            y2={y(1)}
            stroke="var(--color-gold-600)"
            strokeWidth={1.5}
            strokeDasharray="6 4"
          />
          <g transform={`translate(0,${height})`}>
            <Axis
              scale={x}
              orientation="bottom"
              length={inner}
              format={(v) => formatPct(Number(v), 0)}
              label="Confianza"
            />
          </g>
          <Axis
            scale={y}
            orientation="left"
            length={height}
            format={(v) => formatPct(Number(v), 0)}
          />
        </g>
      </svg>
      <figcaption className="text-center text-sm font-semibold">
        {title}
      </figcaption>
    </figure>
  );
}

function CalibrationBlock({ version }: { version: string }) {
  const calibration = useCalibration(version);
  if (calibration.isPending) return <Skeleton className="h-64 w-full" />;
  if (calibration.isError)
    return (
      <p className="text-sm text-text-muted">
        No hay una calibración guardada para {version}: se genera al entrenarla.
      </p>
    );
  const c: CalibrationOut = calibration.data;
  return (
    <div className="grid gap-3">
      <p className="text-sm">
        Temperatura:{" "}
        <strong className="tabular">
          {c.temperature === null ? "—" : c.temperature.toFixed(4)}
        </strong>
        {c.ece_raw !== null && c.ece_calibrated !== null ? (
          <span className="tabular text-text-muted">
            {" "}
            · ECE {c.ece_raw.toFixed(3)} → {c.ece_calibrated.toFixed(3)}
          </span>
        ) : null}
      </p>
      <div className="flex flex-wrap gap-6">
        <ReliabilityDiagram title="Antes de la temperatura" bins={c.raw} />
        <ReliabilityDiagram
          title="Después de la temperatura"
          bins={c.calibrated}
        />
      </div>
      <p className="text-xs text-text-muted">
        Fuente:{" "}
        {c.source === "manifest"
          ? "manifiesto de entrenamiento"
          : "experimentos"}{" "}
        ({c.source_label}). Si las barras siguen la diagonal dorada, la
        confianza es honesta.
      </p>
    </div>
  );
}

// -- Acciones -------------------------------------------------------------

interface ActionCopy {
  label: string;
  title: string;
  description: string;
  variant: "primary" | "secondary" | "danger";
}

const COPY: Record<Action, ActionCopy> = {
  retrain: {
    label: "Reentrenar",
    title: "Reentrenar el modelo",
    description:
      "Entrena una candidata nueva en Kaggle desde el modelo base. Cuesta unos $1 de Gemini (tope $2) y el texto sale a Kaggle. No la promueve.",
    variant: "primary",
  },
  rescore: {
    label: "Re-scoring",
    title: "Re-puntuar la candidata",
    description:
      "Predice el histórico y el oro con la candidata en Kaggle (el texto sale a Kaggle) y guarda la regla de promoción.",
    variant: "secondary",
  },
  promote: {
    label: "Promover",
    title: "Promover la candidata",
    description:
      "La candidata pasa a ser la vigente: cambian las predicciones, la curva y la política de riesgo. Revisaste el veredicto, la curva y la calibración de arriba.",
    variant: "primary",
  },
  rollback: {
    label: "Rollback",
    title: "Volver a una versión anterior",
    description:
      "La versión que estuvo promovida vuelve a ser la vigente, con su curva y su temperatura.",
    variant: "secondary",
  },
  topics_refit: {
    label: "Re-ajustar tópicos",
    title: "Re-ajustar el modelo de tópicos",
    description:
      "Ajusta una versión nueva con la muestra de negativas de los últimos 12 meses. No usa Gemini ni el texto sale de GCP. La versión asigna cuando se cura.",
    variant: "secondary",
  },
};

function ActionButton({
  action,
  state,
  version,
  admin,
  forced,
}: {
  action: Action;
  state: ActionState;
  version: string | null;
  admin: boolean;
  /** Promover con veredicto `worse`: pide escribir FORZAR. */
  forced?: boolean;
}) {
  const run = useRunAction();
  const hint = useId();
  const copy = COPY[action];
  const label = version ? `${copy.label} ${version}` : copy.label;
  const blocked = !admin || !state.enabled;
  const why = !admin
    ? "Solo el rol administrador lanza acciones."
    : state.enabled
      ? null
      : state.reason;
  return (
    <div className="grid content-start gap-1">
      {blocked ? (
        <Button variant="secondary" disabled aria-describedby={hint}>
          {label}
        </Button>
      ) : (
        <ConfirmWithReason
          title={`${copy.title}${version ? `: ${version}` : ""}`}
          description={`${copy.description}${state.reason ? ` ${state.reason}.` : ""}`}
          confirmLabel={copy.label}
          requireWord={forced ? FORCE_WORD : undefined}
          onConfirm={(reason) =>
            run.mutate(
              {
                action,
                reason,
                model_version: version,
                confirm_word: forced ? FORCE_WORD : null,
              },
              {
                onSuccess: (out) =>
                  toast.success(`Se lanzó ${out.job}: ${out.operation}`),
                onError: (error) => toast.error(error.message),
              },
            )
          }
          trigger={<Button variant={copy.variant}>{label}</Button>}
        />
      )}
      {why ? (
        <p id={hint} className="max-w-xs text-xs text-text-muted">
          {why}
        </p>
      ) : state.reason ? (
        <p className="max-w-xs text-xs text-text-muted">{state.reason}</p>
      ) : null}
    </div>
  );
}

function find(states: ActionState[], action: Action): ActionState {
  return (
    states.find((s) => s.action === action) ?? {
      action,
      enabled: false,
      reason: "No disponible",
    }
  );
}

// -- Pestaña --------------------------------------------------------------

function defaultVersion(models: ModelOut[]): string | null {
  const candidates = models.filter((m) => m.status === "candidate");
  return (
    candidates.find((m) => m.check)?.model_version ??
    candidates[0]?.model_version ??
    models.find((m) => m.current)?.model_version ??
    null
  );
}

function CandidateCurve({ version }: { version: string }) {
  const curve = useMlopsCurve(version);
  if (curve.isPending) return <Skeleton className="h-64 w-full" />;
  if (curve.isError)
    return (
      <p className="text-sm text-text-muted">
        La candidata todavía no tiene curva de cobertura y riesgo.
      </p>
    );
  return (
    <ChartFrame
      kicker="Curva nueva"
      title={`Cobertura y riesgo de ${version}`}
      provenance={{
        model: version,
        note: `calculada el ${formatDate(curve.data.curve.computed_at)}`,
      }}
    >
      <CoverageChart data={curve.data} proposed={null} />
    </ChartFrame>
  );
}

export default function RegistryTab() {
  const models = useModels();
  const me = useMe();
  const [picked, setPicked] = useState<string | null>(null);
  if (models.isError)
    return <ErrorState error={models.error} onRetry={models.refetch} />;
  if (models.isPending) return <Skeleton className="h-64 w-full" />;
  const admin = hasRole(me.data, "administrador");
  const { models: rows, actions } = models.data;
  const candidates = rows.filter((m) => m.status === "candidate");
  const selectedName = picked ?? defaultVersion(rows);
  const selected = rows.find((m) => m.model_version === selectedName) ?? null;
  const worse = selected?.check?.verdict === "worse";
  return (
    <div className="grid gap-6">
      <Card className="grid gap-3 p-5">
        <h2 className="font-serif text-xl font-semibold">
          Versiones del modelo
        </h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Versión</TableHead>
              <TableHead scope="col">Estado</TableHead>
              <TableHead scope="col">κ en el oro dev</TableHead>
              <TableHead scope="col">ECE</TableHead>
              <TableHead scope="col">AURC</TableHead>
              <TableHead scope="col">Temperatura</TableHead>
              <TableHead scope="col">Datos (hash)</TableHead>
              <TableHead scope="col">Licencia</TableHead>
              <TableHead scope="col">
                <span className="sr-only">Acciones sobre la versión</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((m) => (
              <TableRow key={m.model_version}>
                <TableCell className="font-semibold">
                  {m.model_version}
                </TableCell>
                <TableCell>
                  {m.current ? (
                    <Badge variant="ok">vigente</Badge>
                  ) : m.status === "candidate" ? (
                    <Badge variant="info">candidata</Badge>
                  ) : (
                    <Badge variant="info">retirada</Badge>
                  )}
                </TableCell>
                <TableCell className="tabular">
                  {formatKappa(m.kappa_dev)}
                </TableCell>
                <TableCell className="tabular">
                  {m.ece_dev === null ? "—" : m.ece_dev.toFixed(3)}
                </TableCell>
                <TableCell className="tabular">
                  {m.aurc_dev === null ? "—" : m.aurc_dev.toFixed(3)}
                </TableCell>
                <TableCell className="tabular">
                  {m.calibration_t.toFixed(2)}
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {m.training_data_hash?.slice(0, 8) ?? "—"}
                </TableCell>
                <TableCell>{m.license}</TableCell>
                <TableCell>
                  {m.current ? null : (
                    <Button
                      size="sm"
                      variant={
                        m.model_version === selectedName
                          ? "primary"
                          : "secondary"
                      }
                      aria-pressed={m.model_version === selectedName}
                      aria-label={`${m.model_version === selectedName ? "Elegida" : "Elegir"} ${m.model_version}`}
                      onClick={() => setPicked(m.model_version)}
                    >
                      {m.model_version === selectedName ? "Elegida" : "Elegir"}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Card className="grid gap-3 p-5">
        <h2 className="font-serif text-xl font-semibold">Historia</h2>
        <Timeline models={rows} />
      </Card>

      <Card className="grid gap-3 p-5">
        <h2 className="font-serif text-xl font-semibold">
          Candidatas y regla de promoción
        </h2>
        <p className="max-w-prose text-sm text-text-muted">
          Elige la versión en la tabla de arriba. Las diferencias son candidata
          menos vigente en el oro dev, con su intervalo del 95 %. Peor: algún
          intervalo queda entero bajo 0. Mejor: alguno queda entero sobre 0.
          Empate: en cualquier otro caso.
        </p>
        {candidates.length === 0 ? (
          <p className="text-sm text-text-muted">No hay candidatas.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Candidata</TableHead>
                <TableHead scope="col">κ en el oro dev</TableHead>
                <TableHead scope="col">Diferencia de κ</TableHead>
                <TableHead scope="col">Diferencia de macro-F1</TableHead>
                <TableHead scope="col">Veredicto</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {candidates.map((m) => (
                <CandidateRow key={m.model_version} model={m} />
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      {selected ? (
        <Card className="grid gap-4 p-5">
          <h2 className="font-serif text-xl font-semibold">
            Calibración y curva de {selected.model_version}
          </h2>
          <CalibrationBlock version={selected.model_version} />
          {selected.status === "candidate" ? (
            <CandidateCurve version={selected.model_version} />
          ) : null}
        </Card>
      ) : null}

      <Card className="grid gap-4 p-5">
        <h2 className="font-serif text-xl font-semibold">Acciones</h2>
        {worse ? (
          <Callout variant="danger" title="El candidato es peor que el vigente">
            Para promoverlo hay que escribir {FORCE_WORD}; la promoción forzada
            queda registrada con tu nombre y tu motivo.
          </Callout>
        ) : null}
        <div className="flex flex-wrap items-start gap-6">
          {selected ? (
            <>
              <ActionButton
                action="rescore"
                state={find(selected.actions, "rescore")}
                version={selected.model_version}
                admin={admin}
              />
              <ActionButton
                action="promote"
                state={find(selected.actions, "promote")}
                version={selected.model_version}
                admin={admin}
                forced={worse}
              />
              <ActionButton
                action="rollback"
                state={find(selected.actions, "rollback")}
                version={selected.model_version}
                admin={admin}
              />
            </>
          ) : null}
          <ActionButton
            action="retrain"
            state={find(actions, "retrain")}
            version={null}
            admin={admin}
          />
          <ActionButton
            action="topics_refit"
            state={find(actions, "topics_refit")}
            version={null}
            admin={admin}
          />
        </div>
      </Card>
    </div>
  );
}
