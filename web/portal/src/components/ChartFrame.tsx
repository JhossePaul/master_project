import { ChevronDown, Table2 } from "lucide-react";
import { type ReactNode, useState } from "react";
import { MethodBadge } from "@/components/MethodBadge";
import { Provenance, type ProvenanceProps } from "@/components/Provenance";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export interface TableData {
  columns: string[];
  rows: (string | number | null)[][];
}

export interface ChartFrameProps {
  kicker: string;
  title: string;
  subtitle?: string;
  howToRead?: ReactNode;
  provenance: ProvenanceProps;
  method?: "ppi" | "raw";
  data?: TableData;
  actions?: ReactNode;
  children: ReactNode;
}

export function ChartFrame({
  kicker,
  title,
  subtitle,
  howToRead,
  provenance,
  method,
  data,
  actions,
  children,
}: ChartFrameProps) {
  const [showData, setShowData] = useState(false);
  return (
    <Card className="flex flex-col gap-4 p-5">
      <header className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-neutral-800">
            {kicker}
          </p>
          <h2 className="font-serif text-xl font-semibold">{title}</h2>
          {subtitle ? (
            <p className="text-sm text-text-muted">{subtitle}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {method ? <MethodBadge method={method} /> : null}
          {actions}
        </div>
      </header>
      {howToRead ? (
        <details className="text-sm text-text-muted">
          <summary className="inline-flex cursor-pointer items-center gap-1 font-semibold text-green-600">
            <ChevronDown className="size-4" aria-hidden="true" />
            Cómo leerla
          </summary>
          <div className="mt-2 max-w-prose">{howToRead}</div>
        </details>
      ) : null}
      <div>{children}</div>
      {data ? (
        <div>
          <button
            type="button"
            aria-expanded={showData}
            onClick={() => setShowData((v) => !v)}
            className="inline-flex items-center gap-1 text-sm font-semibold text-green-600"
          >
            <Table2 className="size-4" aria-hidden="true" />
            {showData ? "Ocultar datos" : "Ver datos"}
          </button>
          {showData ? (
            <div className="mt-2 max-h-72 overflow-auto rounded-sm border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    {data.columns.map((c) => (
                      <TableHead key={c} scope="col">
                        {c}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.rows.map((row) => (
                    <TableRow key={row.map(String).join("|")}>
                      {row.map((cell, i) => (
                        <TableCell key={data.columns[i]}>
                          {cell ?? "—"}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : null}
        </div>
      ) : null}
      <Provenance {...provenance} />
    </Card>
  );
}
