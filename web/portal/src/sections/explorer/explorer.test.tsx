import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { axe } from "vitest-axe";
import { facetsCsv } from "@/sections/explorer/ExplorerView";
import {
  alpha,
  backgroundOf,
  read,
  score,
  segments,
  topWords,
} from "@/sections/explorer/explanation";
import {
  EXPLORER_ROWS,
  syntheticFacets,
  syntheticMe,
  syntheticRow,
} from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

interface Seen {
  facets: URLSearchParams[];
  pages: URLSearchParams[];
}

/** Responde según el sentimiento pedido y anota las consultas. */
function trackFilters(): Seen {
  const seen: Seen = { facets: [], pages: [] };
  const only = (url: URL) => {
    const wanted = url.searchParams.get("sentiment");
    return wanted
      ? EXPLORER_ROWS.filter((r) => wanted.split(",").includes(r.sentiment))
      : EXPLORER_ROWS;
  };
  server.use(
    http.get("*/api/v1/reviews/facets", ({ request }) => {
      const url = new URL(request.url);
      seen.facets.push(url.searchParams);
      const rows = only(url);
      return HttpResponse.json(
        syntheticFacets(
          rows.length,
          rows.map((r) => r.sentiment),
        ),
      );
    }),
    http.get("*/api/v1/reviews", ({ request }) => {
      const url = new URL(request.url);
      seen.pages.push(url.searchParams);
      const rows = only(url);
      return HttpResponse.json({
        rows,
        total: rows.length,
        page: 1,
        page_size: 50,
        window_applied: syntheticFacets().window_applied,
      });
    }),
  );
  return seen;
}

const EXPLANATION = {
  text_key: "a".repeat(64),
  model_version: "sintetico_v1",
  method: "occlusion_v2",
  source: "on_demand",
  computed_at: "2026-10-26T12:00:00Z",
  attributions: [
    { start: 0, end: 2, d_neg: 0.4, d_neu: -0.1, d_pos: -0.3 }, // "No"
    { start: 3, end: 8, d_neg: -0.02, d_neu: 0.01, d_pos: 0.01 }, // "llega"
    { start: 12, end: 18, d_neg: -0.1, d_neu: 0.06, d_pos: 0.04 }, // "código"
  ],
};

describe("explorador", () => {
  it("muestra la tabla con su conteo y los resúmenes", async () => {
    renderApp("/explorador");

    expect(
      await screen.findByRole("heading", { name: "Explorador de reseñas" }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/reseñas del/)).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /Abrir la ficha: No llega/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Sentimiento" }),
    ).toBeInTheDocument();
    const sentiments = screen.getByRole("region", { name: "Por sentimiento" });
    expect(
      within(sentiments).getByRole("button", { name: /NEG/ }),
    ).toBeInTheDocument();
  });

  it("pulsar una barra filtra la tabla y todas las gráficas", async () => {
    const seen = trackFilters();
    const user = userEvent.setup();
    const { router } = renderApp("/explorador");
    await screen.findByRole("button", { name: /Abrir la ficha: Muy buena/ });

    const sentiments = screen.getByRole("region", { name: "Por sentimiento" });
    await user.click(within(sentiments).getByRole("button", { name: /NEG/ }));

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /Abrir la ficha: Muy buena/ }),
      ).not.toBeInTheDocument(),
    );
    expect(router.state.location.search).toContain("sentimiento=NEG");
    expect(seen.pages.at(-1)?.get("sentiment")).toBe("NEG");
    expect(seen.facets.at(-1)?.get("sentiment")).toBe("NEG");
    expect(
      screen.getByRole("button", { name: "Quitar el filtro Sentimiento NEG" }),
    ).toBeInTheDocument();
    // Las demás gráficas se recalculan: ya no hay barra POS.
    expect(
      within(
        screen.getByRole("region", { name: "Por sentimiento" }),
      ).queryByRole("button", { name: /POS/ }),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Quitar el filtro Sentimiento NEG" }),
    );
    expect(
      await screen.findByRole("button", { name: /Abrir la ficha: Muy buena/ }),
    ).toBeInTheDocument();
    expect(router.state.location.search).not.toContain("sentimiento");
  });

  it("los filtros que llegan del cockpit se aplican al entrar", async () => {
    const seen = trackFilters();
    renderApp(
      "/explorador?bancos=BBVA&familia=AC,FA&sentimiento=NEG&estrellas=1,2",
    );

    await screen.findByRole("button", { name: /Abrir la ficha: No llega/ });
    const last = seen.pages.at(-1);
    expect(last?.getAll("banks")).toEqual(["BBVA"]);
    expect(last?.getAll("families")).toEqual(["AC", "FA"]);
    expect(last?.get("sentiment")).toBe("NEG");
    expect(last?.getAll("stars")).toEqual(["1", "2"]);
    expect(
      screen.getByRole("button", {
        name: "Quitar el filtro Acceso y autenticación",
      }),
    ).toBeInTheDocument();
  });

  it("un mes del gráfico fija desde y hasta", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/explorador");
    await screen.findByRole("button", { name: /Abrir la ficha: No llega/ });

    await user.click(
      screen.getByRole("button", { name: /sep 2026: 1 reseñas/ }),
    );

    await waitFor(() =>
      expect(router.state.location.search).toContain("desde=2026-09-01"),
    );
    expect(router.state.location.search).toContain("hasta=2026-09-30");
  });

  it("la revisión humana alterna entre sí, no y sin filtro", async () => {
    const seen = trackFilters();
    const user = userEvent.setup();
    const { router } = renderApp("/explorador");
    await screen.findByRole("button", { name: /Abrir la ficha: No llega/ });

    const hitl = screen.getByRole("region", { name: "Revisión humana" });
    await user.click(within(hitl).getByRole("button", { name: /^Sí/ }));
    await waitFor(() =>
      expect(seen.pages.at(-1)?.get("hitl_reviewed")).toBe("true"),
    );
    expect(router.state.location.search).toContain("hitl=1");
    await user.click(within(hitl).getByRole("button", { name: /^No/ }));
    await waitFor(() =>
      expect(router.state.location.search).toContain("hitl=0"),
    );
    await user.click(within(hitl).getByRole("button", { name: /^No/ }));
    await waitFor(() =>
      expect(router.state.location.search).not.toContain("hitl"),
    );
  });

  it("la ficha calcula la explicación y la dibuja con los dos colores y su leyenda", async () => {
    server.use(
      http.post("*/api/v1/explanations/:key", () =>
        HttpResponse.json(EXPLANATION),
      ),
    );
    const user = userEvent.setup();
    renderApp("/explorador");
    await user.click(
      await screen.findByRole("button", { name: /Abrir la ficha: No llega/ }),
    );

    const panel = await screen.findByRole("complementary", {
      name: "Ficha de la reseña",
    });
    expect(
      await within(panel).findByText(/Confianza 80 %/),
    ).toBeInTheDocument();
    expect(
      await within(panel).findByText(/Puede tardar hasta un minuto/),
    ).toBeInTheDocument();
    expect(
      within(panel).getByText(/Puede tardar hasta un minuto/),
    ).toBeInTheDocument();
    await user.click(
      await within(panel).findByRole("button", {
        name: "Calcular explicación",
      }),
    );

    const text = await within(panel).findByTestId("texto-explicado");
    const marks = [...text.querySelectorAll("mark")];
    expect(marks.find((m) => m.textContent === "No")?.dataset.direction).toBe(
      "neg",
    );
    expect(
      marks.find((m) => m.textContent === "código")?.dataset.direction,
    ).toBe("pos");
    // Sin efecto apreciable: sin fondo propio (nunca el amarillo del navegador).
    const quiet = marks.find((m) => m.textContent === "llega");
    expect(quiet?.dataset.direction).toBe("none");
    expect(quiet?.style.background).toBe("");
    expect(quiet).toHaveClass("bg-transparent");
    expect(marks.find((m) => m.textContent === "No")).toHaveAttribute(
      "title",
      "NEG +0.40 · NEU −0.10 · POS −0.30",
    );
    expect(within(panel).getByText("Empuja hacia NEG")).toBeInTheDocument();
    expect(within(panel).getByText("Empuja hacia POS")).toBeInTheDocument();
    expect(
      within(panel).getByText("Más empujan hacia NEG").nextSibling,
    ).toHaveTextContent("No");
    expect(
      within(panel).getByText("Más empujan hacia POS").nextSibling,
    ).toHaveTextContent("código");
    expect(
      within(panel).getByText(
        "Indica qué palabras movieron la predicción del modelo; no es la causa técnica del fallo.",
      ),
    ).toBeInTheDocument();
    expect(
      within(panel).queryByRole("button", { name: "Calcular explicación" }),
    ).not.toBeInTheDocument();
  });

  it("si la explicación ya existe no ofrece calcularla", async () => {
    server.use(
      http.get("*/api/v1/explanations/:key", () =>
        HttpResponse.json({ ...EXPLANATION, source: "precomputed_hitl" }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/explorador");
    await user.click(
      await screen.findByRole("button", { name: /Abrir la ficha: No llega/ }),
    );

    const panel = await screen.findByRole("complementary", {
      name: "Ficha de la reseña",
    });
    expect(
      await within(panel).findByTestId("texto-explicado"),
    ).toBeInTheDocument();
    expect(within(panel).getByText(/precalculada/)).toBeInTheDocument();
    expect(
      within(panel).queryByRole("button", { name: "Calcular explicación" }),
    ).not.toBeInTheDocument();
  });

  it("una explicación anterior (v1) avisa que solo tiene una dirección", async () => {
    server.use(
      http.get("*/api/v1/explanations/:key", () =>
        HttpResponse.json({
          ...EXPLANATION,
          method: "occlusion_v1",
          attributions: [{ start: 0, end: 2, weight: 0.4 }],
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/explorador");
    await user.click(
      await screen.findByRole("button", { name: /Abrir la ficha: No llega/ }),
    );

    const panel = await screen.findByRole("complementary", {
      name: "Ficha de la reseña",
    });
    expect(
      await within(panel).findByText(
        /Explicación anterior: solo mide cuánto sostiene/,
      ),
    ).toBeInTheDocument();
    expect(
      within(panel).queryByText("Empuja hacia NEG"),
    ).not.toBeInTheDocument();
  });

  it("la ficha se cierra con Escape y no deja la reseña en la URL", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/explorador");
    await user.click(
      await screen.findByRole("button", { name: /Abrir la ficha: No llega/ }),
    );
    await screen.findByRole("complementary", { name: "Ficha de la reseña" });
    expect(router.state.location.search).toContain("ficha=BBVA%3Asyn-0001");

    await user.keyboard("{Escape}");

    await waitFor(() =>
      expect(
        screen.queryByRole("complementary", { name: "Ficha de la reseña" }),
      ).not.toBeInTheDocument(),
    );
    expect(router.state.location.search).not.toContain("ficha");
  });

  it("la búsqueda muestra la distancia, las reseñas iguales y vuelve a la tabla", async () => {
    let body: unknown = null;
    server.use(
      http.post("*/api/v1/reviews/search", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          hits: [
            {
              text_key: "a".repeat(64),
              bank_id: "BBVA",
              distance: 0.0123,
              n_reviews: 7,
              example: syntheticRow(),
            },
          ],
          embedding_model: "minilm",
          months_searched: 12,
          bytes_billed: 1000,
        });
      }),
    );
    const user = userEvent.setup();
    const { router } = renderApp("/explorador");
    await screen.findByRole("button", { name: /Abrir la ficha: No llega/ });

    const box = screen.getByLabelText("Describe el problema que buscas");
    expect(screen.getByRole("button", { name: "Buscar" })).toBeDisabled();
    await user.type(box, "no llega el código");
    await user.click(screen.getByRole("button", { name: "Buscar" }));

    expect(
      await screen.findByRole("columnheader", { name: "Distancia" }),
    ).toBeInTheDocument();
    expect(screen.getByText("0.012")).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Reseñas iguales" }),
    ).toBeInTheDocument();
    expect(body).toMatchObject({ query: "no llega el código", k: 20 });
    // La consulta nunca llega a la URL.
    expect(router.state.location.search).not.toContain("llega");

    await user.click(screen.getByRole("button", { name: "Volver a la tabla" }));
    expect(
      await screen.findByRole("button", { name: /Abrir la ficha: Muy buena/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "Distancia" }),
    ).not.toBeInTheDocument();
  });

  it("un error de la búsqueda se muestra con su id", async () => {
    server.use(
      http.post("*/api/v1/reviews/search", () =>
        HttpResponse.json(
          {
            error: {
              code: "upstream",
              message: "El servicio no respondió",
              request_id: "r-77",
            },
          },
          { status: 502 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp("/explorador");
    await screen.findByRole("button", { name: /Abrir la ficha: No llega/ });

    await user.type(
      screen.getByLabelText("Describe el problema que buscas"),
      "algo raro",
    );
    await user.click(screen.getByRole("button", { name: "Buscar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "El servicio no respondió",
    );
    expect(screen.getByText("r-77")).toBeInTheDocument();
  });

  it("avisa cuando la ventana recortó el rango", async () => {
    server.use(
      http.get("*/api/v1/reviews", () =>
        HttpResponse.json({
          rows: EXPLORER_ROWS,
          total: 2,
          page: 1,
          page_size: 50,
          window_applied: {
            ...syntheticFacets().window_applied,
            clipped: true,
          },
        }),
      ),
    );
    renderApp("/explorador");

    expect(await screen.findByText(/el rango se recortó/)).toBeInTheDocument();
  });

  it("un lector no ve el Explorador", async () => {
    server.use(
      http.get("*/api/v1/me", () =>
        HttpResponse.json(
          syntheticMe({ roles: ["lector"], reviewer_tasks: [] }),
        ),
      ),
    );
    renderApp("/explorador");

    expect(
      await screen.findByText("No tienes acceso a esta sección"),
    ).toBeInTheDocument();
  });

  it("sin reseñas, el estado vacío lo explica", async () => {
    server.use(
      http.get("*/api/v1/reviews", () =>
        HttpResponse.json({
          rows: [],
          total: 0,
          page: 1,
          page_size: 50,
          window_applied: syntheticFacets().window_applied,
        }),
      ),
    );
    renderApp("/explorador");

    expect(
      await screen.findByText("Ninguna reseña con estos filtros"),
    ).toBeInTheDocument();
  });

  it("no tiene violaciones de axe, con la ficha abierta", async () => {
    const user = userEvent.setup();
    const { container } = renderApp("/explorador");
    await user.click(
      await screen.findByRole("button", { name: /Abrir la ficha: No llega/ }),
    );
    await screen.findByRole("complementary", { name: "Ficha de la reseña" });
    await screen.findByRole("button", { name: "Calcular explicación" });

    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("agregados y explicación", () => {
  it("el CSV de agregados no trae texto de reseñas", () => {
    const csv = facetsCsv(syntheticFacets());

    expect(csv.split("\n")[0]).toBe("dimension,clave,etiqueta,reseñas");
    expect(csv).toContain('sentimiento,NEG,"",1');
    expect(csv).toContain('topico,0,"Código de acceso",1');
    for (const row of EXPLORER_ROWS) expect(csv).not.toContain(row.text);
  });

  it("parte el texto en palabras con su atribución", () => {
    const parts = segments("No llega el código", EXPLANATION.attributions);

    expect(parts.map((p) => p.text)).toEqual([
      "No",
      " ",
      "llega",
      " el ",
      "código",
    ]);
    expect(parts[0]?.attribution?.d_neg).toBe(0.4);
    expect(parts[1]?.attribution).toBeNull();
  });

  it("mide el empuje en log-odds, que no se satura con una predicción segura", () => {
    // Texto 99 % POS: quitar la palabra cambia las probabilidades muy poco.
    const base = { p_neg: 0.004, p_pos: 0.992 };
    const word = { start: 0, end: 3, d_neg: -0.003, d_neu: 0, d_pos: 0.003 };
    const filler = { start: 4, end: 6, d_neg: 0, d_neu: 0, d_pos: 0 };

    const strong = score(word, base) as number;

    // Con probabilidades daría 0.006; en log-odds es un efecto claro (0.56).
    expect(Math.abs(word.d_pos - word.d_neg)).toBeLessThan(0.01);
    expect(Math.abs(strong)).toBeGreaterThan(0.4);
    expect(strong).toBeGreaterThan(0); // quitarla baja POS: empujaba hacia POS
    expect(score(filler, base)).toBeCloseTo(0, 6);
    expect(score({ start: 0, end: 1, weight: 0.3 }, base)).toBeNull();
    // Sin probabilidades base cae a la diferencia de cambios.
    expect(score(word)).toBeCloseTo(0.006, 6);
  });

  it("el color sigue la dirección y la opacidad el efecto relativo al texto", () => {
    const base = { p_neg: 0.8, p_pos: 0.05 };
    const reading = read(EXPLANATION.attributions, base);
    const neg = backgroundOf(EXPLANATION.attributions[0] as never, reading, 0);
    const none = backgroundOf(EXPLANATION.attributions[1] as never, reading, 1);
    const pos = backgroundOf(EXPLANATION.attributions[2] as never, reading, 2);

    expect(neg).toMatch(/^rgba\(178, 58, 46, /);
    expect(pos).toMatch(/^rgba\(0, 104, 94, /);
    expect(none).toBeUndefined();
    expect(alpha(0.1, 1)).toBeLessThan(alpha(0.9, 1));
    expect(alpha(5, 1)).toBe(0.75);
    expect(alpha(0, 1)).toBe(0.2);
  });

  it("un texto donde nada mueve la predicción no colorea ni lista palabras", () => {
    const attributions = [
      { start: 0, end: 1, d_neg: 0.0001, d_neu: 0, d_pos: -0.0001 },
      { start: 2, end: 3, d_neg: -0.0001, d_neu: 0, d_pos: 0.0001 },
    ];
    const reading = read(attributions, { p_neg: 0.3, p_pos: 0.4 });

    expect(reading.flat).toBe(true);
    expect(backgroundOf(attributions[0] as never, reading, 0)).toBeUndefined();
    expect(topWords("a b", attributions, reading)).toEqual({
      toNeg: [],
      toPos: [],
    });
  });

  it("las palabras con efecto claro que más empujan hacia cada lado", () => {
    const attributions = [
      { start: 0, end: 1, d_neg: 0.5, d_neu: 0, d_pos: -0.5 },
      { start: 2, end: 3, d_neg: 0.2, d_neu: 0, d_pos: -0.2 },
      { start: 4, end: 5, d_neg: 0.1, d_neu: 0, d_pos: -0.1 },
      { start: 6, end: 7, d_neg: 0.001, d_neu: 0, d_pos: -0.001 },
      { start: 8, end: 9, d_neg: -0.3, d_neu: 0, d_pos: 0.3 },
    ];
    const reading = read(attributions);

    expect(topWords("a b c d e", attributions, reading)).toEqual({
      toNeg: ["a", "b", "c"],
      toPos: ["e"],
    });
  });
});
