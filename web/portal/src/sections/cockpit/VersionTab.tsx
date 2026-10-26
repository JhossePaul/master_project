import { scaleBand, scaleLinear } from "d3-scale";
import { useVersions } from "@/api/kpis";
import { Axis, GridLines, ReferenceLine } from "@/charts/primitives";
import { Callout } from "@/components/Callout";
import { ChartFrame } from "@/components/ChartFrame";
import { ErrorState } from "@/components/ErrorState";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { BankId } from "@/config/banks";
import { formatDate, formatInt, formatPct, formatPctRange } from "@/lib/format";
import { familyName, LoadingBlock } from "./shared";

const W = 640;
const H = 280;
const M = { top: 16, right: 80, bottom: 40, left: 48 };

export function VersionTab({ bank }: { bank: BankId }) {
  const versions = useVersions(bank);
  if (versions.isPending) return <LoadingBlock />;
  if (versions.isError)
    return (
      <ErrorState error={versions.error} onRetry={() => versions.refetch()} />
    );
  const { rows, coverage, median_neg_share: median } = versions.data;
  const x = scaleBand<string>()
    .domain(rows.map((r) => r.release))
    .range([0, W - M.left - M.right])
    .padding(0.3);
  const top = Math.max(
    0.05,
    ...rows.map((r) => r.neg_ci_high),
    ...rows.map((r) => r.u_share),
  );
  const y = scaleLinear()
    .domain([0, top])
    .range([H - M.top - M.bottom, 0]);
  return (
    <div className="grid gap-6">
      <h2 className="font-serif text-2xl font-semibold text-green-800">
        Comparación entre versiones de la app
      </h2>
      <Callout variant="info">
        Descriptivo: no hay pruebas de cambio de nivel entre versiones. Las
        versiones se comparan dentro de un banco porque cada banco numera las
        suyas de otra manera.
      </Callout>
      <p className="text-sm text-text-muted">
        El <span className="tabular">{formatPct(coverage)}</span> de las reseñas
        tiene versión reconocida.
      </p>
      <ChartFrame
        kicker="Por versión"
        title="Reseñas negativas por versión de la app"
        subtitle="En orden cronológico; las versiones con menos de 50 negativas van en OTRAS"
        method="raw"
        howToRead={
          <p>
            El punto es la proporción de reseñas negativas de cada versión y la
            barra, su rango al 95 %. La línea punteada es la mediana del banco.
            El rombo es la proporción de negativas que hablan de actualizar la
            app.
          </p>
        }
        provenance={{ note: "conteo del modelo, sin ajustar" }}
        data={{
          columns: ["Versión", "Reseñas", "Negativas", "Rango", "Marca u"],
          rows: rows.map((r) => [
            r.release,
            r.filas,
            formatPct(r.neg_share),
            formatPctRange(r.neg_ci_low, r.neg_ci_high),
            formatPct(r.u_share),
          ]),
        }}
      >
        {rows.length === 0 ? (
          <p className="text-sm text-text-muted">
            Este banco no tiene versiones reconocidas.
          </p>
        ) : (
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="w-full"
            role="img"
            aria-label="Proporción de negativas por versión"
          >
            <g transform={`translate(${M.left},${M.top})`}>
              <GridLines scale={y} width={W - M.left - M.right} />
              <Axis
                scale={y}
                orientation="left"
                length={H - M.top - M.bottom}
                format={(v) => formatPct(v as number, 0)}
              />
              {median != null ? (
                <ReferenceLine
                  y={median}
                  width={W - M.left - M.right}
                  scale={y}
                  label={`mediana ${formatPct(median)}`}
                />
              ) : null}
              {rows.map((r) => {
                const cx = (x(r.release) ?? 0) + x.bandwidth() / 2;
                return (
                  <g key={r.release}>
                    <line
                      x1={cx}
                      x2={cx}
                      y1={y(r.neg_ci_low)}
                      y2={y(r.neg_ci_high)}
                      stroke="var(--color-green-700)"
                    />
                    <circle
                      cx={cx}
                      cy={y(r.neg_share)}
                      r={4}
                      fill="var(--color-green-700)"
                    >
                      <title>{`${r.release}: ${formatPct(r.neg_share)} ${formatPctRange(r.neg_ci_low, r.neg_ci_high)}`}</title>
                    </circle>
                    <rect
                      x={cx - 4}
                      y={y(r.u_share) - 4}
                      width={8}
                      height={8}
                      fill="var(--color-gold-500)"
                      transform={`rotate(45 ${cx} ${y(r.u_share)})`}
                    >
                      <title>{`${r.release}, marca u: ${formatPct(r.u_share)}`}</title>
                    </rect>
                    <text
                      x={cx}
                      y={H - M.top - M.bottom + 16}
                      textAnchor="middle"
                      fontSize={11}
                      fill="var(--color-neutral-700)"
                    >
                      {r.release}
                    </text>
                  </g>
                );
              })}
            </g>
          </svg>
        )}
      </ChartFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">Versión</TableHead>
            <TableHead scope="col">Fechas</TableHead>
            <TableHead scope="col">Reseñas</TableHead>
            <TableHead scope="col">Negativas</TableHead>
            <TableHead scope="col">Marca u</TableHead>
            <TableHead scope="col">Familias principales</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.release}>
              <TableCell>{r.release}</TableCell>
              <TableCell>
                {formatDate(r.first_seen)} – {formatDate(r.last_seen)}
              </TableCell>
              <TableCell className="tabular">{formatInt(r.filas)}</TableCell>
              <TableCell className="tabular">
                {formatPct(r.neg_share)} (
                {formatPctRange(r.neg_ci_low, r.neg_ci_high)})
              </TableCell>
              <TableCell className="tabular">{formatPct(r.u_share)}</TableCell>
              <TableCell>
                {Object.entries(r.families)
                  .slice(0, 3)
                  .map(
                    ([code, share]) =>
                      `${familyName(code)} ${formatPct(share, 0)}`,
                  )
                  .join(" · ") || "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
