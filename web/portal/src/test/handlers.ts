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
    first_seen: "2026-01-01",
    last_seen: "2026-02-01",
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

export const handlers = [
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
  http.get("*/api/v1/me", () => HttpResponse.json(syntheticMe())),
  http.get("*/api/v1/landing", () => HttpResponse.json(syntheticLanding())),
];
