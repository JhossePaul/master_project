"""Siembra de las versiones iniciales (6.3), desde las métricas de EPIC-5.

Inserta, de solo inserción e idempotente por clave:

* ``model_versions``: RoBERTuito (``robertuito_sentiment_v1``, semilla 1 de
  ``M4_robertuito_s1_ppi``) promovido, con T 1.6811 y sus métricas en el oro
  *dev* (κ, ECE con temperatura y AURC de ``prob_max``);
* ``hitl_coverage_curves``: la curva de la semilla 1 de 5.6, con revisiones y
  minutos por semana (mediana de 7.1 s por reseña, validación de 5.9);
* ``risk_policy`` v1: la evidencia de EPIC-5 y nulos en los parámetros que
  fija el dueño de negocio en 7.10 (D12);
* ``drift_policy_template`` v1 y una ``drift_policy`` por banco (P7-9), con
  umbral nulo en las familias y la marca ``u`` (D8);
* ``guidelines``: ``v2.2`` de sentimiento y ``v2.1`` de aspectos.

El oro (``gold_labels``) lo carga ``load-local``.
"""

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from voc_common.analytics_codes import AspectFamily, HitlTask, ModelStatus
from voc_common.constants import BankKey
from voc_common.hitl_v3 import Guideline
from voc_common.operations_v3 import ModelVersion
from voc_common.policies import (
    CoveragePoint,
    DriftPolicy,
    DriftPolicyTemplate,
    DriftThresholds,
    HitlCoverageCurve,
    RiskPolicy,
)

from ml_inference import artifacts
from ml_inference.bq_io import StagingMergeWriter
from ml_inference.config import InferenceSettings

MODEL_VERSION: Final = "robertuito_sentiment_v1"
# Nombre de la semilla elegida en los reportes de EPIC-5 (D11).
EPIC5_MODEL: Final = "M4_robertuito_s1_ppi"
CALIBRATION_VERSION: Final = "temperature_v0_s1"
RISK_POLICY_VERSION: Final = "risk_policy_v1"
DRIFT_TEMPLATE_VERSION: Final = "drift_policy_template_v1"
# Mediana de segundos por reseña en la validación de la cola de 5.9.
SECONDS_PER_REVIEW: Final = 7.1

# Series del monitor de deriva (6.4) y su umbral (P7-9, D8).
Z_SERIES: Final = (
    "mean_words",
    "single_word_share",
    "over_60_words_share",
    "not_predicted_share",
    "out_of_vocabulary_share",
    "neg_share",
)
Z_THRESHOLD: Final = 4.0
PSI_SERIES: Final = ("length_distribution",)
PSI_THRESHOLD: Final = 0.25
CONTEXT_SERIES: Final = (
    *(f"family_{f.value}" for f in AspectFamily),
    "flag_update_share",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def model_version(
    settings: InferenceSettings, docs: Path, actor_hash: str, now: datetime
) -> ModelVersion:
    calibration = _load(docs / "calibration/calibration_v0_metrics.json")
    selective = _load(docs / "calibration/selective_v0_metrics.json")
    monitor = _load(docs / "scale/model_monitor_v0_metrics.json")
    temperature = calibration["modelos"][EPIC5_MODEL]["temperature"]
    prefix = artifacts.artifact_prefix(
        settings.ml_artifacts_prefix, artifacts.SENTIMENT, MODEL_VERSION
    )
    kappa = monitor["kappa_m4_por_tamano_de_muestra"]["kappa_poblacional_dev"]
    return ModelVersion(
        model_version=MODEL_VERSION,
        registry_uri=artifacts.gcs_uri(
            settings.gcs_raw_datalake_bucket, prefix
        ),
        base_checkpoint="pysentimiento/robertuito-sentiment-analysis",
        training_data="silver_v0 (lote m4_ppi, semilla 1)",
        calibration_version=CALIBRATION_VERSION,
        calibration_t=temperature["temperatura"],
        kappa_dev=kappa,
        ece_dev=temperature["dev_fuera_de_particion"]["ece"],
        aurc_dev=selective["modelos"][EPIC5_MODEL]["aurc"]["prob_max"],
        license="pysentimiento: uso no comercial e investigación",
        status=ModelStatus.PROMOTED,
        promoted_at=now,
        promoted_by_hash=actor_hash,
        recorded_at=now,
    )


def coverage_curve(docs: Path, now: datetime) -> HitlCoverageCurve:
    selective = _load(docs / "calibration/selective_v0_metrics.json")
    weekly = selective["volumen"]["textos_unicos_por_semana"]
    points = []
    for p in selective["modelos"][EPIC5_MODEL]["por_cobertura"].values():
        reviews = (1 - p["cobertura"]) * weekly
        points.append(
            CoveragePoint(
                coverage=p["cobertura"],
                risk=p["riesgo"],
                risk_ci_low=p["ic_riesgo"][0] if "ic_riesgo" in p else None,
                risk_ci_high=p["ic_riesgo"][1] if "ic_riesgo" in p else None,
                threshold=p["umbral"],
                errors_caught=p["errores_atrapados"],
                reviews_per_week=round(reviews, 1),
                minutes_per_week=round(reviews * SECONDS_PER_REVIEW / 60, 1),
            )
        )
    return HitlCoverageCurve(
        model_version=MODEL_VERSION,
        calibration_version=CALIBRATION_VERSION,
        points=sorted(points, key=lambda p: p.coverage),
        weekly_volume_total=round(weekly),
        # El volumen por banco lo agrega el recálculo de 6.4.
        weekly_volume_by_bank={},
        computed_at=now,
    )


def risk_policy(
    curve: HitlCoverageCurve, actor_hash: str, reason: str, now: datetime
) -> RiskPolicy:
    point = next(p for p in curve.points if round(p.coverage, 2) == 0.90)
    return RiskPolicy(
        policy_version=RISK_POLICY_VERSION,
        valid_from=now,
        hitl_signal="prob_max",
        hitl_target_coverage=0.90,
        hitl_threshold=point.threshold,
        model_version=MODEL_VERSION,
        monitor_sample_size=300,
        monitor_frequency="quarterly",
        topic_refit_frequency="quarterly",
        retrain_kappa_floor=0.89,
        warn_correction_rate=0.28,
        warn_agreement_floor=0.94,
        agreement_sample_weekly=500,
        families_exact_floor=0.53,
        families_min_prevalence=0.05,
        set_by_hash=actor_hash,
        reason=reason,
    )


def drift_thresholds() -> DriftThresholds:
    z: dict[str, float | None] = dict.fromkeys(Z_SERIES, Z_THRESHOLD)
    z.update(dict.fromkeys(CONTEXT_SERIES, None))
    return DriftThresholds(z=z, psi=dict.fromkeys(PSI_SERIES, PSI_THRESHOLD))


def drift_policies(
    actor_hash: str, reason: str, now: datetime
) -> tuple[DriftPolicyTemplate, list[DriftPolicy]]:
    body: dict[str, Any] = {
        "valid_from": now,
        "thresholds": drift_thresholds(),
        "baseline_months": 12,
        "min_baseline_months": 6,
        "min_rows_per_month": 200,
        "entry_months": 12,
        "set_by_hash": actor_hash,
        "reason": reason,
    }
    template = DriftPolicyTemplate(
        template_version=DRIFT_TEMPLATE_VERSION, **body
    )
    policies = [
        DriftPolicy(
            drift_policy_version=f"drift_policy_v1_{bank.value.lower()}",
            bank_id=bank.value,
            template_version=DRIFT_TEMPLATE_VERSION,
            **body,
        )
        for bank in BankKey
    ]
    return template, policies


def guidelines(actor_hash: str, now: datetime) -> list[Guideline]:
    return [
        Guideline(
            guideline_version="v2.2",
            task=HitlTask.SENTIMENT,
            content_uri="docs/analytics/labeling/annotation_guideline.md",
            valid_from=now,
            published_by_hash=actor_hash,
        ),
        Guideline(
            guideline_version="v2.1",
            task=HitlTask.ASPECTS,
            content_uri="docs/analytics/eda/eda_aspects_guideline.md",
            valid_from=now,
            published_by_hash=actor_hash,
        ),
    ]


def seed(
    settings: InferenceSettings,
    writer: StagingMergeWriter,
    docs: Path,
    actor_hash: str,
    reason: str,
    now: datetime,
) -> dict[str, int]:
    """Inserta las versiones iniciales; devuelve las filas nuevas por tabla."""
    run_id = f"seed-{now:%Y%m%dT%H%M%S}"
    curve = coverage_curve(docs, now)
    template, policies = drift_policies(actor_hash, reason, now)
    plan: Sequence[tuple[str, Sequence[Any], list[str]]] = (
        (
            "model_versions",
            [model_version(settings, docs, actor_hash, now)],
            ["model_version", "status"],
        ),
        (
            "hitl_coverage_curves",
            [curve],
            ["model_version", "calibration_version"],
        ),
        (
            "risk_policy",
            [risk_policy(curve, actor_hash, reason, now)],
            ["policy_version"],
        ),
        ("drift_policy_template", [template], ["template_version"]),
        ("drift_policy", policies, ["drift_policy_version"]),
        (
            "guidelines",
            guidelines(actor_hash, now),
            ["guideline_version", "task"],
        ),
    )
    return {
        table: writer.write(table, rows, key, run_id)
        for table, rows, key in plan
    }
