import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";

type S = components["schemas"];
export type RiskPolicy = S["RiskPolicy"];
export type RiskPolicyResponse = S["RiskPolicyResponse"];
export type CoverageCurveResponse = S["CoverageCurveResponse"];
export type CoveragePoint = S["CoveragePoint"];
export type RiskPreview = S["RiskPreview"];
export type FieldDiff = S["FieldDiff"];
export type DriftPolicy = S["DriftPolicy"];
export type DriftPolicyResponse = S["DriftPolicyResponse"];
export type DriftThresholds = S["DriftThresholds"];
export type DriftRatesResponse = S["DriftRatesResponse"];
export type SeriesRate = S["SeriesRate"];
export type GoldCriteria = S["GoldCriteria"];
export type GoldPreview = S["GoldPreview"];
export type GoldVersionOut = S["GoldVersionOut"];
export type GoldItemsResponse = S["GoldItemsResponse"];
export type Changes = { [key: string]: unknown };

function required<T>(data: T | undefined, name: string): T {
  if (data === undefined) throw new Error(`Respuesta vacía de ${name}`);
  return data;
}

// Las políticas son decisiones recientes: nunca se sirven de la caché.
const FRESH = { staleTime: 0, gcTime: 0 } as const;

export function useRiskPolicy() {
  return useQuery({
    queryKey: ["admin", "risk-policy"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/admin/risk-policy");
      return required(data, "/admin/risk-policy");
    },
    ...FRESH,
  });
}

export function useCoverageCurve() {
  return useQuery({
    queryKey: ["admin", "coverage-curve"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/admin/coverage-curve", {
        params: { query: {} },
      });
      return required(data, "/admin/coverage-curve");
    },
    staleTime: 5 * 60_000,
  });
}

export async function previewRisk(
  baseVersion: string,
  changes: Changes,
): Promise<RiskPreview> {
  const { data } = await api.POST("/api/v1/admin/risk-policy/preview", {
    body: { base_version: baseVersion, changes },
  });
  return required(data, "/admin/risk-policy/preview");
}

export function useSaveRisk() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      base_version: string;
      changes: Changes;
      reason: string;
      confirm_word?: string | null;
    }) => {
      const { data } = await api.POST("/api/v1/admin/risk-policy", { body });
      return required(data, "/admin/risk-policy");
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin"] }),
  });
}

export function useDriftPolicy(bank: string) {
  return useQuery({
    queryKey: ["admin", "drift-policy", bank],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/admin/drift-policy", {
        params: { query: { bank } },
      });
      return required(data, "/admin/drift-policy");
    },
    ...FRESH,
  });
}

export function useDriftRates(bank: string, thresholds: DriftThresholds) {
  return useQuery({
    queryKey: ["admin", "drift-rates", bank, thresholds],
    queryFn: async () => {
      const { data } = await api.POST("/api/v1/admin/drift-policy/rates", {
        body: { bank, thresholds },
      });
      return required(data, "/admin/drift-policy/rates");
    },
    staleTime: 60_000,
  });
}

export function useSaveDrift() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      bank: string;
      base_version: string;
      changes: Changes;
      reason: string;
    }) => {
      const { data } = await api.POST("/api/v1/admin/drift-policy", { body });
      return required(data, "/admin/drift-policy");
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin"] }),
  });
}

export function useGoldVersions() {
  return useQuery({
    queryKey: ["admin", "gold-versions"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/admin/gold-versions");
      return required(data, "/admin/gold-versions");
    },
    ...FRESH,
  });
}

export async function previewGold(
  criteria: GoldCriteria,
): Promise<GoldPreview> {
  const { data } = await api.POST("/api/v1/admin/gold-versions/preview", {
    body: criteria,
  });
  return required(data, "/admin/gold-versions/preview");
}

export function useCreateGold() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: { criteria: GoldCriteria; reason: string }) => {
      const { data } = await api.POST("/api/v1/admin/gold-versions", { body });
      return required(data, "/admin/gold-versions");
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin", "gold-versions"] }),
  });
}

export function useGoldItems(version: string | null) {
  return useQuery({
    queryKey: ["admin", "gold-items", version],
    enabled: version !== null,
    queryFn: async () => {
      const { data } = await api.GET(
        "/api/v1/admin/gold-versions/{gold_version}/items",
        { params: { path: { gold_version: version as string } } },
      );
      return required(data, "/admin/gold-versions/items");
    },
    staleTime: 5 * 60_000,
  });
}

export type SampleBatch = components["schemas"]["SampleBatchOut"];

export function useSampleBatches() {
  return useQuery({
    queryKey: ["admin", "samples"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/admin/samples");
      return required(data, "/admin/samples");
    },
    staleTime: 0,
  });
}

export function useCreateAspectsSample() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      size: number;
      months: number;
      reason: string;
    }) => {
      const { data } = await api.POST("/api/v1/admin/samples/aspects", {
        body,
      });
      return required(data, "/admin/samples/aspects");
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin", "samples"] }),
  });
}
