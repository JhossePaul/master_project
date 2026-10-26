import { Link, useSearchParams } from "react-router";
import { type AlertRow, type AlertStatus, useAlerts } from "@/api/alerts";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BANK_IDS } from "@/config/banks";
import { driftSeries, formatThreshold } from "@/config/driftSeries";
import { useGlobalFilters } from "@/filters/useGlobalFilters";
import { formatMonth } from "@/lib/format";
import { AlertStatusPill, BankDot, boostSummary, daysSince } from "./shared";

const TABS = [
  { id: "abiertas", label: "Abiertas", status: "open" },
  { id: "confirmadas", label: "Confirmadas", status: "confirmed" },
  { id: "descartadas", label: "Descartadas", status: "dismissed" },
  { id: "todas", label: "Todas", status: null },
] as const satisfies readonly {
  id: string;
  label: string;
  status: AlertStatus | null;
}[];
type TabId = (typeof TABS)[number]["id"];
const DEFAULT_TAB: TabId = "abiertas";

function isTab(value: string | null): value is TabId {
  return TABS.some((t) => t.id === value);
}

const EMPTY: Record<TabId, string> = {
  abiertas: "No hay alertas abiertas",
  confirmadas: "No hay alertas confirmadas",
  descartadas: "No hay alertas descartadas",
  todas: "Todavía no hay alertas de deriva",
};

function AlertsTable({ rows, now }: { rows: AlertRow[]; now: number }) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">Banco</TableHead>
            <TableHead scope="col">Mes</TableHead>
            <TableHead scope="col">Serie</TableHead>
            <TableHead scope="col">Valor</TableHead>
            <TableHead scope="col">Umbral</TableHead>
            <TableHead scope="col">Estado</TableHead>
            <TableHead scope="col">Días abierta</TableHead>
            <TableHead scope="col">Subida de revisión</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const series = driftSeries(row.series);
            return (
              <TableRow key={row.alert_id}>
                <TableCell>
                  <BankDot bank={row.bank_id} />
                </TableCell>
                <TableCell>{formatMonth(row.period)}</TableCell>
                <TableCell>
                  <Link
                    to={`/alertas/${encodeURIComponent(row.alert_id)}`}
                    className="font-semibold text-green-600 underline-offset-4 hover:underline"
                  >
                    {series.label}
                  </Link>
                </TableCell>
                <TableCell>{series.format(row.value)}</TableCell>
                <TableCell>
                  {formatThreshold(row.series, row.threshold)}
                </TableCell>
                <TableCell>
                  <AlertStatusPill status={row.status} />
                </TableCell>
                <TableCell>
                  {row.status === "open" ? daysSince(row.created_at, now) : "—"}
                </TableCell>
                <TableCell>{boostSummary(row.boost)}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function Results({ tab }: { tab: (typeof TABS)[number] }) {
  const [filters] = useGlobalFilters();
  const banks = filters.banks.length < BANK_IDS.length ? filters.banks : [];
  const alerts = useAlerts(tab.status, banks);
  if (alerts.isPending) {
    return <Skeleton className="h-48 w-full" aria-busy="true" />;
  }
  if (alerts.isError) {
    return <ErrorState error={alerts.error} onRetry={() => alerts.refetch()} />;
  }
  if (alerts.data.length === 0) {
    return (
      <EmptyState
        title={EMPTY[tab.id]}
        description={
          banks.length > 0
            ? "Prueba con otros bancos en el filtro de arriba."
            : "El monitor revisa las series una vez por semana."
        }
      />
    );
  }
  return <AlertsTable rows={alerts.data} now={Date.now()} />;
}

export default function AlertsInbox() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("estado");
  const tab = isTab(raw) ? raw : DEFAULT_TAB;
  const current = TABS.find((t) => t.id === tab) ?? TABS[0];

  function select(value: string) {
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        if (value === DEFAULT_TAB) next.delete("estado");
        else next.set("estado", value);
        return next;
      },
      { replace: true },
    );
  }

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold">Alertas de deriva</h1>
        <p className="mt-1 max-w-prose text-sm text-text-muted">
          El monitor semanal compara cada mes cerrado de cada banco con sus 12
          meses previos y abre una alerta cuando una serie pasa su umbral.
        </p>
      </div>
      <Tabs value={tab} onValueChange={select}>
        <TabsList aria-label="Estado de las alertas">
          {TABS.map((t) => (
            <TabsTrigger key={t.id} value={t.id}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value={tab} className="pt-4">
          <Results tab={current} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
