import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { toast } from "sonner";
import { axe } from "vitest-axe";
import { syntheticHitlCase } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

type Body = Record<string, unknown>;

const nextCalls = { count: 0 };

interface Options {
  /** Respuesta propia a la revisión número `n` (desde 1); `undefined` = éxito. */
  review?: (n: number) => Response | undefined;
  /** La llamada número `n` a `/next` falla (la precarga es la 2). */
  failNext?: number;
}

/** Cola de casos; cada guardado y cada petición a `/next` quedan anotados. */
function serve(
  cases: ReturnType<typeof syntheticHitlCase>[],
  options: Options = {},
) {
  nextCalls.count = 0;
  const saved: Body[] = [];
  const nexts: Body[] = [];
  const released: string[] = [];
  const queue = [...cases];
  let reviews = 0;
  server.use(
    http.post("*/api/v1/hitl/next", async ({ request }) => {
      nextCalls.count += 1;
      nexts.push((await request.json()) as Body);
      if (options.failNext === nextCalls.count)
        return HttpResponse.json(
          { error: { code: "upstream", message: "x", request_id: "r" } },
          { status: 502 },
        );
      const next = queue.shift();
      return next
        ? HttpResponse.json(next)
        : new HttpResponse(null, { status: 204 });
    }),
    http.post("*/api/v1/hitl/items/:id/review", async ({ request }) => {
      const body = (await request.json()) as Body;
      reviews += 1;
      const custom = options.review?.(reviews);
      if (custom) return custom;
      saved.push(body);
      return HttpResponse.json({
        review_id: body.review_id,
        next: body.claim_next === false ? null : (queue.shift() ?? null),
      });
    }),
    http.post(
      "*/api/v1/hitl/items/:id/skip",
      () => new HttpResponse(null, { status: 204 }),
    ),
    http.post("*/api/v1/hitl/items/:id/release", ({ params }) => {
      released.push(String(params.id));
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return Object.assign(saved, { nexts, released });
}

const conflict = () =>
  HttpResponse.json(
    {
      error: {
        code: "conflict",
        message: "El caso volvió a la cola; pide el siguiente",
        request_id: "r1",
      },
    },
    { status: 409 },
  );
const dlpDown = () =>
  HttpResponse.json(
    { error: { code: "upstream", message: "dlp", request_id: "r2" } },
    { status: 502 },
  );
const second = () =>
  syntheticHitlCase({
    item_id: "b".repeat(32),
    display_mode: "blind",
    proposal: null,
    text: "Segundo caso de la cola.",
  });

const blind = () =>
  syntheticHitlCase({ display_mode: "blind", proposal: null });

describe("revisión de sentimiento", () => {
  it("la entrada muestra la cola con sus conteos y la muestra de monitoreo", async () => {
    renderApp("/hitl");

    expect(
      await screen.findByRole("heading", { name: "Cola de sentimiento" }),
    ).toBeInTheDocument();
    expect(screen.getByText("197")).toBeInTheDocument();
    expect(screen.getByText("42 s")).toBeInTheDocument();
    expect(
      screen.getByText(/Muestra de monitoreo: 0 de 300/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Empezar" })).toHaveAttribute(
      "href",
      "/hitl/sentimiento",
    );
  });

  it("asistido: muestra la propuesta preseleccionada y la guía", async () => {
    serve([syntheticHitlCase()]);
    renderApp("/hitl/sentimiento");

    expect(
      await screen.findByText(/No puedo entrar a la app/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Caso 1 de esta sesión · guía v2.2 · modo asistido/),
    ).toBeInTheDocument();
    expect(screen.getByText("(0.62)", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "NEG" })).toBeChecked();
    expect(
      await screen.findByRole("heading", { name: "Guía de sentimiento" }),
    ).toBeInTheDocument();
    // La tabla de la guía sale de remark-gfm.
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });

  it("a ciegas: sin propuesta y sin nada preseleccionado; Guardar pide un sentimiento", async () => {
    const saved = serve([blind()]);
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/modo a ciegas/);

    expect(screen.queryByText(/El modelo propone/)).not.toBeInTheDocument();
    for (const name of ["NEG", "NEU", "POS", "No evaluable"]) {
      expect(screen.getByRole("radio", { name })).not.toBeChecked();
    }
    await user.click(screen.getByRole("button", { name: "Guardar y seguir" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Elige un sentimiento",
    );
    expect(saved).toHaveLength(0);
  });

  it("los atajos eligen, marcan y guardan", async () => {
    const saved = serve([blind(), second()]);
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/modo a ciegas/);

    await user.keyboard("2");
    expect(screen.getByRole("radio", { name: "NEU" })).toBeChecked();
    await user.keyboard("f");
    await user.keyboard("n");
    expect(
      screen.getByRole("checkbox", { name: /Menciona una falla concreta/ }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /nombre propio/ }),
    ).toBeChecked();
    await user.keyboard("d");
    await user.keyboard("d");
    expect(
      screen.getByRole("checkbox", { name: /Tengo dudas con esta etiqueta/ }),
    ).not.toBeChecked();
    await user.keyboard("{Enter}");

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toMatchObject({
      validated_label: "NEU",
      flags: ["menciona_falla", "nombre_persona"],
      guideline_version: "v2.2",
      comment: null,
    });
    expect(typeof saved[0]?.review_id).toBe("string");
    // Pasa al siguiente caso.
    expect(
      await screen.findByText(/Caso 2 de esta sesión/),
    ).toBeInTheDocument();
  });

  it("precarga el siguiente caso sin repetir el que se está revisando", async () => {
    nextCalls.count = 0;
    const saved = serve([blind(), second()]);
    renderApp("/hitl/sentimiento");
    await screen.findByText(/Caso 1 de esta sesión/);

    await waitFor(() => expect(nextCalls.count).toBe(2));
    expect(saved.nexts[0]).toEqual({ task: "sentiment", exclude: [] });
    expect(saved.nexts[1]).toEqual({
      task: "sentiment",
      exclude: ["a".repeat(32)],
    });
  });

  it("guardar muestra el siguiente al instante y guarda en segundo plano", async () => {
    nextCalls.count = 0;
    const saved = serve([blind(), second()]);
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/Caso 1 de esta sesión/);
    await waitFor(() => expect(nextCalls.count).toBe(2));

    await user.keyboard("1");
    await user.keyboard("{Enter}");

    expect(
      await screen.findByText("Segundo caso de la cola."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Caso 2 de esta sesión/)).toBeInTheDocument();
    await waitFor(() => expect(saved).toHaveLength(1));
    // No pide otro caso: ya tenía el siguiente (más la precarga del nuevo).
    expect(saved[0]).toMatchObject({
      claim_next: false,
      validated_label: "NEG",
    });
    await waitFor(() => expect(nextCalls.count).toBe(3));
  });

  it("si la precarga falla, guarda de la forma clásica y toma el siguiente en la respuesta", async () => {
    nextCalls.count = 0;
    const saved = serve([blind(), second()], { failNext: 2 });
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/Caso 1 de esta sesión/);
    await waitFor(() => expect(nextCalls.count).toBe(2));

    await user.keyboard("1");
    await user.keyboard("{Enter}");

    expect(
      await screen.findByText("Segundo caso de la cola."),
    ).toBeInTheDocument();
    expect(saved[0]).toMatchObject({ claim_next: true });
  });

  it("sin más casos, guardar muestra el estado vacío", async () => {
    const saved = serve([blind()]);
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/modo a ciegas/);

    await user.keyboard("1");
    await user.keyboard("{Enter}");

    expect(
      await screen.findByText("No quedan casos pendientes en esta cola"),
    ).toBeInTheDocument();
    await waitFor(() => expect(saved).toHaveLength(1));
  });

  it("no ofrece el campo ticket", async () => {
    serve([blind()]);
    renderApp("/hitl/sentimiento");
    await screen.findByText(/modo a ciegas/);

    expect(screen.queryByLabelText(/ticket/i)).not.toBeInTheDocument();
  });

  it("G oculta y muestra la guía", async () => {
    serve([blind()]);
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByRole("complementary", { name: "Guía de revisión" });

    await user.keyboard("g");
    expect(
      screen.queryByRole("complementary", { name: "Guía de revisión" }),
    ).not.toBeInTheDocument();
    await user.keyboard("g");
    expect(
      screen.getByRole("complementary", { name: "Guía de revisión" }),
    ).toBeInTheDocument();
  });

  it("No evaluable envía etiqueta nula con la marca", async () => {
    const saved = serve([blind()]);
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/modo a ciegas/);

    await user.keyboard("0");
    await user.click(screen.getByRole("button", { name: "Guardar y seguir" }));

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toMatchObject({
      validated_label: null,
      flags: ["no_evaluable"],
    });
  });

  it("las teclas dentro del comentario no activan atajos y Ctrl+Enter guarda", async () => {
    const saved = serve([blind()]);
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/modo a ciegas/);

    await user.keyboard("3");
    await user.click(screen.getByLabelText("Comentario (opcional)"));
    await user.keyboard("fdn 1 0");
    expect(screen.getByLabelText("Comentario (opcional)")).toHaveValue(
      "fdn 1 0",
    );
    expect(screen.getByRole("radio", { name: "POS" })).toBeChecked();
    await user.keyboard("{Control>}{Enter}{/Control}");

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toMatchObject({
      validated_label: "POS",
      flags: [],
      comment: "fdn 1 0",
    });
  });

  it("un 409 al guardar en segundo plano avisa con un mensaje y no detiene la revisión", async () => {
    const error = vi.spyOn(toast, "error").mockImplementation(() => "");
    serve([blind(), second()], { review: () => conflict() });
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/Caso 1 de esta sesión/);

    await user.keyboard("1");
    await user.keyboard("{Enter}");

    expect(
      await screen.findByText("Segundo caso de la cola."),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(error).toHaveBeenCalledWith(
        expect.stringContaining("volvió a la cola"),
      ),
    );
    error.mockRestore();
  });

  it("un 409 con la forma clásica ofrece pedir el siguiente", async () => {
    serve([blind(), second()], { failNext: 2, review: () => conflict() });
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/modo a ciegas/);
    await waitFor(() => expect(nextCalls.count).toBeGreaterThan(1));

    await user.keyboard("1");
    await user.keyboard("{Enter}");

    expect(
      await screen.findByText("El caso volvió a la cola"),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Pedir el siguiente" }),
    );
    expect(
      await screen.findByText(/Caso 2 de esta sesión/),
    ).toBeInTheDocument();
  });

  it("un 502 de DLP avisa y permite volver al caso con su formulario", async () => {
    const saved = serve([blind(), second()], {
      review: (n) => (n === 1 ? dlpDown() : undefined),
    });
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/Caso 1 de esta sesión/);

    await user.type(screen.getByLabelText("Comentario (opcional)"), "hola");
    await user.keyboard("{Control>}1{/Control}"); // sin efecto en el comentario
    await user.click(screen.getByRole("radio", { name: "NEG" }));
    await user.click(screen.getByRole("button", { name: "Guardar y seguir" }));

    expect(
      await screen.findByText("Segundo caso de la cola."),
    ).toBeInTheDocument();
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(
      "No se guardó la revisión del caso anterior",
    );
    expect(banner).toHaveTextContent("No se pudo sanitizar el comentario");

    await user.click(screen.getByRole("button", { name: "Volver a ese caso" }));

    expect(screen.getByLabelText("Comentario (opcional)")).toHaveValue("hola");
    expect(screen.getByRole("radio", { name: "NEG" })).toBeChecked();
    expect(
      screen.queryByText("Segundo caso de la cola."),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Guardar y seguir" }));
    // El caso que se estaba viendo no se perdió: vuelve como el siguiente.
    expect(
      await screen.findByText("Segundo caso de la cola."),
    ).toBeInTheDocument();
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toMatchObject({ comment: "hola" });
  });

  it("un 502 con la forma clásica conserva el formulario y lo explica", async () => {
    serve([blind()], { failNext: 2, review: () => dlpDown() });
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/modo a ciegas/);
    await waitFor(() => expect(nextCalls.count).toBeGreaterThan(1));

    await user.keyboard("1");
    await user.type(screen.getByLabelText("Comentario (opcional)"), "hola");
    await user.click(screen.getByRole("button", { name: "Guardar y seguir" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No se pudo sanitizar el comentario",
    );
    expect(screen.getByLabelText("Comentario (opcional)")).toHaveValue("hola");
    expect(screen.getByRole("radio", { name: "NEG" })).toBeChecked();
  });

  it("salir suelta el caso abierto y el precargado", async () => {
    const saved = serve([blind(), second()]);
    const user = userEvent.setup();
    const { router } = renderApp("/hitl/sentimiento");
    await screen.findByText(/Caso 1 de esta sesión/);
    await waitFor(() => expect(saved.nexts).toHaveLength(2));
    await new Promise((r) => setTimeout(r, 20)); // llega la respuesta precargada

    await user.click(screen.getByRole("button", { name: "Salir" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/hitl"));
    // (el cierre de la prueba anterior también puede soltar el suyo)
    expect(saved.released).toEqual(
      expect.arrayContaining(["a".repeat(32), "b".repeat(32)]),
    );
  });

  it("sin casos pendientes muestra el estado vacío", async () => {
    serve([]);
    renderApp("/hitl/sentimiento");

    expect(
      await screen.findByText("No quedan casos pendientes en esta cola"),
    ).toBeInTheDocument();
  });

  it("Saltar pide el siguiente caso", async () => {
    serve([blind(), second()]);
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/Caso 1 de esta sesión/);

    await user.keyboard("s");

    expect(
      await screen.findByText(/Caso 2 de esta sesión/),
    ).toBeInTheDocument();
  });

  it("nada del caso queda en localStorage ni en la URL", async () => {
    serve([blind()]);
    const { router } = renderApp("/hitl/sentimiento");
    await screen.findByText(/modo a ciegas/);

    // Solo la preferencia del menú; nada del caso.
    const stored = JSON.stringify({ ...localStorage });
    expect(stored).not.toContain("aaaaaaaa");
    expect(stored).not.toContain("No puedo entrar");
    expect(router.state.location.pathname).toBe("/hitl/sentimiento");
    expect(router.state.location.search).toBe("");
  });

  it("la pantalla de revisión no tiene violaciones de axe", async () => {
    serve([syntheticHitlCase()]);
    const { container } = renderApp("/hitl/sentimiento");
    await screen.findByRole("heading", { name: "Guía de sentimiento" });

    expect(await axe(container)).toHaveNoViolations();
  });

  it("un lector no ve la revisión", async () => {
    server.use(
      http.get("*/api/v1/me", () =>
        HttpResponse.json({
          email: "x@example.com",
          actor_hash: "a".repeat(64),
          roles: ["lector"],
          reviewer_tasks: [],
          environment: "dev",
          commit: "abc",
        }),
      ),
    );
    renderApp("/hitl");

    expect(
      await screen.findByText("No tienes acceso a esta sección"),
    ).toBeInTheDocument();
  });
});

describe("revisión de sentimiento: casos con guardado en camino", () => {
  /**
   * Un servidor que, como el real, sigue dando como abierto el caso cuyo
   * guardado aún no llegó (el revisor lo conserva `in_review`) y respeta
   * `exclude`.
   */
  function serveOpenCases(ids: string[], holdReviews: Promise<void>) {
    const cases = ids.map((id, i) =>
      syntheticHitlCase({
        item_id: id.repeat(32),
        display_mode: "blind",
        proposal: null,
        text: `Caso ${id}`,
        opened_at: `2026-10-26T12:0${i}:00Z`,
      }),
    );
    const open = new Set(cases.map((c) => c.item_id));
    const nexts: string[][] = [];
    server.use(
      http.post("*/api/v1/hitl/next", async ({ request }) => {
        const body = (await request.json()) as { exclude?: string[] };
        nexts.push(body.exclude ?? []);
        const next = cases.find(
          (c) => open.has(c.item_id) && !body.exclude?.includes(c.item_id),
        );
        return next
          ? HttpResponse.json(next)
          : new HttpResponse(null, { status: 204 });
      }),
      http.post("*/api/v1/hitl/items/:id/review", async ({ params }) => {
        await holdReviews; // el guardado tarda: el caso sigue abierto
        open.delete(String(params.id));
        return HttpResponse.json({ review_id: "x", next: null });
      }),
      http.post(
        "*/api/v1/hitl/items/:id/release",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    return nexts;
  }

  it("la precarga no vuelve a dar un caso recién guardado", async () => {
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const nexts = serveOpenCases(["a", "b", "c", "d"], held);
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText("Caso a");
    await screen.findByText(/Caso 1 de esta sesión/);
    await waitFor(() => expect(nexts).toHaveLength(2)); // precarga de b

    await user.keyboard("1");
    await user.keyboard("{Enter}"); // guarda a (sin terminar) y muestra b
    expect(await screen.findByText("Caso b")).toBeInTheDocument();
    await waitFor(() => expect(nexts).toHaveLength(3));
    // La precarga de c excluye lo que se está revisando y lo ya guardado.
    expect(nexts[2]).toEqual(["b".repeat(32), "a".repeat(32)]);

    await user.keyboard("2");
    await user.keyboard("{Enter}"); // guarda b (sin terminar) y muestra c
    expect(await screen.findByText("Caso c")).toBeInTheDocument();
    await waitFor(() => expect(nexts).toHaveLength(4));
    expect(nexts[3]).toEqual(
      expect.arrayContaining(["c", "b", "a"].map((x) => x.repeat(32))),
    );
    // Nunca reapareció "Caso a" ni "Caso b".
    expect(screen.queryByText("Caso a")).not.toBeInTheDocument();
    expect(screen.queryByText("Caso b")).not.toBeInTheDocument();

    release();
  });

  it("saltar tampoco deja volver al caso saltado", async () => {
    const held = Promise.resolve();
    const nexts = serveOpenCases(["a", "b", "c"], held);
    server.use(
      http.post(
        "*/api/v1/hitl/items/:id/skip",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText("Caso a");
    await waitFor(() => expect(nexts).toHaveLength(2));

    await user.keyboard("s");

    expect(await screen.findByText("Caso b")).toBeInTheDocument();
    await waitFor(() => expect(nexts).toHaveLength(3));
    expect(nexts[2]).toEqual(["b".repeat(32), "a".repeat(32)]);
  });
});
