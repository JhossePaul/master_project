"""``/api/v1/mlops``: señales, registro de modelos y acciones."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from api_backend.sections.mlops import router as mlops_router
from api_backend.sections.mlops.repository import InMemoryMlopsRepository
from api_backend.sections.mlops.sample import sample_repository
from api_backend.testing import LOCAL_EMAIL, LOCAL_SALT, local_app
from fastapi.testclient import TestClient
from voc_common import (
    InferenceRun,
    ModelQuality,
    PromotionVerdict,
    QualitySignal,
    QualityStatus,
    RunEnvironment,
    RunKind,
    RunStatus,
)
from voc_common.text_utils import actor_hash

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
ACTOR = actor_hash(LOCAL_EMAIL, LOCAL_SALT)
REASON = "Hay aviso de reentrenamiento del monitor"
DOCS = (
    Path(__file__).resolve().parents[3]
    / "docs/analytics/calibration/calibration_v0_metrics.json"
)


class FakeJobs:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def execute(self, job: str, args: list[str]) -> str:
        self.calls.append((job, list(args)))
        return f"operations/{len(self.calls)}"


def kit(
    roles: str = "administrador", **extra: Any
) -> tuple[TestClient, InMemoryMlopsRepository, FakeJobs]:
    repo = sample_repository(NOW)
    jobs = FakeJobs()
    app = local_app(roles, calibration_docs_path=str(DOCS), **extra)
    app.state.mlops_repository = repo
    app.state.job_runner = jobs
    app.dependency_overrides[mlops_router.now] = lambda: NOW
    return TestClient(app), repo, jobs


def post(client: TestClient, action: str, **body: Any) -> Any:
    return client.post(
        f"/api/v1/mlops/actions/{action}",
        json={"reason": REASON, **body},
    )


def states(client: TestClient) -> dict[str, dict[str, Any]]:
    """Acciones por versión (``version:acción``) y globales (``acción``)."""
    data = client.get("/api/v1/mlops/models").json()
    out = {a["action"]: a for a in data["actions"]}
    for model in data["models"]:
        for a in model["actions"]:
            out[f"{model['model_version']}:{a['action']}"] = a
    return out


def retrain_notice(repo: InMemoryMlopsRepository) -> None:
    repo.quality_rows.append(
        ModelQuality(
            model_version="sintetico_v1",
            signal=QualitySignal.KAPPA_MONITOR,
            period="2026Q4",
            value=0.85,
            n=300,
            threshold=0.89,
            status=QualityStatus.RETRAIN,
            computed_at=NOW,
        )
    )


def running(kind: RunKind, started: datetime) -> InferenceRun:
    return InferenceRun(
        run_id=f"{kind.value}-en-curso",
        kind=kind,
        environment=RunEnvironment.CLOUDRUN,
        model_version=None,
        started_at=started,
        ended_at=None,
        reviews=0,
        texts=0,
        status=RunStatus.RUNNING,
    )


# -- Roles -------------------------------------------------------------------

READS = (
    "quality",
    "coverage-curve",
    "drift",
    "topics-context",
    "models",
    "models/sintetico_v1/calibration",
    "runs",
    "ingestion",
    "eligibility",
)


@pytest.mark.parametrize("path", READS)
def test_un_analista_lee_y_un_lector_no(path: str) -> None:
    analyst, _, _ = kit("analista")
    assert analyst.get(f"/api/v1/mlops/{path}").status_code in (200, 404)
    assert analyst.get("/api/v1/mlops/models").status_code == 200
    reader, _, _ = kit("lector")
    assert reader.get(f"/api/v1/mlops/{path}").status_code == 403


def test_un_analista_no_lanza_acciones() -> None:
    client, _, jobs = kit("analista")
    response = post(client, "topics_refit")
    assert response.status_code == 403
    assert jobs.calls == []


# -- Señales -----------------------------------------------------------------


def test_cada_senal_trae_su_serie_con_umbral_y_estado() -> None:
    client, _, _ = kit("analista")
    data = client.get("/api/v1/mlops/quality").json()
    by_signal = {s["signal"]: s["points"] for s in data["signals"]}

    assert set(by_signal) == {
        "kappa_monitor",
        "correction_rate",
        "gemini_agreement",
        "families_validation",
    }
    kappa = by_signal["kappa_monitor"]
    assert [p["period"] for p in kappa] == [
        "2025Q4",
        "2026Q1",
        "2026Q2",
        "2026Q3",
    ]
    assert kappa[-1]["threshold"] == 0.89 and kappa[-1]["status"] == "ok"
    assert kappa[-1]["ci_low"] < kappa[-1]["value"] < kappa[-1]["ci_high"]
    families = by_signal["families_validation"][0]
    assert (families["llm_model"], families["prompt_version"]) == (
        "gemini-2.5-flash",
        "aspects_v2_1",
    )


def test_la_curva_vigente_es_la_de_administracion_y_de_solo_lectura() -> None:
    client, _, _ = kit("analista")
    data = client.get("/api/v1/mlops/coverage-curve").json()
    assert data["curve"]["model_version"] == "sintetico_v1"
    assert data["current_point"]["coverage"] == 0.9
    # Una versión sin curva guardada (la candidata aún no se re-puntúa).
    missing = client.get("/api/v1/mlops/coverage-curve?model_version=nada")
    assert missing.status_code == 404


def test_la_deriva_trae_24_meses_por_banco_y_la_lista_de_series() -> None:
    client, _, _ = kit("analista")
    data = client.get("/api/v1/mlops/drift?metric=neg_share").json()

    assert data["metric"] == "neg_share"
    assert data["series"] == [
        "family_AC",
        "flag_update_share",
        "mean_words",
        "neg_share",
    ]
    assert len(data["banks"]) == 5
    assert len(data["cells"]) == 5 * 24
    alerts = [c for c in data["cells"] if c["alert"]]
    assert [(c["bank_id"], c["period"]) for c in alerts] == [
        ("NUBANK", "2026-10")
    ]
    assert alerts[0]["z"] == 4.6 and alerts[0]["threshold"] == 4.0
    assert client.get("/api/v1/mlops/drift?metric=nada").status_code == 404
    assert client.get("/api/v1/mlops/drift").json()["metric"] == "family_AC"


def test_los_topicos_son_contexto_sin_umbral_junto_a_familias_y_u() -> None:
    client, _, _ = kit("analista")
    data = client.get("/api/v1/mlops/topics-context").json()

    assert [s["metric"] for s in data["topics"]] == [
        "topic_noise_share",
        "topic_unaligned_share",
    ]
    assert all(
        c["threshold"] is None and not c["alert"]
        for s in data["topics"]
        for c in s["cells"]
    )
    assert [s["metric"] for s in data["families"]] == [
        "family_AC",
        "flag_update_share",
    ]


# -- Registro de modelos ------------------------------------------------------


def test_el_registro_muestra_la_vigente_su_historia_y_sus_metricas() -> None:
    client, _, _ = kit("analista")
    data = client.get("/api/v1/mlops/models").json()

    assert data["current_version"] == "sintetico_v1"
    assert data["force_word"] == "FORZAR"
    current = data["models"][0]
    assert current["model_version"] == "sintetico_v1" and current["current"]
    assert current["kappa_dev"] == 0.917 and current["calibration_t"] == 1.68
    assert [s["status"] for s in current["history"]] == [
        "candidate",
        "promoted",
    ]
    promoted = current["history"][1]
    assert promoted["actor"] == "a" * 8 and promoted["reason"]
    v2 = next(m for m in data["models"] if m["model_version"] == "sintetico_v2")
    assert v2["check"]["verdict"] == "better"
    assert v2["check"]["kappa_ci_low"] < v2["check"]["kappa_diff"]


def test_acciones_habilitadas_por_version_y_el_motivo_si_no() -> None:
    client, _, _ = kit("analista")
    s = states(client)

    assert s["sintetico_v3:rescore"]["enabled"]
    assert not s["sintetico_v3:promote"]["enabled"]
    assert "re-scoring" in s["sintetico_v3:promote"]["reason"]
    assert not s["sintetico_v2:rescore"]["enabled"]
    assert s["sintetico_v2:promote"]["enabled"]
    assert s["sintetico_v0:rollback"]["enabled"]
    assert s["sintetico_v1:rollback"]["reason"] == "Es la versión vigente"
    assert s["sintetico_v3:rollback"]["reason"] == (
        "Esta versión nunca estuvo promovida"
    )
    assert not s["sintetico_v1:promote"]["enabled"]
    assert not s["retrain"]["enabled"]
    assert s["retrain"]["reason"] == "No hay aviso de reentrenamiento vigente"


def test_el_reajuste_programado_muestra_la_proxima_fecha() -> None:
    client, repo, _ = kit("analista")
    # El último ajuste fue en el trimestre anterior: toca en la próxima
    # corrida del Job.
    due = states(client)["topics_refit"]
    assert not due["enabled"] and due["next_date"] == "2026-10-26"
    assert "Administración" in due["reason"]
    # Ya hay uno de este trimestre: la próxima es el 1.º de enero.
    repo.topic_fit_at = NOW - timedelta(days=10)
    assert states(client)["topics_refit"]["next_date"] == "2027-01-01"


def test_calibracion_de_los_experimentos_si_no_hay_manifiesto() -> None:
    client, _, _ = kit("analista")
    data = client.get(
        "/api/v1/mlops/models/robertuito_sentiment_v1/calibration"
    ).json()

    assert data["source"] == "docs"
    assert "calibration_v0_metrics.json" in data["source_label"]
    assert data["temperature"] == 1.6811
    assert data["ece_calibrated"] < data["ece_raw"]
    assert data["raw"][0]["low"] == 0.5 and data["calibrated"]
    missing = client.get("/api/v1/mlops/models/sintetico_v2/calibration")
    assert missing.status_code == 404


def test_calibracion_del_manifiesto_de_entrenamiento() -> None:
    client, _, _ = kit("analista")
    bins = [
        {
            "low": 0.9,
            "high": 1.0,
            "n": 700,
            "weight": 0.9,
            "confidence": 0.99,
            "accuracy": 0.97,
        }
    ]

    class Manifests:
        def manifest(self, version: str) -> dict[str, Any] | None:
            return {
                "calibration": {
                    "temperature": 1.7,
                    "ece_dev": 0.01,
                    "raw_ece_dev": 0.03,
                    "raw": bins,
                    "calibrated": bins,
                }
            }

    client.app.state.manifest_source = Manifests()  # type: ignore[attr-defined]
    data = client.get("/api/v1/mlops/models/sintetico_v2/calibration").json()
    assert data["source"] == "manifest" and data["temperature"] == 1.7
    assert data["raw"][0]["accuracy"] == 0.97


# -- Corridas ----------------------------------------------------------------


def test_las_corridas_traen_duracion_actor_motivo_y_frescura() -> None:
    client, _, _ = kit("analista")
    data = client.get("/api/v1/mlops/runs?days=30").json()

    assert data["memory_limit_mib"] == 4096
    training = next(r for r in data["runs"] if r["kind"] == "training")
    assert training["duration_seconds"] == 7200
    assert training["actor"] == "a" * 8 and training["cost_usd"] == 0.94
    assert data["freshness"]["last_monitor_at"] is not None
    deltas = client.get("/api/v1/mlops/runs?kind=delta&days=5").json()["runs"]
    assert {r["kind"] for r in deltas} == {"delta"} and len(deltas) == 5
    assert client.get("/api/v1/mlops/runs?days=0").status_code == 422


def test_ingesta_y_elegibilidad() -> None:
    client, _, _ = kit("analista")
    ingestion = client.get("/api/v1/mlops/ingestion?days=30").json()
    failed = [r for r in ingestion if r["status"] == "FAILED"]
    assert [r["bank_id"] for r in failed] == ["AZTECA"]
    assert ingestion[0]["duration_seconds"] > 0
    eligibility = client.get("/api/v1/mlops/eligibility").json()
    assert {"bank_id", "period", "code", "n"} == set(eligibility[0])
    assert eligibility[0]["period"] == "2026-05"


# -- Acciones: habilitación --------------------------------------------------


def test_reentrenar_sin_aviso_da_409_y_no_lanza_nada() -> None:
    client, _, jobs = kit()
    response = post(client, "retrain")
    assert response.status_code == 409
    assert "aviso de reentrenamiento" in response.json()["error"]["message"]
    assert jobs.calls == []


def test_reentrenar_con_aviso_lanza_el_job_con_quien_y_por_que() -> None:
    client, repo, jobs = kit()
    retrain_notice(repo)

    response = post(client, "retrain")

    assert response.status_code == 200
    assert response.json() == {
        "action": "retrain",
        "job": "voc-ml-training",
        "operation": "operations/1",
    }
    assert jobs.calls == [
        (
            "voc-ml-training",
            ["train", f"--actor-hash={ACTOR}", f"--reason={REASON}"],
        )
    ]
    assert "Gemini" in states(client)["retrain"]["reason"]


def test_reentrenar_con_un_entrenamiento_en_curso_da_409() -> None:
    client, repo, jobs = kit()
    retrain_notice(repo)
    repo.run_rows.append(running(RunKind.TRAINING, NOW - timedelta(hours=1)))
    assert post(client, "retrain").status_code == 409
    # Una fila running de hace más que el tiempo máximo del Job es de una
    # corrida que murió: ya no cuenta.
    repo.run_rows[-1] = running(RunKind.TRAINING, NOW - timedelta(hours=5))
    assert post(client, "retrain").status_code == 200
    assert len(jobs.calls) == 1


def test_reentrenar_en_modo_auto_lo_hace_el_monitor() -> None:
    client, repo, jobs = kit()
    retrain_notice(repo)
    repo.policies[0] = repo.policies[0].model_copy(
        update={"retrain_trigger": "auto"}
    )
    response = post(client, "retrain")
    assert response.status_code == 409
    assert "automático" in response.json()["error"]["message"]
    assert jobs.calls == []


def test_re_scoring_de_una_candidata_sin_verificacion() -> None:
    client, _, jobs = kit()
    response = post(client, "rescore", model_version="sintetico_v3")
    assert response.status_code == 200
    assert jobs.calls == [
        (
            "voc-ml-rescoring",
            [
                "rescore",
                "--model-version=sintetico_v3",
                f"--actor-hash={ACTOR}",
                f"--reason={REASON}",
            ],
        )
    ]


def test_re_scoring_con_verificacion_con_otro_en_curso_o_de_la_vigente() -> (
    None
):
    client, repo, jobs = kit()
    assert (
        post(client, "rescore", model_version="sintetico_v2").status_code == 409
    )
    assert (
        post(client, "rescore", model_version="sintetico_v1").status_code == 409
    )
    repo.run_rows.append(running(RunKind.RESCORING, NOW - timedelta(hours=1)))
    other = post(client, "rescore", model_version="sintetico_v3")
    assert other.status_code == 409
    assert "en curso" in other.json()["error"]["message"]
    assert jobs.calls == []


def test_las_acciones_de_una_version_piden_una_version_que_exista() -> None:
    client, _, jobs = kit()
    assert post(client, "rescore").status_code == 422
    assert post(client, "promote", model_version="nada").status_code == 404
    assert jobs.calls == []


def test_promover_una_candidata_verificada() -> None:
    client, _, jobs = kit()
    response = post(client, "promote", model_version="sintetico_v2")
    assert response.status_code == 200
    assert response.json()["job"] == "voc-ml-promote"
    assert jobs.calls == [
        (
            "voc-ml-promote",
            [
                "promote",
                "--model-version=sintetico_v2",
                f"--actor-hash={ACTOR}",
                f"--reason={REASON}",
            ],
        )
    ]


def test_promover_sin_verificacion_o_una_ya_promovida_da_409() -> None:
    client, _, jobs = kit()
    assert (
        post(client, "promote", model_version="sintetico_v3").status_code == 409
    )
    assert (
        post(client, "promote", model_version="sintetico_v1").status_code == 409
    )
    assert (
        post(client, "promote", model_version="sintetico_v0").status_code == 409
    )
    assert jobs.calls == []


def test_promover_si_la_verificacion_fue_contra_otra_vigente_da_409() -> None:
    client, repo, jobs = kit()
    repo.check_rows[0] = repo.check_rows[0].model_copy(
        update={"current_version": "sintetico_v0"}
    )
    response = post(client, "promote", model_version="sintetico_v2")
    assert response.status_code == 409
    assert "otra versión vigente" in response.json()["error"]["message"]
    assert jobs.calls == []


def worse(repo: InMemoryMlopsRepository) -> None:
    repo.check_rows[0] = repo.check_rows[0].model_copy(
        update={
            "kappa_diff": -0.03,
            "kappa_ci_low": -0.05,
            "kappa_ci_high": -0.01,
            "macro_f1_diff": -0.02,
            "macro_f1_ci_low": -0.04,
            "macro_f1_ci_high": -0.005,
            "verdict": PromotionVerdict.WORSE,
        }
    )


def test_promover_una_peor_exige_forzar_y_agrega_el_flag() -> None:
    client, repo, jobs = kit()
    worse(repo)
    assert "FORZAR" in states(client)["sintetico_v2:promote"]["reason"]

    missing = post(client, "promote", model_version="sintetico_v2")
    wrong = post(
        client, "promote", model_version="sintetico_v2", confirm_word="forzar"
    )
    assert (missing.status_code, wrong.status_code) == (422, 422)
    assert jobs.calls == []

    ok = post(
        client, "promote", model_version="sintetico_v2", confirm_word="FORZAR"
    )
    assert ok.status_code == 200
    assert jobs.calls[0][1][-1] == "--force"
    assert jobs.calls[0][1][:2] == ["promote", "--model-version=sintetico_v2"]


def test_el_rollback_usa_el_mismo_comando_y_nunca_fuerza() -> None:
    client, _, jobs = kit()
    response = post(
        client, "rollback", model_version="sintetico_v0", confirm_word="FORZAR"
    )
    assert response.status_code == 200
    assert response.json()["action"] == "rollback"
    assert jobs.calls == [
        (
            "voc-ml-promote",
            [
                "promote",
                "--model-version=sintetico_v0",
                f"--actor-hash={ACTOR}",
                f"--reason={REASON}",
            ],
        )
    ]


def test_rollback_a_la_vigente_o_a_una_nunca_promovida_da_409() -> None:
    client, _, jobs = kit()
    assert (
        post(client, "rollback", model_version="sintetico_v1").status_code
        == 409
    )
    assert (
        post(client, "rollback", model_version="sintetico_v2").status_code
        == 409
    )
    assert jobs.calls == []


def test_reajustar_topicos_solo_en_modo_manual() -> None:
    client, repo, jobs = kit()
    scheduled = post(client, "topics_refit")
    assert scheduled.status_code == 409
    assert "próxima fecha" in scheduled.json()["error"]["message"]
    repo.policies[0] = repo.policies[0].model_copy(
        update={"topic_refit_trigger": "manual"}
    )

    assert post(client, "topics_refit").status_code == 200
    assert jobs.calls == [
        (
            "voc-ml-topics-refit",
            [
                "topics-refit",
                "--force",
                f"--actor-hash={ACTOR}",
                f"--reason={REASON}",
            ],
        )
    ]
    repo.run_rows.append(
        running(RunKind.TOPIC_REFIT, NOW - timedelta(minutes=5))
    )
    assert post(client, "topics_refit").status_code == 409


def test_el_motivo_es_obligatorio_y_la_accion_debe_existir() -> None:
    client, _, jobs = kit()
    short = client.post(
        "/api/v1/mlops/actions/topics_refit", json={"reason": "no"}
    )
    assert short.status_code == 422
    unknown = post(client, "borrar_todo")
    assert unknown.status_code == 422
    assert jobs.calls == []


def test_si_el_job_no_se_puede_lanzar_da_502() -> None:
    import requests

    client, repo, _ = kit()
    retrain_notice(repo)

    class Broken:
        def execute(self, job: str, args: list[str]) -> str:
            raise requests.ConnectionError("sin red")

    client.app.state.job_runner = Broken()  # type: ignore[attr-defined]
    response = post(client, "retrain")
    assert response.status_code == 502
    assert "voc-ml-training" in response.json()["error"]["message"]


def test_los_argumentos_nunca_vienen_del_cliente() -> None:
    client, repo, jobs = kit()
    retrain_notice(repo)
    response = client.post(
        "/api/v1/mlops/actions/retrain",
        json={
            "reason": REASON,
            "args": ["--approve"],
            "job": "voc-ml-inference-delta",
            "actor_hash": "f" * 64,
        },
    )
    assert response.status_code == 200
    assert jobs.calls[0][0] == "voc-ml-training"
    assert jobs.calls[0][1] == [
        "train",
        f"--actor-hash={ACTOR}",
        f"--reason={REASON}",
    ]
