"""CLI: subcomandos, validación del actor y despacho sin red."""

from pathlib import Path
from typing import Any

import ml_inference.__main__ as cli
import pytest

ACTOR = "b" * 64


def test_actor_hash_must_be_sha256() -> None:
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["seed", "--actor-hash", "x", "--reason", "r"])


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("GCP_PROJECT_ID", "p")
    monkeypatch.setenv("GCS_RAW_DATALAKE_BUCKET", "b")
    calls: dict[str, Any] = {}
    monkeypatch.setattr(cli, "_clients", lambda s: ("bq", "gcs"))
    return calls


def test_seed_dispatch(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    import ml_inference.seed as seed

    monkeypatch.setattr(
        seed, "seed", lambda *a: env.setdefault("seed", a) and {}
    )
    assert cli.main(["seed", "--actor-hash", ACTOR, "--reason", "inicio"]) == 0
    assert env["seed"][3:5] == (ACTOR, "inicio")


def test_monitor_dispatch(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    import ml_inference.monitor.drift_job as drift
    import ml_inference.monitor.quality as quality
    import ml_inference.monitor.samples as samples

    monkeypatch.setattr(cli, "_family_labeler", lambda s: "families")
    monkeypatch.setattr(cli, "_sentiment_labeler", lambda s: "sentiment")
    monkeypatch.setattr(
        quality.QualityJob,
        "run",
        lambda self, p, m, n: env.setdefault("quality", self),
    )
    model = type("M", (), {"model_version": "m1"})()
    state = type("S", (), {"model": model, "policy": "policy"})()
    monkeypatch.setattr(cli, "_publisher", lambda s, t: f"publish:{t}")
    monkeypatch.setattr(
        cli, "_monitor_state", lambda s, b, g: (state, frozenset({"a"}))
    )
    monkeypatch.setattr(
        drift, "close_boosts", lambda c, n: env.setdefault("close", c)
    )
    monkeypatch.setattr(
        drift, "run_drift", lambda s, c, n: env.setdefault("drift", c)
    )
    monkeypatch.setattr(
        samples.SampleJob,
        "run",
        lambda self, p, m, n: env.setdefault("samples", (p, m)),
    )
    assert cli.main(["monitor"]) == 0
    assert env["close"] is env["drift"]
    assert env["drift"].publish == "publish:voc-incident-alerts-topic"
    assert env["drift"].run_id.startswith("monitor_")
    assert env["drift"].source.vocab == frozenset({"a"})
    assert env["samples"] == ("policy", "m1")
    assert env["quality"].publish == "publish:voc-model-quality-topic"
    assert env["quality"].family_labeler == "families"
    assert env["quality"].sentiment_labeler == "sentiment"


def test_monitor_without_promoted_model_skips_samples(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ml_inference.monitor.drift_job as drift
    import ml_inference.monitor.samples as samples

    monkeypatch.setattr(cli, "_publisher", lambda s, t: f"publish:{t}")
    monkeypatch.setattr(cli, "_monitor_state", lambda s, b, g: (None, None))
    monkeypatch.setattr(drift, "close_boosts", lambda c, n: None)
    monkeypatch.setattr(drift, "run_drift", lambda s, c, n: None)
    monkeypatch.setattr(
        samples.SampleJob, "run", lambda *a: pytest.fail("no samples")
    )
    assert cli.main(["monitor"]) == 0


def test_monitor_state_tolerates_missing_pieces(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ml_inference.state as state
    import ml_inference.vocab as vocab
    from ml_inference.config import InferenceSettings

    model = type("M", (), {"model_version": "m1"})()
    loaded = type("S", (), {"model": model})()
    monkeypatch.setattr(state, "load_state", lambda b, d: loaded)
    settings = InferenceSettings()  # type: ignore[call-arg]

    def missing(*a: Any) -> frozenset[str]:
        raise FileNotFoundError("no vocabulary for m1")

    def no_model(*a: Any) -> Any:
        raise state.NoPromotedModel("none")

    monkeypatch.setattr(vocab, "load_vocab", lambda s, g, m: frozenset({m}))
    assert cli._monitor_state(settings, "bq", "gcs") == (
        loaded,
        frozenset({"m1"}),
    )
    monkeypatch.setattr(vocab, "load_vocab", missing)
    assert cli._monitor_state(settings, "bq", "gcs") == (loaded, None)
    monkeypatch.setattr(state, "load_state", no_model)
    assert cli._monitor_state(settings, "bq", "gcs") == (None, None)


def test_build_vocab_dispatch(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ml_inference.vocab as vocab

    monkeypatch.setattr(
        vocab,
        "build_vocab",
        lambda s, g, m: env.setdefault("m", m) and (3, "h"),
    )
    assert cli.main(["build-vocab"]) == 0
    assert env["m"] == "robertuito_sentiment_v1"


def test_delta_dispatch(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    import ml_inference.delta as delta
    import voc_nlp.aspects as aspects

    monkeypatch.setattr(
        aspects, "make_client", lambda project, location: "genai"
    )

    class _Run:
        status = type("S", (), {"value": "failed"})()

    monkeypatch.setattr(
        delta, "run_delta", lambda s, c, n: env.setdefault("c", c) and _Run()
    )
    assert cli.main(["delta"]) == 1
    assert env["c"].genai == "genai"


def test_load_local_dispatch(
    env: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ml_inference.load_local as load

    minilm = tmp_path / "minilm"
    minilm.mkdir()
    monkeypatch.setattr(
        load, "load_backfill", lambda *a: env.setdefault("files", a[3])
    )
    args = ["load-local", "--actor-hash", ACTOR, "--work", str(tmp_path / "w")]
    assert (
        cli.main([*args, "--minilm", str(minilm), "--data", str(tmp_path)]) == 0
    )
    assert env["files"].minilm_dir == minilm
    assert (tmp_path / "w").is_dir()


def test_register_and_promote_dispatch(
    env: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, world: Any
) -> None:
    import ml_inference.registry as registry

    curve = tmp_path / "curve.json"
    from voc_common.policies import HitlCoverageCurve

    curve.write_text(
        HitlCoverageCurve.model_validate(
            world.bq.rows("hitl_coverage_curves")[0]
        ).model_dump_json()
    )
    monkeypatch.setattr(
        registry, "register", lambda *a, **k: env.setdefault("reg", k)
    )
    monkeypatch.setattr(
        registry, "promote", lambda *a, **k: env.setdefault("pro", k)
    )
    assert (
        cli.main(
            [
                "register",
                "--weights-uri",
                "gs://b/x/",
                "--model-version",
                "v2",
                "--calibration-version",
                "t2",
                "--calibration-t",
                "1.5",
                "--curve-json",
                str(curve),
                "--serving-image",
                "img",
                "--base-checkpoint",
                "base",
                "--training-data",
                "silver",
                "--license",
                "nc",
                "--kappa-dev",
                "0.94",
            ]
        )
        == 0
    )
    assert env["reg"]["metrics"] == {"kappa_dev": 0.94}
    assert (
        cli.main(
            [
                "promote",
                "--model-version",
                "v2",
                "--actor-hash",
                ACTOR,
                "--reason",
                "r",
            ]
        )
        == 0
    )
    assert env["pro"]["model_version"] == "v2"
