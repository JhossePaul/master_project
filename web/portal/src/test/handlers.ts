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

export const handlers = [
  http.get("*/api/v1/me", () => HttpResponse.json(syntheticMe())),
  http.get("*/api/v1/landing", () => HttpResponse.json(syntheticLanding())),
];
