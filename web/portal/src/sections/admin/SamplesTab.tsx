import { useState } from "react";
import { toast } from "sonner";
import { useCreateAspectsSample, useSampleBatches } from "@/api/admin";
import { Callout } from "@/components/Callout";
import { ConfirmWithReason } from "@/components/ConfirmWithReason";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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
import { formatDateTime, formatInt } from "@/lib/format";

export default function SamplesTab() {
  const batches = useSampleBatches();
  const create = useCreateAspectsSample();
  const [size, setSize] = useState(50);
  const [months, setMonths] = useState(3);
  const valid = size >= 1 && size <= 300 && months >= 1 && months <= 12;

  return (
    <div className="grid gap-6">
      <Callout variant="info" title="Ningún Job crea casos de aspectos">
        Cada muestra es un lote de reseñas negativas de dos palabras o más que
        ya tienen familias de Gemini. Se sortean al azar con la misma cuota por
        banco y se revisan a ciegas: quien revisa nunca ve lo que etiquetó
        Gemini.
      </Callout>

      <Card className="grid gap-4 p-5">
        <h2 className="font-serif text-lg font-semibold">
          Nueva muestra de aspectos
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="grid gap-1">
            <Label htmlFor="sample-size">Reseñas</Label>
            <Input
              id="sample-size"
              type="number"
              min={1}
              max={300}
              value={size}
              onChange={(event) => setSize(Number(event.target.value))}
            />
            <p className="text-xs text-text-muted">
              De 1 a 300; 50 por defecto.
            </p>
          </div>
          <div className="grid gap-1">
            <Label htmlFor="sample-months">Ventana (meses)</Label>
            <Input
              id="sample-months"
              type="number"
              min={1}
              max={12}
              value={months}
              onChange={(event) => setMonths(Number(event.target.value))}
            />
            <p className="text-xs text-text-muted">
              Reseñas de los últimos meses; 3 por defecto.
            </p>
          </div>
        </div>
        <div>
          <ConfirmWithReason
            title="Crear la muestra de aspectos"
            description="Los casos entran a la cola de aspectos de inmediato. Las reseñas ya muestreadas no se repiten."
            confirmLabel="Crear muestra"
            trigger={<Button disabled={!valid}>Crear muestra…</Button>}
            onConfirm={(reason) =>
              create.mutate(
                { size, months, reason },
                {
                  onSuccess: (made) =>
                    toast.success(
                      `Muestra ${made.batch} creada: ${made.created} casos`,
                    ),
                  onError: (error) => toast.error(error.message),
                },
              )
            }
          />
        </div>
      </Card>

      <section className="grid gap-3">
        <h2 className="font-serif text-lg font-semibold">Lotes creados</h2>
        {batches.isPending ? (
          <Skeleton className="h-24" />
        ) : batches.isError ? (
          <ErrorState error={batches.error} onRetry={() => batches.refetch()} />
        ) : batches.data.batches.length === 0 ? (
          <p className="text-sm text-text-muted">Todavía no hay muestras.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Lote</TableHead>
                <TableHead>Creado</TableHead>
                <TableHead className="text-right">Casos</TableHead>
                <TableHead className="text-right">Revisados</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {batches.data.batches.map((batch) => (
                <TableRow key={batch.batch}>
                  <TableCell className="font-mono">{batch.batch}</TableCell>
                  <TableCell>{formatDateTime(batch.created_at)}</TableCell>
                  <TableCell className="tabular text-right">
                    {formatInt(batch.size)}
                  </TableCell>
                  <TableCell className="tabular text-right">
                    {formatInt(batch.reviewed)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
    </div>
  );
}
