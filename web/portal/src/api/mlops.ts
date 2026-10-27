import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";

type S = components["schemas"];
export type QualityResponse = S["QualityResponse"];
export type QualitySeries = S["QualitySeries"];
export type QualityPoint = S["QualityPoint"];
export type DriftResponse = S["DriftResponse"];
export type DriftCell = S["DriftCell"];
export type TopicsContextResponse = S["TopicsContextResponse"];
export type ContextSeries = S["ContextSeries"];
export type ModelsResponse = S["ModelsResponse"];
export type ModelOut = S["ModelOut"];
export type ActionState = S["ActionState"];
export type PromotionCheckOut = S["PromotionCheckOut"];
export type CalibrationOut = S["CalibrationOut"];
export type ReliabilityBin = S["ReliabilityBin"];
export type RunsResponse = S["RunsResponse"];
export type RunOut = S["RunOut"];
export type IngestionRunOut = S["IngestionRunOut"];
export type EligibilityRow = S["EligibilityRow"];
export type Action = S["Action"];
export type CoverageCurveResponse = S["CoverageCurveResponse"];

function required<T>(data: T | undefined, name: string): T {
  if (data === undefined) throw new Error(`Respuesta vacía de ${name}`);
  return data;
}

/** Las corridas se vuelven a leer mientras la pantalla está abierta. */
export const RUNS_REFRESH_MS = 30_000;

export function useQuality() {
  return useQuery({
    queryKey: ["mlops", "quality"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/mlops/quality");
      return required(data, "/mlops/quality");
    },
    staleTime: 60_000,
  });
}

/** La curva del modelo promovido o, con `version`, la de una candidata. */
export function useMlopsCurve(version: string | null = null) {
  return useQuery({
    queryKey: ["mlops", "coverage-curve", version],
    retry: false,
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/mlops/coverage-curve", {
        params: { query: { model_version: version } },
      });
      return required(data, "/mlops/coverage-curve");
    },
    staleTime: 5 * 60_000,
  });
}

export function useDrift(metric: string | null) {
  return useQuery({
    queryKey: ["mlops", "drift", metric],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/mlops/drift", {
        params: { query: { metric } },
      });
      return required(data, "/mlops/drift");
    },
    staleTime: 5 * 60_000,
  });
}

export function useTopicsContext() {
  return useQuery({
    queryKey: ["mlops", "topics-context"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/mlops/topics-context");
      return required(data, "/mlops/topics-context");
    },
    staleTime: 5 * 60_000,
  });
}

/** El registro y sus acciones habilitadas: siempre frescos. */
export function useModels() {
  return useQuery({
    queryKey: ["mlops", "models"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/mlops/models");
      return required(data, "/mlops/models");
    },
    staleTime: 0,
  });
}

export function useCalibration(version: string | null) {
  return useQuery({
    queryKey: ["mlops", "calibration", version],
    enabled: version !== null,
    retry: false,
    queryFn: async () => {
      const { data } = await api.GET(
        "/api/v1/mlops/models/{model_version}/calibration",
        { params: { path: { model_version: version as string } } },
      );
      return required(data, "la calibración");
    },
    staleTime: 5 * 60_000,
  });
}

export function useRuns(days = 30) {
  return useQuery({
    queryKey: ["mlops", "runs", days],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/mlops/runs", {
        params: { query: { days } },
      });
      return required(data, "/mlops/runs");
    },
    staleTime: 0,
    refetchInterval: RUNS_REFRESH_MS,
  });
}

export function useIngestion(days = 30) {
  return useQuery({
    queryKey: ["mlops", "ingestion", days],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/mlops/ingestion", {
        params: { query: { days } },
      });
      return required(data, "/mlops/ingestion");
    },
    staleTime: 60_000,
  });
}

export function useEligibility() {
  return useQuery({
    queryKey: ["mlops", "eligibility"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/mlops/eligibility");
      return required(data, "/mlops/eligibility");
    },
    staleTime: 10 * 60_000,
  });
}

export interface ActionRequest {
  action: Action;
  reason: string;
  model_version?: string | null;
  confirm_word?: string | null;
}

export function useRunAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ action, ...body }: ActionRequest) => {
      const { data } = await api.POST("/api/v1/mlops/actions/{action}", {
        params: { path: { action } },
        body,
      });
      return required(data, "la acción");
    },
    // Un 409 quiere decir que el estado cambió: se vuelve a leer.
    onSettled: () => client.invalidateQueries({ queryKey: ["mlops"] }),
  });
}
