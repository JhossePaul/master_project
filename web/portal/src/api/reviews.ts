import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError, api } from "@/api/client";
import type { components } from "@/api/schema";

export type ReviewRow = components["schemas"]["ReviewRow"];
export type ReviewPage = components["schemas"]["ReviewPage"];
export type Facets = components["schemas"]["Facets"];
export type FacetCount = components["schemas"]["FacetCount"];
export type ReviewDetail = components["schemas"]["ReviewDetail"];
export type SearchResponse = components["schemas"]["SearchResponse"];
export type SearchHit = components["schemas"]["SearchHit"];
export type Explanation = components["schemas"]["ExplanationOut"];
export type Attribution = components["schemas"]["Attribution"];
export type SortKey = "fecha_desc" | "confidence_asc" | "estrellas_asc";

/** Filtros del Explorador tal como los entiende la API. */
export interface ReviewQuery {
  banks: string[];
  date_from: string;
  date_to: string;
  sentiment: string[];
  stars: number[];
  families: string[];
  flag_update?: boolean;
  flag_security?: boolean;
  topic_id?: number;
  hitl_reviewed?: boolean;
  version?: string;
}

function queryParams(q: ReviewQuery) {
  return {
    banks: q.banks as never,
    date_from: q.date_from,
    date_to: q.date_to,
    sentiment: q.sentiment.length > 0 ? (q.sentiment as never) : undefined,
    stars: q.stars.length > 0 ? q.stars : undefined,
    families: q.families.length > 0 ? q.families : undefined,
    flag_update: q.flag_update,
    flag_security: q.flag_security,
    topic_id: q.topic_id,
    hitl_reviewed: q.hitl_reviewed,
    version: q.version,
  };
}

export function useFacets(q: ReviewQuery) {
  return useQuery({
    queryKey: ["reviews", "facets", q],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/reviews/facets", {
        params: { query: queryParams(q) },
      });
      if (!data) throw new Error("Respuesta vacía de /reviews/facets");
      return data;
    },
    staleTime: 60_000,
    placeholderData: (previous) => previous,
  });
}

export function useReviewPage(q: ReviewQuery, page: number, sort: SortKey) {
  return useQuery({
    queryKey: ["reviews", "page", q, page, sort],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/reviews", {
        params: { query: { ...queryParams(q), page, sort } },
      });
      if (!data) throw new Error("Respuesta vacía de /reviews");
      return data;
    },
    staleTime: 60_000,
    placeholderData: (previous) => previous,
  });
}

export function useReviewDetail(bank: string | null, id: string | null) {
  return useQuery({
    queryKey: ["reviews", "detail", bank, id],
    enabled: bank !== null && id !== null,
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/reviews/{bank_id}/{id_resena}", {
        params: { path: { bank_id: bank as never, id_resena: id as string } },
      });
      if (!data) throw new Error("Respuesta vacía de la ficha");
      return data;
    },
    staleTime: 60_000,
  });
}

/** La consulta viaja en el cuerpo y nunca se guarda en la caché ni en la URL. */
export function useSearch() {
  return useMutation({
    mutationFn: async (body: {
      query: string;
      banks: string[];
      k: number;
    }): Promise<SearchResponse> => {
      const { data } = await api.POST("/api/v1/reviews/search", {
        body: { ...body, banks: body.banks as never },
      });
      if (!data) throw new Error("Respuesta vacía de la búsqueda");
      return data;
    },
    gcTime: 0,
  });
}

/** La explicación guardada; `null` si todavía no existe (404). */
export function useStoredExplanation(
  textKey: string | null,
  modelVersion: string | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["explanation", textKey, modelVersion],
    enabled: enabled && textKey !== null,
    retry: false,
    queryFn: async (): Promise<Explanation | null> => {
      try {
        const { data } = await api.GET("/api/v1/explanations/{text_key}", {
          params: {
            path: { text_key: textKey as string },
            query: { model_version: modelVersion ?? undefined },
          },
        });
        return data ?? null;
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    staleTime: 5 * 60_000,
  });
}

export function useComputeExplanation() {
  return useMutation({
    mutationFn: async (row: ReviewRow): Promise<Explanation> => {
      const { data } = await api.POST("/api/v1/explanations/{text_key}", {
        params: { path: { text_key: row.text_key } },
        body: { bank_id: row.bank_id, id_resena: row.id_resena },
      });
      if (!data) throw new Error("Respuesta vacía de la explicación");
      return data;
    },
  });
}
