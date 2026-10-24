"""Registro y promoción con ``aiplatform`` simulado."""

import types
from datetime import timedelta
from typing import Any

import pytest
from ml_inference import registry
from ml_inference.bq_io import StagingMergeWriter


class _Model:
    uploads: list[dict[str, Any]] = []
    existing: list[Any] = []

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.version_id = "7"

    @classmethod
    def list(cls, filter: str) -> list[Any]:
        return cls.existing

    @classmethod
    def upload(cls, **kwargs: Any) -> None:
        cls.uploads.append(kwargs)


class _Registry:
    aliases: list[tuple[list[str], str]] = []

    def __init__(self, model: str) -> None:
        self.model = model

    def add_version_aliases(self, new_aliases: list[str], version: str) -> None:
        self.aliases.append((new_aliases, version))


@pytest.fixture
def aiplatform(monkeypatch: pytest.MonkeyPatch) -> Any:
    fake = types.SimpleNamespace(
        init=lambda **_: None,
        Model=_Model,
        models=types.SimpleNamespace(ModelRegistry=_Registry),
    )
    _Model.uploads, _Model.existing, _Registry.aliases = [], [], []
    monkeypatch.setattr(registry, "_aiplatform", lambda: fake)
    return fake


def _curve(world: Any) -> Any:
    from voc_common.policies import HitlCoverageCurve

    return HitlCoverageCurve.model_validate(
        world.bq.rows("hitl_coverage_curves")[0]
    )


def test_register_uploads_a_candidate(world: Any, aiplatform: Any) -> None:
    writer = StagingMergeWriter(world.bq, world.settings.dataset)
    row = registry.register(
        world.settings,
        writer,
        weights_uri="gs://bucket/ml_artifacts/sentiment/robertuito_sentiment_v2/",
        model_version="robertuito_sentiment_v2",
        calibration_version="temperature_v1",
        calibration_t=1.5,
        curve=_curve(world),
        metrics={"kappa_dev": 0.94},
        serving_image="registry/ml-inference@sha256:" + "a" * 64,
        base_checkpoint="base",
        training_data="silver_v1",
        license_name="nc",
        now=world.now,
    )
    assert row.status.value == "candidate" and row.kappa_dev == 0.94
    upload = _Model.uploads[0]
    assert upload["version_aliases"] == ["robertuito_sentiment_v2"]
    assert upload["parent_model"] is None and upload["is_default_version"]
    names = [m["model_version"] for m in world.bq.rows("model_versions")]
    assert "robertuito_sentiment_v2" in names


def test_promote_moves_the_alias_and_retires_the_previous(
    world: Any, aiplatform: Any
) -> None:
    _Model.existing = [
        types.SimpleNamespace(resource_name="projects/p/models/1")
    ]
    writer = StagingMergeWriter(world.bq, world.settings.dataset)
    candidate = dict(world.bq.rows("model_versions")[0])
    candidate.update(
        model_version="robertuito_sentiment_v2",
        status="candidate",
        promoted_at=None,
        promoted_by_hash=None,
    )
    world.bq.rows("model_versions").append(candidate)
    later = world.now + timedelta(days=1)
    promoted = registry.promote(
        world.settings,
        writer,
        world.bq,
        model_version="robertuito_sentiment_v2",
        actor_hash="c" * 64,
        reason="mejor κ en el dev",
        now=later,
    )
    assert promoted.status.value == "promoted"
    assert _Registry.aliases == [(["produccion"], "7")]
    statuses = {
        (r["model_version"], r["status"])
        for r in world.bq.rows("model_versions")
        if str(r["recorded_at"]).replace("Z", "+00:00") == later.isoformat()
    }
    assert statuses == {
        ("robertuito_sentiment_v1", "retired"),
        ("robertuito_sentiment_v2", "promoted"),
    }


def test_promote_needs_the_registry_and_the_row(
    world: Any, aiplatform: Any
) -> None:
    writer = StagingMergeWriter(world.bq, world.settings.dataset)
    with pytest.raises(LookupError, match="registry"):
        registry.promote(
            world.settings,
            writer,
            world.bq,
            model_version="x",
            actor_hash="c" * 64,
            reason="r",
            now=world.now,
        )
    _Model.existing = [
        types.SimpleNamespace(resource_name="projects/p/models/1")
    ]
    with pytest.raises(LookupError, match="model_versions"):
        registry.promote(
            world.settings,
            writer,
            world.bq,
            model_version="x",
            actor_hash="c" * 64,
            reason="r",
            now=world.now,
        )


def test_resolve_reads_the_promoted_version(world: Any) -> None:
    assert (
        registry.resolve(world.bq, world.settings).model_version
        == "robertuito_sentiment_v1"
    )
