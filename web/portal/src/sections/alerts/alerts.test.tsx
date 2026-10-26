import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { axe } from "vitest-axe";
import type { AlertDetail, AlertRow, AlertStatus } from "@/api/alerts";
import { syntheticMe } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

const NOTE = "Revisado con el equipo, la deriva es real.";

function row(
  bank: string,
  series: string,
  status: AlertStatus,
  extra: Partial<AlertRow> = {},
): AlertRow {
  return {
    alert_id: `drift_${bank}_2026-09_${series}`,
    bank_id: bank,
    period: "2026-09",
    series,
    value: 0.31,
    threshold: 4,
    status,
    status_at: "2026-10-20T12:00:00Z",
    drift_policy_version: "dp1",
    created_at: "2026-10-18T12:00:00Z",
    boost: null,
    ...extra,
  };
}

const ROWS: AlertRow[] = [
  row("NUBANK", "neg_share", "open", {
    boost: {
      boost_id: "boost_1",
      active: true,
      coverage: 0.85,
      starts_at: "2026-10-18T12:00:00Z",
      ends_at: "2026-11-05T12:00:00Z",
      ended_reason: null,
    },
  }),
  row("AZTECA", "mean_words", "confirmed", { value: 7.4 }),
  row("BBVA", "family_AC", "dismissed"),
  row("BBVA", "length_distribution", "open", { value: 0.31, threshold: 0.25 }),
];

function detailOf(alert: AlertRow): AlertDetail {
  const months = Array.from({ length: 24 }, (_, i) => {
    const index = 2026 * 12 + 8 - (23 - i);
    return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
  });
  return {
    alert,
    events: [
      {
        event_id: "e1",
        status: "open",
        at: "2026-10-18T12:00:00Z",
        actor: null,
        note: null,
        ticket: null,
      },
      ...(alert.status === "open"
        ? []
        : [
            {
              event_id: "e2",
              status: alert.status,
              at: "2026-10-20T12:00:00Z",
              actor: "a1b2c3d4",
              note: "Nota de un analista",
              ticket: "VOC-12",
            },
          ]),
    ],
    series: months.map((period) => ({
      period,
      value: period === alert.period ? alert.value : 0.2,
      baseline: 0.18,
      z: period === alert.period ? 4.6 : 0.4,
      psi: null,
      threshold: alert.threshold,
      alert: period === alert.period,
    })),
    explorer: {
      bank_id: alert.bank_id,
      start: "2026-09-01",
      end: "2026-09-30",
    },
  };
}

/** Sirve la bandeja y los detalles; los envíos quedan en `posted`. */
function serve(post?: (body: Record<string, unknown>) => Response) {
  const queries: URLSearchParams[] = [];
  const posted: Record<string, unknown>[] = [];
  server.use(
    http.get("*/api/v1/alerts", ({ request }) => {
      const params = new URL(request.url).searchParams;
      queries.push(params);
      const status = params.get("status");
      const banks = params.getAll("bank");
      return HttpResponse.json(
        ROWS.filter(
          (r) =>
            (!status || r.status === status) &&
            (banks.length === 0 || banks.includes(r.bank_id)),
        ),
      );
    }),
    http.get("*/api/v1/alerts/:id", ({ params }) => {
      const found = ROWS.find((r) => r.alert_id === params.id);
      return found
        ? HttpResponse.json(detailOf(found))
        : new HttpResponse(null, { status: 404 });
    }),
    http.post("*/api/v1/alerts/:id/events", async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>;
      posted.push(body);
      if (post) return post(body);
      const found = ROWS.find((r) => r.alert_id === params.id) as AlertRow;
      return HttpResponse.json(
        detailOf({ ...found, status: body.status as AlertStatus }),
      );
    }),
  );
  return { queries, posted };
}

const idOf = (bank: string, series: string) =>
  `/alertas/drift_${bank}_2026-09_${series}`;

describe("bandeja de alertas", () => {
  it("muestra las abiertas por defecto y filtra por estado", async () => {
    const { queries } = serve();
    const user = userEvent.setup();
    renderApp("/alertas");

    const table = await screen.findByRole("table");
    expect(
      within(table).getByRole("link", { name: "Proporción de negativas" }),
    ).toHaveAttribute("href", idOf("NUBANK", "neg_share"));
    expect(
      within(table).getByRole("link", {
        name: "Distribución de la longitud de las reseñas",
      }),
    ).toBeInTheDocument();
    expect(within(table).queryByText("Palabras por reseña")).toBeNull();
    expect(queries.at(-1)?.get("status")).toBe("open");

    await user.click(screen.getByRole("tab", { name: "Confirmadas" }));
    expect(
      await screen.findByRole("link", { name: "Palabras por reseña" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Proporción de negativas")).toBeNull();

    await user.click(screen.getByRole("tab", { name: "Descartadas" }));
    expect(
      await screen.findByRole("link", { name: /Familia: Acceso/ }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Todas" }));
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(5));
    expect(queries.at(-1)?.has("status")).toBe(false);
  });

  it("lleva el valor contra el umbral, los días abiertas y la subida", async () => {
    serve();
    renderApp("/alertas");

    const table = await screen.findByRole("table");
    const negative = within(table)
      .getByRole("link", { name: "Proporción de negativas" })
      .closest("tr") as HTMLElement;
    expect(within(negative).getByText("31.0 %")).toBeInTheDocument();
    expect(within(negative).getByText("z ≥ 4")).toBeInTheDocument();
    expect(within(negative).getByText("abierta")).toBeInTheDocument();
    expect(
      within(negative).getByText("Activa (cobertura 0.85)"),
    ).toBeInTheDocument();
    const length = within(table)
      .getByRole("link", { name: /longitud/ })
      .closest("tr") as HTMLElement;
    expect(within(length).getByText("PSI ≥ 0.25")).toBeInTheDocument();
    expect(within(length).getByText("Sin subida")).toBeInTheDocument();
  });

  it("el filtro global de bancos viaja a la API", async () => {
    const { queries } = serve();
    renderApp("/alertas?bancos=NUBANK");

    await screen.findByRole("table");
    expect(queries.at(-1)?.getAll("bank")).toEqual(["NUBANK"]);
    expect(
      screen.queryByText("Distribución de la longitud de las reseñas"),
    ).toBeNull();
  });

  it("sin alertas muestra un estado vacío", async () => {
    server.use(http.get("*/api/v1/alerts", () => HttpResponse.json([])));
    renderApp("/alertas");

    expect(
      await screen.findByText("No hay alertas abiertas"),
    ).toBeInTheDocument();
  });

  it("el lector no ve la bandeja", async () => {
    server.use(
      http.get("*/api/v1/me", () =>
        HttpResponse.json(syntheticMe({ roles: ["lector"] })),
      ),
    );
    renderApp("/alertas");

    expect(
      await screen.findByText("No tienes acceso a esta sección"),
    ).toBeInTheDocument();
  });

  it("no tiene violaciones de accesibilidad", async () => {
    serve();
    const { container } = renderApp("/alertas");
    await screen.findByRole("table");

    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("detalle de una alerta", () => {
  it.each([
    ["NUBANK", "neg_share", ["Confirmar", "Descartar"], ["Reabrir"]],
    ["AZTECA", "mean_words", ["Descartar", "Reabrir"], ["Confirmar"]],
    ["BBVA", "family_AC", ["Reabrir"], ["Confirmar", "Descartar"]],
  ])(
    "%s %s solo ofrece las acciones válidas",
    async (bank, series, shown, hidden) => {
      serve();
      renderApp(idOf(bank, series));

      await screen.findByRole("heading", { level: 1 });
      for (const name of shown)
        expect(screen.getByRole("button", { name })).toBeInTheDocument();
      for (const name of hidden)
        expect(screen.queryByRole("button", { name })).toBeNull();
    },
  );

  it("muestra la serie, la subida, la historia y el enlace al Explorador", async () => {
    serve();
    renderApp(idOf("NUBANK", "neg_share"));

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Proporción de negativas",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /24 meses.*mes de la alerta resaltado/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /z mensual/ })).toBeInTheDocument();
    expect(screen.getAllByTestId("alert-month")).toHaveLength(2);
    expect(
      screen.getByText(/la cobertura de este banco baja a/),
    ).toHaveTextContent("0.85");
    expect(screen.getByText("por el monitor")).toBeInTheDocument();
    expect(
      screen.getByText(/no dice por qué/, { exact: false }),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Abrir en el Explorador/ });
    const url = new URL(link.getAttribute("href") as string, "http://x");
    expect(url.pathname).toBe("/explorador");
    expect(url.searchParams.get("bancos")).toBe("NUBANK");
    expect(url.searchParams.get("desde")).toBe("2026-09-01");
    expect(url.searchParams.get("hasta")).toBe("2026-09-30");
  });

  it("una serie de PSI tiene una sola gráfica, con su umbral", async () => {
    serve();
    renderApp(idOf("BBVA", "length_distribution"));

    await screen.findByRole("heading", { level: 1 });
    expect(screen.getAllByRole("img", { name: /24 meses/ })).toHaveLength(1);
    expect(screen.queryByRole("img", { name: /z mensual/ })).toBeNull();
    expect(screen.getAllByText("PSI ≥ 0.25").length).toBeGreaterThan(0);
  });

  it("Confirmar exige una nota de 10 caracteres y manda el ticket", async () => {
    const { posted } = serve();
    const user = userEvent.setup();
    renderApp(idOf("NUBANK", "neg_share"));
    await screen.findByRole("heading", { level: 1 });

    await user.click(screen.getByRole("button", { name: "Confirmar" }));
    const dialog = await screen.findByRole("dialog");
    const send = within(dialog).getByRole("button", { name: "Confirmar" });
    expect(send).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Motivo/), "corta");
    expect(send).toBeDisabled();
    await user.clear(within(dialog).getByLabelText(/Motivo/));
    await user.type(within(dialog).getByLabelText(/Motivo/), NOTE);
    await user.type(within(dialog).getByLabelText(/Ticket/), "VOC-77");
    await user.click(send);

    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject({
      status: "confirmed",
      note: NOTE,
      ticket: "VOC-77",
    });
    expect(posted[0]?.event_id).toMatch(/^[0-9a-f-]{36}$/);
    // La respuesta trae la alerta ya confirmada: cambian las acciones.
    expect(
      await screen.findByRole("button", { name: "Reabrir" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirmar" })).toBeNull();
  });

  it("un 409 avisa que la alerta cambió", async () => {
    serve(() =>
      HttpResponse.json(
        {
          error: {
            code: "conflict",
            message: "La alerta ya está dismissed; recarga la página",
            request_id: "r1",
          },
        },
        { status: 409 },
      ),
    );
    const user = userEvent.setup();
    renderApp(idOf("NUBANK", "neg_share"));
    await screen.findByRole("heading", { level: 1 });

    await user.click(screen.getByRole("button", { name: "Descartar" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Motivo/), NOTE);
    await user.click(within(dialog).getByRole("button", { name: "Descartar" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("La alerta cambió mientras la mirabas");
    expect(alert).toHaveTextContent("ya está dismissed");
  });

  it("una alerta que no existe muestra el error", async () => {
    serve();
    renderApp("/alertas/nada");

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("no tiene violaciones de accesibilidad", async () => {
    serve();
    const { container } = renderApp(idOf("NUBANK", "neg_share"));
    await screen.findByRole("heading", { level: 1 });

    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("landing", () => {
  it("el conteo de abiertas de cada banco enlaza a su bandeja", async () => {
    renderApp("/");

    const link = await screen.findByRole("link", { name: /Banco Morado\s*2/ });
    expect(link).toHaveAttribute("href", "/alertas?bancos=NUBANK");
  });
});
