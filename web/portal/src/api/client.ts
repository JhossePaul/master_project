import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "@/api/schema";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    requestId: string | null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

interface ErrorBody {
  error?: { code?: string; message?: string; request_id?: string };
}

/** Convierte toda respuesta con error en un ApiError con el id de la petición. */
export const errorMiddleware: Middleware = {
  async onResponse({ response }) {
    if (response.ok) return undefined;
    let body: ErrorBody = {};
    try {
      body = (await response.clone().json()) as ErrorBody;
    } catch {
      // La respuesta no es JSON (por ejemplo, una página de IAP).
    }
    throw new ApiError(
      response.status,
      body.error?.code ?? "unknown",
      body.error?.message ?? response.statusText ?? "Error desconocido",
      body.error?.request_id ?? response.headers.get("x-request-id"),
    );
  },
};

// Origen absoluto: el fetch de Node (pruebas) no acepta rutas relativas.
const ORIGIN = typeof location === "undefined" ? "" : location.origin;

export function buildClient(baseUrl = ORIGIN) {
  // fetch se resuelve al llamar: las pruebas lo sustituyen después de crear el cliente.
  const client = createClient<paths>({
    baseUrl,
    fetch: (request) => globalThis.fetch(request),
  });
  client.use(errorMiddleware);
  return client;
}

export const api = buildClient();
