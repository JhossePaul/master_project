import { Link } from "react-router";
import { type TaskSummary, useHitlSummary, useTopicVersions } from "@/api/hitl";
import { useMe } from "@/api/me";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatInt } from "@/lib/format";
import { cn } from "@/lib/utils";

const TASKS: Record<string, { title: string; path: string }> = {
  sentiment: { title: "Sentimiento", path: "/hitl/sentimiento" },
  aspects: { title: "Aspectos", path: "/hitl/aspectos" },
};

export function formatSeconds(seconds: number | null): string {
  if (seconds === null) return "sin datos";
  const total = Math.round(seconds);
  if (total < 60) return `${total} s`;
  const rest = total % 60;
  return rest === 0
    ? `${Math.floor(total / 60)} min`
    : `${Math.floor(total / 60)} min ${rest} s`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-sm text-text-muted">{label}</dt>
      <dd className="tabular text-3xl font-bold">{value}</dd>
    </div>
  );
}

function QueueCard({ summary }: { summary: TaskSummary }) {
  const task = TASKS[summary.task];
  if (!task) return null;
  const heading = `Cola de ${task.title.toLowerCase()}`;
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">{heading}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-5">
        <dl className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Stat label="Pendientes" value={formatInt(summary.pending)} />
          <Stat
            label="Mis revisiones de la semana"
            value={formatInt(summary.mine_this_week)}
          />
          <Stat
            label="Revisiones del equipo"
            value={formatInt(summary.team_this_week)}
          />
          <Stat
            label="Tiempo mediano por caso"
            value={formatSeconds(summary.median_seconds)}
          />
        </dl>
        {summary.monitor_target > 0 ? (
          <p className="text-sm">
            Muestra de monitoreo: {formatInt(summary.monitor_done)} de{" "}
            {formatInt(summary.monitor_target)}
          </p>
        ) : null}
        <div>
          <Link
            to={task.path}
            className={cn(buttonVariants({ variant: "primary" }))}
          >
            Empezar
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

function TopicsCard() {
  const versions = useTopicVersions();
  const pending = (versions.data?.versions ?? []).filter(
    (v) => v.decided < v.paired,
  );
  const open = pending.reduce((n, v) => n + (v.paired - v.decided), 0);
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">Curaduría de tópicos</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-5">
        <p className="text-sm">
          {versions.isPending
            ? "Buscando versiones nuevas…"
            : pending.length === 0
              ? "No hay versiones de tópicos por decidir."
              : `${formatInt(open)} tópicos por decidir en ${pending.length === 1 ? "una versión nueva" : `${pending.length} versiones nuevas`}.`}
        </p>
        <div>
          <Link
            to="/hitl/topicos"
            className={cn(buttonVariants({ variant: "primary" }))}
          >
            Empezar
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

export default function HitlHome() {
  const summary = useHitlSummary();
  const me = useMe();
  const curatesTopics = me.data?.reviewer_tasks.includes("topic") ?? false;
  if (summary.isPending) {
    return (
      <div className="grid gap-4" aria-busy="true">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-48" />
      </div>
    );
  }
  if (summary.isError) {
    return (
      <ErrorState error={summary.error} onRetry={() => summary.refetch()} />
    );
  }
  return (
    <div className="grid gap-6">
      <h1 className="font-serif text-3xl font-semibold">Revisión</h1>
      {summary.data.tasks.length === 0 && !curatesTopics ? (
        <EmptyState
          title="No tienes colas asignadas"
          description="Pide al autor que te asigne una tarea de revisión."
        />
      ) : (
        <>
          {summary.data.tasks.map((task) => (
            <QueueCard key={task.task} summary={task} />
          ))}
          {curatesTopics ? <TopicsCard /> : null}
        </>
      )}
    </div>
  );
}
