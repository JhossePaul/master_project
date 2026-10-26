import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { syntheticMe } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

async function menuFor(roles: string[]) {
  server.use(
    http.get("*/api/v1/me", () =>
      HttpResponse.json(syntheticMe({ roles: roles as never })),
    ),
  );
  renderApp("/");
  const nav = await screen.findByRole("navigation", { name: "Secciones" });
  return within(nav)
    .getAllByRole("link")
    .map((a) => a.textContent);
}

describe("navegación por rol", () => {
  it("lector", async () =>
    expect(await menuFor(["lector"])).toEqual([
      "Inicio",
      "Reporte",
      "Cockpit",
    ]));

  it("analista", async () =>
    expect(await menuFor(["lector", "analista"])).toEqual([
      "Inicio",
      "Reporte",
      "Cockpit",
      "Explorador",
      "Alertas",
      "MLOps y AIOps",
    ]));

  it("revisor", async () =>
    expect(await menuFor(["lector", "revisor"])).toEqual([
      "Inicio",
      "Reporte",
      "Cockpit",
      "Revisión",
    ]));

  it("administrador ve todo, incluido lo del analista", async () =>
    expect(await menuFor(["lector", "administrador"])).toEqual([
      "Inicio",
      "Reporte",
      "Cockpit",
      "Explorador",
      "Alertas",
      "MLOps y AIOps",
      "Administración",
    ]));

  it("conserva los filtros al navegar", async () => {
    server.use(http.get("*/api/v1/me", () => HttpResponse.json(syntheticMe())));
    renderApp("/?bancos=BBVA");
    const link = await screen.findByRole("link", { name: "Cockpit" });
    expect(link.getAttribute("href")).toBe("/cockpit?bancos=BBVA");
  });
});
