import { useState } from "react";
import { toast } from "sonner";
import {
  type GoldCriteria,
  type GoldPreview,
  previewGold,
  useCreateGold,
  useGoldItems,
  useGoldVersions,
} from "@/api/admin";
import { Callout } from "@/components/Callout";
import { ConfirmWithReason } from "@/components/ConfirmWithReason";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { bankLabel } from "@/config/banks";
import { formatDate, formatDateTime, formatInt } from "@/lib/format";

const FLAGS = [
  ["no_evaluable", "No evaluable"],
  ["duda", "Con duda"],
  ["menciona_falla", "Menciona una falla"],
  ["nombre_persona", "Nombre de persona"],
] as const;

type Flag = (typeof FLAGS)[number][0];

function Counts({
  title,
  rows,
  label,
}: {
  title: string;
  rows: { key: string; n: number }[];
  label: (key: string) => string;
}) {
  return (
    <div>
      <h4 className="mb-1 text-sm font-semibold">{title}</h4>
      <ul className="text-sm">
        {rows.map((r) => (
          <li key={r.key} className="tabular">
            {label(r.key)}: {formatInt(r.n)}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function GoldTab() {
  const versions = useGoldVersions();
  const create = useCreateGold();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [guideline, setGuideline] = useState("v2.2");
  const [exclude, setExclude] = useState<Flag[]>(["no_evaluable"]);
  const [preview, setPreview] = useState<GoldPreview | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const items = useGoldItems(open);
  const ready = from !== "" && to !== "" && guideline.trim() !== "";

  const criteria = (): GoldCriteria => ({
    reason: "monitor_sample",
    submitted_from: from,
    submitted_to: to,
    guideline_version: guideline.trim(),
    review_round: 1,
    exclude_flags: exclude,
  });

  async function check() {
    try {
      setPreview(await previewGold(criteria()));
    } catch (error) {
      setPreview(null);
      toast.error(
        error instanceof Error ? error.message : "No se pudo revisar",
      );
    }
  }

  return (
    <div className="grid gap-6">
      <Callout variant="warning" title="Falta un paso manual">
        Crear la versión no la activa: para que el monitor y el reentrenamiento
        usen el oro nuevo hay que cambiar <code>GOLD_VERSION</code> en los Jobs
        y subir sus ids de exclusión.
      </Callout>

      <Card className="grid gap-4 p-5">
        <h3 className="font-serif text-lg font-semibold">
          Nueva versión desde la muestra de monitoreo
        </h3>
        <div className="grid gap-4 md:grid-cols-3">
          <div className="grid gap-1">
            <Label htmlFor="gold-from">Revisadas desde</Label>
            <Input
              id="gold-from"
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="gold-to">Revisadas hasta</Label>
            <Input
              id="gold-to"
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="gold-guideline">Versión de la guía</Label>
            <Input
              id="gold-guideline"
              value={guideline}
              onChange={(e) => setGuideline(e.target.value)}
            />
            <p className="text-xs text-text-muted">
              Una sola guía por versión del oro.
            </p>
          </div>
        </div>
        <fieldset className="flex flex-wrap gap-4">
          <legend className="mb-1 text-sm font-semibold">
            Excluir las revisiones marcadas como
          </legend>
          {FLAGS.map(([flag, label]) => (
            <label key={flag} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={exclude.includes(flag)}
                onChange={(e) =>
                  setExclude((now) =>
                    e.target.checked
                      ? [...now, flag]
                      : now.filter((f) => f !== flag),
                  )
                }
              />
              {label}
            </label>
          ))}
        </fieldset>
        <p className="text-xs text-text-muted">
          Solo entran la primera ronda de revisión y las revisiones de la
          muestra de monitoreo.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" disabled={!ready} onClick={check}>
            Ver cuántas entrarían
          </Button>
          <ConfirmWithReason
            title="Crear la versión del oro"
            description="Se registra una versión nueva con los criterios de arriba y el corte de este momento. Nada se edita ni se borra."
            confirmLabel="Crear versión"
            trigger={
              <Button
                disabled={!ready || preview === null || preview.total === 0}
              >
                Crear versión…
              </Button>
            }
            onConfirm={(reason) =>
              create.mutate(
                { criteria: criteria(), reason },
                {
                  onSuccess: (made) => {
                    toast.success(
                      `Versión ${made.version.gold_version} creada`,
                    );
                    setPreview(null);
                  },
                  onError: (error) => toast.error(error.message),
                },
              )
            }
          />
        </div>
        {preview ? (
          <div className="grid gap-3 rounded-md border border-border p-4 md:grid-cols-3">
            <p className="tabular text-3xl font-bold">
              {formatInt(preview.total)}
              <span className="ml-2 text-sm font-normal text-text-muted">
                revisiones entrarían
              </span>
            </p>
            <Counts
              title="Por banco"
              rows={preview.by_bank}
              label={bankLabel}
            />
            <Counts
              title="Por etiqueta"
              rows={preview.by_label}
              label={(k) => k}
            />
          </div>
        ) : null}
      </Card>

      <Card className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Versión</TableHead>
              <TableHead scope="col">Corte</TableHead>
              <TableHead scope="col">Revisiones</TableHead>
              <TableHead scope="col">Guía</TableHead>
              <TableHead scope="col">Motivo</TableHead>
              <TableHead scope="col">
                <span className="sr-only">Ítems</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(versions.data ?? []).map(({ version, reason }) => (
              <TableRow key={version.gold_version}>
                <TableCell className="font-mono text-xs">
                  {version.gold_version}
                </TableCell>
                <TableCell>{formatDateTime(version.cutoff_at)}</TableCell>
                <TableCell className="tabular">
                  {formatInt(version.items)}
                </TableCell>
                <TableCell>
                  {String(version.criteria.guideline_version ?? "—")}
                </TableCell>
                <TableCell>{reason ?? "—"}</TableCell>
                <TableCell>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-pressed={open === version.gold_version}
                    onClick={() =>
                      setOpen(
                        open === version.gold_version
                          ? null
                          : version.gold_version,
                      )
                    }
                  >
                    {open === version.gold_version ? "Ocultar" : "Ver ítems"}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {versions.data?.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-text-muted">
                  Aún no hay versiones del oro creadas desde la revisión.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </Card>
      {versions.isError ? (
        <ErrorState error={versions.error} onRetry={() => versions.refetch()} />
      ) : null}

      {open && items.data ? (
        <Card className="overflow-x-auto p-4">
          <h3 className="mb-2 font-serif text-lg font-semibold">
            Ítems de {items.data.gold_version}
            <span className="ml-2 text-sm font-normal text-text-muted">
              hasta {formatDate(items.data.cutoff_at)} · sin texto
            </span>
          </h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Ítem</TableHead>
                <TableHead scope="col">Reseña</TableHead>
                <TableHead scope="col">Etiqueta</TableHead>
                <TableHead scope="col">Revisada</TableHead>
                <TableHead scope="col">Revisor</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.data.items.map((i) => (
                <TableRow key={i.item_id}>
                  <TableCell className="font-mono text-xs">
                    {i.item_id}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {i.id_resena}
                  </TableCell>
                  <TableCell>{i.validated_label ?? "—"}</TableCell>
                  <TableCell>{formatDateTime(i.submitted_at)}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {i.reviewer}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      ) : null}
    </div>
  );
}
