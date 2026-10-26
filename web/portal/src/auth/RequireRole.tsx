import type { ReactNode } from "react";
import { useMe } from "@/api/me";
import { hasRole } from "@/auth/roles";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import type { Role } from "@/config/nav";

export function RequireRole({
  role,
  children,
}: {
  role: Role;
  children: ReactNode;
}) {
  const me = useMe();
  if (me.isPending) return <Skeleton className="h-32 w-full" />;
  if (!hasRole(me.data, role)) {
    return (
      <EmptyState
        title="No tienes acceso a esta sección"
        description="Pide el rol correspondiente al autor del portal."
      />
    );
  }
  return <>{children}</>;
}
