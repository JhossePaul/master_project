import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { useRef } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";
import {
  type AlertEventOut,
  type AlertStatus,
  type AlertDetail as Detail,
  useAlert,
  useAlertEvent,
} from "@/api/alerts";
import { ApiError } from "@/api/client";
import { Callout } from "@/components/Callout";
import { ChartFrame } from "@/components/ChartFrame";
import { ConfirmWithReason } from "@/components/ConfirmWithReason";
import { ErrorState } from "@/components/ErrorState";
import { explorerUrl } from "@/components/ExplorerLink";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { BANKS, type BankId, bankLabel } from "@/config/banks";
import { driftSeries, formatThreshold } from "@/config/driftSeries";
import { formatDate, formatDateTime, formatMonth } from "@/lib/format";
import { DriftChart } from "./DriftChart";
import { AlertStatusPill, BankDot, formatCoverage } from "./shared";

interface Action {
  status: AlertStatus;
  label: string;
  title: string;
  description: string;
  variant: "primary" | "secondary" | "danger";
}

const NOTE_HELP =
  "Escribe qué viste y qué decidiste, sin copiar el texto de las reseñas: los nombres y datos personales se reemplazan antes de guardar.";

const CONFIRM: Action = {
  status: "confirmed",
  label: "Confirmar",
  title: "Confirmar la deriva",
  description: `La deriva es real. ${NOTE_HELP}`,
  variant: "primary",
};
const DISMISS: Action = {
  status: "dismissed",
  label: "Descartar",
  title: "Descartar la alerta",
  description: `Es una falsa alarma o ya está explicada. Si la subida de revisión sigue activa, se cierra. ${NOTE_HELP}`,
  variant: "secondary",
};
const REOPEN: Action = {
  status: "open",
  label: "Reabrir",
  title: "Reabrir la alerta",
  description: `Vuelve a la bandeja de abiertas. ${NOTE_HELP}`,
  variant: "secondary",
};

/** Las transiciones que permite la API desde cada estado. */
const ACTIONS: Record<AlertStatus, Action[]> = {
  open: [CONFIRM, DISMISS],
  confirmed: [DISMISS, REOPEN],
  dismissed: [REOPEN],
};

const END_REASON = {
  expired: "terminó su plazo",
  alert_closed: "se cerró al descartar la alerta",
  manual: "se cerró a mano",
} as const;

function BoostCard({ boost }: { boost: Detail["alert"]["boost"] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">Subida de revisión</CardTitle>
      </CardHeader>
      <CardContent className="text-sm">
        {!boost ? (
          <p>
            Esta alerta no tiene subida de revisión: la política de riesgo
            vigente no la configura, así que solo se registró y se avisó.
          </p>
        ) : boost.active ? (
          <p>
            Mientras dure (hasta el {formatDate(boost.ends_at)}), la cobertura
            de este banco baja a{" "}
            <strong className="tabular">
              {formatCoverage(boost.coverage)}
            </strong>
            : se revisan más reseñas.
          </p>
        ) : (
          <p>
            La subida de revisión ya no está activa
            {boost.ended_reason
              ? `: ${END_REASON[boost.ended_reason]}`
              : ` desde el ${formatDate(boost.ends_at)}`}
            .
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function EventsCard({ events }: { events: AlertEventOut[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">Historia</CardTitle>
      </CardHeader>
      <CardContent>
        <ol className="grid gap-4">
          {events.map((event) => (
            <li key={event.event_id} className="grid gap-1 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <AlertStatusPill status={event.status} />
                <span className="tabular text-text-muted">
                  {formatDateTime(event.at)}
                </span>
                <span className="text-text-muted">
                  {event.actor ? (
                    <>
                      por <code className="font-mono">{event.actor}</code>
                    </>
                  ) : (
                    "por el monitor"
                  )}
                </span>
                {event.ticket ? (
                  <span>
                    Ticket <strong>{event.ticket}</strong>
                  </span>
                ) : null}
              </div>
              {event.note ? <p className="max-w-prose">{event.note}</p> : null}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function Actions({ detail }: { detail: Detail }) {
  const alertId = detail.alert.alert_id;
  const mutation = useAlertEvent(alertId);
  // Un reintento del mismo envío reutiliza el id: la API no lo duplica.
  const attempt = useRef<{ key: string; id: string } | null>(null);

  function submit(status: AlertStatus, note: string, ticket?: string) {
    const key = `${alertId}|${status}|${note}|${ticket ?? ""}`;
    if (attempt.current?.key !== key)
      attempt.current = { key, id: crypto.randomUUID() };
    mutation.mutate(
      {
        event_id: attempt.current.id,
        status,
        note,
        ticket: ticket || null,
      },
      {
        onSuccess: () => {
          attempt.current = null;
          toast.success("Guardado");
        },
      },
    );
  }

  const error = mutation.error instanceof ApiError ? mutation.error : null;
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap gap-2">
        {ACTIONS[detail.alert.status].map((action) => (
          <ConfirmWithReason
            key={action.status}
            title={action.title}
            description={action.description}
            confirmLabel={action.label}
            withTicket
            onConfirm={(note, ticket) => submit(action.status, note, ticket)}
            trigger={
              <Button variant={action.variant} disabled={mutation.isPending}>
                {action.label}
              </Button>
            }
          />
        ))}
        <Button asChild variant="secondary" className="ml-auto">
          <Link
            to={explorerUrl({
              banks: [detail.explorer.bank_id],
              from: detail.explorer.start,
              to: detail.explorer.end,
            })}
          >
            Abrir en el Explorador
            <ArrowUpRight aria-hidden="true" />
          </Link>
        </Button>
      </div>
      {mutation.isError ? (
        <Callout
          variant="danger"
          title={
            error?.status === 409
              ? "La alerta cambió mientras la mirabas"
              : "No se guardó"
          }
        >
          {error?.message ?? "Inténtalo de nuevo."}
          {error?.status === 409
            ? " Ya se actualizó la pantalla; revisa el estado y vuelve a intentarlo."
            : null}
        </Callout>
      ) : null}
    </div>
  );
}

function Charts({ detail }: { detail: Detail }) {
  const { alert, series } = detail;
  const info = driftSeries(alert.series);
  const color = BANKS[alert.bank_id as BankId]?.colorVar ?? "--color-bank-all";
  const threshold = formatThreshold(alert.series, alert.threshold);
  const provenance = {
    policy: alert.drift_policy_version,
    note: "Serie mensual del monitor de deriva",
  };
  const table = {
    columns: ["Mes", "Valor", "Línea base", "z", "PSI", "Umbral", "Alerta"],
    rows: series.map((p) => [
      formatMonth(p.period),
      info.format(p.value),
      p.baseline === null ? null : info.format(p.baseline),
      p.z === null ? null : p.z.toFixed(2),
      p.psi === null ? null : p.psi.toFixed(3),
      p.threshold === null ? null : formatThreshold(alert.series, p.threshold),
      p.alert ? "sí" : "no",
    ]),
  };
  const isZ = info.kind === "z";
  return (
    <div className="grid gap-6">
      <ChartFrame
        kicker="Últimos 24 meses"
        title={info.label}
        subtitle={`${bankLabel(alert.bank_id)} · alerta de ${formatMonth(alert.period)}`}
        howToRead={
          isZ
            ? "La línea gris punteada es la línea base: la mediana de los 12 meses previos. El mes resaltado es el de la alerta; el umbral está en la gráfica del z, de abajo."
            : "La línea dorada discontinua es el umbral del PSI. El mes resaltado es el de la alerta."
        }
        provenance={provenance}
        data={table}
      >
        <DriftChart
          label={`${info.label} de ${bankLabel(alert.bank_id)}, 24 meses, con el mes de la alerta resaltado`}
          points={series.map((p) => ({
            period: p.period,
            value: p.value,
            baseline: p.baseline,
          }))}
          highlight={alert.period}
          colorVar={color}
          format={info.format}
          showBaseline={isZ}
          thresholds={isZ ? [] : [{ value: alert.threshold, label: threshold }]}
        />
      </ChartFrame>
      {isZ ? (
        <ChartFrame
          kicker="Cuánto se aleja"
          title="z por mes"
          subtitle="Distancia a la línea base, en desviaciones robustas"
          howToRead="Una alerta se abre cuando el z de un mes cerrado pasa el umbral, hacia arriba o hacia abajo."
          provenance={provenance}
        >
          <DriftChart
            label={`z mensual de ${info.label}, con el umbral en más y menos ${alert.threshold}`}
            points={series.map((p) => ({ period: p.period, value: p.z }))}
            highlight={alert.period}
            colorVar={color}
            format={(v) => v.toFixed(1)}
            thresholds={[
              { value: alert.threshold, label: threshold },
              { value: -alert.threshold, label: `z ≤ −${alert.threshold}` },
            ]}
          />
        </ChartFrame>
      ) : null}
    </div>
  );
}

function Content({ detail }: { detail: Detail }) {
  const { alert } = detail;
  const info = driftSeries(alert.series);
  return (
    <div className="grid gap-6">
      <div className="grid gap-2">
        <Link
          to="/alertas"
          className="inline-flex w-fit items-center gap-1 text-sm font-semibold text-green-600"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          Alertas de deriva
        </Link>
        <h1 className="font-serif text-3xl font-semibold">{info.label}</h1>
        <p className="flex flex-wrap items-center gap-3 text-sm">
          <BankDot bank={alert.bank_id} />
          <span>{formatMonth(alert.period)}</span>
          <AlertStatusPill status={alert.status} />
          <span className="text-text-muted">
            Valor {info.format(alert.value)} · umbral{" "}
            {formatThreshold(alert.series, alert.threshold)}
          </span>
        </p>
      </div>
      <Callout variant="info">
        Una alerta dice que la entrada o la predicción cambió respecto de los 12
        meses previos del banco; no dice por qué.
      </Callout>
      <Actions detail={detail} />
      <Charts detail={detail} />
      <div className="grid gap-6 lg:grid-cols-2">
        <BoostCard boost={alert.boost} />
        <EventsCard events={detail.events} />
      </div>
    </div>
  );
}

export default function AlertDetail() {
  const { alertId = "" } = useParams();
  const alert = useAlert(alertId);
  if (alert.isPending) {
    return (
      <div className="grid gap-4" aria-busy="true">
        <Skeleton className="h-10 w-96" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (alert.isError) {
    return <ErrorState error={alert.error} onRetry={() => alert.refetch()} />;
  }
  return <Content detail={alert.data} />;
}
