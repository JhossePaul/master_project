import { lazy, Suspense } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useParam } from "@/sections/cockpit/params";

const ModelTab = lazy(() => import("./ModelTab"));
const DriftTab = lazy(() => import("./DriftTab"));
const RegistryTab = lazy(() => import("./RegistryTab"));
const PipelineTab = lazy(() => import("./PipelineTab"));

const TABS = [
  ["modelo", "Modelo", ModelTab],
  ["deriva", "Deriva", DriftTab],
  ["registro", "Registro y acciones", RegistryTab],
  ["pipeline", "Pipeline", PipelineTab],
] as const;

const TAB_PARAM = /^(modelo|deriva|registro|pipeline)$/;

export default function MlopsView() {
  const [tab, setTab] = useParam("tab", TAB_PARAM);
  const active = tab ?? "modelo";
  return (
    <div className="grid gap-6">
      <h1 className="sr-only">MLOps y AIOps</h1>
      <Tabs value={active} onValueChange={setTab}>
        <TabsList aria-label="Secciones de MLOps">
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
