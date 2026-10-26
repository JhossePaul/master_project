import { ArrowRight } from "lucide-react";
import { Link, useOutletContext } from "react-router";
import { useLanding } from "@/api/landing";
import type { components } from "@/api/schema";
import { hasRole, type Me } from "@/auth/roles";
import { Callout } from "@/components/Callout";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { StatusPill } from "@/components/StatusPill";
import { Tahali } from "@/components/Tahali";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { BANKS, type BankId, bankLabel } from "@/config/banks";
import { NAV_ITEMS, PORTAL_NAME } from "@/config/nav";
import {
  formatDate,
  formatDateTime,
  formatInt,
  formatRelative,
} from "@/lib/format";
import { BankSummary } from "./BankSummary";

type LandingData = components["schemas"]["LandingResponse"];

const HOUR = 3_600_000;
const FRESH_HOURS = 36;
const MONITOR_DAYS = 8;

export function isFresh(
  iso: string | null | undefined,
  maxHours: number,
  now = Date.now(),
): boolean {
  if (!iso) return false;
  return now - new Date(iso).getTime() <= maxHours * HOUR;
}

type Tone = "ok" | "aviso" | "fallo" | "en_curso";

function FreshnessRow({
  label,
  when,
  status,
  now,
}: {
  label: string;
  when: string | null;
  status: Tone;
  now: number;
}) {
  return (
    <li className="flex items-center justify-between gap-3 border-b border-border py-2 last:border-0">
      <span className="text-sm">{label}</span>
      <span className="flex items-center gap-3 text-sm">
        <time
          dateTime={when ?? undefined}
          title={when ? formatDateTime(when) : undefined}
          className="tabular text-text-muted"
        >
          {when ? formatRelative(when, now) : "sin registro"}
        </time>
        <StatusPill status={status} />
      </span>
    </li>
  );
}

function Freshness({
  data,
  now,
}: {
  data: LandingData["freshness"];
  now: number;
}) {
  const delta = data.last_delta;
  let analysis: Tone = "aviso";
  if (delta?.status === "failed") analysis = "fallo";
  else if (delta?.status === "running") analysis = "en_curso";
  else if (delta && isFresh(delta.started_at, FRESH_HOURS, now))
    analysis = "ok";
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">Última actualización</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-1 text-sm text-gold-700">
          {data.data_until
            ? `Datos al ${formatDate(data.data_until)}`
            : "Sin fecha de datos"}
        </p>
        <ul>
          <FreshnessRow
            label="Reseñas nuevas"
            when={data.last_ingestion_at}
            status={
              isFresh(data.last_ingestion_at, FRESH_HOURS, now) ? "ok" : "aviso"
            }
            now={now}
          />
          <FreshnessRow
            label="Análisis de reseñas"
            when={delta?.started_at ?? null}
            status={analysis}
            now={now}
          />
          <FreshnessRow
            label="Revisión del modelo"
            when={data.last_monitor_at}
            status={
              isFresh(data.last_monitor_at, MONITOR_DAYS * 24, now)
                ? "ok"
                : "aviso"
            }
            now={now}
          />
        </ul>
      </CardContent>
    </Card>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden rounded-md bg-green-900 px-6 py-5 text-neutral-0">
      {/* La franja solo aparece donde cabe sin tocar el texto. */}
      <Tahali className="absolute top-0 right-6 hidden h-full w-32 lg:block" />
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:gap-6 lg:pr-40">
        <img
          src="/logo-posgrados-up.png"
          alt="Posgrados Universidad Panamericana"
          className="h-16 w-auto shrink-0 self-start sm:self-center"
        />
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-gold-400">
            Maestría en Ciencia de Datos
          </p>
          <h1 className="font-serif text-3xl font-semibold">{PORTAL_NAME}</h1>
          <p className="mt-1 max-w-2xl text-green-100">
            Voz del cliente en apps bancarias: qué opinan los usuarios de cinco
            apps, con cada cifra acompañada de qué tan segura es.
          </p>
        </div>
      </div>
    </section>
  );
}

function Content({ data, me }: { data: LandingData; me: Me }) {
  const now = Date.now();
  const alerts = Object.entries(data.open_alerts).filter(([, n]) => n > 0);
  const total = alerts.reduce((sum, [, n]) => sum + n, 0);
  const access = NAV_ITEMS.filter((i) => i.path !== "/" && hasRole(me, i.role));
  return (
    <div className="flex flex-col gap-8">
      <Hero />
      <section
        aria-label="Estado actual"
        className={`grid gap-6 ${
          data.hitl_pending !== null
            ? "lg:grid-cols-[minmax(0,2fr)_minmax(0,1.2fr)_minmax(0,1fr)]"
            : "lg:grid-cols-[minmax(0,2fr)_minmax(0,1.2fr)]"
        }`}
      >
        <Freshness data={data.freshness} now={now} />
        <Card>
          <CardHeader>
            <CardTitle as="h2" id="alertas">
              Alertas de cambios abiertas
            </CardTitle>
          </CardHeader>
          <CardContent>
            {alerts.length === 0 ? (
              <p className="text-sm text-text-muted">Ninguna alerta abierta.</p>
            ) : (
              <>
                <p className="tabular text-4xl font-bold">{formatInt(total)}</p>
                <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                  {alerts.map(([bank, n]) => {
                    const entry = (
                      <>
                        <span
                          aria-hidden="true"
                          className="inline-block size-2.5 rounded-full"
                          style={{
                            background: `var(${BANKS[bank as BankId]?.colorVar})`,
                          }}
                        />
                        <span>{bankLabel(bank)}</span>
                        <span className="tabular font-semibold">
                          {formatInt(n)}
                        </span>
                      </>
                    );
                    return (
                      <li key={bank} className="text-sm">
                        {hasRole(me, "analista") ? (
                          <Link
                            to={`/alertas?bancos=${encodeURIComponent(bank)}`}
                            className="flex items-center gap-1.5 underline-offset-4 hover:underline"
                          >
                            {entry}
                          </Link>
                        ) : (
                          <span className="flex items-center gap-1.5">
                            {entry}
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </>
            )}
            {hasRole(me, "analista") ? (
              <Link
                to="/alertas"
                className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-green-600"
              >
                Ver las alertas{" "}
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            ) : null}
          </CardContent>
        </Card>
        {data.hitl_pending !== null ? (
          <Card>
            <CardHeader>
              <CardTitle as="h2">Casos por revisar</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="tabular text-4xl font-bold">
                {formatInt(data.hitl_pending)}
              </p>
              <Link
                to="/hitl"
                className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-green-600"
              >
                Ir a revisión{" "}
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            </CardContent>
          </Card>
        ) : null}
      </section>
      <BankSummary banks={data.banks} />
      <section aria-labelledby="accesos">
        <h2
          id="accesos"
          className="mb-3 font-serif text-2xl font-semibold text-green-800"
        >
          Accesos
        </h2>
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {access.map(({ path, label, purpose, icon: Icon }) => (
            <li key={path}>
              <Link
                to={path}
                className="flex h-full gap-3 rounded-md border border-border bg-surface p-4 hover:border-green-200 hover:shadow-sm"
              >
                <Icon
                  className="mt-0.5 size-5 shrink-0 text-green-500"
                  aria-hidden="true"
                />
                <span>
                  <span className="block font-semibold">{label}</span>
                  <span className="text-sm text-text-muted">{purpose}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <Callout variant="info">
        Describe lo que dicen las reseñas; no es un diagnóstico ni una detección
        de incidentes.
      </Callout>
      <Footer commit={me.commit} />
    </div>
  );
}

function Footer({ commit }: { commit: string }) {
  return (
    <footer className="flex items-center gap-4 border-t border-border pt-4 text-sm text-text-muted">
      <span className="shrink-0 rounded-sm bg-green-900 p-1.5">
        <img
          src="/logo-posgrados-up.png"
          alt="Posgrados Universidad Panamericana"
          className="h-12 w-auto"
        />
      </span>
      <div>
        <p>
          Versión del portal{" "}
          <code className="font-mono">{commit.slice(0, 7)}</code>
        </p>
        <p>Universidad Panamericana · Maestría en Ciencia de Datos BBVA</p>
        <p>
          Autor: Jhosse Paul Márquez Ruíz · Revisor: Carlos González Martínez
        </p>
      </div>
    </footer>
  );
}

export default function Landing() {
  const me = useOutletContext<Me>();
  const landing = useLanding();
  if (landing.isPending) {
    return (
      <div className="grid gap-4" aria-busy="true">
        <Skeleton className="h-48" />
        <Skeleton className="h-32" />
      </div>
    );
  }
  if (landing.isError)
    return (
      <ErrorState error={landing.error} onRetry={() => landing.refetch()} />
    );
  if (landing.data.banks.length === 0 && !landing.data.freshness.data_until) {
    return (
      <EmptyState
        title="Aún no hay datos"
        description="La ingesta todavía no ha publicado reseñas."
      />
    );
  }
  return <Content data={landing.data} me={me} />;
}
