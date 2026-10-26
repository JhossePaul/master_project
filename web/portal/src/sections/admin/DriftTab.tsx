import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  type Changes,
  type DriftPolicy,
  type DriftThresholds,
  type SeriesRate,
  useDriftPolicy,
  useDriftRates,
  useSaveDrift,
} from "@/api/admin";
import { ChartFrame } from "@/components/ChartFrame";
import { ConfirmWithReason } from "@/components/ConfirmWithReason";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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
import { BANK_IDS, bankLabel } from "@/config/banks";
import { DRIFT_HELP, type DriftParam } from "@/config/policyHelp";
import { formatDate } from "@/lib/format";
import { HelpButton } from "./HelpButton";

const PARAMS: DriftParam[] = [
  "baseline_months",
  "min_baseline_months",
  "min_rows_per_month",
  "entry_months",
];
const BAR_WIDTH = 140;

type Kind = "z" | "psi";
type Draft = Record<string, string>;

function seriesOf(t: DriftThresholds): { series: string; kind: Kind }[] {
  return [
    ...Object.keys(t.z ?? {}).map((series) => ({ series, kind: "z" as Kind })),
    ...Object.keys(t.psi ?? {}).map((series) => ({
      series,
      kind: "psi" as Kind,
    })),
  ].sort((a, b) => a.series.localeCompare(b.series));
}

function thresholdOf(t: DriftThresholds, kind: Kind, series: string) {
  return t[kind]?.[series] ?? null;
}

const toNumber = (text: string | undefined): number | null =>
  text === undefined || text.trim() === "" ? null : Number(text);

/** Umbrales propuestos a partir de lo escrito; igual de estructurados que los vigentes. */
export function proposedThresholds(
  current: DriftThresholds,
  draft: Draft,
): DriftThresholds {
  const out: DriftThresholds = { z: {}, psi: {} };
  for (const { series, kind } of seriesOf(current)) {
    const typed = draft[`${kind}:${series}`];
    const value =
      typed === undefined
        ? thresholdOf(current, kind, series)
        : toNumber(typed);
    (out[kind] as Record<string, number | null>)[series] =
      value !== null && Number.isNaN(value)
        ? thresholdOf(current, kind, series)
        : value;
  }
  return out;
}

function draftOf(policy: DriftPolicy): Draft {
  const out: Draft = {};
  for (const { series, kind } of seriesOf(policy.thresholds)) {
    out[`${kind}:${series}`] = String(
      thresholdOf(policy.thresholds, kind, series) ?? "",
    );
  }
  return out;
}

function sameThresholds(a: DriftThresholds, b: DriftThresholds): boolean {
  return JSON.stringify([a.z, a.psi]) === JSON.stringify([b.z, b.psi]);
}

function RateBar({ rate, max }: { rate: SeriesRate; max: number }) {
  const x = (v: number) => (v / max) * (BAR_WIDTH - 8);
  return (
    <svg
      width={BAR_WIDTH}
      height={22}
      role="img"
      aria-label={`${rate.series}: ${rate.proposed_per_year} meses de alerta al año con el umbral propuesto, ${rate.current_per_year} con el vigente${rate.reference === null ? "" : `, referencia ${rate.reference}`}`}
    >
      <rect
        x={0}
        y={4}
        width={Math.max(x(rate.proposed_per_year), 1)}
        height={14}
        fill="var(--color-green-600)"
      />
      {rate.reference !== null ? (
        <line
          x1={x(rate.reference)}
          x2={x(rate.reference)}
          y1={0}
          y2={22}
          stroke="var(--color-gold-400)"
          strokeWidth={2.5}
        >
          <title>{`Referencia: ${rate.reference}`}</title>
        </line>
      ) : null}
    </svg>
  );
}

export default function DriftTab() {
  const [bank, setBank] = useState<string>(BANK_IDS[0] ?? "");
  const policy = useDriftPolicy(bank);
  const save = useSaveDrift();
  const [draft, setDraft] = useState<Draft>({});
  const [params, setParams] = useState<Record<string, string>>({});
  const current = policy.data?.current;
  const version = current?.drift_policy_version;
  // biome-ignore lint/correctness/useExhaustiveDependencies: solo cambia con la versión
  useEffect(() => {
    if (current) {
      setDraft(draftOf(current));
      setParams(Object.fromEntries(PARAMS.map((p) => [p, String(current[p])])));
    }
  }, [version, bank]);

  const proposed = useMemo(
    () =>
      current
        ? proposedThresholds(current.thresholds, draft)
        : { z: {}, psi: {} },
    [current, draft],
  );
  const deferred = useDeferredValue(proposed);
  const rates = useDriftRates(bank, deferred);

  const changes = useMemo<Changes>(() => {
    if (!current) return {};
    const out: Changes = {};
    if (!sameThresholds(proposed, current.thresholds))
      out.thresholds = proposed;
    for (const name of PARAMS) {
      const value = toNumber(params[name]);
      if (value !== null && value !== current[name]) out[name] = value;
    }
    return out;
  }, [proposed, params, current]);

  const selector = (
    <div className="flex flex-wrap items-center gap-2">
      <Label htmlFor="drift-bank">Banco</Label>
      <select
        id="drift-bank"
        value={bank}
        onChange={(e) => setBank(e.target.value)}
        className="h-9 rounded-sm border border-border-strong bg-surface px-3 text-sm"
      >
        {BANK_IDS.map((id) => (
          <option key={id} value={id}>
            {bankLabel(id)}
          </option>
        ))}
      </select>
    </div>
  );

  if (policy.isPending) {
    return (
      <div className="grid gap-4">
        {selector}
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (policy.isError)
    return (
      <div className="grid gap-4">
        {selector}
        <ErrorState error={policy.error} onRetry={() => policy.refetch()} />
      </div>
    );

  const { template } = policy.data;
  const live = policy.data.current;
  const byRate = new Map((rates.data?.series ?? []).map((r) => [r.series, r]));
  const max = Math.max(
    1,
    ...(rates.data?.series ?? []).flatMap((r) => [
      r.proposed_per_year,
      r.current_per_year,
      r.reference ?? 0,
    ]),
  );
  const dirty = Object.keys(changes).length > 0;

  return (
    <div className="grid gap-6">
      {selector}
      <ChartFrame
        kicker="Deriva por banco"
        title={`Umbrales de ${bankLabel(bank)}`}
        subtitle={`Versión vigente ${live.drift_policy_version}, desde ${formatDate(live.valid_from)} · plantilla ${live.template_version}`}
        howToRead={
          <p>
            Cada fila es una serie que vigila el monitor. Escribe un umbral
            propuesto y la barra muestra cuántos meses al año habría alertado en
            la historia del banco; la línea dorada es la tasa del análisis de
            escala. La columna "Vigente" dice lo mismo con el umbral actual.
          </p>
        }
        provenance={{ note: `plantilla ${template.template_version}` }}
        data={{
          columns: ["Serie", "Vigente", "Plantilla", "Propuesto"],
          rows: seriesOf(live.thresholds).map(({ series, kind }) => [
            series,
            thresholdOf(live.thresholds, kind, series),
            thresholdOf(template.thresholds, kind, series),
            thresholdOf(proposed, kind, series),
          ]),
        }}
      >
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Serie</TableHead>
                <TableHead scope="col">Estadístico</TableHead>
                <TableHead scope="col">Vigente</TableHead>
                <TableHead scope="col">Plantilla</TableHead>
                <TableHead scope="col">Propuesto</TableHead>
                <TableHead scope="col">Meses de alerta al año</TableHead>
                <TableHead scope="col">Vigente (al año)</TableHead>
                <TableHead scope="col">Referencia</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {seriesOf(live.thresholds).map(({ series, kind }) => {
                const now = thresholdOf(live.thresholds, kind, series);
                const base = thresholdOf(template.thresholds, kind, series);
                const rate = byRate.get(series);
                const key = `${kind}:${series}`;
                return (
                  <TableRow key={key}>
                    <TableCell className="font-mono text-xs">
                      {series}
                    </TableCell>
                    <TableCell>{kind === "z" ? "z robusto" : "PSI"}</TableCell>
                    <TableCell className="tabular">{now ?? "—"}</TableCell>
                    <TableCell
                      className={
                        now !== base
                          ? "tabular bg-gold-100 font-semibold"
                          : "tabular"
                      }
                    >
                      {base ?? "—"}
                    </TableCell>
                    <TableCell>
                      <Input
                        aria-label={`Umbral propuesto de ${series}`}
                        type="number"
                        step="0.05"
                        min={0}
                        className="w-24"
                        value={draft[key] ?? ""}
                        onChange={(e) =>
                          setDraft((d) => ({ ...d, [key]: e.target.value }))
                        }
                      />
                    </TableCell>
                    <TableCell>
                      {rate ? (
                        <span className="flex items-center gap-2">
                          <RateBar rate={rate} max={max} />
                          <span className="tabular">
                            {rate.proposed_per_year}
                          </span>
                        </span>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell className="tabular">
                      {rate ? rate.current_per_year : "—"}
                    </TableCell>
                    <TableCell className="tabular">
                      {rate?.reference ?? "—"}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
        <p className="mt-2 text-xs text-text-muted">
          <HelpButton help={DRIFT_HELP.thresholds} /> Un umbral en blanco deja
          la serie sin alertar. Los meses son los que el monitor evaluó con la
          política vigente.
        </p>
      </ChartFrame>

      <Card className="grid gap-4 p-5 md:grid-cols-2">
        <h3 className="col-span-full font-serif text-lg font-semibold">
          Entrada de los bancos
        </h3>
        {PARAMS.map((name) => {
          const help = DRIFT_HELP[name];
          return (
            <div key={name} className="grid gap-1">
              <div className="flex items-center gap-2">
                <Label htmlFor={`param-${name}`}>{help.label}</Label>
                <HelpButton help={help} />
              </div>
              <Input
                id={`param-${name}`}
                type="number"
                min={help.min}
                step={help.step}
                value={params[name] ?? ""}
                onChange={(e) =>
                  setParams((p) => ({ ...p, [name]: e.target.value }))
                }
              />
              <p className="text-xs text-text-muted">
                Plantilla: {template[name]} {help.unit}
              </p>
            </div>
          );
        })}
      </Card>

      <div>
        <ConfirmWithReason
          title={`Guardar una versión nueva para ${bankLabel(bank)}`}
          description="Se crea una versión nueva de la política de este banco con tu nombre y este motivo; el siguiente monitor la usa."
          confirmLabel="Guardar versión"
          trigger={<Button disabled={!dirty}>Guardar…</Button>}
          onConfirm={(reason) =>
            save.mutate(
              {
                bank,
                base_version: live.drift_policy_version,
                changes,
                reason,
              },
              {
                onSuccess: (saved) =>
                  toast.success(
                    `Versión ${saved.drift_policy_version} guardada`,
                  ),
                onError: (error) => toast.error(error.message),
              },
            )
          }
        />
      </div>
    </div>
  );
}
