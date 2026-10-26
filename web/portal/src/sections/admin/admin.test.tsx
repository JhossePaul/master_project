import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { axe } from "vitest-axe";
import { syntheticMe, syntheticRiskPolicy } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";
import { proposedThresholds } from "./DriftTab";
import { compareVersions, flatten, whoIs } from "./HistoryTab";
import { toChanges, toForm } from "./RiskTab";

type Body = Record<string, unknown>;

const PREVIEW_COVERAGE = {
  proposed: syntheticRiskPolicy({ hitl_target_coverage: 0.85 }),
  diff: [
    { field: "hitl_target_coverage", before: 0.9, after: 0.85 },
    { field: "hitl_threshold", before: 0.74, after: 0.66 },
  ],
  large_change: false,
  warnings: [],
  errors: [],
};

/** Captura lo que el portal manda a `preview` y a `risk-policy`. */
function serveRisk(preview: Record<string, unknown> = PREVIEW_COVERAGE) {
  const calls: { preview: Body[]; saved: Body[] } = { preview: [], saved: [] };
  server.use(
    http.post("*/api/v1/admin/risk-policy/preview", async ({ request }) => {
      calls.preview.push((await request.json()) as Body);
      return HttpResponse.json(preview);
    }),
    http.post("*/api/v1/admin/risk-policy", async ({ request }) => {
      calls.saved.push((await request.json()) as Body);
      return HttpResponse.json(
        syntheticRiskPolicy({ policy_version: "risk_policy_v2" }),
        { status: 201 },
      );
    }),
  );
  return calls;
}

async function setCoverage(value: string) {
  const user = userEvent.setup();
  const field = await screen.findByLabelText("Cobertura objetivo");
  await user.clear(field);
  await user.type(field, value);
  return user;
}

describe("administración: apetito de riesgo", () => {
  it("muestra la curva, la tabla con el tiempo medido y el formulario", async () => {
    renderApp("/admin");

    expect(
      await screen.findByRole("heading", {
        name: "Cobertura y error esperado",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/medidos, n = 412/)).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Curva de cobertura/ }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Tope semanal de revisión")).toHaveValue(null);
    expect(
      screen.getByRole("button", { name: "Ayuda: Cobertura objetivo" }),
    ).toBeInTheDocument();
  });

  it("el control de cobertura mueve el punto propuesto", async () => {
    renderApp("/admin");
    await screen.findByLabelText("Cobertura objetivo");
    expect(screen.queryByText("◆ Propuesto")).not.toBeInTheDocument();

    await setCoverage("0.85");

    expect(await screen.findByText("◆ Propuesto")).toBeInTheDocument();
  });

  it("revisar manda solo lo que cambió y el diff lista solo eso", async () => {
    const calls = serveRisk();
    renderApp("/admin");
    const user = await setCoverage("0.85");

    await user.click(screen.getByRole("button", { name: "Revisar cambios" }));

    const panel = await screen.findByText("Cambios propuestos");
    expect(calls.preview[0]).toEqual({
      base_version: "risk_policy_v1",
      changes: { hitl_target_coverage: 0.85 },
    });
    const list = panel.closest("div") as HTMLElement;
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).getByText("hitl_threshold")).toBeInTheDocument();
  });

  it("guardar exige un motivo de al menos 10 caracteres", async () => {
    const calls = serveRisk();
    renderApp("/admin");
    const user = await setCoverage("0.85");
    await user.click(screen.getByRole("button", { name: "Revisar cambios" }));
    await screen.findByText("Cambios propuestos");

    await user.click(screen.getByRole("button", { name: "Guardar…" }));
    const confirm = await screen.findByRole("button", {
      name: "Guardar versión",
    });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText(/Motivo/), "corto");
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText(/Motivo/), " pero suficiente");
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() => expect(calls.saved).toHaveLength(1));
    expect(calls.saved[0]).toMatchObject({
      base_version: "risk_policy_v1",
      changes: { hitl_target_coverage: 0.85 },
      reason: "corto pero suficiente",
      confirm_word: null,
    });
  });

  it("un cambio grande pide escribir CONFIRMAR", async () => {
    const calls = serveRisk({
      ...PREVIEW_COVERAGE,
      large_change: true,
      warnings: [
        "La cobertura cambia más de 5 puntos: pide escribir CONFIRMAR.",
      ],
    });
    renderApp("/admin");
    const user = await setCoverage("0.8");
    await user.click(screen.getByRole("button", { name: "Revisar cambios" }));
    await screen.findByText("Cambios propuestos");

    await user.click(screen.getByRole("button", { name: "Guardar…" }));
    await user.type(
      await screen.findByLabelText(/Motivo/),
      "bajar la revisión esta semana",
    );
    const confirm = screen.getByRole("button", { name: "Guardar versión" });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText(/Escribe/), "CONFIRMAR");
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() => expect(calls.saved).toHaveLength(1));
    expect(calls.saved[0]).toMatchObject({ confirm_word: "CONFIRMAR" });
  });

  it("el disparo automático muestra la advertencia de Kaggle", async () => {
    renderApp("/admin");
    const user = userEvent.setup();
    const select = await screen.findByLabelText(
      "Quién lanza el reentrenamiento",
    );

    await user.selectOptions(select, "auto");

    expect(
      screen.getByText(/el texto sale a Kaggle sin aprobación por corrida/),
    ).toBeInTheDocument();
  });

  it("un campo fuera de rango no llega a la API", async () => {
    const calls = serveRisk();
    renderApp("/admin");
    const user = await setCoverage("0.5");

    await user.click(screen.getByRole("button", { name: "Revisar cambios" }));

    expect(await screen.findByText("Mínimo 0.8")).toBeInTheDocument();
    expect(calls.preview).toHaveLength(0);
  });

  it("no tiene violaciones de axe", async () => {
    const { container } = renderApp("/admin");
    await screen.findByLabelText("Cobertura objetivo");
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("administración: deriva, historial y oro", () => {
  it("un umbral propuesto pide las tasas con ese valor y se guarda por banco", async () => {
    const rates: Body[] = [];
    const saved: Body[] = [];
    server.use(
      http.post("*/api/v1/admin/drift-policy/rates", async ({ request }) => {
        rates.push((await request.json()) as Body);
        return HttpResponse.json({
          bank: "BBVA",
          series: [
            {
              series: "neg_share",
              months: 60,
              proposed_alerts: 6,
              proposed_per_year: 1.2,
              current_alerts: 4,
              current_per_year: 0.8,
              reference: 1.1,
            },
          ],
        });
      }),
      http.post("*/api/v1/admin/drift-policy", async ({ request }) => {
        saved.push((await request.json()) as Body);
        return HttpResponse.json({}, { status: 201 });
      }),
    );
    renderApp("/admin?tab=deriva");
    const user = userEvent.setup();
    const input = await screen.findByLabelText("Umbral propuesto de neg_share");

    await user.clear(input);
    await user.type(input, "3");

    await waitFor(() =>
      expect(rates.at(-1)).toMatchObject({
        thresholds: { z: { neg_share: 3 } },
      }),
    );
    expect(await screen.findByText("1.2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Guardar…" }));
    await user.type(
      await screen.findByLabelText(/Motivo/),
      "z 3 en la proporción negativa",
    );
    await user.click(screen.getByRole("button", { name: "Guardar versión" }));

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toMatchObject({
      bank: "BBVA",
      changes: { thresholds: { z: { neg_share: 3 } } },
    });
  });

  it("el historial dice 'tú' para el hash propio y compara dos versiones", async () => {
    const mine = syntheticMe().actor_hash;
    const v1 = syntheticRiskPolicy();
    const v2 = syntheticRiskPolicy({
      policy_version: "risk_policy_v2",
      valid_from: "2026-10-20T00:00:00Z",
      set_by_hash: mine,
      reason: "Bajar la cobertura",
      hitl_target_coverage: 0.85,
    });
    server.use(
      http.get("*/api/v1/admin/risk-policy", () =>
        HttpResponse.json({ current: v2, history: [v1, v2] }),
      ),
    );
    renderApp("/admin?tab=historial");
    const user = userEvent.setup();

    expect(await screen.findByText("tú")).toBeInTheDocument();
    expect(screen.getByText("bbbbbbbb")).toBeInTheDocument();
    await user.click(screen.getByLabelText("Comparar risk_policy_v1"));
    await user.click(screen.getByLabelText("Comparar risk_policy_v2"));

    expect(await screen.findByText("hitl_target_coverage")).toBeInTheDocument();
    expect(screen.queryByText("retrain_kappa_floor")).not.toBeInTheDocument();
  });

  it("el oro cuenta lo que entraría, avisa de GOLD_VERSION y crea la versión", async () => {
    const created: Body[] = [];
    server.use(
      http.post("*/api/v1/admin/gold-versions/preview", () =>
        HttpResponse.json({
          total: 12,
          by_bank: [{ key: "BBVA", n: 12 }],
          by_label: [{ key: "NEG", n: 12 }],
        }),
      ),
      http.post("*/api/v1/admin/gold-versions", async ({ request }) => {
        created.push((await request.json()) as Body);
        return HttpResponse.json(
          {
            version: {
              gold_version: "gold_hitl_v1",
              criteria: {},
              cutoff_at: "2026-10-26T12:00:00Z",
              items: 12,
              created_by_hash: "b".repeat(64),
              created_at: "2026-10-26T12:00:00Z",
            },
            reason: "muestra del trimestre",
          },
          { status: 201 },
        );
      }),
    );
    renderApp("/admin?tab=oro");
    const user = userEvent.setup();
    expect(await screen.findByText(/GOLD_VERSION/)).toBeInTheDocument();

    await user.type(screen.getByLabelText("Revisadas desde"), "2026-07-01");
    await user.type(screen.getByLabelText("Revisadas hasta"), "2026-09-30");
    await user.click(
      screen.getByRole("button", { name: "Ver cuántas entrarían" }),
    );
    expect(await screen.findByText("revisiones entrarían")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Crear versión…" }));
    await user.type(
      await screen.findByLabelText(/Motivo/),
      "muestra del trimestre",
    );
    await user.click(screen.getByRole("button", { name: "Crear versión" }));

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({
      criteria: {
        submitted_from: "2026-07-01",
        guideline_version: "v2.2",
        exclude_flags: ["no_evaluable"],
        review_round: 1,
      },
      reason: "muestra del trimestre",
    });
  });
});

describe("administración: acceso", () => {
  it("un analista no entra", async () => {
    server.use(
      http.get("*/api/v1/me", () =>
        HttpResponse.json(syntheticMe({ roles: ["lector", "analista"] })),
      ),
    );
    renderApp("/admin");
    expect(
      await screen.findByText("No tienes acceso a esta sección"),
    ).toBeInTheDocument();
  });
});

describe("funciones puras", () => {
  it("toChanges deja solo lo que cambió y apaga los grupos", () => {
    const current = syntheticRiskPolicy();
    const values = {
      ...toForm(current),
      hitl_target_coverage: 0.85,
      retrain_trigger: "auto" as const,
    };

    expect(toChanges(values, current)).toEqual({
      hitl_target_coverage: 0.85,
      retrain_trigger: "auto",
    });
    expect(toChanges(toForm(current), current)).toEqual({});
    const withBoost = syntheticRiskPolicy({
      drift_boost_coverage: 0.95,
      drift_boost_days: 7,
      drift_boost_weekly_cap: 300,
    });
    expect(
      toChanges({ ...toForm(withBoost), no_boost: true }, withBoost),
    ).toEqual({
      drift_boost_coverage: null,
      drift_boost_days: null,
      drift_boost_weekly_cap: null,
    });
  });

  it("proposedThresholds respeta el tipo de cada serie", () => {
    const current = { z: { a: 4, b: 4 }, psi: { c: 0.25 } };

    expect(
      proposedThresholds(current, { "z:a": "3", "z:b": "", "psi:c": "x" }),
    ).toEqual({ z: { a: 3, b: null }, psi: { c: 0.25 } });
  });

  it("flatten, compareVersions y whoIs", () => {
    expect(flatten({ a: { b: 1 }, c: [1, 2] })).toEqual({
      "a.b": 1,
      c: [1, 2],
    });
    const base = { id: "a", valid_from: "", set_by_hash: "", reason: "" };
    expect(
      compareVersions(
        { ...base, row: { reason: "x", t: { z: 4 }, k: 1 } },
        { ...base, row: { reason: "y", t: { z: 3 }, k: 1 } },
      ),
    ).toEqual([{ field: "t.z", before: 4, after: 3 }]);
    const me = syntheticMe();
    expect(whoIs(me.actor_hash, me)).toBe("tú");
    expect(whoIs("c".repeat(64), me)).toBe("cccccccc");
  });
});
