import {
  BarChart3,
  BookOpen,
  Home,
  ListChecks,
  type LucideIcon,
  Search,
  Settings,
  ShieldAlert,
  Waypoints,
} from "lucide-react";

export type Role = "lector" | "analista" | "revisor" | "administrador";
export type Audience = "ejecutivo" | "analista" | "academico" | "tecnico";
export type NavGroup =
  | "Consultar"
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
  "Consultar",
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
    group: "Consultar",
    icon: Home,
    role: "lector",
    audience: "ejecutivo",
    purpose: "Estado de los datos y de cada banco.",
  },
  {
    path: "/cockpit",
    label: "Cockpit",
    group: "Consultar",
    icon: BarChart3,
    role: "lector",
    audience: "analista",
    purpose: "Series diarias, comparaciones y temas por día.",
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
];

/** Secciones que muestran la barra de filtros globales. */
export const FILTER_PATHS = ["/cockpit", "/explorador", "/alertas"];

export const PORTAL_NAME = "VoC Analyzer";
