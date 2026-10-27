import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { axe } from "vitest-axe";
import type {
  ActionState,
  CalibrationOut,
  DriftCell,
  EligibilityRow,
  IngestionRunOut,
  ModelOut,
  ModelsResponse,
  QualityPoint,
  QualityResponse,
  RunOut,
} from "@/api/mlops";
import { syntheticMe } from "@/test/handlers";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

const REASON = "Hay un aviso de reentrenamiento del monitor";

function point(over: Partial<QualityPoint> = {}): QualityPoint {
  return {
    period: "2026Q3",
    value: 0.93,
    ci_low: 0.9,
    ci_high: 0.95,
    n: 300,
    threshold: 0.89,
    status: "ok",
    model_version: "m1",
    llm_model: null,
    prompt_version: null,
    computed_at: "2026-10-20T12:00:00Z",
    ...over,
  };
}

const QUALITY: QualityResponse = {
  signals: [
    {
      signal: "kappa_monitor",
      points: [
        point({ period: "2026Q2", value: 0.94 }),
        point({ value: 0.87, status: "retrain" }),
      ],
    },
    {
      signal: "correction_rate",
      points: [
        point({
          period: "2026-10",
          value: 0.31,
          threshold: 0.28,
          status: "warning",
          ci_low: null,
          ci_high: null,
        }),
      ],
    },
    {
      signal: "gemini_agreement",
      points: [
        point({
          period: "2026-10",
          value: 0.97,
          threshold: 0.94,
          ci_low: null,
          ci_high: null,
        }),
      ],
    },
    {
      signal: "families_validation",
      points: [
        point({
          value: 0.4,
          threshold: 0.53,
          status: "rejected",
          model_version: null,
          llm_model: "gemini-x",
          prompt_version: "aspects_v2_1",
        }),
      ],
    },
  ],
};

const CURVE = {
  curve: {
    model_version: "m1",
    calibration_version: "cal1",
    points: [
      {
        coverage: 0.8,
        risk: 0.02,
        risk_ci_low: 0.01,
        risk_ci_high: 0.03,
        threshold: 0.6,
        errors_caught: 0.5,
        reviews_per_week: 700,
        minutes_per_week: 80,
      },
      {
        coverage: 0.9,
        risk: 0.004,
        risk_ci_low: 0.001,
        risk_ci_high: 0.01,
        threshold: 0.74,
        errors_caught: 0.8,
        reviews_per_week: 350,
        minutes_per_week: 40,
      },
    ],
    weekly_volume_total: 3500,
    weekly_volume_by_bank: { BBVA: 700 },
    computed_at: "2026-10-01T12:00:00Z",
  },
  current_point: null,
  median_seconds: 7,
  timed_n: 100,
  window_days: 90,
  hitl_boosts_active: [],
};

function cells(metric: string): DriftCell[] {
  const periods = ["2026-08", "2026-09", "2026-10"];
  return ["BBVA", "NUBANK"].flatMap((bank) =>
    periods.map((period, i) => ({
      bank_id: bank,
      period,
      value: 0.2 + i / 100,
      baseline: 0.19,
      z: bank === "NUBANK" && i === 2 ? 4.6 : 0.5 * i,
      psi: null,
      threshold: metric.startsWith("topic_") ? null : 4,
      alert: bank === "NUBANK" && i === 2,
    })),
  );
}

function action(
  name: ActionState["action"],
  enabled: boolean,
  reason: string | null,
): ActionState {
  return { action: name, enabled, reason };
}

function model(over: Partial<ModelOut> & { model_version: string }): ModelOut {
  return {
    status: "candidate",
    current: false,
    ever_promoted: false,
    base_checkpoint: "base",
    training_data: "plata",
    training_data_hash: "b".repeat(64),
    calibration_version: "cal",
    calibration_t: 1.68,
    kappa_dev: 0.92,
    ece_dev: 0.011,
    aurc_dev: 0.004,
    license: "Apache-2.0",
    history: [
      {
        status: "candidate",
        at: "2026-10-01T12:00:00Z",
        actor: null,
        reason: null,
      },
    ],
    check: null,
    actions: [
      action("rescore", true, "El texto sale a Kaggle"),
      action("promote", false, "Falta el re-scoring de esta candidata"),
      action("rollback", false, "Esta versión nunca estuvo promovida"),
    ],
    ...over,
  };
}

const CHECK = {
  candidate_version: "v2",
  current_version: "v1",
  gold_version: "gold_v1",
  n: 794,
  kappa_diff: 0.012,
  kappa_ci_low: 0.004,
  kappa_ci_high: 0.02,
  macro_f1_diff: 0.01,
  macro_f1_ci_low: -0.002,
  macro_f1_ci_high: 0.022,
  verdict: "better" as const,
  computed_at: "2026-10-10T12:00:00Z",
};

function models(verdict: "better" | "worse" = "better"): ModelsResponse {
  const check =
    verdict === "worse"
      ? {
          ...CHECK,
          kappa_diff: -0.03,
          kappa_ci_low: -0.05,
          kappa_ci_high: -0.01,
          verdict,
        }
      : CHECK;
  return {
    current_version: "v1",
    force_word: "FORZAR",
    models: [
      model({
        model_version: "v1",
        status: "promoted",
        current: true,
        ever_promoted: true,
        kappa_dev: 0.917,
        history: [
          {
            status: "candidate",
            at: "2026-08-01T12:00:00Z",
            actor: null,
            reason: null,
          },
          {
            status: "promoted",
            at: "2026-08-10T12:00:00Z",
            actor: "a1b2c3d4",
            reason: "Mejor que la anterior",
          },
        ],
        actions: [
          action("rescore", false, "Solo se re-puntúan las candidatas"),
          action("promote", false, "Solo se promueven candidatas"),
          action("rollback", false, "Es la versión vigente"),
        ],
      }),
      model({
        model_version: "v2",
        check,
        actions: [
          action(
            "rescore",
            false,
            "Ya tiene su verificación de re-scoring en el registro",
          ),
          action(
            "promote",
            true,
            verdict === "worse"
              ? "El veredicto es peor: para promover hay que escribir FORZAR"
              : null,
          ),
          action("rollback", false, "Esta versión nunca estuvo promovida"),
        ],
      }),
      model({
        model_version: "v0",
        status: "retired",
        ever_promoted: true,
        history: [
          {
            status: "candidate",
            at: "2026-01-01T12:00:00Z",
            actor: null,
            reason: null,
          },
          {
            status: "promoted",
            at: "2026-01-10T12:00:00Z",
            actor: "a1b2c3d4",
            reason: "Primera",
          },
          {
            status: "retired",
            at: "2026-08-10T12:00:00Z",
            actor: null,
            reason: "reemplazada por v1",
          },
        ],
        actions: [
          action("rescore", false, "Solo se re-puntúan las candidatas"),
          action("promote", false, "Solo se promueven candidatas"),
          action("rollback", true, null),
        ],
      }),
    ],
    actions: [
      action("retrain", false, "No hay aviso de reentrenamiento vigente"),
      {
        action: "topics_refit",
        enabled: false,
        reason:
          "Re-ajuste programado: próxima fecha 2027-01-01. Para lanzarlo a mano, cambia el modo en Administración",
        next_date: "2027-01-01",
      },
    ],
  };
}

const BIN = {
  low: 0.9,
  high: 1,
  n: 700,
  weight: 0.9,
  confidence: 0.99,
  accuracy: 0.97,
};
const CALIBRATION: CalibrationOut = {
  model_version: "v2",
  source: "docs",
  source_label: "docs/analytics/calibration/calibration_v0_metrics.json",
  temperature: 1.6811,
  ece_raw: 0.0256,
  ece_calibrated: 0.0109,
  raw: [BIN],
  calibrated: [{ ...BIN, accuracy: 0.98 }],
};

const RUNS: RunOut[] = [
  {
    run_id: "delta-1",
    kind: "delta",
    environment: "cloudrun",
    status: "succeeded",
    started_at: "2026-10-25T06:00:00Z",
    ended_at: "2026-10-25T06:10:00Z",
    duration_seconds: 600,
    reviews: 900,
    texts: 900,
    cost_usd: 0,
    peak_memory_mib: 2500,
    model_version: "v1",
    topic_model_version: "topics_v1",
    actor: null,
    reason: null,
  },
  {
    run_id: "training-1",
    kind: "training",
    environment: "kaggle",
    status: "running",
    started_at: "2026-10-26T06:00:00Z",
    ended_at: null,
    duration_seconds: null,
    reviews: 0,
    texts: 0,
    cost_usd: null,
    peak_memory_mib: null,
    model_version: "v2",
    topic_model_version: null,
    actor: "a1b2c3d4",
    reason: "Reentrenamiento con la plata de abril",
  },
];

const INGESTION: IngestionRunOut[] = [
  {
    run_id: "ing-1",
    bank_id: "BBVA",
    mode: "incremental",
    started_at: "2026-10-25T08:00:00Z",
    ended_at: "2026-10-25T08:05:00Z",
    duration_seconds: 300,
    status: "COMPLETED",
    reviews_extracted: 420,
    reviews_published: 400,
    reviews_discarded: 20,
  },
];

const ELIGIBILITY: EligibilityRow[] = [
  ["ELEGIBLE", 800],
  ["TNSS_SINGLE_WORD", 150],
  ["TNSS_EMPTY", 50],
].map(([code, n]) => ({
  bank_id: "BBVA",
  period: "2026-09",
  code: code as string,
  n: n as number,
}));

interface Posted {
  action: string;
  body: Record<string, unknown>;
}

/** Sirve todo lo de MLOps; las acciones quedan en `posted`. */
function serve(
  options: { verdict?: "better" | "worse"; roles?: string[] } = {},
) {
  const posted: Posted[] = [];
  server.use(
    http.get("*/api/v1/me", () =>
      HttpResponse.json(
        syntheticMe({
          roles: (options.roles ?? [
            "lector",
            "analista",
            "administrador",
          ]) as never,
        }),
      ),
    ),
    http.get("*/api/v1/mlops/quality", () => HttpResponse.json(QUALITY)),
    http.get("*/api/v1/mlops/coverage-curve", () => HttpResponse.json(CURVE)),
    http.get("*/api/v1/mlops/drift", ({ request }) => {
      const metric =
        new URL(request.url).searchParams.get("metric") ?? "family_AC";
      return HttpResponse.json({
        metric,
        series: ["family_AC", "mean_words", "neg_share"],
        banks: ["BBVA", "NUBANK"],
        cells: cells(metric),
      });
    }),
    http.get("*/api/v1/mlops/topics-context", () =>
      HttpResponse.json({
        topics: [
          { metric: "topic_noise_share", cells: cells("topic_noise_share") },
        ],
        families: [
          { metric: "flag_update_share", cells: cells("flag_update_share") },
        ],
      }),
    ),
    http.get("*/api/v1/mlops/models", () =>
      HttpResponse.json(models(options.verdict)),
    ),
    http.get("*/api/v1/mlops/models/:version/calibration", ({ params }) =>
      params.version === "v2"
        ? HttpResponse.json(CALIBRATION)
        : HttpResponse.json(
            {
              error: { code: "not_found", message: "No hay", request_id: "r" },
            },
            { status: 404 },
          ),
    ),
    http.get("*/api/v1/mlops/runs", () =>
      HttpResponse.json({
        runs: RUNS,
        memory_limit_mib: 4096,
        freshness: {
          last_ingestion_at: "2026-10-26T05:00:00Z",
          last_delta_at: "2026-10-25T06:10:00Z",
          last_monitor_at: "2026-10-21T06:10:00Z",
        },
      }),
    ),
    http.get("*/api/v1/mlops/ingestion", () => HttpResponse.json(INGESTION)),
    http.get("*/api/v1/mlops/eligibility", () =>
      HttpResponse.json(ELIGIBILITY),
    ),
    http.post("*/api/v1/mlops/actions/:action", async ({ params, request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      posted.push({ action: params.action as string, body });
      return HttpResponse.json({
        action: params.action,
        job: "voc-ml-promote",
        operation: "operations/1",
      });
    }),
  );
  return { posted };
}

describe("MLOps: modelo", () => {
  it("cada señal muestra su umbral vigente y su estado", async () => {
    serve();
    renderApp("/mlops");

    const kappa = (
      await screen.findByRole("heading", { name: /κ trimestral/ })
    ).closest("div") as HTMLElement;
    expect(within(kappa).getByText("reentrenar")).toBeInTheDocument();
    expect(
      within(kappa).getByText(/Umbral vigente \(piso\)/),
    ).toBeInTheDocument();
    expect(within(kappa).getByText("0.890")).toBeInTheDocument();
    expect(within(kappa).getByText("0.870")).toBeInTheDocument();

    const correction = screen
      .getByRole("heading", { name: /Tasa de corrección/ })
      .closest("div") as HTMLElement;
    expect(within(correction).getByText("aviso")).toBeInTheDocument();
    expect(
      within(correction).getByText(/Umbral vigente \(tope\)/),
    ).toBeInTheDocument();

    const families = screen
      .getByRole("heading", { name: /Revalidación de las familias/ })
      .closest("div") as HTMLElement;
    expect(within(families).getByText("rechazado")).toBeInTheDocument();
    expect(
      within(families).getByText(/gemini-x, prompt aspects_v2_1/),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("img", { name: /serie por periodo con su umbral/ }),
    ).toHaveLength(4);
  });

  it("muestra la curva vigente y los tópicos como contexto sin umbral", async () => {
    serve();
    renderApp("/mlops");

    expect(
      await screen.findByText("Cobertura y riesgo del modelo promovido"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Curva de cobertura/ }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/se acumulan para fijar uno con evidencia/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: /cláusulas sin tópico por banco y mes/i,
      }),
    ).toBeInTheDocument();
  });

  it("no tiene violaciones de axe", async () => {
    serve();
    const { container } = renderApp("/mlops");
    await screen.findByText("Cobertura y riesgo del modelo promovido");
    await screen.findByText(/se acumulan para fijar uno/);
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("MLOps: deriva", () => {
  it("pinta el mapa de calor, marca los meses sobre el umbral y abre la serie", async () => {
    serve();
    const user = userEvent.setup();
    renderApp("/mlops?tab=deriva");

    const alert = await screen.findByRole("button", {
      name: /Banco Morado, oct 2026: z 4.6, supera el umbral/i,
    });
    expect(alert.getAttribute("style")).toContain("--color-gold-600");
    expect(screen.getByText(/1 mes supera el umbral/)).toBeInTheDocument();

    await user.click(alert);
    expect(
      await screen.findByText(/Umbral vigente: z ≥ 4/),
    ).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /z mensual/ })).toBeInTheDocument();
  });

  it("cambia de serie desde el selector y lo guarda en la URL", async () => {
    serve();
    const user = userEvent.setup();
    const { router } = renderApp("/mlops?tab=deriva");

    await user.selectOptions(
      await screen.findByLabelText("Serie"),
      "neg_share",
    );

    await waitFor(() =>
      expect(router.state.location.search).toContain("serie=neg_share"),
    );
  });
});

describe("MLOps: registro y acciones", () => {
  it("muestra las versiones, su historia y las diferencias de la regla de promoción", async () => {
    serve();
    renderApp("/mlops?tab=registro");

    expect(await screen.findByText("vigente")).toBeInTheDocument();
    expect(screen.getAllByText(/Promovida/)).toHaveLength(2);
    expect(screen.getByText(/Retirada/)).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: /Diferencia de κ de v2: \+0.012, intervalo de \+0.004 a \+0.020/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("mejor")).toBeInTheDocument();
    expect(await screen.findByText(/Temperatura:/)).toBeInTheDocument();
    expect(screen.getByText("1.6811")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Antes de la temperatura/ }),
    ).toBeInTheDocument();
  });

  it("los botones deshabilitados explican por qué", async () => {
    serve();
    renderApp("/mlops?tab=registro");

    const retrain = await screen.findByRole("button", { name: "Reentrenar" });
    expect(retrain).toBeDisabled();
    expect(retrain).toHaveAccessibleDescription(
      "No hay aviso de reentrenamiento vigente",
    );
    expect(
      screen.getByRole("button", { name: "Re-scoring v2" }),
    ).toHaveAccessibleDescription(/Ya tiene su verificación/);
    expect(
      screen.getByRole("button", { name: "Rollback v2" }),
    ).toHaveAccessibleDescription("Esta versión nunca estuvo promovida");
    expect(
      screen.getByRole("button", { name: "Re-ajustar tópicos" }),
    ).toHaveAccessibleDescription(/próxima fecha 2027-01-01/);
    expect(screen.getByRole("button", { name: "Promover v2" })).toBeEnabled();
  });

  it("un analista ve los botones pero no puede lanzar nada", async () => {
    serve({ roles: ["lector", "analista"] });
    renderApp("/mlops?tab=registro");

    const promote = await screen.findByRole("button", { name: "Promover v2" });
    expect(promote).toBeDisabled();
    expect(promote).toHaveAccessibleDescription(
      "Solo el rol administrador lanza acciones.",
    );
  });

  it("promover pide el motivo y lanza la acción con la versión", async () => {
    const { posted } = serve();
    const user = userEvent.setup();
    renderApp("/mlops?tab=registro");

    await user.click(
      await screen.findByRole("button", { name: "Promover v2" }),
    );
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Promover" });
    expect(confirm).toBeDisabled();
    expect(within(dialog).queryByLabelText(/Escribe/)).not.toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Motivo/), REASON);
    await user.click(confirm);

    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({
      action: "promote",
      body: { reason: REASON, model_version: "v2", confirm_word: null },
    });
  });

  it("promover una peor pide escribir FORZAR", async () => {
    const { posted } = serve({ verdict: "worse" });
    const user = userEvent.setup();
    renderApp("/mlops?tab=registro");

    expect(await screen.findByText("peor")).toBeInTheDocument();
    expect(
      screen.getByText(/El candidato es peor que el vigente/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Promover v2" }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Promover" });
    await user.type(within(dialog).getByLabelText(/Motivo/), REASON);
    expect(confirm).toBeDisabled();

    await user.type(within(dialog).getByLabelText(/Escribe/), "FORZAR");
    await user.click(confirm);

    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]?.body.confirm_word).toBe("FORZAR");
  });

  it("el rollback se lanza desde la versión retirada", async () => {
    const { posted } = serve();
    const user = userEvent.setup();
    renderApp("/mlops?tab=registro");

    expect(
      await screen.findByRole("button", { name: "Rollback v2" }),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Elegir v0" }));
    await user.click(screen.getByRole("button", { name: "Rollback v0" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Motivo/), REASON);
    await user.click(within(dialog).getByRole("button", { name: "Rollback" }));

    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({
      action: "rollback",
      body: { reason: REASON, model_version: "v0", confirm_word: null },
    });
  });

  it("no tiene violaciones de axe", async () => {
    serve();
    const { container } = renderApp("/mlops?tab=registro");
    await screen.findByText(/Temperatura:/);
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("MLOps: pipeline", () => {
  it("muestra frescura, corridas con quién y por qué, ingesta y no predecibles", async () => {
    serve();
    renderApp("/mlops?tab=pipeline");

    expect(
      await screen.findByText("Última ingesta completa"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/el monitor no registra sus corridas/),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("table").length).toBeGreaterThanOrEqual(3);
    expect(
      screen.getByRole("cell", { name: "Entrenamiento" }),
    ).toBeInTheDocument();
    expect(screen.getByText("a1b2c3d4")).toBeInTheDocument();
    expect(
      screen.getByText(/Reentrenamiento con la plata de abril/),
    ).toBeInTheDocument();
    expect(screen.getByText("en curso")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /límite de 4 GiB/ }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("sin dato").length).toBeGreaterThan(0);
    expect(
      await screen.findByText(/No predecibles por motivo y banco/),
    ).toBeInTheDocument();
    expect(screen.getByText("20.0 %")).toBeInTheDocument();
  });

  it("filtra las corridas por tipo", async () => {
    serve();
    const user = userEvent.setup();
    renderApp("/mlops?tab=pipeline");

    await user.selectOptions(await screen.findByLabelText("Tipo"), "training");

    const rows = screen.getAllByRole("row");
    expect(rows.some((r) => /Delta diario/.test(r.textContent ?? ""))).toBe(
      false,
    );
    expect(rows.some((r) => /Entrenamiento/.test(r.textContent ?? ""))).toBe(
      true,
    );
  });

  it("no tiene violaciones de axe", async () => {
    serve();
    const { container } = renderApp("/mlops?tab=pipeline");
    await screen.findByText(/No predecibles por motivo y banco/);
    expect(await axe(container)).toHaveNoViolations();
  });
});
