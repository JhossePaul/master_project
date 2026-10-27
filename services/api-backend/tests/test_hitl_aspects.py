"""Cola de aspectos, muestras del administrador y curaduría de tópicos."""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from api_backend.dlp import FAKE_NAME, FAKE_TOKEN, FixedNameSanitizer
from api_backend.sections.admin import router as admin_router
from api_backend.sections.admin.samples import (
    AspectCandidate,
    InMemorySamplesRepository,
)
from api_backend.sections.hitl import router as hitl_router
from api_backend.sections.hitl import topics as topics_router
from api_backend.sections.hitl.repository import (
    InMemoryHitlRepository,
    text_matches,
)
from api_backend.sections.hitl.topics import (
    CatalogTopic,
    InMemoryTopicsRepository,
)
from api_backend.testing import StaticRoleSource, local_app, role_map
from fastapi.testclient import TestClient
from voc_common import (
    AspectFamily,
    DisplayMode,
    Guideline,
    HitlItem,
    HitlReason,
    HitlTask,
    ReviewOutcome,
)
from voc_common.text_utils import text_key

T0 = datetime(2026, 10, 26, 12, tzinfo=UTC)
BANK = "BANCO_SECRETO"


def aspects_item(
    n: int, families: list[str], u: bool = False, s: bool = False
) -> tuple[HitlItem, str]:
    text = f"No puedo entrar con mi token número {n}"
    return (
        HitlItem(
            item_id=f"aspects:manual:lote1:syn-{n}:{text_key(text)[:16]}",
            id_resena=f"syn-{n}",
            bank_id=BANK,
            task=HitlTask.ASPECTS,
            reason=HitlReason.MANUAL,
            display_mode=DisplayMode.BLIND,
            predicted={
                "families": families,
                "flag_update": u,
                "flag_security": s,
                "praise": True,
                "prompt_version": "aspects_v2_1",
            },
            priority=1.0,
            created_at=T0 - timedelta(hours=1, minutes=-n),
        ),
        text,
    )


def guideline(task: HitlTask, version: str) -> Guideline:
    return Guideline(
        guideline_version=version,
        task=task,
        content_uri="g.md",
        valid_from=T0 - timedelta(days=10),
        published_by_hash="a" * 64,
    )


def client_for(
    tmp_path: Path,
    repo: InMemoryHitlRepository,
    tasks: list[str],
    user: str = "eva",
) -> TestClient:
    (tmp_path / "g.md").write_text("# Guía", encoding="utf-8")
    app = local_app("revisor", portal_local_user=f"{user}@example.com")
    app.state.role_source = StaticRoleSource(
        role_map(
            **{
                f"{user}@example.com": {
                    "roles": ["revisor"],
                    "reviewer_tasks": tasks,
                }
            }
        )
    )
    app.state.hitl_repository = repo
    app.state.comment_sanitizer = FixedNameSanitizer()
    app.state.guidelines_dir = tmp_path
    app.dependency_overrides[hitl_router.now] = lambda: T0
    app.dependency_overrides[topics_router.now] = lambda: T0
    return TestClient(app)


@pytest.fixture
def aspects_repo() -> InMemoryHitlRepository:
    pairs = [
        aspects_item(1, ["AC"]),
        aspects_item(2, ["TR", "UX"], u=True),
    ]
    return InMemoryHitlRepository(
        [i for i, _ in pairs],
        {(BANK, i.id_resena): t for i, t in pairs},
        [guideline(HitlTask.ASPECTS, "v2.1")],
    )


def take(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/v1/hitl/next", json={"task": "aspects"})
    assert response.status_code == 200, response.text
    return response.json()


def review(client: TestClient, case: dict[str, Any], **kw: Any) -> Any:
    body = {
        "review_id": kw.pop(
            "review_id", "11111111-1111-4111-8111-111111111111"
        ),
        "families": kw.pop("families", ["AC"]),
        "flag_update": kw.pop("flag_update", False),
        "flag_security": kw.pop("flag_security", False),
        "guideline_version": case["guideline_version"],
        **kw,
    }
    return client.post(
        f"/api/v1/hitl/items/{case['item_id']}/review-aspects", json=body
    )


# -- cola de aspectos -------------------------------------------------------


def test_el_caso_de_aspectos_es_a_ciegas_y_no_trae_a_gemini(
    tmp_path: Path, aspects_repo: InMemoryHitlRepository
) -> None:
    eva = client_for(tmp_path, aspects_repo, ["aspects"])

    case = take(eva)

    assert case["task"] == "aspects"
    assert case["display_mode"] == "blind"
    assert case["proposal"] is None
    assert case["guideline_version"] == "v2.1"
    dumped = str(case)
    for leaked in ("families", "flag_update", "praise", "aspects_v2_1", BANK):
        assert leaked not in dumped
    assert "manual" not in dumped


def test_outcome_confirmado_con_las_familias_en_otro_orden(
    tmp_path: Path, aspects_repo: InMemoryHitlRepository
) -> None:
    eva = client_for(tmp_path, aspects_repo, ["aspects"])
    first = take(eva)
    assert review(eva, first, families=["AC"]).status_code == 200
    second = take(eva)

    # Gemini dijo ["TR", "UX"] y u: el revisor las da al revés.
    response = review(
        eva,
        second,
        review_id="22222222-2222-4222-8222-222222222222",
        families=["UX", "TR"],
        flag_update=True,
    )

    assert response.status_code == 200, response.text
    done = {r.id_resena: r for r in aspects_repo.reviews}
    assert done["syn-1"].outcome is ReviewOutcome.CONFIRMED
    assert done["syn-2"].outcome is ReviewOutcome.CONFIRMED
    assert done["syn-2"].validated_families == [
        AspectFamily.TR,
        AspectFamily.UX,
    ]
    assert done["syn-2"].predicted_flag_update is True
    assert done["syn-2"].task is HitlTask.ASPECTS
    assert done["syn-2"].display_mode is DisplayMode.BLIND


def test_corregir_una_marca_o_una_familia_es_corrected(
    tmp_path: Path, aspects_repo: InMemoryHitlRepository
) -> None:
    eva = client_for(tmp_path, aspects_repo, ["aspects"])
    case = take(eva)

    response = review(eva, case, families=[], flag_security=True)

    assert response.status_code == 200, response.text
    saved = aspects_repo.reviews[0]
    assert saved.outcome is ReviewOutcome.CORRECTED
    assert saved.validated_families == []
    assert saved.validated_flag_security is True


def test_un_comentario_pasa_por_el_sanitizador(
    tmp_path: Path, aspects_repo: InMemoryHitlRepository
) -> None:
    eva = client_for(tmp_path, aspects_repo, ["aspects"])
    case = take(eva)

    review(eva, case, comment=f"Escribió {FAKE_NAME}")

    assert aspects_repo.reviews[0].comment == f"Escribió {FAKE_TOKEN}"


def test_familias_repetidas_o_desconocidas_son_422(
    tmp_path: Path, aspects_repo: InMemoryHitlRepository
) -> None:
    eva = client_for(tmp_path, aspects_repo, ["aspects"])
    case = take(eva)

    assert review(eva, case, families=["AC", "AC"]).status_code == 422
    assert review(eva, case, families=["ZZ"]).status_code == 422


def test_reintentar_con_el_mismo_review_id_no_duplica(
    tmp_path: Path, aspects_repo: InMemoryHitlRepository
) -> None:
    eva = client_for(tmp_path, aspects_repo, ["aspects"])
    case = take(eva)

    assert review(eva, case).status_code == 200
    assert review(eva, case).status_code == 200

    assert len(aspects_repo.reviews) == 1


def test_no_se_guardan_aspectos_por_la_ruta_de_sentimiento(
    tmp_path: Path, aspects_repo: InMemoryHitlRepository
) -> None:
    eva = client_for(tmp_path, aspects_repo, ["aspects", "sentiment"])
    case = take(eva)

    response = eva.post(
        f"/api/v1/hitl/items/{case['item_id']}/review",
        json={
            "review_id": "33333333-3333-4333-8333-333333333333",
            "validated_label": "NEG",
            "flags": [],
            "guideline_version": "v2.1",
        },
    )

    assert response.status_code == 422
    assert aspects_repo.reviews == []


def test_un_revisor_de_sentimiento_recibe_403_en_aspectos_y_topicos(
    tmp_path: Path, aspects_repo: InMemoryHitlRepository
) -> None:
    ana = client_for(tmp_path, aspects_repo, ["sentiment"], user="ana")

    next_aspects = ana.post("/api/v1/hitl/next", json={"task": "aspects"})
    assert next_aspects.status_code == 403
    assert ana.get("/api/v1/hitl/guidelines/aspects").status_code == 403
    assert ana.get("/api/v1/hitl/topics/versions").status_code == 403


def test_el_resumen_de_aspectos_no_trae_muestra_de_monitoreo(
    tmp_path: Path, aspects_repo: InMemoryHitlRepository
) -> None:
    eva = client_for(tmp_path, aspects_repo, ["aspects"])

    (task,) = eva.get("/api/v1/hitl/summary").json()["tasks"]

    assert task["task"] == "aspects"
    assert task["pending"] == 2
    assert task["monitor_target"] == 0


def test_resena_editada_expira_en_aspectos(
    tmp_path: Path, aspects_repo: InMemoryHitlRepository
) -> None:
    aspects_repo.texts[(BANK, "syn-1")] = "El texto cambió después"
    eva = client_for(tmp_path, aspects_repo, ["aspects"])

    case = take(eva)

    assert "número 2" in case["text"]  # el 1 expiró y se ofreció el siguiente


def test_text_matches_usa_el_final_del_item_id_en_aspectos() -> None:
    item, text = aspects_item(7, ["AC"])

    assert text_matches(item.item_id, text, HitlTask.ASPECTS)
    assert not text_matches(item.item_id, text + "!", HitlTask.ASPECTS)


def test_un_caso_sin_familias_validas_no_se_ofrece(tmp_path: Path) -> None:
    item, text = aspects_item(1, ["AC"])
    broken = item.model_copy(update={"predicted": {"families": "AC"}})
    repo = InMemoryHitlRepository(
        [broken], {(BANK, "syn-1"): text}, [guideline(HitlTask.ASPECTS, "v2.1")]
    )
    eva = client_for(tmp_path, repo, ["aspects"])

    response = eva.post("/api/v1/hitl/next", json={"task": "aspects"})

    assert response.status_code == 204


# -- muestras del administrador ---------------------------------------------


def candidate(n: int, bank: str) -> AspectCandidate:
    return AspectCandidate(
        id_resena=f"r{n}",
        bank_id=bank,
        text_key=hashlib.sha256(f"t{n}".encode()).hexdigest(),
        predicted={
            "families": ["AC"],
            "flag_update": False,
            "flag_security": False,
            "praise": False,
            "prompt_version": "aspects_v2_1",
        },
    )


def admin_client(samples: InMemorySamplesRepository) -> TestClient:
    app = local_app("administrador")
    app.state.samples_repository = samples
    app.dependency_overrides[admin_router.now] = lambda: T0
    return TestClient(app)


SAMPLE_BODY = {"size": 10, "months": 3, "reason": "Revalidar las familias"}


def test_la_muestra_tiene_cuota_igual_por_banco_y_casos_a_ciegas() -> None:
    pool = [candidate(n, "A") for n in range(40)] + [
        candidate(n + 100, "B") for n in range(8)
    ]
    samples = InMemorySamplesRepository(pool)
    admin = admin_client(samples)

    response = admin.post("/api/v1/admin/samples/aspects", json=SAMPLE_BODY)

    assert response.status_code == 201, response.text
    out = response.json()
    assert out["created"] == 10
    assert out["per_bank"] == {"A": 5, "B": 5}
    assert len(samples.items) == len(samples.events) == 10
    for item in samples.items:
        assert item.task is HitlTask.ASPECTS
        assert item.reason is HitlReason.MANUAL
        assert item.display_mode is DisplayMode.BLIND
        assert item.item_id.startswith(f"aspects:manual:{out['batch']}:")
        assert item.predicted and item.predicted["prompt_version"]
    assert {e.status.value for e in samples.events} == {"queued"}
    assert {e.actor_hash for e in samples.events} == {None}


def test_un_banco_corto_deja_que_los_demas_completen_la_muestra() -> None:
    pool = [candidate(n, "A") for n in range(40)] + [candidate(900, "B")]
    samples = InMemorySamplesRepository(pool)

    out = admin_client(samples).post(
        "/api/v1/admin/samples/aspects", json=SAMPLE_BODY
    )

    assert out.json()["per_bank"] == {"A": 9, "B": 1}


def test_la_muestra_no_repite_resenas_de_lotes_anteriores() -> None:
    samples = InMemorySamplesRepository([candidate(n, "A") for n in range(12)])
    admin = admin_client(samples)

    admin.post("/api/v1/admin/samples/aspects", json=SAMPLE_BODY)
    second = admin.post("/api/v1/admin/samples/aspects", json=SAMPLE_BODY)

    assert second.json()["created"] == 2
    assert len({i.id_resena for i in samples.items}) == 12


def test_sin_candidatos_es_404_y_no_escribe() -> None:
    samples = InMemorySamplesRepository([])

    response = admin_client(samples).post(
        "/api/v1/admin/samples/aspects", json=SAMPLE_BODY
    )

    assert response.status_code == 404
    assert samples.items == []


def test_el_motivo_es_obligatorio_y_los_lotes_se_listan() -> None:
    samples = InMemorySamplesRepository([candidate(1, "A")])
    admin = admin_client(samples)

    short = admin.post(
        "/api/v1/admin/samples/aspects", json={**SAMPLE_BODY, "reason": "x"}
    )
    assert short.status_code == 422
    admin.post("/api/v1/admin/samples/aspects", json=SAMPLE_BODY)

    (batch,) = admin.get("/api/v1/admin/samples").json()["batches"]
    assert batch["size"] == 1
    assert batch["reviewed"] == 0


@pytest.mark.parametrize("roles", ["analista", "lector", "revisor"])
def test_las_muestras_son_solo_del_administrador(roles: str) -> None:
    app = local_app(roles)
    app.state.samples_repository = InMemorySamplesRepository()
    client = TestClient(app)

    assert client.get("/api/v1/admin/samples").status_code == 403
    created = client.post("/api/v1/admin/samples/aspects", json=SAMPLE_BODY)
    assert created.status_code == 403


# -- curaduría de tópicos ---------------------------------------------------

V0 = datetime(2026, 7, 1, tzinfo=UTC)
V1 = datetime(2026, 10, 1, tzinfo=UTC)


def topics_repo() -> InMemoryTopicsRepository:
    return InMemoryTopicsRepository(
        versions=[("v0", V0), ("v1", V1)],
        catalog={
            "v0": [CatalogTopic(0, ("token",), 10, None, None)],
            "v1": [
                CatalogTopic(0, ("token", "codigo"), 12, 0, 0.9),
                CatalogTopic(1, ("spei",), 8, None, None),
                CatalogTopic(2, ("login", "acceso"), 5, 0, 0.7),
            ],
        },
        examples={("v1", 0): [(BANK, f"syn-{n}") for n in range(1, 4)]},
    )


def topics_client(
    tmp_path: Path, repo: InMemoryTopicsRepository, tasks: list[str]
) -> TestClient:
    texts = InMemoryHitlRepository(
        [], {(BANK, f"syn-{n}"): f"Texto {n}" for n in range(1, 4)}, []
    )
    client = client_for(tmp_path, texts, tasks)
    client.app.state.topics_repository = repo  # type: ignore[attr-defined]
    return client


CURATION = {
    "curated_name": "Códigos de acceso",
    "coherence_1_5": 4,
    "audience": "producto",
    "families": ["AC"],
    "is_new_theme": False,
    "mapping_confirmed": True,
}


def test_las_versiones_pendientes_traen_su_avance(tmp_path: Path) -> None:
    eva = topics_client(tmp_path, topics_repo(), ["topic"])

    versions = eva.get("/api/v1/hitl/topics/versions").json()["versions"]

    by_name = {v["topic_model_version"]: v for v in versions}
    assert by_name["v1"]["paired"] == 2
    assert by_name["v1"]["decided"] == 0
    assert by_name["v1"]["is_current"] is False
    assert by_name["v1"]["activates_on_completion"] is True
    assert by_name["v0"]["is_current"] is True  # v1 aún no está completa


def test_la_ficha_trae_el_par_anterior_con_su_curaduria(
    tmp_path: Path,
) -> None:
    eva = topics_client(tmp_path, topics_repo(), ["topic"])
    assert (
        eva.post("/api/v1/hitl/topics/v0/0", json=CURATION).status_code == 201
    )

    detail = eva.get("/api/v1/hitl/topics/v1").json()

    first = detail["topics"][0]
    assert first["terms"] == ["token", "codigo"]
    assert first["size"] == 12
    assert first["previous"]["topic_id"] == 0
    assert first["previous"]["curation"]["curated_name"] == "Códigos de acceso"
    assert detail["topics"][1]["previous"] is None
    assert first["decision"] is None


def test_curar_valida_con_topic_curation(tmp_path: Path) -> None:
    eva = topics_client(tmp_path, topics_repo(), ["topic"])

    bad = {**CURATION, "coherence_1_5": 9}
    assert eva.post("/api/v1/hitl/topics/v1/0", json=bad).status_code == 422
    dup = {**CURATION, "families": ["AC", "AC"]}
    assert eva.post("/api/v1/hitl/topics/v1/0", json=dup).status_code == 422
    missing = eva.post("/api/v1/hitl/topics/v1/99", json=CURATION)
    assert missing.status_code == 404


def test_al_decidir_todos_los_pares_la_version_pasa_a_ser_la_vigente(
    tmp_path: Path,
) -> None:
    repo = topics_repo()
    eva = topics_client(tmp_path, repo, ["topic"])
    assert repo.current_version() == "v0"

    first = eva.post("/api/v1/hitl/topics/v1/0", json=CURATION).json()
    assert (first["decided"], first["paired"]) == (1, 2)
    assert first["completed"] is False
    assert repo.current_version() == "v0"

    last = eva.post(
        "/api/v1/hitl/topics/v1/2",
        json={**CURATION, "mapping_confirmed": False, "is_new_theme": True},
    ).json()

    assert last["completed"] is True
    assert repo.current_version() == "v1"
    saved = repo.rows[-1]
    assert saved.curator_hash
    assert saved.curated_at == T0
    assert saved.mapping_confirmed is False


def test_la_ultima_decision_de_un_topico_gana(tmp_path: Path) -> None:
    repo = topics_repo()
    eva = topics_client(tmp_path, repo, ["topic"])
    eva.post("/api/v1/hitl/topics/v1/0", json=CURATION)
    later = datetime(2026, 10, 27, tzinfo=UTC)
    overrides = eva.app.dependency_overrides  # type: ignore[attr-defined]
    overrides[topics_router.now] = lambda: later

    eva.post(
        "/api/v1/hitl/topics/v1/0",
        json={**CURATION, "curated_name": "Otro nombre"},
    )

    detail = eva.get("/api/v1/hitl/topics/v1").json()
    assert detail["topics"][0]["decision"]["curated_name"] == "Otro nombre"
    assert detail["decided"] == 1  # el mismo tópico no cuenta dos veces


def test_los_ejemplos_son_estables_y_vienen_del_tds(tmp_path: Path) -> None:
    eva = topics_client(tmp_path, topics_repo(), ["topic"])
    url = "/api/v1/hitl/topics/v1/0/examples?n=2"

    first = eva.get(url).json()
    second = eva.get(url).json()

    assert first == second
    assert len(first["examples"]) == 2
    assert all(e["text"].startswith("Texto ") for e in first["examples"])
    assert BANK not in str(first)
    assert eva.get("/api/v1/hitl/topics/v1/77/examples").status_code == 404


def test_topicos_exige_la_tarea_topic(tmp_path: Path) -> None:
    ana = topics_client(tmp_path, topics_repo(), ["sentiment", "aspects"])

    assert ana.get("/api/v1/hitl/topics/versions").status_code == 403
    assert ana.get("/api/v1/hitl/topics/v1").status_code == 403
    assert ana.get("/api/v1/hitl/topics/v1/0/examples").status_code == 403
    posted = ana.post("/api/v1/hitl/topics/v1/0", json=CURATION)
    assert posted.status_code == 403


def test_version_desconocida_es_404(tmp_path: Path) -> None:
    eva = topics_client(tmp_path, topics_repo(), ["topic"])

    assert eva.get("/api/v1/hitl/topics/nope").status_code == 404
