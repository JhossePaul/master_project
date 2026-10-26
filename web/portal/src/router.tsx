import { createBrowserRouter, type RouteObject } from "react-router";
import { RequireRole } from "@/auth/RequireRole";
import { AppShell } from "@/components/AppShell";
import type { Role } from "@/config/nav";
import { NotFound, UnderConstruction } from "@/sections/Placeholder";

function guarded(role: Role, title: string): RouteObject["element"] {
  return (
    <RequireRole role={role}>
      <UnderConstruction title={title} />
    </RequireRole>
  );
}

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      {
        index: true,
        lazy: async () => ({
          Component: (await import("@/sections/landing/Landing")).default,
        }),
      },
      { path: "reporte/*", element: guarded("lector", "Reporte de la tesis") },
      {
        path: "cockpit",
        lazy: async () => ({
          Component: (await import("@/sections/cockpit/Cockpit")).default,
        }),
      },
      { path: "explorador", element: guarded("analista", "Explorador") },
      { path: "alertas", element: guarded("analista", "Alertas de deriva") },
      {
        path: "alertas/:alertId",
        element: guarded("analista", "Alerta de deriva"),
      },
      { path: "hitl/*", element: guarded("revisor", "HITL") },
      { path: "mlops", element: guarded("analista", "MLOps y AIOps") },
      { path: "admin", element: guarded("administrador", "Administración") },
      { path: "gobernanza", element: guarded("lector", "Gobernanza") },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
