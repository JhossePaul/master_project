import { useState } from "react";
import {
  type EligibilityRow,
  type IngestionRunOut,
  type RunOut,
  useEligibility,
  useIngestion,
  useRuns,
} from "@/api/mlops";
import { Callout } from "@/components/Callout";
import { ChartFrame } from "@/components/ChartFrame";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { type Status, StatusPill } from "@/components/StatusPill";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { bankLabel } from "@/config/banks";
import {
  formatDateTime,
  formatInt,
  formatMonth,
  formatPct,
  formatRelative,
} from "@/lib/format";
import { SeriesChart } from "./shared";

const KINDS: Record<RunOut["kind"], string> = {
  backfill: "Backfill",
  delta: "Delta diario",
  rescoring: "Re-scoring",
  training: "Entrenamiento",
  topic_backfill: "Backfill de tópicos",
  aspect_backfill: "Backfill de familias",
  topic_refit: "Re-ajuste de tópicos",
};

const RUN_PILL: Record<RunOut["status"], Status> = {
  running: "en_curso",
  succeeded: "ok",
  failed: "fallo",
};

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`;
}

function usd(value: number | null): string {
  return value === null ? "—" : `$${value.toFixed(2)}`;
}

function dayLabel(iso: string): string {
  return iso.slice(5, 10);
}

// -- Frescura -------------------------------------------------------------

function Freshness({
  ingestion,
  delta,
  monitor,
}: {
  ingestion: string | null;
  delta: string | null;
  monitor: string | null;
}) {
  const items = [
    ["Última ingesta completa", ingestion, ""],
    ["Último delta exitoso", delta, ""],
    [
      "Último monitor",
      monitor,
      "Se infiere de las estimaciones de KPI: el monitor no registra sus corridas.",
    ],
  ] as const;
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      {items.map(([title, at, note]) => (
        <Card key={title} className="grid gap-1 p-4">
          <p className="text-sm text-text-muted">{title}</p>
          <p className="text-2xl font-semibold">{formatRelative(at)}</p>
          <p className="text-xs text-text-muted">
            {at ? formatDateTime(at) : "Sin dato"}
          </p>
          {note ? <p className="text-xs text-text-muted">{note}</p> : null}
        </Card>
      ))}
    </div>
  );
}

// -- Corridas de inferencia ------------------------------------------------

function DeltaCharts({
  runs,
  memoryLimit,
}: {
  runs: RunOut[];
  memoryLimit: number;
}) {
  const delta = runs
    .filter((r) => r.kind === "delta" && r.status !== "running")
    .sort((a, b) => a.started_at.localeCompare(b.started_at));
  if (delta.length === 0) return null;
  const label = (r: RunOut) => dayLabel(r.started_at);
  return (
    <div className="grid gap-4 lg:grid-cols-3 [&>*]:min-w-0">
      <ChartFrame
        kicker="Delta"
        title="Duración por día"
        provenance={{ note: "minutos" }}
      >
        <SeriesChart
          label="Duración del delta por día, en minutos"
          points={delta.map((r) => ({
            label: label(r),
            value: (r.duration_seconds ?? 0) / 60,
          }))}
          format={(v) => `${v.toFixed(0)} min`}
        />
      </ChartFrame>
      <ChartFrame
        kicker="Delta"
        title="Costo por día"
        provenance={{ note: "dólares de Gemini; el delta no la usa" }}
      >
        <SeriesChart
          label="Costo del delta por día, en dólares"
          points={delta.map((r) => ({
            label: label(r),
            value: r.cost_usd ?? 0,
          }))}
          format={(v) => usd(v)}
        />
      </ChartFrame>
      <ChartFrame
        kicker="Delta"
        title="Memoria pico"
        provenance={{ note: "contra los 4 GiB del Job" }}
      >
        <SeriesChart
          label="Memoria pico del delta por día contra el límite de 4 GiB"
          points={delta.map((r) => ({
            label: label(r),
            value: r.peak_memory_mib ?? 0,
          }))}
          threshold={memoryLimit}
          thresholdLabel="4 GiB"
          format={(v) => `${formatInt(v)} MiB`}
        />
      </ChartFrame>
    </div>
  );
}

function RunsTable({ runs }: { runs: RunOut[] }) {
  const [kind, setKind] = useState<string>("");
  const shown = runs.filter((r) => !kind || r.kind === kind);
  return (
    <Card className="grid gap-3 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-serif text-xl font-semibold">
          Corridas de inferencia (30 días)
        </h2>
        <div className="flex items-center gap-2">
          <Label htmlFor="mlops-kind">Tipo</Label>
          <select
            id="mlops-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="h-9 rounded-sm border border-border-strong bg-surface px-3 text-sm"
          >
            <option value="">Todas</option>
            {Object.entries(KINDS).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="max-h-96 overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Tipo</TableHead>
              <TableHead scope="col">Estado</TableHead>
              <TableHead scope="col">Inicio</TableHead>
              <TableHead scope="col">Duración</TableHead>
              <TableHead scope="col">Reseñas</TableHead>
              <TableHead scope="col">Textos</TableHead>
              <TableHead scope="col">Costo</TableHead>
              <TableHead scope="col">Memoria pico</TableHead>
              <TableHead scope="col">Versiones</TableHead>
              <TableHead scope="col">Quién y por qué</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((r) => (
              <TableRow key={`${r.run_id}|${r.status}`}>
                <TableCell>{KINDS[r.kind]}</TableCell>
                <TableCell>
                  <StatusPill status={RUN_PILL[r.status]} />
                </TableCell>
                <TableCell className="tabular">
                  {formatDateTime(r.started_at)}
                </TableCell>
                <TableCell className="tabular">
                  {formatDuration(r.duration_seconds)}
                </TableCell>
                <TableCell className="tabular">
                  {formatInt(r.reviews)}
                </TableCell>
                <TableCell className="tabular">{formatInt(r.texts)}</TableCell>
                <TableCell className="tabular">{usd(r.cost_usd)}</TableCell>
                <TableCell className="tabular">
                  {r.peak_memory_mib === null
                    ? "—"
                    : `${formatInt(r.peak_memory_mib)} MiB`}
                </TableCell>
                <TableCell className="text-xs">
                  {[r.model_version, r.topic_model_version]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </TableCell>
                <TableCell className="text-xs">
                  {r.actor ? (
                    <>
                      <span className="font-mono">{r.actor}</span>
                      {r.reason ? ` · ${r.reason}` : ""}
                    </>
                  ) : (
                    "Programada"
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Card>
  );
}

// -- Ingesta ---------------------------------------------------------------

function ingestionPill(status: string): Status {
  if (status === "COMPLETED") return "ok";
  if (status === "FAILED") return "fallo";
  return "en_curso";
}

function IngestionTable({ runs }: { runs: IngestionRunOut[] }) {
  return (
    <Card className="grid gap-3 p-5">
      <h2 className="font-serif text-xl font-semibold">
        Corridas de ingesta (30 días)
      </h2>
      <p className="text-xs text-text-muted">
        La duración sale de la primera y la última actualización de cada
        corrida. El costo no se mide: queda como «sin dato».
      </p>
      <div className="max-h-96 overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Banco</TableHead>
              <TableHead scope="col">Modo</TableHead>
              <TableHead scope="col">Estado</TableHead>
              <TableHead scope="col">Inicio</TableHead>
              <TableHead scope="col">Duración</TableHead>
              <TableHead scope="col">Extraídas</TableHead>
              <TableHead scope="col">Publicadas</TableHead>
              <TableHead scope="col">Descartadas</TableHead>
              <TableHead scope="col">Costo</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs.map((r) => (
              <TableRow key={r.run_id}>
                <TableCell>{bankLabel(r.bank_id)}</TableCell>
                <TableCell>{r.mode}</TableCell>
                <TableCell>
                  <StatusPill
                    status={ingestionPill(r.status)}
                    label={r.status}
                  />
                </TableCell>
                <TableCell className="tabular">
                  {formatDateTime(r.started_at)}
                </TableCell>
                <TableCell className="tabular">
                  {formatDuration(r.duration_seconds)}
                </TableCell>
                <TableCell className="tabular">
                  {formatInt(r.reviews_extracted)}
                </TableCell>
                <TableCell className="tabular">
                  {formatInt(r.reviews_published)}
                </TableCell>
                <TableCell className="tabular">
                  {formatInt(r.reviews_discarded)}
                </TableCell>
                <TableCell className="text-text-muted">sin dato</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Card>
  );
}

// -- No predecibles --------------------------------------------------------

const REASONS: Record<string, string> = {
  TNSS_EMPTY: "Vacía",
  TNSS_NO_TEXT_CONTENT: "Sin contenido de texto",
  TNSS_TIME_OUTLIER: "Fuera del rango de tiempo",
  TNSS_SINGLE_WORD: "Una sola palabra",
};

function Eligibility({ rows }: { rows: EligibilityRow[] }) {
  const period = rows
    .map((r) => r.period)
    .sort()
    .at(-1);
  const latest = rows.filter((r) => r.period === period);
  const banks = [...new Set(latest.map((r) => r.bank_id))].sort();
  return (
    <Card className="grid gap-3 p-5">
      <h2 className="font-serif text-xl font-semibold">
        No predecibles por motivo y banco
        {period ? ` (${formatMonth(period)})` : ""}
      </h2>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">Banco</TableHead>
            {Object.values(REASONS).map((label) => (
              <TableHead key={label} scope="col">
                {label}
              </TableHead>
            ))}
            <TableHead scope="col">Total no predecible</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {banks.map((bank) => {
            const mine = latest.filter((r) => r.bank_id === bank);
            const total = mine.reduce((sum, r) => sum + r.n, 0);
            const share = (code: string) =>
              (mine.find((r) => r.code === code)?.n ?? 0) / (total || 1);
            const blocked = Object.keys(REASONS).reduce(
              (sum, code) => sum + share(code),
              0,
            );
            return (
              <TableRow key={bank}>
                <TableCell>{bankLabel(bank)}</TableCell>
                {Object.keys(REASONS).map((code) => (
                  <TableCell key={code} className="tabular">
                    {formatPct(share(code))}
                  </TableCell>
                ))}
                <TableCell className="tabular font-semibold">
                  {formatPct(blocked)}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Card>
  );
}

export default function PipelineTab() {
  const runs = useRuns(30);
  const ingestion = useIngestion(30);
  const eligibility = useEligibility();
  return (
    <div className="grid gap-6">
      {runs.isError ? (
        <ErrorState error={runs.error} onRetry={runs.refetch} />
      ) : runs.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <>
          <section aria-label="Frescura" className="grid gap-3">
            <Freshness
              ingestion={runs.data.freshness.last_ingestion_at}
              delta={runs.data.freshness.last_delta_at}
              monitor={runs.data.freshness.last_monitor_at}
            />
          </section>
          <DeltaCharts
            runs={runs.data.runs}
            memoryLimit={runs.data.memory_limit_mib}
          />
          {runs.data.runs.length === 0 ? (
            <EmptyState title="No hubo corridas en los últimos 30 días" />
          ) : (
            <RunsTable runs={runs.data.runs} />
          )}
        </>
      )}
      {ingestion.isError ? (
        <ErrorState error={ingestion.error} onRetry={ingestion.refetch} />
      ) : ingestion.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <IngestionTable runs={ingestion.data} />
      )}
      {eligibility.isError ? (
        <ErrorState error={eligibility.error} onRetry={eligibility.refetch} />
      ) : eligibility.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <Eligibility rows={eligibility.data} />
      )}
      <Callout title="Lo que no se mide todavía">
        El monitor no escribe sus corridas en el registro (su última corrida se
        infiere de las estimaciones) y la ingesta no tiene costo: medirlo exige
        la exportación de facturación de Cloud Billing.
      </Callout>
    </div>
  );
}
