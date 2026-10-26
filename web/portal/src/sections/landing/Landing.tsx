import { ArrowRight } from "lucide-react";
import { Link, useOutletContext } from "react-router";
import { useLanding } from "@/api/landing";
import type { components } from "@/api/schema";
import { hasRole, type Me } from "@/auth/roles";
import { Callout } from "@/components/Callout";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { GlossaryTerm } from "@/components/GlossaryTerm";
import { KpiCard, KpiCardFrame } from "@/components/KpiCard";
import { StatusPill } from "@/components/StatusPill";
import { Tahali } from "@/components/Tahali";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { BANK_IDS, BANKS, bankLabel } from "@/config/banks";
import { NAV_ITEMS, PORTAL_NAME } from "@/config/nav";
import {
  formatDate,
  formatDateTime,
  formatInt,
  formatMonth,
  formatPct,
  formatPctRange,
  formatRelative,
  formatStars,
  formatStarsRange,
} from "@/lib/format";

type LandingData = components["schemas"]["LandingResponse"];
type Headline = components["schemas"]["BankHeadline"];

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

function BankCard({ bank }: { bank: Headline }) {
  const style = BANKS[bank.bank_id as keyof typeof BANKS];
  return (
    <KpiCardFrame colorVar={style?.colorVar}>
      <h3 className="mb-3 font-serif text-xl font-semibold">
        <Link
          to={{ pathname: "/cockpit", search: `?bancos=${bank.bank_id}` }}
          className="after:absolute after:inset-0"
        >
          {bankLabel(bank.bank_id)}
        </Link>
      </h3>
      <div className="grid gap-4">
        <KpiCard
          label="Reseñas negativas"
          value={formatPct(bank.neg.estimate)}
          interval={formatPctRange(bank.neg.ci_low, bank.neg.ci_high)}
          method={bank.neg.method}
        />
        <KpiCard
          label={
            <span className="relative z-10">
              <GlossaryTerm id="gap_estrellas">
                Brecha en estrellas
              </GlossaryTerm>
            </span>
          }
          value={formatStars(bank.gap_estrellas.estimate)}
          interval={formatStarsRange(
            bank.gap_estrellas.ci_low,
            bank.gap_estrellas.ci_high,
          )}
          method={bank.gap_estrellas.method}
          collapsedProvenance={{
            explanation: (
              <p className="text-sm">
                Cifras de {formatMonth(bank.period)}. Un modelo clasifica todas
                las reseñas y personas revisaron una muestra para ajustar el
                cálculo.
              </p>
            ),
            provenance: { model: bank.model_version, gold: bank.gold_version },
          }}
        />
      </div>
    </KpiCardFrame>
  );
}

function MissingBankCard({ id }: { id: string }) {
  return (
    <KpiCardFrame colorVar={BANKS[id as keyof typeof BANKS]?.colorVar}>
      <h3 className="mb-2 font-serif text-xl font-semibold">{bankLabel(id)}</h3>
      <p className="text-sm text-text-muted">
        Sin cifra con revisión humana en un mes cerrado: aún no hay suficientes
        reseñas revisadas.
      </p>
    </KpiCardFrame>
  );
}

function Hero({ dataUntil }: { dataUntil: string | null }) {
  return (
    <section className="relative overflow-hidden rounded-md bg-green-900 px-8 py-10 text-neutral-0">
      {/* La franja solo aparece donde cabe sin tocar el texto. */}
      <Tahali className="absolute top-0 right-8 hidden h-full w-48 lg:block" />
      <div className="lg:pr-56">
        <img
          src="/logo-posgrados-up.png"
          alt="Posgrados Universidad Panamericana"
          className="mb-5 h-24 w-auto"
        />
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-gold-400">
          Maestría en Ciencia de Datos
        </p>
        <h1 className="mt-2 font-serif text-5xl font-semibold">
          {PORTAL_NAME}
        </h1>
        <p className="mt-3 max-w-xl text-lg text-green-100">
          Voz del cliente en apps bancarias: qué opinan los usuarios de cinco
          apps, con cada cifra acompañada de qué tan segura es.
        </p>
        <p className="mt-4 text-sm text-gold-300">
          {dataUntil
            ? `Datos al ${formatDate(dataUntil)}`
            : "Sin fecha de datos"}
        </p>
      </div>
    </section>
  );
}

function Content({ data, me }: { data: LandingData; me: Me }) {
  const now = Date.now();
  const alerts = Object.entries(data.open_alerts).filter(([, n]) => n > 0);
  const byBank = new Map(data.banks.map((b) => [b.bank_id, b]));
  const access = NAV_ITEMS.filter((i) => i.path !== "/" && hasRole(me, i.role));
  return (
    <div className="flex flex-col gap-8">
      <Hero dataUntil={data.freshness.data_until} />
      <Freshness data={data.freshness} now={now} />
      <section aria-labelledby="bancos">
        <h2
          id="bancos"
          className="mb-3 font-serif text-2xl font-semibold text-green-800"
        >
          Los cinco bancos
        </h2>
        <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-3">
          {BANK_IDS.map((id) => {
            const bank = byBank.get(id);
            return bank ? (
              <BankCard key={id} bank={bank} />
            ) : (
              <MissingBankCard key={id} id={id} />
            );
          })}
        </div>
      </section>
      <section aria-labelledby="alertas" className="grid gap-6 lg:grid-cols-2">
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
              <ul className="grid gap-1">
                {alerts.map(([bank, n]) => (
                  <li
                    key={bank}
                    className="flex items-center justify-between text-sm"
                  >
                    <span>{bankLabel(bank)}</span>
                    <span className="flex items-center gap-2">
                      <span className="tabular">{formatInt(n)}</span>
                      <StatusPill status="abierta" />
                    </span>
                  </li>
                ))}
              </ul>
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
