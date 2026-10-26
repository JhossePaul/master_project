import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

export function useLanding() {
  return useQuery({
    queryKey: ["landing"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/landing");
      if (!data) throw new Error("Respuesta vacía de /landing");
      return data;
    },
    staleTime: 5 * 60_000,
  });
}
