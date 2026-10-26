import type { ReactNode } from "react";
import type { ReviewRow } from "@/api/reviews";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { BANKS, type BankId, bankLabel } from "@/config/banks";
import { formatDate, formatPct } from "@/lib/format";
import { FAMILY_NAMES } from "@/sections/cockpit/shared";

const SENTIMENT_COLOR: Record<string, string> = {
  NEG: "--color-sent-neg",
  NEU: "--color-sent-neu",
  POS: "--color-sent-pos",
};

export function SentimentBadge({ value }: { value: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-semibold">
      <span
        aria-hidden="true"
        className="size-2.5 rounded-full"
        style={{
          background: `var(${SENTIMENT_COLOR[value] ?? "--color-sent-none"})`,
        }}
      />
      {value === "NO_PREDICTED" ? "Sin predicción" : value}
    </span>
  );
}

/** Probabilidades calibradas como una barra apilada pequeña. */
export function ProbabilityBar({ row }: { row: ReviewRow }) {
  if (row.p_neg == null || row.p_neu == null || row.p_pos == null) return null;
  const parts = [
    ["NEG", row.p_neg],
    ["NEU", row.p_neu],
    ["POS", row.p_pos],
  ] as const;
  return (
    <span
      role="img"
      aria-label={parts.map(([k, v]) => `${k} ${formatPct(v, 0)}`).join(", ")}
      className="flex h-2 w-20 overflow-hidden rounded-sm"
    >
      {parts.map(([k, v]) => (
        <span
          key={k}
          style={{
            width: `${v * 100}%`,
            background: `var(${SENTIMENT_COLOR[k]})`,
          }}
        />
      ))}
    </span>
  );
}

export function BankDot({ id }: { id: string }) {
  const style = BANKS[id as BankId];
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className="size-2.5 rounded-full"
        style={{ background: style ? `var(${style.colorVar})` : undefined }}
      />
      {bankLabel(id)}
    </span>
  );
}

export interface ExtraColumn {
  header: string;
  cell: (row: ReviewRow, index: number) => ReactNode;
}

/** Tabla de reseñas; 50 filas por página no piden virtualizar. */
export function ResultsTable({
  rows,
  onOpen,
  extra = [],
  leading = [],
  selected,
}: {
  rows: ReviewRow[];
  onOpen: (row: ReviewRow) => void;
  extra?: ExtraColumn[];
  leading?: ExtraColumn[];
  selected: string | null;
}) {
  return (
    <div className="overflow-x-auto rounded-md border border-border bg-surface">
      <Table>
        <TableHeader>
          <TableRow>
            {leading.map((c) => (
              <TableHead key={c.header}>{c.header}</TableHead>
            ))}
            <TableHead>Fecha</TableHead>
            <TableHead>Banco</TableHead>
            <TableHead>Versión</TableHead>
            <TableHead>★</TableHead>
            <TableHead>Sentimiento</TableHead>
            <TableHead>Confianza</TableHead>
            <TableHead>Familias</TableHead>
            <TableHead>Marcas</TableHead>
            <TableHead>Tópico</TableHead>
            <TableHead>HITL</TableHead>
            {extra.map((c) => (
              <TableHead key={c.header}>{c.header}</TableHead>
            ))}
            <TableHead className="min-w-72">Texto</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow
              key={`${row.bank_id}:${row.id_resena}`}
              data-selected={selected === `${row.bank_id}:${row.id_resena}`}
              className="border-t border-border data-[selected=true]:bg-green-50"
            >
              {leading.map((c) => (
                <TableCell key={c.header}>{c.cell(row, index)}</TableCell>
              ))}
              <TableCell className="whitespace-nowrap">
                {formatDate(row.fecha)}
              </TableCell>
              <TableCell className="whitespace-nowrap">
                <BankDot id={row.bank_id} />
              </TableCell>
              <TableCell>{row.version_app ?? "—"}</TableCell>
              <TableCell>{row.estrellas}</TableCell>
              <TableCell>
                <div className="grid gap-1">
                  <SentimentBadge value={row.sentiment} />
                  <ProbabilityBar row={row} />
                </div>
              </TableCell>
              <TableCell>
                {row.confidence == null ? "—" : formatPct(row.confidence, 0)}
              </TableCell>
              <TableCell>
                {row.families.length === 0
                  ? "—"
                  : row.families.map((f) => (
                      <abbr key={f} title={FAMILY_NAMES[f]} className="mr-1">
                        {f}
                      </abbr>
                    ))}
              </TableCell>
              <TableCell>
                <span className="flex gap-1">
                  {row.flag_update ? <Badge variant="warning">u</Badge> : null}
                  {row.flag_security ? <Badge variant="danger">s</Badge> : null}
                  {!row.flag_update && !row.flag_security ? "—" : null}
                </span>
              </TableCell>
              <TableCell>
                {row.topics.length === 0
                  ? "—"
                  : row.topics
                      .map((t) => t.name ?? `Tópico ${t.topic_id}`)
                      .join(", ")}
              </TableCell>
              <TableCell>{row.hitl_reviewed ? "Sí" : "No"}</TableCell>
              {extra.map((c) => (
                <TableCell key={c.header}>{c.cell(row, index)}</TableCell>
              ))}
              <TableCell>
                <button
                  type="button"
                  onClick={() => onOpen(row)}
                  className="line-clamp-2 max-w-md text-left font-serif hover:underline"
                  aria-label={`Abrir la ficha: ${row.text.slice(0, 60) || row.id_resena}`}
                >
                  {row.text || "(texto no disponible)"}
                </button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
