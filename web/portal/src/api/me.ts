import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/me");
      if (!data) throw new Error("Respuesta vacía de /me");
      return data;
    },
    staleTime: 5 * 60_000,
    retry: false,
  });
}
