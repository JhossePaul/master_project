"""Datos sintéticos de administración para diseñar el portal sin GCP."""

from datetime import UTC, datetime, timedelta

from voc_common import (
    DriftPolicy,
    DriftPolicyTemplate,
    DriftThresholds,
    HitlBoost,
    HitlCoverageCurve,
    RiskPolicy,
)
from voc_common.policies import CoveragePoint

from api_backend.sections.admin.repository import (
    DriftMonth,
    GoldRow,
    InMemoryAdminRepository,
)

MODEL = "sintetico_v1"
GUIDELINE = "v2.2"
BANKS = ("AZTECA", "BANORTE", "BBVA", "NUBANK", "SANTANDER")
Z_SERIES = (
    "mean_words",
    "single_word_share",
    "over_60_words_share",
    "not_predicted_share",
    "out_of_vocabulary_share",
    "neg_share",
)
HASH = "a" * 64
# (cobertura, riesgo, umbral, errores atrapados)
CURVE = (
    (0.8, 0.021, 0.58, 0.55),
    (0.85, 0.014, 0.66, 0.66),
    (0.9, 0.004, 0.74, 0.80),
    (0.95, 0.002, 0.86, 0.91),
    (0.98, 0.001, 0.95, 0.97),
    (1.0, 0.0, 1.0, 1.0),
)
WEEKLY_TOTAL = 3500


def curve(now: datetime) -> HitlCoverageCurve:
    points = [
        CoveragePoint(
            coverage=c,
            risk=risk,
            risk_ci_low=None if c == 1.0 else max(risk - 0.003, 0.0),
            risk_ci_high=None if c == 1.0 else risk + 0.004,
            threshold=threshold,
            errors_caught=caught,
            reviews_per_week=round((1 - c) * WEEKLY_TOTAL, 1),
            minutes_per_week=round((1 - c) * WEEKLY_TOTAL * 7 / 60, 1),
        )
        for c, risk, threshold, caught in CURVE
    ]
    return HitlCoverageCurve(
        model_version=MODEL,
        calibration_version="cal_sintetica_v1",
        points=points,
        weekly_volume_total=WEEKLY_TOTAL,
        weekly_volume_by_bank={b: WEEKLY_TOTAL // 5 for b in BANKS},
        computed_at=now - timedelta(days=3),
    )


def risk_policy(now: datetime) -> RiskPolicy:
    return RiskPolicy(
        policy_version="risk_policy_v1",
        valid_from=now - timedelta(days=30),
        hitl_signal="prob_max",
        hitl_target_coverage=0.9,
        hitl_threshold=0.74,
        model_version=MODEL,
        monitor_sample_size=300,
        monitor_frequency="quarterly",
        topic_refit_frequency="quarterly",
        retrain_kappa_floor=0.89,
        warn_correction_rate=0.28,
        warn_agreement_floor=0.94,
        agreement_sample_weekly=500,
        families_exact_floor=0.53,
        families_min_prevalence=0.05,
        set_by_hash=HASH,
        reason="Semilla inicial (datos de muestra)",
    )


def thresholds() -> DriftThresholds:
    return DriftThresholds(
        z={s: 4.0 for s in Z_SERIES},
        psi={"length_distribution": 0.25},
    )


def _months(seed: int) -> list[DriftMonth]:
    out = []
    for i in range(36):
        year, month = 2023 + i // 12, i % 12 + 1
        period = f"{year}-{month:02d}"
        for n, series in enumerate(Z_SERIES):
            z = ((i * 7 + n * 5 + seed * 3) % 11) / 2 - 2.5
            out.append(DriftMonth(series, period, z, None))
        psi = ((i * 3 + seed) % 9) / 30
        out.append(DriftMonth("length_distribution", period, None, psi))
    return out


def sample_repository(now: datetime | None = None) -> InMemoryAdminRepository:
    now = now or datetime.now(UTC)
    repo = InMemoryAdminRepository()
    repo.risk = [risk_policy(now)]
    repo.promoted = MODEL
    repo.curves = {MODEL: curve(now)}
    repo.timed = (7.0, 412)
    repo.boosts = [
        HitlBoost(
            boost_id="boost-sintetico",
            bank_id="NUBANK",
            alert_id="alert-sintetica",
            risk_policy_version="risk_policy_v1",
            coverage=0.95,
            weekly_cap=400,
            starts_at=now - timedelta(days=2),
            ends_at=now + timedelta(days=5),
        )
    ]
    template = DriftPolicyTemplate(
        template_version="drift_template_v1",
        valid_from=now - timedelta(days=60),
        thresholds=thresholds(),
        baseline_months=12,
        min_baseline_months=6,
        min_rows_per_month=200,
        entry_months=12,
        set_by_hash=HASH,
        reason="Plantilla inicial (datos de muestra)",
    )
    repo.templates = {template.template_version: template}
    for n, bank in enumerate(BANKS):
        repo.drift[bank] = [
            DriftPolicy(
                drift_policy_version=f"drift_policy_v1_{bank}",
                bank_id=bank,
                template_version=template.template_version,
                valid_from=template.valid_from,
                thresholds=template.thresholds,
                baseline_months=template.baseline_months,
                min_baseline_months=template.min_baseline_months,
                min_rows_per_month=template.min_rows_per_month,
                entry_months=template.entry_months,
                set_by_hash=HASH,
                reason="Copia de la plantilla (datos de muestra)",
            )
        ]
        repo.months[bank] = _months(n)
    for n in range(1, 13):
        item = f"monitor_sample:2026Q3:syn-gold-{n:03d}:{MODEL}"
        repo.reviews.append(
            GoldRow(
                item_id=item,
                id_resena=f"syn-gold-{n:03d}",
                bank_id=BANKS[n % 5],
                validated_label=("NEG", "NEU", "POS")[n % 3],
                submitted_at=now - timedelta(days=20 - n),
                reviewer_hash=HASH,
            )
        )
        repo.review_meta[item] = {
            "reason": "monitor_sample",
            "review_round": 1,
            "guideline_version": GUIDELINE,
            "flags": [],
        }
    return repo
