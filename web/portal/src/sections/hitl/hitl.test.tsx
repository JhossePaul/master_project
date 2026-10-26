import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { axe } from "vitest-axe";
import { syntheticHitlCase } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

type Body = Record<string, unknown>;

const nextCalls = { count: 0 };

/** Cola de un solo caso; cada guardado queda en `saved`. */
function serve(
  cases: ReturnType<typeof syntheticHitlCase>[],
  review?: () => Response,
) {
  const saved: Body[] = [];
  const queue = [...cases];
  server.use(
    http.post("*/api/v1/hitl/next", () => {
      nextCalls.count += 1;
      const next = queue.shift();
      return next
        ? HttpResponse.json(next)
        : new HttpResponse(null, { status: 204 });
    }),
    http.post("*/api/v1/hitl/items/:id/review", async ({ request }) => {
      const body = (await request.json()) as Body;
      if (review) return review();
      saved.push(body);
      return HttpResponse.json({
        review_id: body.review_id,
        next: queue.shift() ?? null,
      });
    }),
    http.post(
      "*/api/v1/hitl/items/:id/skip",
      () => new HttpResponse(null, { status: 204 }),
    ),
  );
  return saved;
}

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
    const saved = serve([blind(), blind()]);
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/modo a ciegas/);

    await user.keyboard("2");
    expect(screen.getByRole("radio", { name: "NEU" })).toBeChecked();
    await user.keyboard("f");
    await user.keyboard("n");
    expect(
      screen.getByRole("checkbox", { name: /Menciona falla/ }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /nombre propio/ }),
    ).toBeChecked();
    await user.keyboard("d");
    await user.keyboard("d");
    expect(screen.getByRole("checkbox", { name: /Duda/ })).not.toBeChecked();
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

  it("guardar muestra el siguiente caso sin pedirlo otra vez", async () => {
    nextCalls.count = 0;
    serve([blind(), blind()]);
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/Caso 1 de esta sesión/);

    await user.keyboard("1");
    await user.keyboard("{Enter}");

    expect(
      await screen.findByText(/Caso 2 de esta sesión/),
    ).toBeInTheDocument();
    expect(nextCalls.count).toBe(1); // solo la primera apertura
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

  it("un 409 avisa que el caso volvió a la cola y ofrece el siguiente", async () => {
    serve([blind(), blind()], () =>
      HttpResponse.json(
        {
          error: {
            code: "conflict",
            message: "El caso volvió a la cola; pide el siguiente",
            request_id: "r1",
          },
        },
        { status: 409 },
      ),
    );
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/modo a ciegas/);

    await user.keyboard("1");
    await user.keyboard("{Enter}");

    expect(
      await screen.findByText("El caso volvió a la cola"),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Pedir el siguiente" }),
    );
    expect(await screen.findByText(/modo a ciegas/)).toBeInTheDocument();
  });

  it("un 502 de DLP conserva el formulario y lo explica", async () => {
    serve([blind()], () =>
      HttpResponse.json(
        { error: { code: "upstream", message: "dlp", request_id: "r2" } },
        { status: 502 },
      ),
    );
    const user = userEvent.setup();
    renderApp("/hitl/sentimiento");
    await screen.findByText(/modo a ciegas/);

    await user.keyboard("1");
    await user.type(screen.getByLabelText("Comentario (opcional)"), "hola");
    await user.click(screen.getByRole("button", { name: "Guardar y seguir" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No se pudo sanitizar el comentario",
    );
    expect(screen.getByLabelText("Comentario (opcional)")).toHaveValue("hola");
    expect(screen.getByRole("radio", { name: "NEG" })).toBeChecked();
  });

  it("sin casos pendientes muestra el estado vacío", async () => {
    serve([]);
    renderApp("/hitl/sentimiento");

    expect(
      await screen.findByText("No quedan casos pendientes en esta cola"),
    ).toBeInTheDocument();
  });

  it("Saltar pide el siguiente caso", async () => {
    serve([blind(), blind()]);
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
