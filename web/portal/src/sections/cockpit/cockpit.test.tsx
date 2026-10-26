import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { axe } from "vitest-axe";
import { legendHtml } from "@/charts/TimeSeries";
import {
  syntheticCards,
  syntheticDaily,
  syntheticMonthly,
  syntheticTopics,
  syntheticVersionDaily,
} from "@/test/handlers";
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

  it("la tabla compara cada banco con su referencia y su intervalo", async () => {
    renderApp("/cockpit");

    const row = (await screen.findByRole("row", {
      name: /Banco Azul/,
    })) as HTMLElement;

    expect(within(row).getByText("15.0 %")).toBeInTheDocument();
    expect(within(row).getByText("[14.0, 16.0]")).toBeInTheDocument();
    expect(
      within(row).getByText("12.0 %", { selector: "p" }),
    ).toBeInTheDocument();
    expect(within(row).getByText("+3.0 pts")).toBeInTheDocument();
    expect(
      within(row).getByRole("img", { name: "Banco Azul: 12.0 % a 15.0 %" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Comparando sep 2026 vs sep 2025"),
    ).toBeInTheDocument();
    // Una insignia para la tabla y otra para la matriz, no una por banco.
    expect(screen.getAllByText("Con revisión humana")).toHaveLength(2);
    expect(screen.getByText(/Modelo sintetico_v1/)).toBeInTheDocument();
    expect(
      within(row.closest("table") as HTMLElement).getAllByRole("row"),
    ).toHaveLength(6);
  });

  it("el KPI se elige con botones y queda en la URL", async () => {
    const { router } = renderApp("/cockpit");
    await screen.findByRole("row", { name: /Banco Azul/ });

    await userEvent.click(
      screen.getByRole("button", { name: "Brecha en estrellas" }),
    );

    const row = screen.getByRole("row", { name: /Banco Azul/ });
    expect(within(row).getByText("−0.30 ★")).toBeInTheDocument();
    expect(within(row).getByText("[−0.35, −0.25]")).toBeInTheDocument();
    expect(router.state.location.search).toContain("kpi=gap");
    expect(
      screen.getByRole("button", { name: "Brecha en estrellas" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("compara con el mes anterior si se pide", async () => {
    renderApp("/cockpit");
    await screen.findByRole("row", { name: /Banco Azul/ });

    await userEvent.click(screen.getByRole("button", { name: "Mes anterior" }));

    expect(
      screen.getByText("Comparando sep 2026 vs ago 2026"),
    ).toBeInTheDocument();
    const row = screen.getByRole("row", { name: /Banco Azul/ });
    expect(
      within(row).getByText(/14\.0 %/, { selector: "p" }),
    ).toBeInTheDocument();
  });

  it("ordena por el valor actual", async () => {
    renderApp("/cockpit");
    await screen.findByRole("row", { name: /Banco Azul/ });

    await userEvent.click(screen.getByRole("button", { name: "Valor actual" }));

    const table = screen
      .getByRole("row", { name: /Banco Azul/ })
      .closest("table") as HTMLElement;
    const first = within(table).getAllByRole("row")[1] as HTMLElement;
    expect(first).toHaveTextContent("Banco Gris");
  });

  it("el mes elegido viaja a la API", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get("*/api/v1/kpis/cards", ({ request }) => {
        seen.push(new URL(request.url).searchParams.get("period"));
        return HttpResponse.json(syntheticCards());
      }),
    );
    renderApp("/cockpit?mes=2026-08");

    await waitFor(() => expect(seen).toContain("2026-08"));
  });

  it("la serie diaria se marca como cruda", async () => {
    renderApp("/evolucion");
    const frame = (await screen.findByText("Serie diaria")).closest("div")
      ?.parentElement?.parentElement as HTMLElement;
    expect(within(frame).getByText("Solo modelo")).toBeInTheDocument();
    await waitFor(() => expect(graphs.options.length).toBeGreaterThan(0));
  });

  it("elegir un día abre el panel con las dos listas y el aviso", async () => {
    const { router } = renderApp("/evolucion");
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
    const { router } = renderApp("/evolucion");
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
    renderApp("/topicos");
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

  it("elegir familias escribe ?familia= en la URL y deja solo esas en la gráfica", async () => {
    const { router, container } = renderApp("/topicos");
    const group = await screen.findByRole("group", {
      name: "Familias a mostrar",
    });
    const stackedTitles = () =>
      [
        ...container.querySelectorAll(
          'svg[aria-label="Negativas por familia y mes"] title',
        ),
      ].map((t) => t.textContent ?? "");
    expect(stackedTitles().some((t) => t.includes("Lentitud general"))).toBe(
      true,
    );

    await userEvent.click(
      within(group).getByRole("button", { name: /Acceso y autenticación/ }),
    );
    await userEvent.click(
      within(group).getByRole("button", { name: /Falla general de la app/ }),
    );

    expect(router.state.location.search).toContain("familia=AC%2CFA");
    const titles = stackedTitles();
    expect(titles.length).toBeGreaterThan(0);
    expect(
      titles.every((t) => /Acceso y autenticación|Falla general/.test(t)),
    ).toBe(true);
    expect(titles.some((t) => t.includes("Lentitud general"))).toBe(false);

    await userEvent.click(
      within(group).getByRole("button", { name: /Acceso y autenticación/ }),
    );
    expect(router.state.location.search).toContain("familia=FA");

    await userEvent.click(
      within(group).getByRole("button", { name: "Quitar la selección" }),
    );
    expect(router.state.location.search).not.toContain("familia");
  });

  it("las familias elegidas atenúan los tópicos que no las tienen", async () => {
    renderApp("/topicos?familia=TR");

    const login = (
      await screen.findByText("Inicio de sesión que falla")
    ).closest("li") as HTMLElement;
    const transfers = screen
      .getByText("Transferencias que no llegan")
      .closest("li") as HTMLElement;

    expect(login.className).toContain("opacity-40");
    expect(transfers.className).not.toContain("opacity-40");
  });

  it("Abrir en el Explorador arma la URL con los filtros", async () => {
    renderApp(
      "/topicos?bancos=BBVA,AZTECA&desde=2026-08-01&hasta=2026-09-30&familia=AC,FA",
    );

    await screen.findByRole("img", { name: "Negativas por familia y mes" });
    await waitFor(() =>
      expect(
        screen.getAllByRole("link", { name: /Abrir en el Explorador/ }).length,
      ).toBeGreaterThanOrEqual(2),
    );
    const href =
      screen
        .getAllByRole("link", { name: /Abrir en el Explorador/ })[0]
        ?.getAttribute("href") ?? "";
    const params = new URL(href, "http://x").searchParams;

    expect(params.get("bancos")).toBe("BBVA");
    expect(params.get("desde")).toBe("2026-08-01");
    expect(params.get("hasta")).toBe("2026-09-30");
    expect(params.get("familia")).toBe("AC,FA");
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

  it("Cockpit no tiene violaciones de axe", async () => {
    const { container } = renderApp("/cockpit");
    await screen.findByRole("table", { name: /Proporción de reseñas/ });
    await screen.findByRole("row", { name: /Banco Azul/ });
    expect(await axe(container)).toHaveNoViolations();
  });

  it("Tópicos no tiene violaciones de axe", async () => {
    const { container } = renderApp("/topicos");
    await screen.findByRole("img", { name: "Negativas por familia y mes" });
    await screen.findByText("Inicio de sesión que falla");
    expect(await axe(container)).toHaveNoViolations();
  });

  it("Evolución no tiene violaciones de axe", async () => {
    const { container } = renderApp("/evolucion");
    await screen.findByRole("img", {
      name: "Reseñas por día y versión de la app",
    });
    await screen.findByText("Reseñas negativas por mes");
    await screen.findByText("11.33", { selector: "td" });
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("cockpit, pestaña Por versión", () => {
  it("el aviso va antes que los filtros de banco y trae la cobertura", async () => {
    renderApp("/evolucion");

    const notice = await screen.findByText(
      /no hay pruebas de cambio de nivel entre versiones/,
    );
    const picker = screen.getByRole("group", {
      name: "Banco de la vista por versión",
    });

    expect(
      notice.compareDocumentPosition(picker) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(await screen.findByText(/90\.9 %/)).toBeInTheDocument();
  });

  it("muestra las versiones por día con su leyenda y la tabla del banco", async () => {
    renderApp("/evolucion");

    expect(
      await screen.findByRole("img", {
        name: "Reseñas por día y versión de la app",
      }),
    ).toBeInTheDocument();
    const legend = screen.getByRole("list", { name: "Versiones" });
    expect(within(legend).getByText("26.80.9")).toBeInTheDocument();
    expect(within(legend).getByText("Otras o sin versión")).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "" });
    expect(within(table).getByText("11.33")).toBeInTheDocument();
    expect(
      screen.getByText(/Mediana del banco entre todas sus versiones/),
    ).toBeInTheDocument();
  });

  it("filtrar el sentimiento vuelve a pedir las reseñas de ese tipo", async () => {
    const seen: string[] = [];
    server.use(
      http.get("*/api/v1/kpis/versions/daily", ({ request }) => {
        const url = new URL(request.url);
        seen.push(
          `${url.searchParams.get("bank")}:${url.searchParams.get("sentiment")}`,
        );
        return HttpResponse.json(syntheticVersionDaily());
      }),
    );
    renderApp("/evolucion");
    await screen.findByRole("img", {
      name: "Reseñas por día y versión de la app",
    });

    await userEvent.click(screen.getByRole("button", { name: "Negativas" }));

    await waitFor(() => expect(seen).toContain("BBVA:NEG"));
    expect(seen[0]).toBe("BBVA:ALL");
  });

  it("cambiar de banco pide ese banco", async () => {
    const seen: string[] = [];
    server.use(
      http.get("*/api/v1/kpis/versions/daily", ({ request }) => {
        seen.push(new URL(request.url).searchParams.get("bank") ?? "");
        return HttpResponse.json(syntheticVersionDaily());
      }),
    );
    renderApp("/evolucion");
    await screen.findByRole("img", {
      name: "Reseñas por día y versión de la app",
    });

    await userEvent.click(screen.getByRole("button", { name: "Banco Verde" }));

    await waitFor(() => expect(seen).toContain("AZTECA"));
  });

  it("no tiene violaciones de axe", async () => {
    const { container } = renderApp("/evolucion");
    await screen.findByRole("img", {
      name: "Reseñas por día y versión de la app",
    });
    await screen.findByText("11.33", { selector: "td" });
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("cockpit, leyenda y medida de la serie diaria", () => {
  const series = (yHTML: string) => [
    {
      color: "#1f64b0",
      dashHTML: "<svg/>",
      label: "Banco Azul",
      labelHTML: "Banco Azul",
      yHTML,
    },
    {
      color: "#1f64b0",
      dashHTML: "<svg/>",
      label: "Banco Azul (día)",
      labelHTML: "Banco Azul (día)",
      yHTML,
    },
  ];

  it("sin cursor la leyenda trae los nombres con un guion", () => {
    const html = legendHtml({
      x: undefined,
      xHTML: "",
      series: series(""),
    } as never);

    expect(html).toContain("Banco Azul");
    expect(html).toContain("—");
    expect(html).not.toContain("(día)");
  });

  it("con cursor trae la fecha y el valor, en el mismo formato", () => {
    const html = legendHtml({
      x: 1,
      xHTML: "26 oct 2026",
      series: series("35.1 %"),
    } as never);

    expect(html).toContain("26 oct 2026");
    expect(html).toContain("35.1 %");
    expect(html).not.toContain("(día)");
  });

  it("la leyenda de dygraphs es una sola y de altura fija", async () => {
    renderApp("/evolucion");
    await waitFor(() => expect(graphs.options.length).toBeGreaterThan(0));

    const options = lastOptions();

    expect(options.legend).toBe("always");
    expect(options.legendFormatter).toBe(legendHtml);
    expect((options.labelsDiv as unknown as HTMLElement).className).toContain(
      "h-8",
    );
  });

  it("la medida es un solo selector fijo que gobierna la serie y el mensual", async () => {
    renderApp("/evolucion");
    const buttons = await screen.findAllByRole("button", {
      name: "Brecha en estrellas",
    });

    expect(buttons).toHaveLength(1);
    const bar = buttons[0]?.closest("div.sticky") as HTMLElement;
    expect(bar).toHaveTextContent("Medida:");
    expect(bar).toHaveTextContent("serie diaria y a la mensual");

    await userEvent.click(buttons[0] as HTMLElement);

    expect(
      await screen.findByText("Brecha en estrellas por mes"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Brecha en estrellas", { selector: "h2" }),
    ).toBeInTheDocument();
  });
});

describe("cockpit, suavizado de la serie diaria", () => {
  beforeEach(() => {
    graphs.options.length = 0;
  });

  it("trae el suavizado de 7 días y lo cambia sin otra petición", async () => {
    let calls = 0;
    server.use(
      http.get("*/api/v1/kpis/daily", () => {
        calls += 1;
        return HttpResponse.json(syntheticDaily());
      }),
    );
    renderApp("/evolucion");
    const seven = await screen.findByRole("button", { name: "7 días" });
    expect(seven).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(graphs.options.length).toBeGreaterThan(0));
    const before = graphs.options.length;

    await userEvent.click(screen.getByRole("button", { name: "28 días" }));

    expect(screen.getByRole("button", { name: "28 días" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await waitFor(() => expect(graphs.options.length).toBeGreaterThan(before));
    expect(calls).toBe(1);
  });

  it("pide 27 días de más al inicio para completar la primera ventana", async () => {
    const seen: string[] = [];
    server.use(
      http.get("*/api/v1/kpis/daily", ({ request }) => {
        seen.push(new URL(request.url).searchParams.get("date_from") ?? "");
        return HttpResponse.json(syntheticDaily());
      }),
    );
    renderApp("/evolucion?desde=2026-09-28&hasta=2026-10-26");

    await waitFor(() => expect(seen).toHaveLength(1));

    expect(seen[0]).toBe("2026-09-01");
  });

  it("con un banco deja el dato diario como línea de fondo", async () => {
    renderApp("/evolucion?bancos=BBVA");
    await waitFor(() => expect(graphs.options.length).toBeGreaterThan(0));

    const labels = lastOptions().labels as unknown as string[];

    expect(labels).toEqual(["día (UTC)", "Banco Azul (día)", "Banco Azul"]);
  });

  it("con cinco bancos solo hay una línea por banco y una franja de leyenda", async () => {
    renderApp("/evolucion");
    await waitFor(() => expect(graphs.options.length).toBeGreaterThan(0));

    const options = lastOptions();

    expect((options.labels as unknown as string[]).length).toBe(6);
    expect(options.legend).toBe("always");
    expect(options.labelsDiv).toBeInstanceOf(HTMLElement);
  });

  it("el panel aclara que el día no es el promedio", async () => {
    renderApp("/evolucion");
    await waitFor(() => expect(graphs.options.length).toBeGreaterThan(0));

    act(() => {
      lastOptions().clickCallback?.(
        {},
        new Date("2026-10-12T00:00:00Z").getTime(),
      );
    });

    expect(
      await screen.findByText(/no del promedio de 7 días/),
    ).toBeInTheDocument();
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
});

describe("tópicos, filtro de bancos y paginador", () => {
  function manyTopics(n: number) {
    const base = syntheticTopics();
    return Array.from({ length: n }, (_, i) =>
      base.map((t) => ({
        ...t,
        topic_id: i,
        nombre: `Tópico ${i}`,
        filas: t.filas + (n - i),
      })),
    ).flat();
  }

  it("empieza con los bancos del filtro general y deja quitar uno", async () => {
    const { container } = renderApp("/topicos?bancos=BBVA,AZTECA");
    const filter = await screen.findByRole("group", {
      name: "Bancos de los tópicos",
    });
    const azul = within(filter).getByRole("button", { name: "Banco Azul" });
    expect(azul).toHaveAttribute("aria-pressed", "true");
    expect(
      within(filter).getByRole("button", { name: "Banco Verde" }),
    ).toHaveAttribute("aria-pressed", "true");
    const titles = () =>
      [...container.querySelectorAll("li svg title")].map((t) => t.textContent);
    expect(titles().some((t) => t?.startsWith("Banco Azul"))).toBe(true);

    await userEvent.click(azul);

    expect(azul).toHaveAttribute("aria-pressed", "false");
    expect(titles().some((t) => t?.startsWith("Banco Azul"))).toBe(false);
    expect(titles().some((t) => t?.startsWith("Banco Verde"))).toBe(true);
  });

  it("siempre queda al menos un banco", async () => {
    renderApp("/topicos?bancos=BBVA");
    const filter = await screen.findByRole("group", {
      name: "Bancos de los tópicos",
    });
    const azul = within(filter).getByRole("button", { name: "Banco Azul" });

    await userEvent.click(azul);

    expect(azul).toHaveAttribute("aria-pressed", "true");
  });

  it("muestra seis tópicos por página y se pagina", async () => {
    server.use(
      http.get("*/api/v1/kpis/topics", () => HttpResponse.json(manyTopics(9))),
    );
    renderApp("/topicos?bancos=BBVA");

    const region = await screen.findByRole("region", { name: "Tópicos" });
    expect(within(region).getAllByRole("listitem")).toHaveLength(6);
    expect(within(region).getByText(/1–6 de 9 tópicos/)).toBeInTheDocument();
    const prev = within(region).getByRole("button", {
      name: "Tópicos anteriores",
    });
    const next = within(region).getByRole("button", {
      name: "Tópicos siguientes",
    });
    expect(prev).toHaveAttribute("aria-disabled", "true");

    await userEvent.click(next);

    expect(within(region).getAllByRole("listitem")).toHaveLength(3);
    expect(within(region).getByText(/7–9 de 9 tópicos/)).toBeInTheDocument();
    expect(next).toHaveAttribute("aria-disabled", "true");
    expect(within(region).getByText("Tópico 8")).toBeInTheDocument();

    await userEvent.click(prev);
    expect(within(region).getByText(/1–6 de 9 tópicos/)).toBeInTheDocument();
  });

  it("las flechas del teclado cambian de página", async () => {
    server.use(
      http.get("*/api/v1/kpis/topics", () => HttpResponse.json(manyTopics(9))),
    );
    renderApp("/topicos?bancos=BBVA");
    const region = await screen.findByRole("region", { name: "Tópicos" });
    const next = within(region).getByRole("button", {
      name: "Tópicos siguientes",
    });
    next.focus();

    await userEvent.keyboard("{ArrowRight}");
    expect(within(region).getByText(/7–9 de 9 tópicos/)).toBeInTheDocument();

    await userEvent.keyboard("{ArrowLeft}");
    expect(within(region).getByText(/1–6 de 9 tópicos/)).toBeInTheDocument();
  });

  it("ordena los tópicos por volumen", async () => {
    server.use(
      http.get("*/api/v1/kpis/topics", () => HttpResponse.json(manyTopics(3))),
    );
    renderApp("/topicos?bancos=BBVA");

    const items = await within(
      await screen.findByRole("region", { name: "Tópicos" }),
    ).findAllByRole("listitem");

    expect(items[0]).toHaveTextContent("Tópico 0");
    expect(items[2]).toHaveTextContent("Tópico 2");
  });
});

describe("cockpit, ajustes de la primera pasada", () => {
  it("los tópicos muestran la audiencia junto al nombre y sus familias", async () => {
    renderApp("/topicos");

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
    renderApp("/topicos");

    expect(
      (await screen.findAllByText("sin familia asociada")).length,
    ).toBeGreaterThan(0);
  });

  it("la anomalía de familias muestra el z de cada mes", async () => {
    const { container } = renderApp("/topicos");
    await userEvent.click(
      await screen.findByRole("button", { name: "Anomalía" }),
    );

    const titles = [...container.querySelectorAll("svg title")].map(
      (t) => t.textContent,
    );

    expect(titles.some((t) => t?.includes("z = 4.6"))).toBe(true);
    expect(screen.getByText(/menos de lo habitual/)).toBeInTheDocument();
    expect(
      screen.getAllByText(
        "Relacionada con una actualización",
      )[0] as HTMLElement,
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
    renderApp("/evolucion");
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
    renderApp("/evolucion");
    const table = await screen.findByRole("table");

    expect(within(table).getAllByRole("columnheader")[0]?.className).toContain(
      "sticky",
    );
  });
});
