import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";

export type HitlCase = components["schemas"]["HitlCase"];
export type SentimentReviewIn = components["schemas"]["SentimentReviewIn"];
export type ReviewOut = components["schemas"]["ReviewOut"];
export type TaskSummary = components["schemas"]["TaskSummary"];

/** Cuenta de cada cola; siempre fresca: la cola cambia con cada revisión. */
export function useHitlSummary() {
  return useQuery({
    queryKey: ["hitl", "summary"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/hitl/summary");
      if (!data) throw new Error("Respuesta vacía de /hitl/summary");
      return data;
    },
    staleTime: 0,
    gcTime: 0,
  });
}

export function useGuideline(task: "sentiment") {
  return useQuery({
    queryKey: ["hitl", "guideline", task],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/hitl/guidelines/{task}", {
        params: { path: { task } },
      });
      if (!data) throw new Error("Respuesta vacía de la guía");
      return data;
    },
    staleTime: 5 * 60_000,
  });
}

/** Toma el siguiente caso; `null` si no quedan pendientes (204). */
export async function nextCase(): Promise<HitlCase | null> {
  const { data } = await api.POST("/api/v1/hitl/next", {
    body: { task: "sentiment" },
  });
  return data ?? null;
}

export async function saveReview(
  itemId: string,
  body: SentimentReviewIn,
): Promise<ReviewOut> {
  const { data } = await api.POST("/api/v1/hitl/items/{item_id}/review", {
    params: { path: { item_id: itemId } },
    body,
  });
  if (!data) throw new Error("Respuesta vacía al guardar");
  return data;
}

export async function skipCase(itemId: string): Promise<void> {
  await api.POST("/api/v1/hitl/items/{item_id}/skip", {
    params: { path: { item_id: itemId } },
  });
}

export async function releaseCase(itemId: string): Promise<void> {
  await api.POST("/api/v1/hitl/items/{item_id}/release", {
    params: { path: { item_id: itemId } },
  });
}

/** Al cerrar la pestaña `fetch` no alcanza a salir; `sendBeacon` sí. */
export function releaseOnExit(itemId: string): void {
  const url = `/api/v1/hitl/items/${encodeURIComponent(itemId)}/release`;
  if (typeof navigator.sendBeacon === "function") {
    navigator.sendBeacon(url);
    return;
  }
  void releaseCase(itemId).catch(() => undefined);
}
