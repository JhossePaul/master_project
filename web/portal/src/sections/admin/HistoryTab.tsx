import { useState } from "react";
import { useOutletContext } from "react-router";
import { useDriftPolicy, useRiskPolicy } from "@/api/admin";
import type { Me } from "@/auth/roles";
import { ErrorState } from "@/components/ErrorState";
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
import { BANK_IDS, bankLabel } from "@/config/banks";
import { formatDateTime } from "@/lib/format";

const RISK = "riesgo";
const HASH_PREFIX = 8;

interface Version {
  id: string;
  valid_from: string;
  set_by_hash: string;
  reason: string;
  row: Record<string, unknown>;
}

/** Aplana un objeto a `campo.subcampo → valor` para compararlo. */
export function flatten(
  value: unknown,
  prefix = "",
  out: Record<string, unknown> = {},
): Record<string, unknown> {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    for (const [key, inner] of Object.entries(value)) {
      flatten(inner, prefix ? `${prefix}.${key}` : key, out);
    }
  } else {
    out[prefix] = value;
  }
  return out;
}

const BOOKKEEPING = new Set([
  "policy_version",
  "drift_policy_version",
  "valid_from",
  "set_by_hash",
  "reason",
]);

export function compareVersions(a: Version, b: Version) {
  const x = flatten(a.row);
  const y = flatten(b.row);
  return [...new Set([...Object.keys(x), ...Object.keys(y)])]
    .filter((field) => !BOOKKEEPING.has(field))
    .filter((field) => JSON.stringify(x[field]) !== JSON.stringify(y[field]))
    .sort()
    .map((field) => ({ field, before: x[field], after: y[field] }));
}

export function whoIs(hash: string, me: Me): string {
  return hash === me.actor_hash ? "tú" : hash.slice(0, HASH_PREFIX);
}

const show = (v: unknown) =>
  v === null || v === undefined ? "nulo" : String(v);

export default function HistoryTab() {
  const me = useOutletContext<Me>();
  const [kind, setKind] = useState<string>(RISK);
  const [picked, setPicked] = useState<string[]>([]);
  const risk = useRiskPolicy();
  const drift = useDriftPolicy(kind === RISK ? (BANK_IDS[0] ?? "") : kind);
  const source = kind === RISK ? risk : drift;

  const versions: Version[] =
    kind === RISK
      ? (risk.data?.history ?? []).map((p) => ({
          id: p.policy_version,
          valid_from: p.valid_from,
          set_by_hash: p.set_by_hash,
          reason: p.reason,
          row: p as unknown as Record<string, unknown>,
        }))
      : (drift.data?.history ?? []).map((p) => ({
          id: p.drift_policy_version,
          valid_from: p.valid_from,
          set_by_hash: p.set_by_hash,
          reason: p.reason,
          row: p as unknown as Record<string, unknown>,
        }));
  const ordered = [...versions].reverse();

  function toggle(id: string) {
    setPicked((now) =>
      now.includes(id) ? now.filter((v) => v !== id) : [...now, id].slice(-2),
    );
  }

  const [first, second] = picked
    .map((id) => versions.find((v) => v.id === id))
    .filter((v): v is Version => v !== undefined)
    .sort((a, b) => a.valid_from.localeCompare(b.valid_from));
  const diff = first && second ? compareVersions(first, second) : null;

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-2">
        <Label htmlFor="history-kind">Política</Label>
        <select
          id="history-kind"
          value={kind}
          onChange={(e) => {
            setKind(e.target.value);
            setPicked([]);
          }}
          className="h-9 rounded-sm border border-border-strong bg-surface px-3 text-sm"
        >
          <option value={RISK}>Apetito de riesgo (global)</option>
          {BANK_IDS.map((id) => (
            <option key={id} value={id}>
              Deriva · {bankLabel(id)}
            </option>
          ))}
        </select>
      </div>
      {source.isPending ? <Skeleton className="h-48 w-full" /> : null}
      {source.isError ? (
        <ErrorState error={source.error} onRetry={() => source.refetch()} />
      ) : null}
      {source.data ? (
        <Card className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Comparar</TableHead>
                <TableHead scope="col">Versión</TableHead>
                <TableHead scope="col">Desde</TableHead>
                <TableHead scope="col">Quién</TableHead>
                <TableHead scope="col">Motivo</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {ordered.map((v) => (
                <TableRow key={v.id}>
                  <TableCell>
                    <input
                      type="checkbox"
                      aria-label={`Comparar ${v.id}`}
                      checked={picked.includes(v.id)}
                      onChange={() => toggle(v.id)}
                    />
                  </TableCell>
                  <TableCell className="font-mono text-xs">{v.id}</TableCell>
                  <TableCell>{formatDateTime(v.valid_from)}</TableCell>
                  <TableCell>{whoIs(v.set_by_hash, me)}</TableCell>
                  <TableCell>{v.reason}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      ) : null}
      {diff && first && second ? (
        <Card className="grid gap-2 p-4" aria-live="polite">
          <h3 className="font-serif text-lg font-semibold">
            {first.id} → {second.id}
          </h3>
          {diff.length === 0 ? (
            <p className="text-sm text-text-muted">
              Las dos versiones tienen los mismos parámetros.
            </p>
          ) : (
            <ul className="grid gap-1 text-sm">
              {diff.map((d) => (
                <li key={d.field}>
                  <code className="font-mono">{d.field}</code>:{" "}
                  <span className="tabular">{show(d.before)}</span> →{" "}
                  <strong className="tabular">{show(d.after)}</strong>
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : (
        <p className="text-sm text-text-muted">
          Marca dos versiones para ver qué cambió entre ellas.
        </p>
      )}
    </div>
  );
}
