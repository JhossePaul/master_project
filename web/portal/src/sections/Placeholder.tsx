import { Construction } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";

export function UnderConstruction({ title }: { title: string }) {
  return (
    <div className="grid gap-4">
      <h1 className="font-serif text-3xl font-semibold">{title}</h1>
      <EmptyState
        title="En construcción"
        description="Esta sección llega en un paso posterior del portal."
        action={
          <Construction
            className="size-5 text-neutral-500"
            aria-hidden="true"
          />
        }
      />
    </div>
  );
}

export function NotFound() {
  return (
    <div className="grid gap-4">
      <h1 className="font-serif text-3xl font-semibold">
        Página no encontrada
      </h1>
      <EmptyState
        title="No existe esa dirección"
        description="Revisa el enlace o vuelve al inicio desde el menú."
      />
    </div>
  );
}
