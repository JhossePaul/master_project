import { PanelLeftClose, PanelLeftOpen, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { ApiError } from "@/api/client";
import { useMe } from "@/api/me";
import { hasRole } from "@/auth/roles";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { ExplorerProvider } from "@/components/ExplorerLink";
import { FilterBar } from "@/components/FilterBar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DASHBOARD_PATHS,
  FILTER_PATHS,
  NAV_GROUPS,
  NAV_ITEMS,
  PORTAL_NAME,
  SHARED_PARAMS,
} from "@/config/nav";
import { cn } from "@/lib/utils";

/** Solo los parámetros que valen en cualquier sección. */
function sharedSearch(search: string): string {
  const from = new URLSearchParams(search);
  const out = new URLSearchParams();
  for (const name of SHARED_PARAMS) {
    const value = from.get(name);
    if (value) out.set(name, value);
  }
  const text = out.toString();
  return text ? `?${text}` : "";
}

const COLLAPSE_KEY = "voc.nav.collapsed";

function initialCollapsed(): boolean {
  try {
    const stored = localStorage.getItem(COLLAPSE_KEY);
    if (stored !== null) return stored === "1";
  } catch {
    // Sin almacenamiento: se usa el ancho de la ventana.
  }
  return typeof window !== "undefined" && window.innerWidth < 1280;
}

export function AppShell() {
  const me = useMe();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(initialCollapsed);

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      // No es dato sensible; si falla, no se recuerda.
    }
  }, [collapsed]);

  if (me.isPending) return <Skeleton className="m-8 h-40" />;
  if (me.isError) {
    if (me.error instanceof ApiError && me.error.status === 403) {
      return (
        <main className="mx-auto max-w-xl p-10">
          <EmptyState
            title="Tu cuenta no tiene acceso al portal"
            description="Pide acceso al autor del portal."
          />
        </main>
      );
    }
    return (
      <main className="mx-auto max-w-xl p-10">
        <ErrorState error={me.error} onRetry={() => me.refetch()} />
      </main>
    );
  }

  const user = me.data;
  const showFilters = FILTER_PATHS.some((p) => location.pathname.startsWith(p));
  // El Explorador es de analistas: el enlace solo sale en el Dashboard y para ellos.
  const explore =
    hasRole(user, "analista") &&
    DASHBOARD_PATHS.some((p) => location.pathname.startsWith(p));

  return (
    <ExplorerProvider>
      <div className="flex min-h-screen flex-col">
        <a
          href="#contenido"
          className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-surface focus:p-2"
        >
          Saltar al contenido
        </a>
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between bg-green-900 px-6 text-neutral-0">
          <Link to="/" className="font-serif text-lg font-semibold">
            {PORTAL_NAME}
          </Link>
          <div className="flex items-center gap-4 text-sm">
            {user.environment !== "prod" ? (
              <Badge className="bg-gold-400 text-neutral-950">
                {user.environment}
              </Badge>
            ) : null}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-neutral-0 hover:bg-green-800"
                >
                  Cuenta
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>{user.email}</DropdownMenuLabel>
                <DropdownMenuLabel className="flex items-center gap-1">
                  <UserRound className="size-3" aria-hidden="true" />
                  Roles: {user.roles.join(", ")}
                </DropdownMenuLabel>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <div className="flex flex-1">
          <nav
            aria-label="Secciones"
            className={cn(
              "sticky top-14 h-[calc(100vh-3.5rem)] shrink-0 self-start overflow-y-auto border-r border-border bg-surface p-3 transition-[width]",
              collapsed ? "w-16" : "w-60",
            )}
          >
            <Button
              variant="ghost"
              size="icon"
              className="mb-2"
              aria-label={
                collapsed ? "Expandir navegación" : "Plegar navegación"
              }
              onClick={() => setCollapsed((v) => !v)}
            >
              {collapsed ? (
                <PanelLeftOpen aria-hidden="true" />
              ) : (
                <PanelLeftClose aria-hidden="true" />
              )}
            </Button>
            {NAV_GROUPS.map((group) => {
              const items = NAV_ITEMS.filter(
                (i) => i.group === group && hasRole(user, i.role),
              );
              if (items.length === 0) return null;
              return (
                <div key={group} className="mb-3">
                  {collapsed ? null : (
                    <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-[0.08em] text-neutral-800">
                      {group}
                    </p>
                  )}
                  <ul>
                    {items.map(({ path, label, icon: Icon }) => (
                      <li key={path}>
                        <NavLink
                          to={{
                            pathname: path,
                            search: sharedSearch(location.search),
                          }}
                          end={path === "/"}
                          title={label}
                          className={({ isActive }) =>
                            cn(
                              "flex items-center gap-3 border-l-[3px] border-transparent px-3 py-2 text-sm",
                              isActive
                                ? "border-green-600 bg-green-50 font-semibold text-green-800"
                                : "hover:bg-neutral-100",
                            )
                          }
                        >
                          <Icon
                            className="size-4 shrink-0"
                            aria-hidden="true"
                          />
                          <span className={collapsed ? "sr-only" : undefined}>
                            {label}
                          </span>
                        </NavLink>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </nav>
          <div className="min-w-0 flex-1">
            {showFilters ? <FilterBar explore={explore} /> : null}
            <main
              id="contenido"
              className="mx-auto w-full max-w-[1440px] px-6 py-6 xl:px-8"
            >
              <Outlet context={user} />
            </main>
          </div>
        </div>
      </div>
    </ExplorerProvider>
  );
}
