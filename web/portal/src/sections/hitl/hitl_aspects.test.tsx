import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { axe } from "vitest-axe";
import { syntheticHitlCase } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";
import { FAMILY_GROUPS } from "./families";

type Body = Record<string, unknown>;

const aspectsCase = (overrides = {}) =>
  syntheticHitlCase({
    task: "aspects",
    display_mode: "blind",
    proposal: null,
    guideline_version: "v2.1",
    text: "No me llega el token para entrar.",
    ...overrides,
  });

function serveAspects(cases: ReturnType<typeof aspectsCase>[]) {
  const saved: Body[] = [];
  const queue = [...cases];
  server.use(
    http.post("*/api/v1/hitl/next", () => {
      const next = queue.shift();
      return next
        ? HttpResponse.json(next)
        : new HttpResponse(null, { status: 204 });
    }),
    http.post("*/api/v1/hitl/items/:id/review-aspects", async ({ request }) => {
      const body = (await request.json()) as Body;
      saved.push(body);
      return HttpResponse.json({
        review_id: body.review_id,
        next: body.claim_next === false ? null : (queue.shift() ?? null),
      });
    }),
    http.get("*/api/v1/hitl/guidelines/:task", () =>
      HttpResponse.json({
        task: "aspects",
        guideline_version: "v2.1",
        valid_from: "2026-10-01T00:00:00Z",
        content: "# Guía de aspectos",
      }),
    ),
  );
  return saved;
}

describe("revisión de aspectos", () => {
  it("las familias salen agrupadas en el orden de decisión de la guía", async () => {
    serveAspects([aspectsCase()]);
    renderApp("/hitl/aspectos");
    await screen.findByText(/modo a ciegas/);

    for (const group of FAMILY_GROUPS) {
      const box = screen.getByRole("group", { name: group.title });
      const codes = within(box)
        .getAllByRole("checkbox")
        .map(
          (c) => /^([A-Z]{2}) ·/.exec(c.parentElement?.textContent ?? "")?.[1],
        );
      expect(codes).toEqual(group.families);
    }
    const titles = screen
      .getAllByRole("group")
      .map((g) => g.querySelector("legend")?.textContent)
      .filter((t): t is string => /^\d · /.test(t ?? ""));
    expect(titles).toEqual(FAMILY_GROUPS.map((g) => g.title));
    expect(screen.queryByText(/El modelo propone/)).not.toBeInTheDocument();
  });

  it("«Sin problema concreto» limpia las familias y elegir una lo desmarca", async () => {
    serveAspects([aspectsCase()]);
    const user = userEvent.setup();
    renderApp("/hitl/aspectos");
    await screen.findByText(/modo a ciegas/);
    const none = screen.getByRole("checkbox", {
      name: /Sin problema concreto/,
    });
    const access = screen.getByRole("checkbox", {
      name: /Acceso y autenticación/,
    });

    await user.click(access);
    expect(access).toBeChecked();
    await user.click(none);
    expect(none).toBeChecked();
    expect(access).not.toBeChecked();
    await user.click(access);
    expect(none).not.toBeChecked();
  });

  it("pide familias o «Sin problema concreto», no ambas ni ninguna", async () => {
    const saved = serveAspects([aspectsCase()]);
    const user = userEvent.setup();
    renderApp("/hitl/aspectos");
    await screen.findByText(/modo a ciegas/);

    await user.click(screen.getByRole("button", { name: "Guardar y seguir" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Marca «Sin problema concreto» o al menos una familia",
    );
    expect(saved).toHaveLength(0);
  });

  it("guarda familias y marcas y pasa al siguiente", async () => {
    const saved = serveAspects([
      aspectsCase(),
      aspectsCase({ item_id: "b".repeat(32), text: "Segundo caso." }),
    ]);
    const user = userEvent.setup();
    renderApp("/hitl/aspectos");
    await screen.findByText(/modo a ciegas/);

    await user.click(
      screen.getByRole("checkbox", { name: /Acceso y autenticación/ }),
    );
    await user.click(screen.getByRole("checkbox", { name: /Usabilidad/ }));
    await user.keyboard("u");
    await user.keyboard("e");
    await user.keyboard("{Enter}");

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toMatchObject({
      families: ["AC", "UX"],
      flag_update: true,
      flag_security: true,
      guideline_version: "v2.1",
      comment: null,
    });
    expect(
      await screen.findByText(/Caso 2 de esta sesión/),
    ).toBeInTheDocument();
  });

  it("«Sin problema concreto» se guarda sin familias", async () => {
    const saved = serveAspects([aspectsCase()]);
    const user = userEvent.setup();
    renderApp("/hitl/aspectos");
    await screen.findByText(/modo a ciegas/);

    await user.keyboard("0");
    await user.keyboard("{Enter}");

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toMatchObject({
      families: [],
      flag_update: false,
      flag_security: false,
    });
  });

  it("nada del caso queda en localStorage y no tiene violaciones de axe", async () => {
    serveAspects([aspectsCase()]);
    const { container } = renderApp("/hitl/aspectos");
    await screen.findByText(/modo a ciegas/);
    await screen.findByRole("heading", { name: "Guía de aspectos" });

    expect(await axe(container)).toHaveNoViolations();
    expect(JSON.stringify({ ...localStorage })).not.toMatch(/token/);
  });

  it("la entrada ofrece la cola de aspectos y la curaduría de tópicos", async () => {
    server.use(
      http.get("*/api/v1/hitl/summary", () =>
        HttpResponse.json({
          tasks: [
            {
              task: "aspects",
              pending: 50,
              mine_this_week: 3,
              team_this_week: 9,
              median_seconds: 61,
              monitor_done: 0,
              monitor_target: 0,
            },
          ],
        }),
      ),
      http.get("*/api/v1/hitl/topics/versions", () =>
        HttpResponse.json({
          versions: [
            {
              topic_model_version: "model_v1",
              fitted_at: "2026-10-01T00:00:00Z",
              topics: 100,
              paired: 97,
              decided: 12,
              is_current: false,
              activates_on_completion: true,
            },
          ],
        }),
      ),
    );
    renderApp("/hitl");

    expect(
      await screen.findByRole("heading", { name: "Cola de aspectos" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/85 tópicos por decidir en una versión nueva/),
    ).toBeInTheDocument();
    expect(
      screen
        .getAllByRole("link", { name: "Empezar" })
        .map((a) => a.getAttribute("href")),
    ).toEqual(["/hitl/aspectos", "/hitl/topicos"]);
  });
});
