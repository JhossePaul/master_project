import { lazy, Suspense } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useParam } from "@/sections/cockpit/params";

const RiskTab = lazy(() => import("./RiskTab"));
const DriftTab = lazy(() => import("./DriftTab"));
const HistoryTab = lazy(() => import("./HistoryTab"));
const GoldTab = lazy(() => import("./GoldTab"));

const TABS = [
  ["riesgo", "Apetito de riesgo", RiskTab],
  ["deriva", "Deriva por banco", DriftTab],
  ["historial", "Historial", HistoryTab],
  ["oro", "Oro", GoldTab],
] as const;

const TAB_PARAM = /^(riesgo|deriva|historial|oro)$/;

export default function AdminView() {
  const [tab, setTab] = useParam("tab", TAB_PARAM);
  const active = tab ?? "riesgo";
  return (
    <div className="grid gap-6">
      <h1 className="sr-only">Administración</h1>
      <Tabs value={active} onValueChange={setTab}>
        <TabsList aria-label="Secciones de administración">
          {TABS.map(([id, label]) => (
            <TabsTrigger key={id} value={id}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
        {TABS.map(([id, , Content]) => (
          <TabsContent key={id} value={id} className="pt-6">
            <Suspense fallback={<Skeleton className="h-64 w-full" />}>
              <Content />
            </Suspense>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
