"""Datos sintéticos de MLOps para diseñar el portal sin GCP.

Un modelo vigente (``sintetico_v1``), una candidata con su verificación
(``sintetico_v2``), otra sin ella (``sintetico_v3``) y una versión retirada
a la que se puede volver (``sintetico_v0``). El monitor no tiene avisos.
"""

from datetime import UTC, date, datetime, timedelta

from voc_common import (
    DriftMetric,
    InferenceRun,
    ModelQuality,
    ModelStatus,
    ModelVersion,
    PromotionCheckResult,
    PromotionVerdict,
    QualitySignal,
    QualityStatus,
    RunEnvironment,
    RunKind,
    RunStatus,
)

from api_backend.sections.admin.sample import BANKS, HASH, MODEL, risk_policy
from api_backend.sections.mlops.repository import (
    EligibilityCount,
    IngestionRun,
    InMemoryMlopsRepository,
)

DRIFT_SERIES = (
    ("mean_words", 4.0, "z"),
    ("neg_share", 4.0, "z"),
    ("family_AC", 4.0, "z"),
    ("flag_update_share", 4.0, "z"),
    ("topic_noise_share", None, "z"),
    ("topic_unaligned_share", None, "z"),
)
LLM = "gemini-2.5-flash"
PROMPT = "aspects_v2_1"


def _months(last: date, count: int) -> list[date]:
    out = []
    for back in range(count - 1, -1, -1):
        index = last.year * 12 + last.month - 1 - back
        out.append(date(index // 12, index % 12 + 1, 1))
    return out


def _version(
    name: str,
    status: ModelStatus,
    at: datetime,
    kappa: float,
    *,
    promoted_at: datetime | None = None,
    reason: str | None = None,
) -> ModelVersion:
    return ModelVersion(
        model_version=name,
        registry_uri=f"gs://datos-de-muestra/ml_artifacts/sentiment/{name}/",
        base_checkpoint="pysentimiento/robertuito-base-uncased",
        training_data="plata de muestra, 2026-04",
        training_data_hash="b" * 64,
        calibration_version=f"cal_{name}",
        calibration_t=1.68,
        kappa_dev=kappa,
        ece_dev=0.011,
        aurc_dev=0.004,
        license="Apache-2.0",
        status=status,
        promoted_at=promoted_at,
        promoted_by_hash=HASH if promoted_at else None,
        reason=reason,
        recorded_at=at,
    )


def _check(now: datetime, verdict: PromotionVerdict) -> PromotionCheckResult:
    better = verdict is PromotionVerdict.BETTER
    return PromotionCheckResult(
        candidate_version="sintetico_v2",
        current_version=MODEL,
        gold_version="gold_v1",
        n=794,
        kappa_diff=0.012 if better else -0.03,
        kappa_ci_low=0.004 if better else -0.05,
        kappa_ci_high=0.02 if better else -0.01,
        macro_f1_diff=0.01 if better else -0.02,
        macro_f1_ci_low=-0.002 if better else -0.04,
        macro_f1_ci_high=0.022 if better else -0.005,
        verdict=verdict,
        run_id="rescoring-sintetico_v2",
        computed_at=now - timedelta(days=4),
    )


def _quality(now: datetime) -> list[ModelQuality]:
    rows = []
    for n, period in enumerate(("2025Q4", "2026Q1", "2026Q2", "2026Q3")):
        rows.append(
            ModelQuality(
                model_version=MODEL,
                signal=QualitySignal.KAPPA_MONITOR,
                period=period,
                value=0.93 - 0.005 * n,
                n=300,
                ci_low=0.9 - 0.005 * n,
                ci_high=0.95 - 0.005 * n,
                threshold=0.89,
                status=QualityStatus.OK,
                computed_at=now - timedelta(days=90 * (3 - n)),
            )
        )
    for n, month in enumerate(("2026-07", "2026-08", "2026-09", "2026-10")):
        at = now - timedelta(days=30 * (3 - n))
        rows.append(
            ModelQuality(
                model_version=MODEL,
                signal=QualitySignal.CORRECTION_RATE,
                period=month,
                value=0.18 + 0.01 * n,
                n=1200,
                threshold=0.28,
                status=QualityStatus.OK,
                computed_at=at,
            )
        )
        rows.append(
            ModelQuality(
                model_version=MODEL,
                signal=QualitySignal.GEMINI_AGREEMENT,
                period=month,
                value=0.97 - 0.004 * n,
                n=500,
                threshold=0.94,
                status=QualityStatus.OK,
                computed_at=at,
            )
        )
    rows.append(
        ModelQuality(
            llm_model=LLM,
            prompt_version=PROMPT,
            signal=QualitySignal.FAMILIES_VALIDATION,
            period="2026Q3",
            value=0.61,
            n=420,
            threshold=0.53,
            status=QualityStatus.OK,
            computed_at=now - timedelta(days=20),
        )
    )
    return rows


def _drift(now: datetime) -> list[DriftMetric]:
    last = date(now.year, now.month, 1)
    rows = []
    for b, bank in enumerate(BANKS):
        for s, (series, threshold, _kind) in enumerate(DRIFT_SERIES):
            for m, period in enumerate(_months(last, 24)):
                z = ((m * 7 + b * 3 + s * 5) % 13) / 2 - 3.0
                spike = bank == "NUBANK" and series == "neg_share" and m == 23
                if spike:
                    z = 4.6
                rows.append(
                    DriftMetric(
                        bank_id=bank,
                        period=period,
                        metric=series,
                        value=0.15 + 0.01 * ((m + b) % 4),
                        baseline=0.16,
                        z=None if threshold is None else z,
                        psi=None,
                        threshold=threshold,
                        alert=spike,
                        drift_policy_version="drift_policy_v2",
                        computed_at=now - timedelta(days=2),
                    )
                )
    return rows


def _runs(now: datetime) -> list[InferenceRun]:
    rows = []
    for day in range(30):
        start = now - timedelta(days=day, hours=6)
        failed = day == 11
        rows.append(
            InferenceRun(
                run_id=f"delta-{day:02d}",
                kind=RunKind.DELTA,
                environment=RunEnvironment.CLOUDRUN,
                model_version=MODEL,
                topic_model_version="topics_v1",
                started_at=start,
                ended_at=start + timedelta(minutes=9 + day % 5),
                reviews=0 if failed else 900 + 10 * day,
                texts=0 if failed else 900 + 10 * day,
                status=RunStatus.FAILED if failed else RunStatus.SUCCEEDED,
                cost_usd=0.0,
                peak_memory_mib=2400 + 60 * (day % 6),
            )
        )
    rows.append(
        InferenceRun(
            run_id="training-sintetico_v2",
            kind=RunKind.TRAINING,
            environment=RunEnvironment.KAGGLE,
            model_version="sintetico_v2",
            started_at=now - timedelta(days=9),
            ended_at=now - timedelta(days=9) + timedelta(hours=2),
            reviews=0,
            texts=21000,
            status=RunStatus.SUCCEEDED,
            cost_usd=0.94,
            actor_hash=HASH,
            reason="Reentrenamiento con la plata de abril",
        )
    )
    return rows


def _ingestion(now: datetime) -> list[IngestionRun]:
    rows = []
    for day in range(10):
        for bank in BANKS:
            start = now - timedelta(days=day, hours=8)
            rows.append(
                IngestionRun(
                    run_id=f"ing-{bank}-{day}",
                    bank_id=bank,
                    mode="incremental",
                    started_at=start,
                    ended_at=start + timedelta(minutes=4 + day),
                    status="FAILED"
                    if (day, bank) == (3, "AZTECA")
                    else "COMPLETED",
                    reviews_extracted=420,
                    reviews_published=400,
                    reviews_discarded=20,
                )
            )
    return rows


def _eligibility(now: datetime) -> list[EligibilityCount]:
    rows = []
    codes = (
        ("ELEGIBLE", 700),
        ("TNSS_SINGLE_WORD", 150),
        ("TNSS_EMPTY", 30),
        ("TNSS_NO_TEXT_CONTENT", 40),
        ("TNSS_TIME_OUTLIER", 12),
    )
    for period in _months(date(now.year, now.month, 1), 6):
        for b, bank in enumerate(BANKS):
            for code, n in codes:
                rows.append(EligibilityCount(bank, period, code, n + 5 * b))
    return rows


def sample_repository(now: datetime | None = None) -> InMemoryMlopsRepository:
    now = now or datetime.now(UTC)
    day = timedelta(days=1)
    return InMemoryMlopsRepository(
        policies=[risk_policy(now)],
        quality_rows=_quality(now),
        drift_rows=_drift(now),
        model_rows=[
            _version(
                "sintetico_v0", ModelStatus.CANDIDATE, now - 300 * day, 0.9
            ),
            _version(
                "sintetico_v0",
                ModelStatus.PROMOTED,
                now - 200 * day,
                0.9,
                promoted_at=now - 200 * day,
                reason="Primera promoción",
            ),
            # Como el registro real: la fila de retiro conserva la promoción.
            _version(
                "sintetico_v0",
                ModelStatus.RETIRED,
                now - 60 * day,
                0.9,
                promoted_at=now - 200 * day,
                reason=f"reemplazada por {MODEL}",
            ),
            _version(MODEL, ModelStatus.CANDIDATE, now - 70 * day, 0.917),
            _version(
                MODEL,
                ModelStatus.PROMOTED,
                now - 60 * day,
                0.917,
                promoted_at=now - 60 * day,
                reason="Mejor que la versión anterior",
            ),
            _version(
                "sintetico_v2", ModelStatus.CANDIDATE, now - 9 * day, 0.925
            ),
            _version(
                "sintetico_v3", ModelStatus.CANDIDATE, now - 1 * day, 0.92
            ),
        ],
        check_rows=[_check(now, PromotionVerdict.BETTER)],
        run_rows=_runs(now),
        ingestion_rows=_ingestion(now),
        eligibility_rows=_eligibility(now),
        ingestion_at=now - timedelta(hours=7),
        monitor_at=now - 5 * day,
        topic_fit_at=now - 40 * day,
    )
