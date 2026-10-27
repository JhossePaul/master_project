import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";

export type HitlCase = components["schemas"]["HitlCase"];
export type SentimentReviewIn = components["schemas"]["SentimentReviewIn"];
export type ReviewOut = components["schemas"]["ReviewOut"];
export type TaskSummary = components["schemas"]["TaskSummary"];
export type AspectsReviewIn = components["schemas"]["AspectsReviewIn"];
export type QueueTask = "sentiment" | "aspects";
export type TopicVersions = components["schemas"]["TopicVersionsResponse"];
export type TopicVersionDetail = components["schemas"]["TopicVersionDetail"];
export type TopicOut = components["schemas"]["TopicOut"];
export type TopicCurationIn = components["schemas"]["TopicCurationIn"];

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

export function useGuideline(task: QueueTask) {
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

/**
 * Toma el siguiente caso; `null` si no quedan pendientes (204). Con `exclude`
 * (los casos que ya tengo abiertos) sirve para precargarlo.
 */
export async function nextCase(
  exclude: string[] = [],
  task: QueueTask = "sentiment",
): Promise<HitlCase | null> {
  const { data } = await api.POST("/api/v1/hitl/next", {
    body: { task, exclude },
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

export async function saveAspectsReview(
  itemId: string,
  body: AspectsReviewIn,
): Promise<ReviewOut> {
  const { data } = await api.POST(
    "/api/v1/hitl/items/{item_id}/review-aspects",
    { params: { path: { item_id: itemId } }, body },
  );
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

/** Versiones de tópicos desde la vigente, con su avance de curaduría. */
export function useTopicVersions() {
  return useQuery({
    queryKey: ["hitl", "topics", "versions"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/hitl/topics/versions");
      if (!data) throw new Error("Respuesta vacía de /hitl/topics/versions");
      return data;
    },
    staleTime: 0,
    gcTime: 0,
  });
}

export function useTopicVersion(version: string | null) {
  return useQuery({
    queryKey: ["hitl", "topics", "detail", version],
    enabled: version !== null,
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/hitl/topics/{version}", {
        params: { path: { version: version as string } },
      });
      if (!data) throw new Error("Respuesta vacía de la versión");
      return data;
    },
    // Lo que se decide cambia con cada guardado: se invalida al curar.
    staleTime: 60_000,
  });
}

/** Ejemplos estables (semilla fija por tópico): no cambian entre visitas. */
export function useTopicExamples(version: string | null, topicId: number) {
  return useQuery({
    queryKey: ["hitl", "topics", "examples", version, topicId],
    enabled: version !== null,
    queryFn: async () => {
      const { data } = await api.GET(
        "/api/v1/hitl/topics/{version}/{topic_id}/examples",
        {
          params: {
            path: { version: version as string, topic_id: topicId },
            query: { n: 5 },
          },
        },
      );
      if (!data) throw new Error("Respuesta vacía de los ejemplos");
      return data;
    },
    staleTime: 15 * 60_000,
  });
}

export function useCurateTopic(version: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (args: { topicId: number; body: TopicCurationIn }) => {
      const { data } = await api.POST(
        "/api/v1/hitl/topics/{version}/{topic_id}",
        {
          params: { path: { version, topic_id: args.topicId } },
          body: args.body,
        },
      );
      if (!data) throw new Error("Respuesta vacía al curar");
      return data;
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["hitl", "topics"] }),
  });
}
