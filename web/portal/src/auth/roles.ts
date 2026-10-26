import type { components } from "@/api/schema";
import type { Role } from "@/config/nav";

export type Me = components["schemas"]["MeResponse"];

/** Mismas reglas de la API: todo rol incluye al lector y el administrador al analista. */
export function hasRole(
  me: Pick<Me, "roles"> | undefined,
  role: Role,
): boolean {
  if (!me) return false;
  const roles = me.roles as string[];
  if (role === "lector") return roles.length > 0;
  if (roles.includes(role)) return true;
  return role === "analista" && roles.includes("administrador");
}
