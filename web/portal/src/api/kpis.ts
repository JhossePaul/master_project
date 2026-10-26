import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";
import type { BankId } from "@/config/banks";

export type BankCard = components["schemas"]["BankCard"];
export type DailyPoint = components["schemas"]["DailyPoint"];
export type DailyTopics = components["schemas"]["DailyTopics"];
export type MonthlyKpi = components["schemas"]["MonthlyKpi"];
export type FamiliesResponse = components["schemas"]["FamiliesResponse"];
export type FamilyMonth = components["schemas"]["FamilyMonth"];
export type TopicMonth = components["schemas"]["TopicMonth"];
export type MatrixCell = components["schemas"]["MatrixCell"];
export type VersionsResponse = components["schemas"]["VersionsResponse"];
export type VersionRow = components["schemas"]["VersionRow"];
export type VersionDailyResponse =
  components["schemas"]["VersionDailyResponse"];
export type SentimentFilter = "ALL" | "NEG" | "NEU" | "POS";
export type ModelChange = components["schemas"]["ModelChange"];

const STALE = 5 * 60_000;

function required<T>(data: T | undefined, name: string): T {
  if (data === undefined) throw new Error(`Respuesta vacía de ${name}`);
  return data;
}

export function useCards(banks: BankId[]) {
  return useQuery({
    queryKey: ["kpis", "cards", banks],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/kpis/cards", {
        params: { query: { banks } },
      });
      return required(data, "/kpis/cards");
    },
    staleTime: STALE,
  });
}

export function useDaily(banks: BankId[], from: string, to: string) {
  return useQuery({
    queryKey: ["kpis", "daily", banks, from, to],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/kpis/daily", {
        params: { query: { banks, date_from: from, date_to: to } },
      });
      return required(data, "/kpis/daily");
    },
    staleTime: STALE,
  });
}

export function useDailyTopics(bank: BankId, day: string | null) {
  return useQuery({
    queryKey: ["kpis", "daily-topics", bank, day],
    enabled: day !== null,
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/kpis/daily-topics", {
        params: { query: { bank, day: day as string } },
      });
      return required(data, "/kpis/daily-topics");
    },
    staleTime: STALE,
  });
}

export function useMonthly(banks: BankId[]) {
  return useQuery({
    queryKey: ["kpis", "monthly", banks],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/kpis/monthly", {
        params: { query: { banks, metrics: "neg,gap_estrellas" } },
      });
      return required(data, "/kpis/monthly");
    },
    staleTime: STALE,
  });
}

export function useFamilies(banks: BankId[]) {
  return useQuery({
    queryKey: ["kpis", "families", banks],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/kpis/families", {
        params: { query: { banks } },
      });
      return required(data, "/kpis/families");
    },
    staleTime: STALE,
  });
}

export function useTopics(banks: BankId[]) {
  return useQuery({
    queryKey: ["kpis", "topics", banks],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/kpis/topics", {
        params: { query: { banks } },
      });
      return required(data, "/kpis/topics");
    },
    staleTime: STALE,
  });
}

export function useMatrix(bank: BankId, period: string | null) {
  return useQuery({
    queryKey: ["kpis", "matrix", bank, period],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/kpis/matrix", {
        params: { query: { banks: [bank], period } },
      });
      return required(data, "/kpis/matrix");
    },
    staleTime: STALE,
  });
}

export function useVersions(bank: BankId) {
  return useQuery({
    queryKey: ["kpis", "versions", bank],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/kpis/versions", {
        params: { query: { bank } },
      });
      return required(data, "/kpis/versions");
    },
    staleTime: STALE,
  });
}

export function useVersionDaily(
  bank: BankId,
  from: string,
  to: string,
  sentiment: SentimentFilter,
) {
  return useQuery({
    queryKey: ["kpis", "versions-daily", bank, from, to, sentiment],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/kpis/versions/daily", {
        params: {
          query: { bank, date_from: from, date_to: to, sentiment },
        },
      });
      return required(data, "/kpis/versions/daily");
    },
    staleTime: STALE,
  });
}

export function useModelChanges() {
  return useQuery({
    queryKey: ["kpis", "model-changes"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/kpis/model-changes");
      return required(data, "/kpis/model-changes");
    },
    staleTime: STALE,
  });
}
