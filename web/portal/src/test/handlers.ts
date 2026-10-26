import { HttpResponse, http } from "msw";
import type { components } from "@/api/schema";

type Me = components["schemas"]["MeResponse"];
type Landing = components["schemas"]["LandingResponse"];

export function syntheticMe(overrides: Partial<Me> = {}): Me {
  return {
    email: "ana@example.com",
    actor_hash: "a".repeat(64),
    roles: ["lector", "analista", "revisor", "administrador"],
    reviewer_tasks: ["sentiment", "aspects", "topic"],
    environment: "dev",
    commit: "abc1234def",
    ...overrides,
  };
}

const BANKS = ["BBVA", "AZTECA", "SANTANDER", "NUBANK", "BANORTE"];

export function syntheticLanding(overrides: Partial<Landing> = {}): Landing {
  const recent = new Date(Date.now() - 3_600_000).toISOString();
  return {
    freshness: {
      last_ingestion_at: recent,
      last_delta: {
        run_id: "delta-1",
        kind: "delta",
        status: "succeeded",
        started_at: recent,
        ended_at: recent,
        model_version: "sintetico_v1",
      },
      last_monitor_at: recent,
      data_until: "2026-10-24",
    },
    open_alerts: { AZTECA: 1, NUBANK: 2 },
    banks: BANKS.map((bank_id, i) => ({
      bank_id,
      period: "2026-09",
      neg: {
        estimate: 0.15 + i / 50,
        ci_low: 0.14 + i / 50,
        ci_high: 0.16 + i / 50,
        method: "ppi",
        n_gold: 1200,
        n_unlabeled: 18000,
      },
      gap_estrellas: {
        estimate: -0.3 - i / 20,
        ci_low: -0.35 - i / 20,
        ci_high: -0.25 - i / 20,
        method: "ppi",
        n_gold: 1200,
        n_unlabeled: 18000,
      },
      model_version: "sintetico_v1",
      gold_version: "gold_sintetico",
    })),
    hitl_pending: 42,
    ...overrides,
  };
}

type HitlCase = components["schemas"]["HitlCase"];
type HitlSummary = components["schemas"]["HitlSummary"];

export function syntheticHitlCase(overrides: Partial<HitlCase> = {}): HitlCase {
  return {
    item_id: "a".repeat(32),
    task: "sentiment",
    text: "No puedo entrar a la app desde ayer.\nSale un error.",
    display_mode: "assisted",
    proposal: { label: "NEG", p_neg: 0.62, p_neu: 0.25, p_pos: 0.13 },
    guideline_version: "v2.2",
    opened_at: "2026-10-26T12:00:00Z",
    review_round: 1,
    ...overrides,
  };
}

export function syntheticHitlSummary(): HitlSummary {
  return {
    tasks: [
      {
        task: "sentiment",
        pending: 197,
        mine_this_week: 12,
        team_this_week: 30,
        median_seconds: 42,
        monitor_done: 0,
        monitor_target: 300,
      },
    ],
  };
}

type Estimate = components["schemas"]["Estimate"];
type Card = components["schemas"]["BankCard"];

function est(
  value: number,
  spread = 0.01,
  method: "ppi" | "raw" = "ppi",
): Estimate {
  return {
    estimate: value,
    ci_low: method === "ppi" ? value - spread : null,
    ci_high: method === "ppi" ? value + spread : null,
    method,
    n_gold: method === "ppi" ? 1200 : null,
    n_unlabeled: 18000,
  };
}

export function syntheticCards(): Card[] {
  return BANKS.map((bank_id, i) => ({
    bank_id,
    period: "2026-09",
    neg: est(0.15 + i / 50),
    gap_estrellas: est(-0.3 - i / 20, 0.05),
    quejas_4_5: est(0.04),
    previous_month: {
      period: "2026-08",
      neg: est(0.14),
      gap_estrellas: est(-0.25, 0.05),
      quejas_4_5: est(0.035),
    },
    previous_year: {
      period: "2025-09",
      neg: est(0.12),
      gap_estrellas: est(-0.2, 0.05),
      quejas_4_5: est(0.03),
    },
    model_version: "sintetico_v1",
    gold_version: "gold_sintetico",
    open_alerts: i === 1 ? 1 : 0,
  }));
}

export function syntheticDaily(): components["schemas"]["DailyPoint"][] {
  return BANKS.flatMap((bank_id) =>
    ["2026-10-10", "2026-10-11", "2026-10-12"].map((dia) => ({
      bank_id,
      dia,
      filas: 110,
      predichas: 100,
      neg: 20,
      neu: 10,
      pos: 70,
      no_predichas: 10,
      gap_crudo: -0.4,
      texto_peor: 15,
      texto_mejor: 8,
      neg_4_5: 3,
    })),
  );
}

export function syntheticDailyTopics(): components["schemas"]["DailyTopics"] {
  const theme = (codigo: string, nombre: string) => ({
    codigo,
    nombre,
    filas: 8,
    participacion: 0.4,
    habitual: 0.25,
  });
  return {
    bank_id: "BBVA",
    dia: "2026-10-12",
    n_neg: 20,
    familias: [
      theme("AC", "Acceso y autenticación"),
      theme("FA", "Falla general de la app"),
    ],
    topicos: [theme("3", "Inicio de sesión que falla")],
    aspects_prompt_version: "aspects_v2_1",
    topic_model_version: "topics_sintetico",
  };
}

const PERIODS = ["2026-07", "2026-08", "2026-09"];

export function syntheticMonthly(): components["schemas"]["MonthlyKpi"][] {
  return BANKS.flatMap((bank_id, i) =>
    PERIODS.flatMap((period) =>
      [
        ["neg", 0.15 + i / 50],
        ["gap_estrellas", -0.3 - i / 20],
      ].map(([metric, value]) => ({
        bank_id,
        period,
        metric: metric as string,
        ppi: est(value as number, 0.02),
        raw: est((value as number) * 1.05, 0, "raw"),
        model_version: "sintetico_v1",
      })),
    ),
  );
}

export function syntheticFamilies(): components["schemas"]["FamiliesResponse"] {
  return {
    series: BANKS.flatMap((bank_id) =>
      PERIODS.flatMap((period, k) =>
        ["AC", "FA", "u"].map((family) => ({
          bank_id,
          period,
          family,
          neg_count: 40 + k,
          share: 0.2,
          z: family === "AC" && k === 2 ? 4.6 : 0.3,
          threshold: 4,
          alert: family === "AC" && k === 2,
        })),
      ),
    ),
    prompt_changes: [
      {
        prompt_version: "aspects_v2_1",
        first_labeled_at: "2026-08-03T00:00:00Z",
      },
    ],
  };
}

export function syntheticTopics(): components["schemas"]["TopicMonth"][] {
  return BANKS.flatMap((bank_id) =>
    PERIODS.flatMap((period) =>
      [
        [1, "Inicio de sesión que falla", ["AC"]],
        [2, "Transferencias que no llegan", ["TR"]],
      ].map(([topic_id, nombre, families]) => ({
        bank_id,
        period,
        topic_id: topic_id as number,
        nombre: nombre as string,
        audience: "ingenieria",
        families: families as string[],
        filas: 30,
        share: 0.1,
        topic_model_version: "topics_sintetico",
      })),
    ),
  );
}

export function syntheticMatrix(): components["schemas"]["MatrixCell"][] {
  const classes = ["NEG", "NEU", "POS"] as const;
  return classes.flatMap((stars_class) =>
    classes.map((text_class) => ({
      bank_id: "BBVA",
      period: "2026-09",
      stars_class,
      text_class,
      ppi: est(stars_class === text_class ? 0.2 : 0.05),
      raw: est(0.1, 0, "raw"),
    })),
  );
}

export function syntheticVersions(): components["schemas"]["VersionsResponse"] {
  const row = (release: string, share: number) => ({
    release,
    first_seen: new Date(Date.now() - 20 * 86_400_000)
      .toISOString()
      .slice(0, 10),
    last_seen: new Date().toISOString().slice(0, 10),
    filas: 1000,
    neg: Math.round(share * 1000),
    neg_share: share,
    neg_ci_low: share - 0.03,
    neg_ci_high: share + 0.03,
    u_share: 0.18,
    families: { FA: 0.4, AC: 0.2, LE: 0.1, TR: 0.05 },
  });
  return {
    bank_id: "BBVA",
    rows: [row("11.33", 0.4), row("11.34", 0.38), row("OTRAS", 0.3)],
    coverage: 0.909,
    median_neg_share: 0.38,
    median_u_share: 0.18,
  };
}

export function syntheticVersionDaily(
  sentiment: "ALL" | "NEG" | "NEU" | "POS" = "ALL",
): components["schemas"]["VersionDailyResponse"] {
  const days = ["2026-10-10", "2026-10-11", "2026-10-12"];
  return {
    bank_id: "BBVA",
    sentiment,
    total: 90,
    releases: [
      { release: "26.80.9", filas: 30, first_day: "2026-10-10" },
      { release: "26.90.10", filas: 40, first_day: "2026-10-11" },
      { release: "OTRAS", filas: 20, first_day: "2026-10-10" },
    ],
    days: days.map((dia, i) => ({
      dia,
      counts: (i === 0
        ? { "26.80.9": 20, OTRAS: 10 }
        : { "26.80.9": 10, "26.90.10": 20, OTRAS: 5 }) as Record<
        string,
        number
      >,
    })),
  };
}

type RiskPolicy = components["schemas"]["RiskPolicy"];
type DriftPolicy = components["schemas"]["DriftPolicy"];

export function syntheticRiskPolicy(
  overrides: Partial<RiskPolicy> = {},
): RiskPolicy {
  return {
    policy_version: "risk_policy_v1",
    valid_from: "2026-10-01T00:00:00Z",
    hitl_signal: "prob_max",
    hitl_target_coverage: 0.9,
    hitl_threshold: 0.74,
    model_version: "sintetico_v1",
    monitor_sample_size: 300,
    monitor_frequency: "quarterly",
    topic_refit_frequency: "quarterly",
    retrain_kappa_floor: 0.89,
    warn_correction_rate: 0.28,
    warn_agreement_floor: 0.94,
    agreement_sample_weekly: 500,
    families_exact_floor: 0.53,
    families_min_prevalence: 0.05,
    set_by_hash: "b".repeat(64),
    reason: "Semilla inicial",
    ...overrides,
  };
}

const CURVE: [number, number, number][] = [
  [0.8, 0.021, 0.58],
  [0.85, 0.014, 0.66],
  [0.9, 0.004, 0.74],
  [0.95, 0.002, 0.86],
];

export function syntheticCurve(): components["schemas"]["CoverageCurveResponse"] {
  const points = CURVE.map(([coverage, risk, threshold]) => ({
    coverage,
    risk,
    risk_ci_low: Math.max(risk - 0.003, 0),
    risk_ci_high: risk + 0.004,
    threshold,
    errors_caught: 0.7,
    reviews_per_week: Math.round((1 - coverage) * 3500),
    minutes_per_week: Math.round(((1 - coverage) * 3500 * 7) / 60),
  }));
  return {
    curve: {
      model_version: "sintetico_v1",
      calibration_version: "cal_v1",
      points,
      weekly_volume_total: 3500,
      weekly_volume_by_bank: { BBVA: 3500 },
      computed_at: "2026-10-23T00:00:00Z",
    },
    current_point: points[2] ?? null,
    median_seconds: 7,
    timed_n: 412,
    window_days: 90,
    hitl_boosts_active: [],
  };
}

export function syntheticDriftPolicy(bank: string): DriftPolicy {
  return {
    drift_policy_version: `drift_policy_v1_${bank}`,
    bank_id: bank,
    template_version: "drift_template_v1",
    valid_from: "2026-09-01T00:00:00Z",
    thresholds: {
      z: { neg_share: 4, mean_words: 4 },
      psi: { length_distribution: 0.25 },
    },
    baseline_months: 12,
    min_baseline_months: 6,
    min_rows_per_month: 200,
    entry_months: 12,
    set_by_hash: "b".repeat(64),
    reason: "Copia de la plantilla",
  };
}

const adminHandlers = [
  http.get("*/api/v1/admin/risk-policy", () => {
    const current = syntheticRiskPolicy();
    return HttpResponse.json({ current, history: [current] });
  }),
  http.get("*/api/v1/admin/coverage-curve", () =>
    HttpResponse.json(syntheticCurve()),
  ),
  http.get("*/api/v1/admin/drift-policy", ({ request }) => {
    const bank = new URL(request.url).searchParams.get("bank") ?? "BBVA";
    const current = syntheticDriftPolicy(bank);
    return HttpResponse.json({
      current,
      template: {
        template_version: "drift_template_v1",
        valid_from: "2026-08-01T00:00:00Z",
        thresholds: current.thresholds,
        baseline_months: 12,
        min_baseline_months: 6,
        min_rows_per_month: 200,
        entry_months: 12,
        set_by_hash: "b".repeat(64),
        reason: "Plantilla",
      },
      history: [current],
      diff_vs_template: [],
    });
  }),
  http.post("*/api/v1/admin/drift-policy/rates", () =>
    HttpResponse.json({
      bank: "BBVA",
      series: [
        {
          series: "neg_share",
          months: 60,
          proposed_alerts: 4,
          proposed_per_year: 0.8,
          current_alerts: 4,
          current_per_year: 0.8,
          reference: 1.1,
        },
      ],
    }),
  ),
  http.get("*/api/v1/admin/gold-versions", () => HttpResponse.json([])),
];

export const handlers = [
  http.get("*/api/v1/kpis/versions/daily", ({ request }) =>
    HttpResponse.json(
      syntheticVersionDaily(
        (new URL(request.url).searchParams.get("sentiment") ?? "ALL") as "ALL",
      ),
    ),
  ),
  http.get("*/api/v1/kpis/cards", () => HttpResponse.json(syntheticCards())),
  http.get("*/api/v1/kpis/daily", () => HttpResponse.json(syntheticDaily())),
  http.get("*/api/v1/kpis/daily-topics", () =>
    HttpResponse.json(syntheticDailyTopics()),
  ),
  http.get("*/api/v1/kpis/monthly", () =>
    HttpResponse.json(syntheticMonthly()),
  ),
  http.get("*/api/v1/kpis/families", () =>
    HttpResponse.json(syntheticFamilies()),
  ),
  http.get("*/api/v1/kpis/topics", () => HttpResponse.json(syntheticTopics())),
  http.get("*/api/v1/kpis/matrix", () => HttpResponse.json(syntheticMatrix())),
  http.get("*/api/v1/kpis/versions", () =>
    HttpResponse.json(syntheticVersions()),
  ),
  http.get("*/api/v1/kpis/model-changes", () =>
    HttpResponse.json([
      { model_version: "sintetico_v1", promoted_at: "2026-10-11T00:00:00Z" },
    ]),
  ),
  http.get("*/api/v1/hitl/summary", () =>
    HttpResponse.json(syntheticHitlSummary()),
  ),
  http.get("*/api/v1/hitl/guidelines/:task", () =>
    HttpResponse.json({
      task: "sentiment",
      guideline_version: "v2.2",
      valid_from: "2026-10-01T00:00:00Z",
      content:
        "# Guía de sentimiento\n\n| Etiqueta | Cuándo |\n| :-- | :-- |\n| NEG | Queja |",
    }),
  ),
  http.post(
    "*/api/v1/hitl/items/:id/release",
    () => new HttpResponse(null, { status: 204 }),
  ),
  http.get("*/api/v1/me", () => HttpResponse.json(syntheticMe())),
  http.get("*/api/v1/landing", () => HttpResponse.json(syntheticLanding())),
  ...adminHandlers,
];
