import { useMemo, useState } from "react";
import {
  type DailyPoint,
  useCards,
  useDaily,
  useDailyTopics,
  useModelChanges,
} from "@/api/kpis";
import { TimeSeries, type TimeSeriesItem } from "@/charts/TimeSeries";
import { Callout } from "@/components/Callout";
import { ChartFrame } from "@/components/ChartFrame";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { BANKS, type BankId, bankLabel } from "@/config/banks";
import { formatDate, formatPct, formatStars } from "@/lib/format";
import { useKpi } from "./kpi";
import { BankPicker, familyName, LoadingBlock, OpenInExplorer } from "./shared";
import {
  dayShift,
  MAX_WINDOW,
  rolling,
  type SeriesMetric,
  type SmoothingWindow,
  WINDOWS,
} from "./smoothing";

const METRICS: Record<
  SeriesMetric,
  {
    label: string;
    value: (p: DailyPoint) => number | null;
    format: (v: number) => string;
  }
> = {
  neg: {
    label: "Proporción de negativas",
    value: (p) => (p.predichas > 0 ? p.neg / p.predichas : null),
    format: (v) => formatPct(v),
  },
  gap: {
    label: "Brecha en estrellas",
    value: (p) => p.gap_crudo,
    format: (v) => formatStars(v),
  },
  neg45: {
    label: "Quejas con 4–5 estrellas",
    value: (p) => (p.predichas > 0 ? p.neg_4_5 / p.predichas : null),
    format: (v) => formatPct(v),
  },
};

export function DayPanel({
  banks,
  day,
  smoothing,
  onClose,
}: {
  banks: BankId[];
  day: string;
  smoothing: SmoothingWindow;
  onClose: () => void;
}) {
  const [bank, setBank] = useState<BankId>(banks[0] as BankId);
  const active = banks.includes(bank) ? bank : (banks[0] as BankId);
  const topics = useDailyTopics(active, day);
  return (
    <aside
      aria-label={`Temas del ${formatDate(day)}`}
      className="flex flex-col gap-3 rounded-md border border-border bg-surface-muted p-4"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-serif text-lg font-semibold">
          Temas del {formatDate(day)}
        </h3>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Cerrar
        </Button>
      </div>
      {banks.length > 1 ? (
        <BankPicker
          banks={banks}
          value={active}
          onChange={setBank}
          label="Banco del panel"
        />
      ) : null}
      <Callout variant="info">
        Describe lo que dicen las reseñas negativas de ese día; no es un
        diagnóstico ni la detección de un incidente.
        {smoothing > 1
          ? ` Son los temas de ese solo día, no del promedio de ${smoothing} días.`
          : ""}
      </Callout>
      {topics.isPending ? <LoadingBlock /> : null}
      {topics.isError ? (
        <ErrorState error={topics.error} onRetry={() => topics.refetch()} />
      ) : null}
      {topics.data ? (
        topics.data.n_neg === 0 ? (
          <p className="text-sm text-text-muted">
            Ese día no hay reseñas negativas de dos palabras o más.
          </p>
        ) : (
          <>
            <p className="text-sm text-text-muted">
              <span className="tabular">{topics.data.n_neg}</span> reseñas
              negativas ese día.
            </p>
            <ThemeList
              title="Familias"
              items={topics.data.familias}
              color={BANKS[active].colorVar}
              translate
            />
            <ThemeList
              title="Tópicos útiles"
              items={topics.data.topicos}
              color={BANKS[active].colorVar}
            />
            <p className="text-xs text-text-muted">
              {[
                topics.data.aspects_prompt_version &&
                  `prompt ${topics.data.aspects_prompt_version}`,
                topics.data.topic_model_version &&
                  `tópicos ${topics.data.topic_model_version}`,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </>
        )
      ) : null}
    </aside>
  );
}

function ThemeList({
  title,
  items,
  color,
  translate = false,
}: {
  title: string;
  items: {
    codigo: string;
    nombre?: string | null;
    participacion: number;
    habitual?: number | null;
  }[];
  color: string;
  translate?: boolean;
}) {
  return (
    <section aria-label={title}>
      <h4 className="mb-1 text-sm font-semibold">{title}</h4>
      <ul className="grid gap-2">
        {items.map((item) => (
          <li key={item.codigo} className="text-sm">
            <div className="flex justify-between gap-2">
              <span>
                {item.nombre ??
                  (translate ? familyName(item.codigo) : item.codigo)}
              </span>
              <span className="tabular text-text-muted">
                {formatPct(item.participacion)}
                {item.habitual != null
                  ? ` · habitual ${formatPct(item.habitual)}`
                  : ""}
              </span>
            </div>
            <div
              className="relative mt-1 h-2 rounded-full bg-neutral-100"
              aria-hidden="true"
            >
              {item.habitual != null ? (
                <div
                  className="absolute inset-y-0 left-0 rounded-full bg-neutral-400"
                  style={{ width: `${Math.min(item.habitual, 1) * 100}%` }}
                />
              ) : null}
              <div
                className="absolute inset-y-0.5 left-0 rounded-full"
                style={{
                  width: `${Math.min(item.participacion, 1) * 100}%`,
                  background: `var(${color})`,
                }}
              />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function SeriesBlock({
  banks,
  from,
  to,
  day,
  familia,
  onDay,
  onRange,
}: {
  banks: BankId[];
  from: string;
  to: string;
  day: string | null;
  familia: string | null;
  onDay: (day: string | null) => void;
  onRange: (from: string, to: string) => void;
}) {
  const [kpi] = useKpi();
  const metric: SeriesMetric = kpi === "quejas" ? "neg45" : kpi;
  const [smoothing, setSmoothing] = useState<SmoothingWindow>(7);
  // Siempre se piden 27 días de más al inicio para que el promedio móvil
  // del primer día del rango ya tenga su ventana completa.
  const daily = useDaily(banks, dayShift(from, -(MAX_WINDOW - 1)), to);
  const models = useModelChanges();
  const cards = useCards(banks);
  const spec = METRICS[metric];

  const series = useMemo<TimeSeriesItem[]>(() => {
    const rows = daily.data ?? [];
    // Con uno o dos bancos se deja el dato diario como línea de fondo.
    const withRaw = smoothing > 1 && banks.length <= 2;
    const out: TimeSeriesItem[] = [];
    for (const id of banks) {
      const own = rows.filter((r) => r.bank_id === id);
      const points = (window: number) =>
        rolling(own, window, metric)
          .filter((p) => p.dia >= from)
          .map(
            (p) =>
              [new Date(`${p.dia}T00:00:00Z`), p.value] as [
                Date,
                number | null,
              ],
          );
      if (withRaw)
        out.push({
          id: `${id}-dia`,
          label: `${bankLabel(id)} (día)`,
          colorVar: BANKS[id].colorVar,
          faint: true,
          points: points(1),
        });
      out.push({
        id,
        label: bankLabel(id),
        colorVar: BANKS[id].colorVar,
        dash: BANKS[id].dash,
        points: points(smoothing),
      });
    }
    return out;
  }, [daily.data, banks, metric, smoothing, from]);

  const markers = useMemo(
    () =>
      (models.data ?? [])
        .map((m) => ({
          at: new Date(m.promoted_at),
          label: `Modelo ${m.model_version}`,
        }))
        .filter(
          (m) =>
            m.at >= new Date(`${from}T00:00:00Z`) &&
            m.at <= new Date(`${to}T23:59:59Z`),
        ),
    [models.data, from, to],
  );
  const selected = useMemo(
    () => (day ? new Date(`${day}T00:00:00Z`) : null),
    [day],
  );

  const lastDay = (daily.data ?? [])
    .map((r) => r.dia)
    .sort()
    .at(-1);
  const model = cards.data?.find((c) => c.model_version)?.model_version;

  function brushed(a: Date, b: Date) {
    const f = a.toISOString().slice(0, 10);
    const t = b.toISOString().slice(0, 10);
    if (f !== from || t !== to) onRange(f, t);
  }

  return (
    <div className={day ? "grid gap-6 xl:grid-cols-[1fr_22rem]" : "grid gap-6"}>
      <ChartFrame
        kicker="Serie diaria"
        title={spec.label}
        subtitle="Por día (UTC), una línea por banco. El rango de la barra de filtros aplica a esta serie."
        method="raw"
        actions={
          <OpenInExplorer
            filters={{
              banks,
              from,
              to,
              familia,
              sentimiento: metric === "gap" ? null : "NEG",
            }}
          />
        }
        howToRead={
          <p>
            Cada punto es un día. Haz clic en un día para ver de qué hablan las
            reseñas negativas de ese día, o arrastra sobre la gráfica para
            acercar un rango. Las cifras son las del modelo sin ajustar. Con
            suavizado, cada punto es el promedio de los últimos N días (pesado
            por las reseñas de cada día) y los días con pocas reseñas pesan
            menos.
          </p>
        }
        provenance={{
          model,
          dataUntil: lastDay ?? null,
          note: `del ${formatDate(from)} al ${formatDate(to)}`,
        }}
        data={{
          columns: ["Día", "Banco", "Predichas", "Valor"],
          rows: (daily.data ?? [])
            .filter((r) => r.dia >= from)
            .map((r) => {
              const v = spec.value(r);
              return [
                r.dia,
                bankLabel(r.bank_id),
                r.predichas,
                v === null ? null : spec.format(v),
              ];
            }),
        }}
      >
        <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-2">
          <fieldset className="m-0 flex flex-wrap items-center gap-1 border-0 p-0">
            <legend className="sr-only">Suavizado</legend>
            <span className="text-sm text-text-muted">Suavizado:</span>
            {WINDOWS.map((w) => (
              <Button
                key={w}
                size="sm"
                variant={w === smoothing ? "primary" : "secondary"}
                aria-pressed={w === smoothing}
                onClick={() => setSmoothing(w)}
              >
                {w === 1 ? "Sin suavizar" : `${w} días`}
              </Button>
            ))}
          </fieldset>
        </div>
        {daily.isPending ? <LoadingBlock /> : null}
        {daily.isError ? (
          <ErrorState error={daily.error} onRetry={() => daily.refetch()} />
        ) : null}
        {daily.data ? (
          daily.data.length === 0 ? (
            <p className="text-sm text-text-muted">
              No hay reseñas en ese rango.
            </p>
          ) : (
            <TimeSeries
              series={series}
              markers={markers}
              valueFormatter={spec.format}
              height={280}
              selectedDate={selected}
              onSelectDate={(d) => onDay(d.toISOString().slice(0, 10))}
              onRangeChange={brushed}
            />
          )
        ) : null}
      </ChartFrame>
      {day ? (
        <DayPanel
          banks={banks}
          day={day}
          smoothing={smoothing}
          onClose={() => onDay(null)}
        />
      ) : null}
    </div>
  );
}
