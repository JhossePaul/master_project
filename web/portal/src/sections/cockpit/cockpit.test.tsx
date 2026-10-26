import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { axe } from "vitest-axe";
import { syntheticMonthly, syntheticTopics } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";
import { shiftMonths } from "./MonthlyBlock";
import { explorerUrl } from "./shared";

const graphs = vi.hoisted(() => ({
  options: [] as Record<string, (...args: unknown[]) => unknown>[],
}));

vi.mock("dygraphs", () => ({
  default: class {
    constructor(_el: unknown, _data: unknown, options: Record<string, never>) {
      graphs.options.push(options);
    }
    ready(fn: () => void) {
      fn();
    }
    setAnnotations() {}
    destroy() {}
  },
}));

function lastOptions() {
  return graphs.options.at(-1) as Record<string, (...a: unknown[]) => unknown>;
}

describe("cockpit, pestaña Diario", () => {
  beforeEach(() => {
    graphs.options.length = 0;
  });

  it("las tarjetas muestran la insignia, el intervalo y el cambio anual", async () => {
    renderApp("/cockpit");

    const title = await screen.findByRole("heading", { name: "Banco Azul" });
    const card = title.closest("div")?.parentElement as HTMLElement;
    expect(within(card).getAllByText("Con revisión humana")).toHaveLength(3);
    expect(within(card).getByText("entre 14.0 % y 16.0 %")).toBeInTheDocument();
    expect(within(card).getByText("entre −0.35 y −0.25")).toBeInTheDocument();
    expect(within(card).getAllByText(/frente a sep 2025/)).toHaveLength(3);
    expect(within(card).getByText(/Modelo sintetico_v1/)).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 3 }).length).toBeGreaterThan(
      5,
    );
  });

  it("la serie diaria se marca como cruda", async () => {
    renderApp("/cockpit");
    const frame = (await screen.findByText("Serie diaria")).closest("div")
      ?.parentElement?.parentElement as HTMLElement;
    expect(within(frame).getByText("Solo modelo")).toBeInTheDocument();
    await waitFor(() => expect(graphs.options.length).toBeGreaterThan(0));
  });

  it("elegir un día abre el panel con las dos listas y el aviso", async () => {
    const { router } = renderApp("/cockpit");
    await waitFor(() => expect(graphs.options.length).toBeGreaterThan(0));

    act(() => {
      lastOptions().clickCallback?.(
        {},
        new Date("2026-10-12T00:00:00Z").getTime(),
      );
    });

    const panel = await screen.findByRole("complementary", {
      name: /Temas del 12 oct 2026/,
    });
    expect(router.state.location.search).toContain("dia=2026-10-12");
    expect(
      await within(panel).findByText("Inicio de sesión que falla"),
    ).toBeInTheDocument();
    expect(
      within(panel).getByRole("region", { name: "Familias" }),
    ).toBeInTheDocument();
    expect(
      within(panel).getByRole("region", { name: "Tópicos útiles" }),
    ).toBeInTheDocument();
    expect(
      within(panel).getByText(
        /no es un diagnóstico ni la detección de un incidente/,
      ),
    ).toBeInTheDocument();
    expect(within(panel).getAllByText(/habitual 25.0 %/).length).toBe(3);
  });

  it("arrastrar un rango cambia desde y hasta en la URL", async () => {
    const { router } = renderApp("/cockpit");
    await waitFor(() => expect(graphs.options.length).toBeGreaterThan(0));

    act(() => {
      lastOptions().zoomCallback?.(Date.UTC(2026, 8, 1), Date.UTC(2026, 8, 20));
    });

    await waitFor(() =>
      expect(router.state.location.search).toContain("desde=2026-09-01"),
    );
    expect(router.state.location.search).toContain("hasta=2026-09-20");
  });

  it("el conmutador de familias cambia de vista sin otra petición", async () => {
    let calls = 0;
    server.use(
      http.get("*/api/v1/kpis/families", async () => {
        calls += 1;
        const { syntheticFamilies } = await import("@/test/handlers");
        return HttpResponse.json(syntheticFamilies());
      }),
    );
    renderApp("/cockpit");
    expect(
      await screen.findByRole("img", { name: "Negativas por familia y mes" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/vienen del prompt con el que se etiquetaron/),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Anomalía" }));

    expect(
      screen.getByRole("img", { name: "Anomalía de cada familia por mes" }),
    ).toBeInTheDocument();
    expect(calls).toBe(1);
  });

  it("pulsar una familia escribe ?familia= en la URL", async () => {
    const { router } = renderApp("/cockpit");
    const group = await screen.findByRole("group", {
      name: "Familia resaltada",
    });

    await userEvent.click(
      within(group).getByRole("button", { name: /Acceso y autenticación/ }),
    );

    expect(router.state.location.search).toContain("familia=AC");
  });

  it("Abrir en el Explorador arma la URL con los filtros", async () => {
    renderApp(
      "/cockpit?bancos=BBVA,AZTECA&desde=2026-08-01&hasta=2026-09-30&familia=AC",
    );

    await waitFor(() =>
      expect(
        screen.getAllByRole("link", { name: /Abrir en el Explorador/ }).length,
      ).toBeGreaterThanOrEqual(5),
    );
    const links = screen.getAllByRole("link", {
      name: /Abrir en el Explorador/,
    });
    const href = links[0]?.getAttribute("href") ?? "";
    const params = new URL(href, "http://x").searchParams;
    expect(params.get("bancos")).toBe("BBVA,AZTECA");
    expect(params.get("desde")).toBe("2026-08-01");
    expect(params.get("hasta")).toBe("2026-09-30");
    expect(params.get("familia")).toBe("AC");
    expect(params.get("sentimiento")).toBe("NEG");
  });

  it("un error de la API muestra ErrorState con el id de la petición", async () => {
    server.use(
      http.get("*/api/v1/kpis/cards", () =>
        HttpResponse.json(
          {
            error: {
              code: "upstream",
              message: "BigQuery no pudo responder",
              request_id: "req-9",
            },
          },
          { status: 502 },
        ),
      ),
    );
    renderApp("/cockpit");

    expect(await screen.findByText("req-9")).toBeInTheDocument();
  });

  it("la matriz marca las celdas de incongruencia extrema", async () => {
    renderApp("/cockpit");

    const table = await screen.findByRole("table", {
      name: /Proporción de reseñas por estrellas/,
    });

    expect(within(table).getAllByText("incongruencia")).toHaveLength(2);
    expect(within(table).getByText("4–5 ★")).toBeInTheDocument();
  });

  it("no tiene violaciones de axe", async () => {
    const { container } = renderApp("/cockpit");
    await screen.findByRole("table", { name: /Proporción de reseñas/ });
    await screen.findByRole("img", { name: "Negativas por familia y mes" });
    await screen.findByText("Inicio de sesión que falla");
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("cockpit, pestaña Por versión", () => {
  it("muestra el aviso descriptivo, la cobertura y la tabla", async () => {
    renderApp("/cockpit?vista=version");

    expect(
      await screen.findByText(
        /no hay pruebas de cambio de nivel entre versiones/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/90\.9 %/)).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "" });
    expect(within(table).getByText("11.33")).toBeInTheDocument();
    expect(within(table).getByText("OTRAS")).toBeInTheDocument();
  });

  it("cambiar de pestaña escribe vista en la URL", async () => {
    const { router } = renderApp("/cockpit");
    await userEvent.click(
      await screen.findByRole("tab", { name: "Por versión" }),
    );
    expect(router.state.location.search).toContain("vista=version");
    fireEvent.click(screen.getByRole("tab", { name: "Diario" }));
  });

  it("no tiene violaciones de axe", async () => {
    const { container } = renderApp("/cockpit?vista=version");
    await screen.findByText("OTRAS", { selector: "td" });
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("explorerUrl", () => {
  it("omite los bancos si son los cinco y suma lo que está fijado", () => {
    const base = { from: "2026-01-01", to: "2026-02-01" };
    expect(
      explorerUrl({
        ...base,
        banks: ["BBVA", "AZTECA", "SANTANDER", "NUBANK", "BANORTE"],
      }),
    ).toBe("/explorador?desde=2026-01-01&hasta=2026-02-01");
    expect(
      explorerUrl({
        ...base,
        banks: ["BBVA"],
        familia: "FA",
        sentimiento: "NEG",
      }),
    ).toBe(
      "/explorador?bancos=BBVA&desde=2026-01-01&hasta=2026-02-01&familia=FA&sentimiento=NEG",
    );
  });
});

describe("cockpit, barra fija y secciones", () => {
  beforeEach(() => {
    graphs.options.length = 0;
  });

  it("la barra dice cuántos bancos hay y marca el atajo activo", async () => {
    renderApp("/cockpit?bancos=BBVA,AZTECA");

    expect(
      await screen.findByRole("button", {
        name: "2 de 5 bancos seleccionados",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "90 días" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await userEvent.click(screen.getByRole("button", { name: "30 días" }));

    expect(screen.getByRole("button", { name: "30 días" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "90 días" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("el menú sigue la sección que está a la vista al hacer scroll", async () => {
    renderApp("/cockpit");
    const menu = await screen.findByRole("button", { name: /Sección:/ });
    const tops: Record<string, number> = {
      resumen: -900,
      serie: -600,
      mensual: -300,
      familias: 120,
      topicos: 700,
    };
    const spy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockImplementation(function (this: HTMLElement) {
        return { top: tops[this.id] ?? 2000 } as DOMRect;
      });

    act(() => {
      window.dispatchEvent(new Event("scroll"));
    });

    await waitFor(() => expect(menu).toHaveTextContent("Familias"));
    spy.mockRestore();
  });

  it("la barra es fija y trae el menú de secciones", async () => {
    renderApp("/cockpit");

    const menu = await screen.findByRole("button", { name: /Sección:/ });
    const bar = menu.closest("search") as HTMLElement;
    expect(bar.className).toContain("sticky");
    expect(menu).toHaveTextContent("Último mes por banco");

    await userEvent.click(menu);

    for (const name of [
      "Serie diaria",
      "Gráficas mensuales",
      "Familias",
      "Tópicos",
      "Estrellas × texto",
      "Comparación entre bancos",
    ]) {
      expect(await screen.findByRole("menuitem", { name })).toBeInTheDocument();
    }
  });
});

describe("cockpit, ajustes de la primera pasada", () => {
  it("las tarjetas comparan con el mes anterior si se pide", async () => {
    renderApp("/cockpit");
    await screen.findByRole("heading", { name: "Banco Azul" });
    expect((await screen.findAllByText(/frente a sep 2025/)).length).toBe(15);

    await userEvent.click(screen.getByRole("button", { name: "Mes anterior" }));

    expect(screen.getAllByText(/frente a ago 2026/)).toHaveLength(15);
  });

  it("los tópicos muestran la audiencia junto al nombre y sus familias", async () => {
    renderApp("/cockpit");

    const item = (
      await screen.findByText("Inicio de sesión que falla")
    ).closest("li") as HTMLElement;

    expect(within(item).getByText("Ingeniería")).toBeInTheDocument();
    expect(
      within(item).getByText("Acceso y autenticación"),
    ).toBeInTheDocument();
    expect(item).not.toHaveTextContent("sin familia");
  });

  it("un tópico sin familias lo dice", async () => {
    server.use(
      http.get("*/api/v1/kpis/topics", () =>
        HttpResponse.json(
          syntheticTopics().map((t) => ({ ...t, families: [] })),
        ),
      ),
    );
    renderApp("/cockpit");

    expect(
      (await screen.findAllByText("sin familia asociada")).length,
    ).toBeGreaterThan(0);
  });

  it("la anomalía de familias muestra el z de cada mes", async () => {
    const { container } = renderApp("/cockpit");
    await userEvent.click(
      await screen.findByRole("button", { name: "Anomalía" }),
    );

    const titles = [...container.querySelectorAll("svg title")].map(
      (t) => t.textContent,
    );

    expect(titles.some((t) => t?.includes("z = 4.6"))).toBe(true);
    expect(screen.getByText(/menos de lo habitual/)).toBeInTheDocument();
    expect(
      screen.getByText("Habla de una actualización (u)"),
    ).toBeInTheDocument();
  });

  it("las gráficas mensuales ocultan los meses con pocas reseñas", async () => {
    server.use(
      http.get("*/api/v1/kpis/monthly", () =>
        HttpResponse.json(
          syntheticMonthly().flatMap((r) => [
            r,
            {
              ...r,
              period: "2024-01",
              ppi: r.ppi && { ...r.ppi, n_unlabeled: 5 },
              raw: r.raw && { ...r.raw, n_unlabeled: 5 },
            },
          ]),
        ),
      ),
    );
    renderApp("/cockpit");
    const frame = (
      await screen.findByText("Reseñas negativas por mes")
    ).closest("div")?.parentElement?.parentElement as HTMLElement;

    await userEvent.click(
      within(frame).getByRole("button", { name: "Ver datos" }),
    );

    expect(within(frame).queryByText("2024-01")).not.toBeInTheDocument();
    expect(within(frame).getAllByText("2026-09").length).toBeGreaterThan(0);
    expect(screen.getByText(/menos de 100 reseñas/)).toBeInTheDocument();
  });

  it("shiftMonths cruza el año", () => {
    expect(shiftMonths("2026-02", -3)).toBe("2025-11");
    expect(shiftMonths("2026-09", -23)).toBe("2024-10");
  });

  it("los encabezados de las tablas se quedan fijos", async () => {
    renderApp("/cockpit?vista=version");
    const table = await screen.findByRole("table");

    expect(within(table).getAllByRole("columnheader")[0]?.className).toContain(
      "sticky",
    );
  });
});
