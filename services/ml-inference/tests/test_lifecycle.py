"""Curva, política, regla de promoción, promoción y *rollback*."""

import types
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest
from ml_inference import lifecycle, registry
from ml_inference.bq_io import StagingMergeWriter
from ml_inference.lifecycle import (
    COVERAGES,
    GoldPrediction,
    Lifecycle,
    PromotionRefused,
    build_curve,
    check_promotion,
    gold_period,
    gold_predictions,
    next_policy_version,
    point_for,
    promote_version,
    propose_risk_policy,
    week_window,
    weekly_volume,
)
from ml_inference.seed import SECONDS_PER_REVIEW
from voc_common.operations_v3 import ModelVersion
from voc_common.policies import RiskPolicy
from voc_nlp.selective import at_coverage

MODEL = "robertuito_sentiment_v1"
CANDIDATE = "robertuito_sentiment_v2"
ACTOR = "b" * 64
NOW = datetime(2026, 11, 4, 9, 30, tzinfo=UTC)
DATASET = "test-project.bbva_voc_tds"
LABELS = ("NEG", "NEU", "POS")


def synthetic_gold(n: int = 300, wrong: int = 30, seed: int = 0):
    """Oro con ``wrong`` errores de baja confianza; pesos de 1 a 4."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        label = LABELS[i % 3]
        bad = i < wrong
        out.append(
            GoldPrediction(
                id_resena=f"r{i}",
                label=label,
                weight=float(1 + i % 4),
                stratum=f"B{i % 5}|2023-2024",
                predicted=LABELS[(i + 1) % 3] if bad else label,
                confidence=float(
                    rng.uniform(0.4, 0.7) if bad else rng.uniform(0.6, 1.0)
                ),
            )
        )
    return out


def test_coverage_never_exceeds_one_by_rounding() -> None:
    """Con estos pesos, cumsum entre sum da 1.0000000000000002."""
    weights = [31.109, 25.364, 33.784, 23.204, 39.447, 44.647, 5.388, 53.39]
    assert np.cumsum(weights)[-1] / np.sum(np.array(weights)) > 1.0
    gold = [
        GoldPrediction(
            id_resena=f"r{i}",
            label=LABELS[0],
            weight=weight,
            stratum="B0|2023-2024",
            predicted=LABELS[0],
            confidence=0.99 - i * 0.01,
        )
        for i, weight in enumerate(weights)
    ]
    points = lifecycle.curve_points(gold, 100.0, 7.0, n_boot=20)
    assert points[-1].coverage == 1.0
    assert all(p.coverage <= 1.0 for p in points)


def model_row(version: str = MODEL) -> ModelVersion:
    return ModelVersion(
        model_version=version,
        registry_uri="gs://b/x/",
        base_checkpoint="base",
        training_data="silver",
        calibration_version="temperature_s1",
        calibration_t=1.2,
        license="nc",
        status="candidate",
        recorded_at=NOW,
    )


# -- Curva -------------------------------------------------------------------


def test_curve_matches_the_shared_selective_curve() -> None:
    gold = synthetic_gold()
    curve = build_curve(
        model_row(),
        gold,
        {"BBVA": 600.4, "NU": 400.2},
        1000.0,
        6.0,
        NOW,
        n_boot=200,
    )
    conf = np.array([g.confidence for g in gold])
    err = np.array([g.predicted != g.label for g in gold], dtype=float)
    w = np.array([g.weight for g in gold])
    assert len(curve.points) == len(COVERAGES)
    for target, point in zip(COVERAGES, curve.points, strict=True):
        expected = at_coverage(conf, err, w, target)
        assert point.coverage == pytest.approx(expected.coverage)
        assert point.risk == pytest.approx(expected.risk)
        assert point.threshold == pytest.approx(expected.threshold)
        assert point.reviews_per_week == round((1 - point.coverage) * 1000, 1)
        assert point.minutes_per_week == pytest.approx(
            point.reviews_per_week * 6 / 60, abs=0.06
        )
        if target < 1.0:
            assert point.risk_ci_low <= point.risk <= point.risk_ci_high
        else:
            assert point.risk_ci_low is None and point.reviews_per_week == 0
    assert curve.weekly_volume_total == 1000
    assert curve.weekly_volume_by_bank == {"BBVA": 600, "NU": 400}
    assert curve.calibration_version == "temperature_s1"


def test_curve_needs_model_probabilities() -> None:
    gold = [
        GoldPrediction("r1", "NEG", 1.0, "B|2020-2022", "NEU", None),
    ]
    with pytest.raises(ValueError, match="probabilities"):
        build_curve(model_row(), gold, {}, 10.0, 7.0, NOW)


def test_gold_predictions_classify_and_stratify() -> None:
    rows = gold_predictions(
        [
            {
                "id_resena": "a",
                "label": "NEG",
                "weight": 2,
                "bank_id": "BBVA",
                "fecha": datetime(2019, 5, 1, tzinfo=UTC),
                "sentiment": "NEG",
                "label_source": "MODEL",
                "p_neg": 0.7,
                "p_neu": 0.2,
                "p_pos": 0.1,
            },
            {
                "id_resena": "b",
                "label": "POS",
                "weight": 1,
                "bank_id": "NU",
                "fecha": "2025-02-01T00:00:00Z",
                "sentiment": "NO_PREDICTED",
                "label_source": "NO_PREDICTED",
                "p_neg": None,
                "p_neu": None,
                "p_pos": None,
            },
        ]
    )
    assert rows[0] == GoldPrediction("a", "NEG", 2.0, "BBVA|<=2019", "NEG", 0.7)
    assert rows[1] == GoldPrediction(
        "b", "POS", 1.0, "NU|2025-2026", "NEU", None
    )
    assert [gold_period(y) for y in (2019, 2020, 2022, 2023, 2024, 2026)] == [
        "<=2019",
        "2020-2022",
        "2020-2022",
        "2023-2024",
        "2023-2024",
        "2025-2026",
    ]


def test_volume_is_the_mean_of_eight_full_weeks() -> None:
    start, end = week_window(datetime(2026, 11, 4, 9, tzinfo=UTC))
    assert end == datetime(2026, 11, 2, tzinfo=UTC)
    assert start == end - timedelta(weeks=8)
    by_bank, total = weekly_volume(
        [
            {"bank_id": "BBVA", "week": "w1", "texts": 80},
            {"bank_id": "BBVA", "week": "w2", "texts": 160},
            {"bank_id": None, "week": "w1", "texts": 400},
        ]
    )
    assert by_bank == {"BBVA": 30.0} and total == 50.0


# -- Política ----------------------------------------------------------------


def policy() -> RiskPolicy:
    return RiskPolicy(
        policy_version="risk_policy_v1",
        valid_from=NOW - timedelta(days=30),
        hitl_signal="prob_max",
        hitl_target_coverage=0.9,
        hitl_threshold=0.7,
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
        set_by_hash="a" * 64,
        reason="inicio",
    )


def test_proposed_policy_takes_the_threshold_of_its_coverage() -> None:
    curve = build_curve(
        model_row(CANDIDATE),
        synthetic_gold(),
        {},
        1000.0,
        7.0,
        NOW,
        n_boot=50,
    )
    new = propose_risk_policy(curve, policy(), ACTOR, "nuevo modelo", NOW)
    assert new.policy_version == "risk_policy_v2"
    assert new.model_version == CANDIDATE
    assert new.hitl_threshold == point_for(curve, 0.9).threshold
    assert (new.set_by_hash, new.reason, new.valid_from) == (
        ACTOR,
        "nuevo modelo",
        NOW,
    )
    assert new.retrain_kappa_floor == 0.89
    lower = propose_risk_policy(curve, policy(), ACTOR, "r", NOW, 0.85)
    assert lower.hitl_target_coverage == 0.85
    assert lower.hitl_threshold >= new.hitl_threshold
    with pytest.raises(ValueError, match="reach"):
        point_for(curve.model_copy(update={"points": curve.points[:2]}), 0.95)


def test_next_policy_version() -> None:
    assert next_policy_version("risk_policy_v9") == "risk_policy_v10"
    assert next_policy_version("custom") == "custom_v2"


# -- Regla -------------------------------------------------------------------


def test_rule_tells_better_tie_and_worse() -> None:
    current = synthetic_gold(wrong=45)
    same = check_promotion(current, current, n_boot=100)
    assert same.verdict == "tie" and same.n == 300
    assert all(d.value == 0 for d in same.differences)
    better = check_promotion(current, synthetic_gold(wrong=5), n_boot=100)
    assert better.verdict == "better"
    assert {d.metric for d in better.differences} == {"kappa", "macro_f1"}
    worse = check_promotion(current, synthetic_gold(wrong=120), n_boot=100)
    assert worse.verdict == "worse"
    assert worse.describe().startswith("worse (n=300): kappa -")
    with pytest.raises(ValueError, match="share"):
        check_promotion(current[:1], current[1:2])


# -- Con BigQuery simulado ---------------------------------------------------


class LifecycleReads:
    """Lecturas del ciclo de vida sobre el ``FakeBigQuery`` del delta."""

    def __init__(self, fake: Any) -> None:
        self.fake, self.base = fake, fake._select
        self.gold: dict[str, list[GoldPrediction]] = {}
        self.timed: tuple[int, float | None] = (0, None)
        self.asked: list[str] = []

    def __call__(self, sql: str, params: dict[str, Any]) -> list[dict]:
        if "FROM `" + DATASET + ".gold_labels` AS g" in sql:
            self.asked.append(params["model_version"])
            return [
                {
                    "id_resena": g.id_resena,
                    "label": g.label,
                    "weight": g.weight,
                    "bank_id": g.stratum.split("|")[0],
                    "fecha": datetime(2023, 3, 1, tzinfo=UTC),
                    "sentiment": g.predicted,
                    "label_source": "MODEL",
                    "p_neg": g.confidence,
                    "p_neu": 0.0,
                    "p_pos": 0.0,
                }
                for g in self.gold.get(params["model_version"], [])
            ]
        if "GROUPING SETS" in sql:
            return [
                {"bank_id": "B0", "week": "w", "texts": 800},
                {"bank_id": None, "week": "w", "texts": 800},
            ]
        if "APPROX_QUANTILES" in sql:
            n, median = self.timed
            return [{"n": n, "median": median}]
        return self.base(sql, params)


@pytest.fixture
def bq(world: Any) -> Any:
    fake = world.bq
    assert world.settings.dataset == DATASET and world.now == NOW
    candidate = dict(fake.rows("model_versions")[0])
    candidate.update(
        model_version=CANDIDATE,
        status="candidate",
        promoted_at=None,
        promoted_by_hash=None,
    )
    fake.rows("model_versions").append(candidate)
    reads = LifecycleReads(fake)
    fake._select = reads
    fake.gold, fake.asked = reads.gold, reads.asked
    fake.reads = reads
    return fake


@pytest.fixture
def aiplatform(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    aliases: list[Any] = []

    class _Model:
        def __init__(self, model_name: str) -> None:
            self.version_id = model_name.rsplit("@", 1)[-1]

        @classmethod
        def list(cls, filter: str) -> list[Any]:
            return [types.SimpleNamespace(resource_name="projects/p/models/1")]

    class _Registry:
        def __init__(self, model: str) -> None:
            pass

        def add_version_aliases(self, new_aliases: list[str], version: str):
            aliases.append(version)

    fake = types.SimpleNamespace(
        init=lambda **_: None,
        Model=_Model,
        models=types.SimpleNamespace(ModelRegistry=_Registry),
    )
    monkeypatch.setattr(registry, "_aiplatform", lambda: fake)
    return aliases


def job(bq: Any) -> Lifecycle:
    return Lifecycle(bq, StagingMergeWriter(bq, DATASET), DATASET)


def latest(bq: Any, table: str) -> dict[str, Any]:
    return bq.rows(table)[-1]


def test_recompute_curve_writes_with_measured_seconds(bq: Any) -> None:
    bq.gold[MODEL] = synthetic_gold()
    curve = job(bq).recompute_curve(model_row(), NOW)
    assert curve.weekly_volume_total == 100
    assert curve.weekly_volume_by_bank == {"B0": 100}
    point = point_for(curve, 0.9)
    reviews = (1 - point.coverage) * 100
    assert point.minutes_per_week == round(reviews * SECONDS_PER_REVIEW / 60, 1)
    assert latest(bq, "hitl_coverage_curves")["model_version"] == MODEL
    bq.reads.timed = (40, 12.0)
    assert job(bq).seconds_per_review(NOW) == 12.0
    bq.reads.timed = (10, 12.0)
    assert job(bq).seconds_per_review(NOW) == SECONDS_PER_REVIEW


def test_set_coverage_writes_the_next_policy(bq: Any) -> None:
    bq.gold[MODEL] = synthetic_gold()
    life = job(bq)
    model = model_row()
    life.recompute_curve(model, NOW)
    new = life.set_coverage(model, 0.85, ACTOR, "menos carga", NOW)
    assert new.policy_version == "risk_policy_v2"
    assert latest(bq, "risk_policy")["hitl_target_coverage"] == 0.85
    bq.tables["hitl_coverage_curves"] = []
    with pytest.raises(LookupError, match="curve"):
        life.set_coverage(model, 0.9, ACTOR, "r", NOW)


def test_set_coverage_needs_a_policy(bq: Any) -> None:
    bq.tables["risk_policy"] = []
    with pytest.raises(LookupError, match="risk_policy"):
        job(bq).set_coverage(model_row(), 0.9, ACTOR, "r", NOW)


def promote(bq: Any, version: str = CANDIDATE, **kw: Any) -> ModelVersion:
    settings = types.SimpleNamespace(
        gcp_project_id="test-project", gcp_region="us-central1", dataset=DATASET
    )
    return promote_version(
        settings,
        job(bq),
        model_version=version,
        actor_hash=ACTOR,
        reason="reentrenado",
        now=NOW + timedelta(days=1),
        **kw,
    )


def test_promotion_of_a_better_candidate(bq: Any, aiplatform: Any) -> None:
    bq.gold.update(
        {
            MODEL: synthetic_gold(wrong=45),
            CANDIDATE: synthetic_gold(wrong=5),
        }
    )
    promoted = promote(bq)
    assert promoted.status.value == "promoted"
    assert aiplatform == [CANDIDATE.replace("_", "-")]
    assert latest(bq, "hitl_coverage_curves")["model_version"] == CANDIDATE
    policy = latest(bq, "risk_policy")
    assert policy["policy_version"] == "risk_policy_v2"
    assert policy["model_version"] == CANDIDATE
    assert policy["reason"] == "reentrenado"


def test_worse_candidate_is_refused_unless_forced(
    bq: Any, aiplatform: Any
) -> None:
    bq.gold.update(
        {
            MODEL: synthetic_gold(wrong=5),
            CANDIDATE: synthetic_gold(wrong=120),
        }
    )
    with pytest.raises(PromotionRefused, match="worse"):
        promote(bq)
    assert aiplatform == [] and len(bq.rows("risk_policy")) == 1
    assert promote(bq, force=True).status.value == "promoted"


def test_rollback_skips_the_rule(bq: Any, aiplatform: Any) -> None:
    bq.gold.update(
        {
            MODEL: synthetic_gold(wrong=120),
            CANDIDATE: synthetic_gold(wrong=5),
        }
    )
    promote(bq)
    bq.asked.clear()
    # La versión 1 vuelve sin evaluar la regla contra la 2 ni re-predecir.
    back = promote(bq, MODEL)
    assert back.status.value == "promoted" and bq.asked == [MODEL]
    assert latest(bq, "risk_policy")["model_version"] == MODEL


def test_promotion_preconditions(bq: Any, aiplatform: Any) -> None:
    with pytest.raises(LookupError, match="model_versions"):
        promote(bq, "nadie")
    with pytest.raises(ValueError, match="already promoted"):
        promote(bq, MODEL)
    with pytest.raises(LookupError, match="rescore"):
        promote(bq)


def test_promotion_without_policy_only_warns(
    bq: Any, aiplatform: Any, caplog: pytest.LogCaptureFixture
) -> None:
    bq.gold.update(
        {
            MODEL: synthetic_gold(wrong=45),
            CANDIDATE: synthetic_gold(wrong=45),
        }
    )
    bq.tables["risk_policy"] = []
    assert promote(bq).status.value == "promoted"
    assert "sin risk_policy" in caplog.text
    assert lifecycle.PromotionCheck(0, ()).verdict == "tie"
