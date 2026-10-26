import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";
import type { BankId } from "@/config/banks";

export type AlertRow = components["schemas"]["AlertRow"];
export type AlertDetail = components["schemas"]["AlertDetail"];
export type AlertEventIn = components["schemas"]["AlertEventIn"];
export type AlertEventOut = components["schemas"]["AlertEventOut"];
export type AlertStatus = AlertRow["status"];
export type SeriesPoint = components["schemas"]["SeriesPoint"];

/** Las alertas cambian con cada análisis: siempre frescas. */
export function useAlerts(status: AlertStatus | null, banks: BankId[]) {
  return useQuery({
    queryKey: ["alerts", "list", status, banks],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/alerts", {
        params: {
          query: {
            status,
            bank: banks.length > 0 ? banks : undefined,
          },
        },
      });
      if (!data) throw new Error("Respuesta vacía de /alerts");
      return data;
    },
    staleTime: 0,
  });
}

export function useAlert(alertId: string) {
  return useQuery({
    queryKey: ["alerts", "detail", alertId],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/alerts/{alert_id}", {
        params: { path: { alert_id: alertId } },
      });
      if (!data) throw new Error("Respuesta vacía de la alerta");
      return data;
    },
    staleTime: 0,
  });
}

/** Registra la transición; responde con la alerta ya actualizada. */
export function useAlertEvent(alertId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: AlertEventIn) => {
      const { data } = await api.POST("/api/v1/alerts/{alert_id}/events", {
        params: { path: { alert_id: alertId } },
        body,
      });
      if (!data) throw new Error("Respuesta vacía al guardar");
      return data;
    },
    onSuccess: (detail) => {
      client.setQueryData(["alerts", "detail", alertId], detail);
      void client.invalidateQueries({ queryKey: ["alerts", "list"] });
      void client.invalidateQueries({ queryKey: ["landing"] });
    },
    onError: () => {
      // Un 409 quiere decir que el estado cambió: se vuelve a leer.
      void client.invalidateQueries({ queryKey: ["alerts"] });
    },
  });
}
