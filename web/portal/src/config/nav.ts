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
export type NavGroup =
  | "Consultar"
  | "Investigar"
  | "Revisar"
  | "Operar"
  | "Configurar";

export interface NavItem {
  path: string;
  label: string;
  group: NavGroup;
  icon: LucideIcon;
  role: Role;
  /** Para qué sirve; lo usa la landing en sus accesos. */
  purpose: string;
}

export const NAV_GROUPS: NavGroup[] = [
  "Consultar",
  "Investigar",
  "Revisar",
  "Operar",
  "Configurar",
];

export const NAV_ITEMS: NavItem[] = [
  {
    path: "/",
    label: "Inicio",
    group: "Consultar",
    icon: Home,
    role: "lector",
    purpose: "Estado de los datos y de cada banco.",
  },
  {
    path: "/reporte",
    label: "Reporte",
    group: "Consultar",
    icon: BookOpen,
    role: "lector",
    purpose: "La tesis con sus cifras vigentes.",
  },
  {
    path: "/cockpit",
    label: "Cockpit",
    group: "Consultar",
    icon: BarChart3,
    role: "lector",
    purpose: "Series diarias, comparaciones y temas por día.",
  },
  {
    path: "/explorador",
    label: "Explorador",
    group: "Investigar",
    icon: Search,
    role: "analista",
    purpose: "Buscar y leer reseñas con su explicación.",
  },
  {
    path: "/alertas",
    label: "Alertas",
    group: "Investigar",
    icon: ShieldAlert,
    role: "analista",
    purpose: "Alertas de deriva del modelo y su atención.",
  },
  {
    path: "/hitl",
    label: "HITL",
    group: "Revisar",
    icon: ListChecks,
    role: "revisor",
    purpose: "Cola de casos para revisar.",
  },
  {
    path: "/mlops",
    label: "MLOps y AIOps",
    group: "Operar",
    icon: Waypoints,
    role: "analista",
    purpose: "Modelo vigente, corridas y estado del pipeline.",
  },
  {
    path: "/admin",
    label: "Administración",
    group: "Configurar",
    icon: Settings,
    role: "administrador",
    purpose: "Políticas, umbrales y muestras.",
  },
];

/** Secciones que muestran la barra de filtros globales. */
export const FILTER_PATHS = ["/cockpit", "/explorador", "/alertas"];

export const PORTAL_NAME = "Observatorio de reseñas de apps bancarias";
