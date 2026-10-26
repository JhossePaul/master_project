import {
  BarChart3,
  BookOpen,
  Home,
  ListChecks,
  type LucideIcon,
  Search,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Tags,
  TrendingUp,
  Waypoints,
} from "lucide-react";

export type Role = "lector" | "analista" | "revisor" | "administrador";
export type Audience = "ejecutivo" | "analista" | "academico" | "tecnico";
export type NavGroup =
  | "Dashboard"
  | "Investigar"
  | "Revisar"
  | "Operar"
  | "Configurar"
  | "Documentación";

export interface NavItem {
  path: string;
  label: string;
  group: NavGroup;
  icon: LucideIcon;
  role: Role;
  /** Para qué sirve; lo usa la landing en sus accesos. */
  purpose: string;
  /** Registro del lenguaje de la sección (guía visual, sección 10). */
  audience: Audience;
}

export const NAV_GROUPS: NavGroup[] = [
  "Dashboard",
  "Investigar",
  "Revisar",
  "Operar",
  "Configurar",
  "Documentación",
];

export const NAV_ITEMS: NavItem[] = [
  {
    path: "/",
    label: "Inicio",
    group: "Dashboard",
    icon: Home,
    role: "lector",
    audience: "ejecutivo",
    purpose: "Estado de los datos y de cada banco.",
  },
  {
    path: "/cockpit",
    label: "Cockpit",
    group: "Dashboard",
    icon: BarChart3,
    role: "lector",
    audience: "analista",
    purpose: "Comparación entre bancos y estrellas contra texto.",
  },
  {
    path: "/evolucion",
    label: "Evolución",
    group: "Dashboard",
    icon: TrendingUp,
    role: "lector",
    audience: "analista",
    purpose: "Series diarias, mensuales y por versión de la app.",
  },
  {
    path: "/topicos",
    label: "Tópicos",
    group: "Dashboard",
    icon: Tags,
    role: "lector",
    audience: "analista",
    purpose: "De qué hablan las reseñas negativas: familias y tópicos.",
  },
  {
    path: "/explorador",
    label: "Explorador",
    group: "Investigar",
    icon: Search,
    role: "analista",
    audience: "analista",
    purpose: "Buscar y leer reseñas con su explicación.",
  },
  {
    path: "/alertas",
    label: "Alertas",
    group: "Investigar",
    icon: ShieldAlert,
    role: "analista",
    audience: "analista",
    purpose: "Avisos de cambios en las reseñas o en el modelo.",
  },
  {
    path: "/hitl",
    label: "Revisión",
    group: "Revisar",
    icon: ListChecks,
    role: "revisor",
    audience: "analista",
    purpose: "Casos que una persona debe revisar.",
  },
  {
    path: "/mlops",
    label: "MLOps y AIOps",
    group: "Operar",
    icon: Waypoints,
    role: "analista",
    audience: "tecnico",
    purpose: "Modelo vigente, corridas y estado del pipeline.",
  },
  {
    path: "/admin",
    label: "Administración",
    group: "Configurar",
    icon: Settings,
    role: "administrador",
    audience: "tecnico",
    purpose: "Políticas, umbrales y muestras.",
  },
  {
    path: "/reporte",
    label: "Reporte",
    group: "Documentación",
    icon: BookOpen,
    role: "lector",
    audience: "academico",
    purpose: "La tesis con sus cifras vigentes.",
  },
  {
    path: "/gobernanza",
    label: "Gobernanza",
    group: "Documentación",
    icon: ShieldCheck,
    role: "lector",
    audience: "academico",
    purpose: "Fichas de los datos y del modelo, y matriz de riesgos.",
  },
];

/** Secciones que muestran la barra de filtros globales. */
export const FILTER_PATHS = [
  "/cockpit",
  "/evolucion",
  "/topicos",
  "/explorador",
  "/alertas",
];

/** Parámetros de la URL que viajan al cambiar de sección (los globales y el KPI). */
export const SHARED_PARAMS = ["bancos", "desde", "hasta", "kpi"];

export const PORTAL_NAME = "VoC Analyzer";
