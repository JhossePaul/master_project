import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { axe } from "vitest-axe";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

type Body = Record<string, unknown>;

const VERSION = {
  topic_model_version: "model_v1",
  fitted_at: "2026-10-01T00:00:00Z",
  topics: 3,
  paired: 2,
  decided: 0,
  is_current: false,
  activates_on_completion: true,
};

const previous = {
  topic_id: 0,
  centroid_similarity: 0.93,
  curation: {
    curated_name: "Códigos de acceso",
    coherence_1_5: 4,
    audience: "producto",
    families: ["AC"],
    is_new_theme: false,
    mapping_confirmed: true,
    curated_at: "2026-07-01T00:00:00Z",
  },
};

const DETAIL = {
  topic_model_version: "model_v1",
  fitted_at: "2026-10-01T00:00:00Z",
  is_current: false,
  paired: 2,
  decided: 0,
  topics: [
    {
      topic_id: 0,
      terms: ["token", "codigo"],
      size: 140,
      previous,
      decision: null,
    },
    {
      topic_id: 1,
      terms: ["spei", "error"],
      size: 95,
      previous: { ...previous, topic_id: 1, curation: null },
      decision: null,
    },
    {
      topic_id: 2,
      terms: ["actualizacion", "forzosa"],
      size: 60,
      previous: null,
      decision: null,
    },
  ],
};

function serveTopics() {
  const saved: { topic: string; body: Body }[] = [];
  server.use(
    http.get("*/api/v1/hitl/topics/versions", () =>
      HttpResponse.json({ versions: [VERSION] }),
    ),
    http.get("*/api/v1/hitl/topics/model_v1", () => HttpResponse.json(DETAIL)),
    http.get("*/api/v1/hitl/topics/model_v1/:id/examples", ({ params }) =>
      HttpResponse.json({
        topic_id: Number(params.id),
        examples: [{ text: `Ejemplo del tópico ${params.id}` }],
      }),
    ),
    http.post(
      "*/api/v1/hitl/topics/model_v1/:id",
      async ({ request, params }) => {
        saved.push({
          topic: String(params.id),
          body: (await request.json()) as Body,
        });
        return HttpResponse.json(
          { paired: 2, decided: saved.length, completed: false },
          { status: 201 },
        );
      },
    ),
  );
  return saved;
}

describe("curaduría de tópicos", () => {
  it("lista la versión pendiente con su avance y el aviso de activación", async () => {
    serveTopics();
    renderApp("/hitl/topicos");

    expect(
      await screen.findByText(/Al decidir el último, la versión se activa/),
    ).toBeInTheDocument();
    expect(screen.getByText(/0 de 2/)).toBeInTheDocument();
    expect(
      await screen.findByText(/140 cláusulas asignadas/),
    ).toBeInTheDocument();
  });

  it("la ficha trae términos, ejemplos y el par anterior con su curaduría", async () => {
    serveTopics();
    renderApp("/hitl/topicos");

    expect(await screen.findByText("token · codigo")).toBeInTheDocument();
    expect(await screen.findByText("Ejemplo del tópico 0")).toBeInTheDocument();
    expect(screen.getByText(/similitud del centroide/)).toBeInTheDocument();
    expect(
      screen.getByText(/Códigos de acceso · Producto · AC/),
    ).toBeInTheDocument();
  });

  it("guardar pide nombre, coherencia y audiencia, y manda la decisión", async () => {
    const saved = serveTopics();
    const user = userEvent.setup();
    renderApp("/hitl/topicos");
    await screen.findByText(/140 cláusulas asignadas/);

    await user.clear(screen.getByLabelText("Nombre"));
    await user.click(screen.getByRole("button", { name: "Guardar y seguir" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Escribe el nombre",
    );

    await user.type(screen.getByLabelText("Nombre"), "Acceso con token");
    await user.click(screen.getByRole("button", { name: "Guardar y seguir" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("coherencia");

    await user.click(screen.getByRole("radio", { name: "4" }));
    await user.click(screen.getByRole("button", { name: "Guardar y seguir" }));

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toEqual({
      topic: "0",
      body: {
        curated_name: "Acceso con token",
        coherence_1_5: 4,
        // Propuestos desde la curaduría del tópico anterior.
        audience: "producto",
        families: ["AC"],
        is_new_theme: false,
        mapping_confirmed: true,
      },
    });
  });

  it("un tópico sin par anterior no ofrece confirmar el emparejamiento", async () => {
    serveTopics();
    const user = userEvent.setup();
    renderApp("/hitl/topicos");
    await screen.findByText(/140 cláusulas asignadas/);

    await user.keyboard("jj");

    expect(
      await screen.findByText(/60 cláusulas asignadas/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Sin tópico anterior emparejado/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("checkbox", { name: /emparejamiento/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Es un tema nuevo" }),
    ).toBeChecked();
  });

  it("el filtro deja solo los pendientes emparejados y no tiene violaciones de axe", async () => {
    serveTopics();
    const user = userEvent.setup();
    const { container } = renderApp("/hitl/topicos");
    await screen.findByText(/140 cláusulas asignadas/);

    await user.click(screen.getByRole("checkbox", { name: "Solo pendientes" }));

    const list = screen.getByRole("navigation", {
      name: "Tópicos de la versión",
    });
    expect(within(list).getAllByRole("button")).toHaveLength(2);
    expect(await axe(container)).toHaveNoViolations();
  });
});
