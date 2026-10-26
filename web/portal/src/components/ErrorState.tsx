import { TriangleAlert } from "lucide-react";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const api = error instanceof ApiError ? error : null;
  const message = api?.message ?? "No se pudo cargar la información.";
  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-md border border-danger/30 bg-danger-bg p-5 text-danger"
    >
      <p className="flex items-center gap-2 font-semibold">
        <TriangleAlert className="size-4" aria-hidden="true" />
        {message}
      </p>
      {api?.requestId ? (
        <p className="text-xs">
          Id de la petición: <code className="font-mono">{api.requestId}</code>
        </p>
      ) : null}
      {onRetry ? (
        <div>
          <Button size="sm" variant="secondary" onClick={onRetry}>
            Reintentar
          </Button>
        </div>
      ) : null}
    </div>
  );
}
