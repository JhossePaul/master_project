import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { syntheticLanding, syntheticMe } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

describe("landing", () => {
  it("muestra el resumen de los cinco bancos con su intervalo, la frescura y las alertas", async () => {
    renderApp("/");

    expect(
      await screen.findByRole("heading", { level: 1, name: /VoC Analyzer/ }),
    ).toBeInTheDocument();
    for (const name of [
      "Banco Azul",
      "Banco Verde",
      "Banco Rojo",
      "Banco Morado",
      "Banco Gris",
    ]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    expect(
      screen.getByRole("heading", { name: "Resumen" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: /Banco Azul/ }).length).toBe(2);
    expect(screen.getAllByText("entre 14.0 % y 16.0 %").length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText(/Datos al 24 oct 2026/)).toBeInTheDocument();

    const fresh = screen
      .getByRole("heading", { name: "Última actualización" })
      .closest("div")?.parentElement as HTMLElement;
    expect(within(fresh).getByText("Reseñas nuevas")).toBeInTheDocument();
    expect(within(fresh).getByText("Revisión del modelo")).toBeInTheDocument();
    expect(within(fresh).getAllByText("ok").length).toBe(3);

    const alerts = screen
      .getByRole("heading", { name: "Alertas de cambios abiertas" })
      .closest("div")?.parentElement as HTMLElement;
    expect(within(alerts).getByText("Banco Morado")).toBeInTheDocument();
  });

  it("marca aviso cuando una corrida está vencida", async () => {
    const old = "2026-01-01T00:00:00Z";
    const base = syntheticLanding();
    server.use(
      http.get("*/api/v1/landing", () =>
        HttpResponse.json({
          ...base,
          freshness: { ...base.freshness, last_ingestion_at: old },
        }),
      ),
    );
    renderApp("/");
    expect(await screen.findAllByText("aviso")).not.toHaveLength(0);
  });

  it("los casos HITL solo salen para quien los puede revisar", async () => {
    server.use(
      http.get("*/api/v1/landing", () =>
        HttpResponse.json(syntheticLanding({ hitl_pending: null })),
      ),
    );
    renderApp("/");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText("Casos por revisar")).not.toBeInTheDocument();
  });

  it("sin PPI en ningún mes cerrado, la tarjeta lo dice", async () => {
    server.use(
      http.get("*/api/v1/landing", () =>
        HttpResponse.json(syntheticLanding({ banks: [] })),
      ),
    );
    renderApp("/");
    expect(
      (await screen.findAllByText(/Sin cifra con revisión humana/)).length,
    ).toBe(5);
  });

  it("un error muestra ErrorState con el request_id", async () => {
    server.use(
      http.get("*/api/v1/landing", () =>
        HttpResponse.json(
          {
            error: {
              code: "upstream",
              message: "BigQuery no pudo responder",
              request_id: "req-123",
            },
          },
          { status: 502 },
        ),
      ),
    );
    renderApp("/");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "BigQuery no pudo responder",
    );
    expect(screen.getByText("req-123")).toBeInTheDocument();
  });

  it("403 en /me: pantalla completa sin acceso", async () => {
    server.use(
      http.get("*/api/v1/me", () =>
        HttpResponse.json(
          { error: { code: "forbidden", message: "x", request_id: "r" } },
          { status: 403 },
        ),
      ),
    );
    renderApp("/");
    expect(
      await screen.findByText("Tu cuenta no tiene acceso al portal"),
    ).toBeInTheDocument();
  });

  it("una sección sin el rol dice que no hay acceso", async () => {
    server.use(
      http.get("*/api/v1/me", () =>
        HttpResponse.json(syntheticMe({ roles: ["lector"] })),
      ),
    );
    renderApp("/admin");
    expect(
      await screen.findByText("No tienes acceso a esta sección"),
    ).toBeInTheDocument();
  });

  it("una ruta desconocida muestra la página no encontrada", async () => {
    renderApp("/no-existe");
    expect(
      await screen.findByRole("heading", { name: "Página no encontrada" }),
    ).toBeInTheDocument();
  });
});
