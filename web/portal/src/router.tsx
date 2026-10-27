import { lazy, type ReactNode, Suspense } from "react";
import { createBrowserRouter, type RouteObject } from "react-router";
import { RequireRole } from "@/auth/RequireRole";
import { AppShell } from "@/components/AppShell";
import { Skeleton } from "@/components/ui/skeleton";
import type { Role } from "@/config/nav";
import { NotFound, UnderConstruction } from "@/sections/Placeholder";

function guarded(role: Role, title: string): RouteObject["element"] {
  return (
    <RequireRole role={role}>
      <UnderConstruction title={title} />
    </RequireRole>
  );
}

const HitlHome = lazy(() => import("@/sections/hitl/HitlHome"));
const SentimentReview = lazy(() => import("@/sections/hitl/SentimentReview"));
const AspectsReview = lazy(() => import("@/sections/hitl/AspectsReview"));
const TopicsCuration = lazy(() => import("@/sections/hitl/TopicsCuration"));
const AlertsInbox = lazy(() => import("@/sections/alerts/AlertsInbox"));
const AlertDetail = lazy(() => import("@/sections/alerts/AlertDetail"));
const AdminView = lazy(() => import("@/sections/admin/AdminView"));
const REVIEWER: Role = "revisor";
const ANALYST: Role = "analista";
const ADMIN: Role = "administrador";
const ExplorerView = lazy(() => import("@/sections/explorer/ExplorerView"));

function AnalystOnly({ children }: { children: ReactNode }) {
  return (
    <RequireRole role={ANALYST}>
      <Suspense fallback={<Skeleton className="h-32 w-full" />}>
        {children}
      </Suspense>
    </RequireRole>
  );
}

function ReviewerOnly({ children }: { children: ReactNode }) {
  return (
    <RequireRole role={REVIEWER}>
      <Suspense fallback={<Skeleton className="h-32 w-full" />}>
        {children}
      </Suspense>
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
          Component: (await import("@/sections/cockpit/CockpitView")).default,
        }),
      },
      {
        path: "evolucion",
        lazy: async () => ({
          Component: (await import("@/sections/cockpit/EvolutionView")).default,
        }),
      },
      {
        path: "topicos",
        lazy: async () => ({
          Component: (await import("@/sections/cockpit/TopicsView")).default,
        }),
      },
      {
        path: "explorador",
        element: (
          <AnalystOnly>
            <ExplorerView />
          </AnalystOnly>
        ),
      },
      {
        path: "alertas",
        element: (
          <AnalystOnly>
            <AlertsInbox />
          </AnalystOnly>
        ),
      },
      {
        path: "alertas/:alertId",
        element: (
          <AnalystOnly>
            <AlertDetail />
          </AnalystOnly>
        ),
      },
      {
        path: "hitl",
        element: (
          <ReviewerOnly>
            <HitlHome />
          </ReviewerOnly>
        ),
      },
      {
        path: "hitl/sentimiento",
        element: (
          <ReviewerOnly>
            <SentimentReview />
          </ReviewerOnly>
        ),
      },
      {
        path: "hitl/aspectos",
        element: (
          <ReviewerOnly>
            <AspectsReview />
          </ReviewerOnly>
        ),
      },
      {
        path: "hitl/topicos",
        element: (
          <ReviewerOnly>
            <TopicsCuration />
          </ReviewerOnly>
        ),
      },
      { path: "mlops", element: guarded("analista", "MLOps y AIOps") },
      {
        path: "admin",
        element: (
          <RequireRole role={ADMIN}>
            <Suspense fallback={<Skeleton className="h-32 w-full" />}>
              <AdminView />
            </Suspense>
          </RequireRole>
        ),
      },
      { path: "gobernanza", element: guarded("lector", "Gobernanza") },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
