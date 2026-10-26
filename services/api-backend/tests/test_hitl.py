"""``/api/v1/hitl`` con la cola en memoria: reglas de la cola y de guardado."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from api_backend.dlp import FAKE_NAME, FAKE_TOKEN, FixedNameSanitizer
from api_backend.errors import ApiError, ErrorCode
from api_backend.sections.hitl import router as hitl_router
from api_backend.sections.hitl.repository import (
    InMemoryHitlRepository,
    public_id,
)
from api_backend.testing import (
    LOCAL_SALT,
    StaticRoleSource,
    local_app,
    role_map,
)
from fastapi.testclient import TestClient
from voc_common import (
    DisplayMode,
    Guideline,
    HitlEvent,
    HitlItem,
    HitlReason,
    HitlStatus,
    HitlTask,
)
from voc_common.text_utils import actor_hash, text_key

T0 = datetime(2026, 10, 26, 12, tzinfo=UTC)
MODEL = "m1"
BAD_COMMENT = f"Escribió {FAKE_NAME} en la reseña"


@dataclass
class Clock:
    at: datetime = T0

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **delta: float) -> None:
        self.at += timedelta(**delta)


def make_item(
    n: int,
    *,
    reason: HitlReason = HitlReason.LOW_CONFIDENCE,
    priority: float = 0.5,
    label: str | None = "NEG",
    text: str | None = None,
) -> tuple[HitlItem, str]:
    text = text or f"Texto sintético número {n}"
    blind = reason in (HitlReason.MONITOR_SAMPLE, HitlReason.AGREEMENT_SAMPLE)
    item = HitlItem(
        item_id=(
            f"{reason.value}:2026Q3:syn-{n}:{text_key(text)[:16]}:{MODEL}"
            if blind
            else f"sentiment:syn-{n}:{text_key(text)[:16]}:{MODEL}"
        ),
        id_resena=f"syn-{n}",
        bank_id="BANCO_SECRETO",
        task=HitlTask.SENTIMENT,
        reason=reason,
        display_mode=DisplayMode.BLIND if blind else DisplayMode.ASSISTED,
        model_version=MODEL,
        risk_policy_version="rp1",
        predicted={"label": label, "p_neg": 0.7, "p_neu": 0.2, "p_pos": 0.1},
        priority=priority,
        created_at=T0 - timedelta(days=1, minutes=n),
    )
    return item, text


def guideline(version: str = "v2.2", uri: str = "g.md") -> Guideline:
    return Guideline(
        guideline_version=version,
        task=HitlTask.SENTIMENT,
        content_uri=uri,
        valid_from=T0 - timedelta(days=10),
        published_by_hash="a" * 64,
    )


class Failing:
    def sanitize(self, text: str) -> str:
        raise ApiError(ErrorCode.UPSTREAM, "dlp caído")


@dataclass
class Kit:
    repo: InMemoryHitlRepository
    clock: Clock
    guides: Path
    sanitizer: Any
    apps: dict[str, TestClient]

    def client(self, name: str, roles: str = "revisor") -> TestClient:
        """Un revisor distinto por nombre, con la misma cola."""
        key = f"{name}:{roles}"
        if key not in self.apps:
            app = local_app(roles, portal_local_user=f"{name}@example.com")
            app.state.hitl_repository = self.repo
            app.state.comment_sanitizer = self.sanitizer
            app.state.guidelines_dir = self.guides
            app.dependency_overrides[hitl_router.now] = self.clock
            self.apps[key] = TestClient(app)
        return self.apps[key]

    def actor(self, name: str) -> str:
        return actor_hash(f"{name}@example.com", LOCAL_SALT)


@pytest.fixture
def make_kit(tmp_path: Path) -> Callable[..., Kit]:
    def build(*pairs: tuple[HitlItem, str]) -> Kit:
        (tmp_path / "g.md").write_text("# Guía de prueba", encoding="utf-8")
        repo = InMemoryHitlRepository(
            [item for item, _ in pairs],
            {("BANCO_SECRETO", item.id_resena): text for item, text in pairs},
            [guideline()],
        )
        return Kit(repo, Clock(), tmp_path, FixedNameSanitizer(), {})

    return build


def take(client: TestClient) -> dict[str, Any] | None:
    response = client.post("/api/v1/hitl/next", json={"task": "sentiment"})
    if response.status_code == 204:
        return None
    assert response.status_code == 200, response.text
    return response.json()


def body(case: dict[str, Any], label: str | None = "NEG", **extra: Any) -> dict:
    return {
        "review_id": extra.pop(
            "review_id", "11111111-1111-4111-8111-111111111111"
        ),
        "validated_label": label,
        "flags": extra.pop("flags", []),
        "guideline_version": case["guideline_version"],
        **extra,
    }


def review(client: TestClient, case: dict[str, Any], **kw: Any) -> Any:
    return client.post(
        f"/api/v1/hitl/items/{case['item_id']}/review", json=body(case, **kw)
    )


# -- orden y modo ---------------------------------------------------------


def test_la_cola_sigue_prioridad_y_luego_created_at(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(
        make_item(1, priority=0.3),
        make_item(2, priority=0.9),
        make_item(3, priority=0.3),
    )
    ana = kit.client("ana")

    first = take(ana)
    assert first is not None and "número 2" in first["text"]
    review(ana, first)
    # A igual prioridad, el más antiguo (n mayor → creado antes).
    second = take(ana)
    assert second is not None and "número 3" in second["text"]


def test_blind_nunca_devuelve_la_propuesta(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(
        make_item(1, reason=HitlReason.MONITOR_SAMPLE, priority=2),
        make_item(2, reason=HitlReason.AGREEMENT_SAMPLE, priority=1.5),
        make_item(3, priority=0.5),
    )
    ana = kit.client("ana")
    seen = []
    for _ in range(3):
        case = take(ana)
        assert case is not None
        seen.append(case)
        review(
            ana,
            case,
            review_id=f"00000000-0000-4000-8000-00000000000{len(seen)}",
        )

    modes = [(c["display_mode"], c["proposal"]) for c in seen]
    assert modes[0] == ("blind", None)
    assert modes[1] == ("blind", None)
    assert modes[2][0] == "assisted" and modes[2][1]["label"] == "NEG"


def test_la_propuesta_se_oculta_aunque_el_modo_diga_assisted(
    make_kit: Callable[..., Kit],
) -> None:
    item, text = make_item(1, reason=HitlReason.LOW_CONFIDENCE)
    # Un caso del oro mal guardado como asistido: el motivo manda.
    forged = item.model_copy(update={"reason": HitlReason.AGREEMENT_SAMPLE})
    kit = make_kit((forged, text))

    case = take(kit.client("ana"))

    assert case is not None and case["proposal"] is None


def test_ninguna_respuesta_trae_banco_motivo_ni_explicacion(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1), make_item(2, reason=HitlReason.MONITOR_SAMPLE))
    ana = kit.client("ana")
    out = []
    out.append(ana.get("/api/v1/hitl/summary").text)
    case = take(ana)
    assert case is not None
    out.append(json.dumps(case))
    out.append(ana.get("/api/v1/hitl/guidelines/sentiment").text)
    out.append(review(ana, case).text)

    joined = "\n".join(out).lower()
    for forbidden in (
        "banco_secreto",
        "bank",
        "estrellas",
        "stars",
        "reason",
        "sentiment:",
        "low_confidence",
        "monitor_sample",
        "explanation",
        "attributions",
    ):
        assert forbidden not in joined, forbidden
    assert set(case) == {
        "item_id",
        "task",
        "text",
        "display_mode",
        "proposal",
        "guideline_version",
        "opened_at",
        "review_round",
    }


# -- bloqueo, saltos y doble revisión ---------------------------------------


def test_bloqueo_de_15_minutos(make_kit: Callable[..., Kit]) -> None:
    kit = make_kit(make_item(1))
    ana, beto = kit.client("ana"), kit.client("beto")

    assert take(ana) is not None
    assert take(beto) is None
    kit.clock.advance(minutes=14)
    assert take(beto) is None
    kit.clock.advance(minutes=2)
    assert take(beto) is not None


def test_el_mismo_revisor_recupera_su_caso_sin_perder_el_tiempo(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1))
    ana = kit.client("ana")
    first = take(ana)
    kit.clock.advance(minutes=3)

    again = take(ana)

    assert again is not None
    assert again["item_id"] == first["item_id"]  # type: ignore[index]
    assert again["opened_at"] == first["opened_at"]  # type: ignore[index]


def test_saltado_vuelve_a_otros_pero_no_al_mismo_en_7_dias(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1))
    ana, beto = kit.client("ana"), kit.client("beto")
    case = take(ana)
    assert case is not None

    skipped = ana.post(f"/api/v1/hitl/items/{case['item_id']}/skip")
    assert skipped.status_code == 204
    assert take(ana) is None
    assert take(beto) is not None  # vuelve a la cola para los demás
    kit.clock.advance(days=6)
    assert take(ana) is None
    kit.clock.advance(days=2)
    kit.clock.advance(minutes=20)  # ya venció el bloqueo de beto
    assert take(ana) is not None


def test_la_segunda_ronda_va_a_otro_revisor_y_nunca_al_mismo(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1, reason=HitlReason.AGREEMENT_SAMPLE))
    ana, beto, carla = (kit.client(n) for n in ("ana", "beto", "carla"))
    first = take(ana)
    assert first is not None and first["review_round"] == 1
    assert review(ana, first).status_code == 200

    assert take(ana) is None  # nunca dos veces
    second = take(beto)
    assert second is not None and second["review_round"] == 2
    assert (
        review(
            beto, second, review_id="22222222-2222-4222-8222-222222222222"
        ).status_code
        == 200
    )
    assert take(carla) is None  # ya hay dos revisiones
    assert [r.review_round for r in kit.repo.reviews] == [1, 2]


def test_un_caso_normal_se_cierra_con_la_primera_revision(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1))
    ana, beto = kit.client("ana"), kit.client("beto")
    case = take(ana)
    assert case is not None
    review(ana, case)

    assert take(beto) is None


def test_resena_editada_expira_y_se_ofrece_la_siguiente(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1, priority=0.9), make_item(2, priority=0.1))
    # El texto del TDS cambió después de crear el caso 1.
    kit.repo.texts[("BANCO_SECRETO", "syn-1")] = "Texto editado"

    case = take(kit.client("ana"))

    assert case is not None and "número 2" in case["text"]
    expired = [e for e in kit.repo.events if e.status is HitlStatus.EXPIRED]
    assert len(expired) == 1 and expired[0].actor_hash is None
    assert take(kit.client("beto")) is None  # el expirado no vuelve


def test_salir_devuelve_el_caso_a_la_cola(make_kit: Callable[..., Kit]) -> None:
    kit = make_kit(make_item(1))
    ana, beto = kit.client("ana"), kit.client("beto")
    case = take(ana)
    assert case is not None

    assert (
        ana.post(f"/api/v1/hitl/items/{case['item_id']}/release").status_code
        == 204
    )
    assert take(beto) is not None
    # Soltar un caso que ya no es suyo no hace nada.
    assert (
        ana.post(f"/api/v1/hitl/items/{case['item_id']}/release").status_code
        == 204
    )
    assert kit.repo.entry(case["item_id"], kit.clock()).actor_hash == kit.actor(
        "beto"
    )  # type: ignore[union-attr]


# -- guardado ---------------------------------------------------------------


def test_revision_confirmada_guarda_modo_guia_y_tiempo(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1))
    ana = kit.client("ana")
    case = take(ana)
    assert case is not None
    kit.clock.advance(seconds=42)

    response = review(
        ana, case, flags=["menciona_falla"], ticket=" T-1 ", comment="ok"
    )

    assert response.status_code == 200
    assert response.json() == {
        "review_id": "11111111-1111-4111-8111-111111111111",
        "next_available": False,
    }
    saved = kit.repo.reviews[0]
    assert saved.outcome.value == "confirmed"
    assert (saved.predicted_label, saved.validated_label) == ("NEG", "NEG")
    assert saved.display_mode is DisplayMode.ASSISTED
    assert saved.seconds_spent == 42
    assert saved.review_round == 1
    assert saved.guideline_version == "v2.2"
    assert saved.model_version == MODEL and saved.risk_policy_version == "rp1"
    assert saved.reviewer_hash == kit.actor("ana")
    assert saved.opened_at == T0 and saved.submitted_at == T0 + timedelta(
        seconds=42
    )
    assert saved.ticket == "T-1" and saved.comment == "ok"
    assert kit.repo.events[-1].status is HitlStatus.SUBMITTED


def test_en_blind_la_comparacion_se_hace_en_el_servidor(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1, reason=HitlReason.MONITOR_SAMPLE, label="NEG"))
    ana = kit.client("ana")
    case = take(ana)
    assert case is not None and case["proposal"] is None

    assert review(ana, case, label="POS").status_code == 200

    saved = kit.repo.reviews[0]
    assert saved.predicted_label == "NEG"
    assert saved.outcome.value == "corrected"
    assert saved.display_mode is DisplayMode.BLIND


def test_no_evaluable_guarda_etiqueta_nula_y_corrected(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1))
    ana = kit.client("ana")
    case = take(ana)
    assert case is not None

    response = review(ana, case, label=None, flags=["no_evaluable"])

    assert response.status_code == 200
    saved = kit.repo.reviews[0]
    assert saved.validated_label is None
    assert saved.outcome.value == "corrected"


@pytest.mark.parametrize(
    ("label", "flags"),
    [(None, []), ("NEG", ["no_evaluable"]), ("NEG", ["duda", "duda"])],
)
def test_etiqueta_y_marcas_incoherentes_son_422(
    make_kit: Callable[..., Kit], label: str | None, flags: list[str]
) -> None:
    kit = make_kit(make_item(1))
    ana = kit.client("ana")
    case = take(ana)
    assert case is not None

    assert review(ana, case, label=label, flags=flags).status_code == 422
    assert kit.repo.reviews == []


def test_idempotente_por_review_id(make_kit: Callable[..., Kit]) -> None:
    kit = make_kit(make_item(1))
    ana = kit.client("ana")
    case = take(ana)
    assert case is not None

    first = review(ana, case)
    again = review(ana, case)

    assert first.status_code == again.status_code == 200
    assert len(kit.repo.reviews) == 1
    assert [e.status for e in kit.repo.events].count(HitlStatus.SUBMITTED) == 1


def test_409_si_el_caso_volvio_a_la_cola(make_kit: Callable[..., Kit]) -> None:
    kit = make_kit(make_item(1))
    ana, beto = kit.client("ana"), kit.client("beto")
    case = take(ana)
    assert case is not None
    kit.clock.advance(minutes=16)
    assert take(beto) is not None  # beto lo tomó cuando venció el bloqueo

    response = review(ana, case)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert kit.repo.reviews == []


def test_409_al_revisar_un_caso_que_nunca_se_tomo(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1))
    case = {
        "item_id": public_id(kit.repo.items[0].item_id),
        "guideline_version": "v2.2",
    }

    assert review(kit.client("ana"), case).status_code == 409


def test_la_version_de_guia_debe_existir(make_kit: Callable[..., Kit]) -> None:
    kit = make_kit(make_item(1))
    ana = kit.client("ana")
    case = take(ana)
    assert case is not None

    response = ana.post(
        f"/api/v1/hitl/items/{case['item_id']}/review",
        json={**body(case), "guideline_version": "v9"},
    )

    assert response.status_code == 422
    assert kit.repo.reviews == []


def test_el_comentario_pasa_por_el_sanitizador(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1))
    ana = kit.client("ana")
    case = take(ana)
    assert case is not None

    review(ana, case, comment=BAD_COMMENT)

    assert kit.repo.reviews[0].comment == f"Escribió {FAKE_TOKEN} en la reseña"


def test_si_dlp_falla_no_se_escribe_nada(make_kit: Callable[..., Kit]) -> None:
    kit = make_kit(make_item(1))
    kit.sanitizer = Failing()
    ana = kit.client("ana")
    case = take(ana)
    assert case is not None
    events_before = len(kit.repo.events)

    response = review(ana, case, comment=BAD_COMMENT)

    assert response.status_code == 502
    assert kit.repo.reviews == []
    assert len(kit.repo.events) == events_before
    # El caso sigue siendo suyo: puede reintentar sin comentario.
    assert review(ana, case).status_code == 200


# -- roles y resumen -----------------------------------------------------------


@pytest.mark.parametrize("roles", ["lector", "analista", "administrador"])
def test_sin_rol_de_revisor_es_403(
    make_kit: Callable[..., Kit], roles: str
) -> None:
    kit = make_kit(make_item(1))
    client = kit.client("ana", roles)

    assert client.get("/api/v1/hitl/summary").status_code == 403
    assert (
        client.post("/api/v1/hitl/next", json={"task": "sentiment"}).status_code
        == 403
    )
    assert client.get("/api/v1/hitl/guidelines/sentiment").status_code == 403


def test_un_revisor_de_aspectos_no_recibe_casos_de_sentimiento(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1))
    app = local_app("revisor", portal_local_user="eva@example.com")
    app.state.role_source = StaticRoleSource(
        role_map(
            **{
                "eva@example.com": {
                    "roles": ["revisor"],
                    "reviewer_tasks": ["aspects"],
                }
            }
        )
    )
    app.state.hitl_repository = kit.repo
    app.dependency_overrides[hitl_router.now] = kit.clock
    eva = TestClient(app)

    assert (
        eva.post("/api/v1/hitl/next", json={"task": "sentiment"}).status_code
        == 403
    )
    assert eva.get("/api/v1/hitl/summary").json() == {"tasks": []}
    item_id = public_id(kit.repo.items[0].item_id)
    assert eva.post(f"/api/v1/hitl/items/{item_id}/skip").status_code == 403


def test_resumen_con_solo_conteos(make_kit: Callable[..., Kit]) -> None:
    kit = make_kit(
        make_item(1),
        make_item(2),
        make_item(3, reason=HitlReason.MONITOR_SAMPLE, priority=2),
        make_item(4, reason=HitlReason.MONITOR_SAMPLE, priority=2),
    )
    ana, beto = kit.client("ana"), kit.client("beto")
    case = take(ana)
    assert case is not None
    kit.clock.advance(seconds=30)
    review(ana, case)
    other = take(beto)
    assert other is not None
    kit.clock.advance(seconds=50)
    review(beto, other, review_id="33333333-3333-4333-8333-333333333333")

    summary = ana.get("/api/v1/hitl/summary").json()["tasks"][0]

    assert summary == {
        "task": "sentiment",
        "pending": 2,
        "mine_this_week": 1,
        "team_this_week": 2,
        "median_seconds": 50.0,
        "monitor_done": 2,
        "monitor_target": 2,
    }


# -- guía ----------------------------------------------------------------------


def test_la_guia_vigente_trae_version_fecha_y_markdown(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1))

    out = kit.client("ana").get("/api/v1/hitl/guidelines/sentiment").json()

    assert out["guideline_version"] == "v2.2"
    assert out["content"] == "# Guía de prueba"
    assert out["valid_from"].startswith("2026-10-16")


def test_guia_sin_archivo_es_404_con_la_ruta(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1))
    (kit.guides / "g.md").unlink()

    response = kit.client("ana").get("/api/v1/hitl/guidelines/sentiment")

    assert response.status_code == 404
    assert "g.md" in response.json()["error"]["message"]


def test_la_guia_no_sale_de_su_carpeta(make_kit: Callable[..., Kit]) -> None:
    kit = make_kit(make_item(1))
    kit.repo._guidelines = [guideline(uri="../secreto.md")]  # noqa: SLF001
    (kit.guides.parent / "secreto.md").write_text("no", encoding="utf-8")

    response = kit.client("ana").get("/api/v1/hitl/guidelines/sentiment")

    assert response.status_code == 404


def test_caso_sin_prediccion_no_se_ofrece(make_kit: Callable[..., Kit]) -> None:
    kit = make_kit(make_item(1, label=None))

    assert take(kit.client("ana")) is None


def test_evento_de_otro_item_no_cambia_el_estado(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_item(1), make_item(2))
    kit.repo.add_event(
        HitlEvent(
            event_id="e1",
            item_id=kit.repo.items[1].item_id,
            status=HitlStatus.IN_REVIEW,
            actor_hash=kit.actor("beto"),
            at=T0,
        )
    )

    case = take(kit.client("ana"))

    assert case is not None and "número 1" in case["text"]
