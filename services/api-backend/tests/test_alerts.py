"""``/api/v1/alerts`` con alertas en memoria: lectura, transiciones y subida."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from api_backend.dlp import FAKE_NAME, FAKE_TOKEN, FixedNameSanitizer
from api_backend.errors import ApiError, ErrorCode
from api_backend.fixtures import SENTINEL
from api_backend.sections.alerts import router as alerts_router
from api_backend.sections.alerts.repository import InMemoryAlertRepository
from api_backend.sections.alerts.sample import sample_repository
from api_backend.testing import LOCAL_SALT, local_app
from fastapi.testclient import TestClient
from voc_common import (
    AlertStatus,
    BoostEndReason,
    DriftAlert,
    DriftAlertEvent,
    DriftMetric,
    HitlBoost,
)
from voc_common.text_utils import actor_hash

T0 = datetime(2026, 10, 26, 12, tzinfo=UTC)
PERIOD = date(2026, 9, 1)
NOTE = "Revisado con el equipo, la deriva es real."


def make_alert(
    bank: str = "BBVA",
    series: str = "neg_share",
    period: date = PERIOD,
    boost: str | None = None,
) -> DriftAlert:
    return DriftAlert(
        alert_id=f"drift_{bank}_{period:%Y-%m}_{series}",
        bank_id=bank,
        period=period,
        series=series,
        value=0.31,
        threshold=4.0,
        drift_policy_version="dp1",
        hitl_boost_id=boost,
        created_at=T0 - timedelta(days=5),
    )


def open_event(alert: DriftAlert) -> DriftAlertEvent:
    return DriftAlertEvent(
        event_id=f"{alert.alert_id}_open",
        alert_id=alert.alert_id,
        status=AlertStatus.OPEN,
        at=T0 - timedelta(days=5),
    )


def make_boost(alert: DriftAlert, *, ends_in_days: int = 5) -> HitlBoost:
    return HitlBoost(
        boost_id=f"boost_{alert.alert_id}",
        bank_id=alert.bank_id,
        alert_id=alert.alert_id,
        risk_policy_version="rp1",
        coverage=0.85,
        weekly_cap=100,
        starts_at=T0 - timedelta(days=5),
        ends_at=T0 + timedelta(days=ends_in_days),
    )


def make_metrics(alert: DriftAlert, months: int = 30) -> list[DriftMetric]:
    out = []
    for back in range(months):
        index = alert.period.year * 12 + alert.period.month - 1 - back
        period = date(index // 12, index % 12 + 1, 1)
        out.append(
            DriftMetric(
                bank_id=alert.bank_id,
                period=period,
                metric=alert.series,
                value=0.2,
                baseline=0.18,
                z=0.5,
                threshold=4.0,
                alert=False,
                drift_policy_version="dp1",
                computed_at=T0,
            )
        )
    return out


class Failing:
    def sanitize(self, text: str) -> str:
        raise ApiError(ErrorCode.UPSTREAM, "dlp caído")


@dataclass
class Kit:
    repo: InMemoryAlertRepository
    sanitizer: Any
    apps: dict[str, TestClient]

    def client(self, name: str = "ana", roles: str = "analista") -> TestClient:
        key = f"{name}:{roles}"
        if key not in self.apps:
            app = local_app(roles, portal_local_user=f"{name}@example.com")
            app.state.alert_repository = self.repo
            app.state.comment_sanitizer = self.sanitizer
            app.dependency_overrides[alerts_router.now] = lambda: T0
            self.apps[key] = TestClient(app)
        return self.apps[key]

    def post(
        self,
        alert: DriftAlert,
        status: str,
        *,
        name: str = "ana",
        event_id: str | None = None,
        note: str = NOTE,
        ticket: str | None = None,
    ) -> Any:
        body: dict[str, Any] = {
            "event_id": event_id or str(uuid4()),
            "status": status,
            "note": note,
        }
        if ticket is not None:
            body["ticket"] = ticket
        return self.client(name).post(
            f"/api/v1/alerts/{alert.alert_id}/events", json=body
        )


@pytest.fixture
def make_kit() -> Callable[..., Kit]:
    def build(
        *alerts: DriftAlert,
        boosts: list[HitlBoost] | None = None,
        sanitizer: Any = None,
    ) -> Kit:
        repo = InMemoryAlertRepository(
            list(alerts),
            [open_event(a) for a in alerts],
            [m for a in alerts for m in make_metrics(a)],
            boosts or [],
        )
        return Kit(repo, sanitizer or FixedNameSanitizer(), {})

    return build


def statuses(kit: Kit, alert: DriftAlert) -> list[str]:
    return [e.status.value for e in kit.repo.events(alert.alert_id)]


def boost_rows(kit: Kit) -> list[HitlBoost]:
    return kit.repo.boost_rows


# -- Lectura -----------------------------------------------------------------


def test_la_bandeja_filtra_por_estado_y_banco(
    make_kit: Callable[..., Kit],
) -> None:
    a = make_alert("BBVA")
    b = make_alert("AZTECA", "mean_words")
    c = make_alert("NUBANK", "family_AC", date(2026, 8, 1))
    kit = make_kit(a, b, c)
    assert kit.post(b, "confirmed").status_code == 200

    client = kit.client()
    everything = client.get("/api/v1/alerts").json()
    opened = client.get("/api/v1/alerts", params={"status": "open"}).json()
    confirmed = client.get(
        "/api/v1/alerts", params={"status": "confirmed"}
    ).json()
    banks = client.get(
        "/api/v1/alerts", params=[("bank", "BBVA"), ("bank", "NUBANK")]
    ).json()

    # Del mes más reciente al más viejo; a igual mes, por banco.
    assert [r["alert_id"] for r in everything] == [
        b.alert_id,
        a.alert_id,
        c.alert_id,
    ]
    assert {r["alert_id"] for r in opened} == {a.alert_id, c.alert_id}
    assert [r["alert_id"] for r in confirmed] == [b.alert_id]
    assert {r["bank_id"] for r in banks} == {"BBVA", "NUBANK"}
    first = everything[0]
    assert first["period"] == "2026-09"
    assert first["drift_policy_version"] == "dp1"


def test_la_bandeja_trae_la_subida_activa_o_cerrada(
    make_kit: Callable[..., Kit],
) -> None:
    a = make_alert("BBVA", boost="boost_drift_BBVA_2026-09_neg_share")
    b = make_alert("AZTECA", "mean_words")
    boost = make_boost(a)
    kit = make_kit(a, b, boosts=[boost])

    rows = {r["alert_id"]: r for r in kit.client().get("/api/v1/alerts").json()}

    assert rows[a.alert_id]["boost"]["active"] is True
    assert rows[a.alert_id]["boost"]["coverage"] == 0.85
    assert rows[b.alert_id]["boost"] is None

    kit.repo.close_boost(
        boost.model_copy(update={"ended_reason": BoostEndReason.EXPIRED})
    )
    row = kit.client().get(f"/api/v1/alerts/{a.alert_id}").json()["alert"]
    assert row["boost"]["active"] is False
    assert row["boost"]["ended_reason"] == "expired"


def test_el_detalle_trae_eventos_serie_y_enlace_al_explorador(
    make_kit: Callable[..., Kit],
) -> None:
    alert = make_alert()
    kit = make_kit(alert)
    kit.post(alert, "confirmed", ticket="VOC-7")

    body = kit.client().get(f"/api/v1/alerts/{alert.alert_id}").json()

    assert [e["status"] for e in body["events"]] == ["open", "confirmed"]
    monitor, person = body["events"]
    assert monitor["actor"] is None
    assert person["actor"] == actor_hash("ana@example.com", LOCAL_SALT)[:8]
    assert person["note"] == NOTE and person["ticket"] == "VOC-7"
    assert len(body["series"]) == 24
    assert body["series"][-1]["period"] == "2026-09"
    assert body["series"][0]["period"] == "2024-10"
    assert set(body["series"][0]) == {
        "period",
        "value",
        "baseline",
        "z",
        "psi",
        "threshold",
        "alert",
    }
    assert body["explorer"] == {
        "bank_id": "BBVA",
        "start": "2026-09-01",
        "end": "2026-09-30",
    }
    assert body["alert"]["status"] == "confirmed"


def test_una_alerta_inexistente_es_404(make_kit: Callable[..., Kit]) -> None:
    kit = make_kit(make_alert())

    assert kit.client().get("/api/v1/alerts/nada").status_code == 404
    response = kit.client().post(
        "/api/v1/alerts/nada/events",
        json={"event_id": str(uuid4()), "status": "confirmed", "note": NOTE},
    )
    assert response.status_code == 404


# -- Transiciones ------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (["confirmed"], ["open", "confirmed"]),
        (["dismissed"], ["open", "dismissed"]),
        (["confirmed", "dismissed"], ["open", "confirmed", "dismissed"]),
        (["confirmed", "open"], ["open", "confirmed", "open"]),
        (["dismissed", "open"], ["open", "dismissed", "open"]),
        (
            ["dismissed", "open", "confirmed"],
            ["open", "dismissed", "open", "confirmed"],
        ),
    ],
)
def test_transiciones_validas(
    make_kit: Callable[..., Kit], path: list[str], expected: list[str]
) -> None:
    alert = make_alert()
    kit = make_kit(alert)

    for step in path:
        response = kit.post(alert, step, ticket="VOC-1")
        assert response.status_code == 200, response.text

    assert statuses(kit, alert) == expected
    assert response.json()["alert"]["status"] == path[-1]


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ([], "open"),
        (["confirmed"], "confirmed"),
        (["dismissed"], "dismissed"),
        (["dismissed"], "confirmed"),
    ],
)
def test_transiciones_invalidas_dan_409(
    make_kit: Callable[..., Kit], path: list[str], status: str
) -> None:
    alert = make_alert()
    kit = make_kit(alert)
    for step in path:
        assert kit.post(alert, step).status_code == 200
    before = statuses(kit, alert)

    response = kit.post(alert, status)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert statuses(kit, alert) == before


def test_si_el_estado_cambio_entre_la_lectura_y_la_escritura_es_409(
    make_kit: Callable[..., Kit],
) -> None:
    alert = make_alert()
    kit = make_kit(alert)
    # Dos analistas ven la alerta abierta; Luis descarta primero.
    assert kit.post(alert, "dismissed", name="luis").status_code == 200

    response = kit.post(alert, "confirmed", name="ana")

    assert response.status_code == 409
    assert "dismissed" in response.json()["error"]["message"]
    assert statuses(kit, alert) == ["open", "dismissed"]


def test_cada_evento_guarda_quien_cuando_nota_y_ticket(
    make_kit: Callable[..., Kit],
) -> None:
    alert = make_alert()
    kit = make_kit(alert)

    kit.post(alert, "confirmed", name="luis", ticket=" VOC-9 ")

    event = kit.repo.events(alert.alert_id)[-1]
    assert event.actor_hash == actor_hash("luis@example.com", LOCAL_SALT)
    assert event.at == T0
    assert event.note == NOTE
    assert event.ticket == "VOC-9"


def test_la_nota_pide_diez_caracteres_y_el_ticket_vacio_es_nulo(
    make_kit: Callable[..., Kit],
) -> None:
    alert = make_alert()
    kit = make_kit(alert)

    short = kit.post(alert, "confirmed", note="  corta  ")
    assert short.status_code == 422
    blank = kit.post(alert, "confirmed", ticket="   ")
    assert blank.status_code == 200
    assert kit.repo.events(alert.alert_id)[-1].ticket is None
    assert len(kit.repo.events(alert.alert_id)) == 2


def test_la_nota_pasa_por_el_sanitizador(make_kit: Callable[..., Kit]) -> None:
    alert = make_alert()
    kit = make_kit(alert)

    response = kit.post(alert, "confirmed", note=f"Habló {FAKE_NAME} del tema")

    assert response.status_code == 200
    saved = kit.repo.events(alert.alert_id)[-1].note
    assert saved == f"Habló {FAKE_TOKEN} del tema"
    assert FAKE_NAME not in response.text


def test_si_dlp_falla_no_se_escribe_nada(make_kit: Callable[..., Kit]) -> None:
    alert = make_alert(boost="boost_x")
    boost = make_boost(alert).model_copy(update={"boost_id": "boost_x"})
    kit = make_kit(alert, boosts=[boost], sanitizer=Failing())

    response = kit.post(alert, "dismissed")

    assert response.status_code == 502
    assert statuses(kit, alert) == ["open"]
    assert boost_rows(kit) == [boost]


# -- Subida de revisión ------------------------------------------------------


def with_boost(
    kit_factory: Callable[..., Kit], **kwargs: Any
) -> tuple[Any, Kit]:
    alert = make_alert()
    boost = make_boost(alert, **kwargs)
    alert = alert.model_copy(update={"hitl_boost_id": boost.boost_id})
    return alert, kit_factory(alert, boosts=[boost])


def test_descartar_cierra_la_subida_activa_con_alert_closed(
    make_kit: Callable[..., Kit],
) -> None:
    alert, kit = with_boost(make_kit)

    response = kit.post(alert, "dismissed")

    assert response.status_code == 200
    closing = [b for b in boost_rows(kit) if b.ended_reason is not None]
    assert len(closing) == 1
    assert closing[0].boost_id == alert.hitl_boost_id
    assert closing[0].ended_reason is BoostEndReason.ALERT_CLOSED
    assert response.json()["alert"]["boost"]["active"] is False
    assert response.json()["alert"]["boost"]["ended_reason"] == "alert_closed"


def test_confirmar_no_cierra_la_subida(make_kit: Callable[..., Kit]) -> None:
    alert, kit = with_boost(make_kit)

    response = kit.post(alert, "confirmed")

    assert response.status_code == 200
    assert [b.ended_reason for b in boost_rows(kit)] == [None]
    assert response.json()["alert"]["boost"]["active"] is True


def test_descartar_con_la_subida_vencida_no_escribe_otro_cierre(
    make_kit: Callable[..., Kit],
) -> None:
    alert, kit = with_boost(make_kit, ends_in_days=-1)

    assert kit.post(alert, "dismissed").status_code == 200

    assert [b.ended_reason for b in boost_rows(kit)] == [None]


def test_descartar_sin_subida_funciona(make_kit: Callable[..., Kit]) -> None:
    alert = make_alert()
    kit = make_kit(alert)

    assert kit.post(alert, "dismissed").status_code == 200
    assert boost_rows(kit) == []


# -- Idempotencia ------------------------------------------------------------


def test_un_reintento_con_el_mismo_event_id_no_duplica(
    make_kit: Callable[..., Kit],
) -> None:
    alert = make_alert()
    kit = make_kit(alert)
    event_id = str(uuid4())

    first = kit.post(alert, "confirmed", event_id=event_id)
    again = kit.post(alert, "confirmed", event_id=event_id)

    assert first.status_code == again.status_code == 200
    assert statuses(kit, alert) == ["open", "confirmed"]
    assert again.json()["alert"]["status"] == "confirmed"


def test_reintentar_un_descarte_cierra_la_subida_que_quedo_abierta(
    make_kit: Callable[..., Kit],
) -> None:
    alert, kit = with_boost(make_kit)
    event_id = str(uuid4())
    # El evento se escribió pero el cierre de la subida falló.
    kit.repo.add_event(
        DriftAlertEvent(
            event_id=event_id,
            alert_id=alert.alert_id,
            status=AlertStatus.DISMISSED,
            actor_hash="a" * 64,
            at=T0,
            note=NOTE,
        )
    )
    assert [b.ended_reason for b in boost_rows(kit)] == [None]

    response = kit.post(alert, "dismissed", event_id=event_id)

    assert response.status_code == 200
    assert [b.ended_reason for b in boost_rows(kit)] == [
        None,
        BoostEndReason.ALERT_CLOSED,
    ]
    assert statuses(kit, alert) == ["open", "dismissed"]


# -- Roles y resumen ---------------------------------------------------------


def test_el_resumen_de_lector_solo_trae_conteos() -> None:
    app = local_app("lector")
    app.state.alert_repository = sample_repository(T0)
    client = TestClient(app)

    response = client.get("/api/v1/alerts/summary")

    assert response.status_code == 200
    assert response.json() == {"open_by_bank": {"NUBANK": 1}}
    assert SENTINEL not in response.text


def test_el_resumen_cuenta_las_abiertas_por_banco(
    make_kit: Callable[..., Kit],
) -> None:
    a = make_alert("BBVA")
    b = make_alert("BBVA", "mean_words")
    c = make_alert("AZTECA")
    kit = make_kit(a, b, c)
    kit.post(b, "dismissed")

    response = kit.client(roles="lector").get("/api/v1/alerts/summary")

    assert response.json() == {"open_by_bank": {"BBVA": 1, "AZTECA": 1}}


def test_el_lector_recibe_403_en_las_demas_rutas(
    make_kit: Callable[..., Kit],
) -> None:
    alert = make_alert()
    kit = make_kit(alert)
    reader = kit.client(roles="lector")

    assert reader.get("/api/v1/alerts").status_code == 403
    assert reader.get(f"/api/v1/alerts/{alert.alert_id}").status_code == 403
    response = reader.post(
        f"/api/v1/alerts/{alert.alert_id}/events",
        json={"event_id": str(uuid4()), "status": "confirmed", "note": NOTE},
    )
    assert response.status_code == 403
    assert statuses(kit, alert) == ["open"]


def test_el_revisor_sin_rol_de_analista_recibe_403(
    make_kit: Callable[..., Kit],
) -> None:
    kit = make_kit(make_alert())

    assert kit.client(roles="revisor").get("/api/v1/alerts").status_code == 403


def test_los_datos_sinteticos_sirven_para_el_portal() -> None:
    app = local_app("analista")
    client = TestClient(app)

    rows = client.get("/api/v1/alerts").json()
    by_status = {r["status"] for r in rows}
    detail = client.get(f"/api/v1/alerts/{rows[0]['alert_id']}").json()

    assert by_status == {"open", "confirmed", "dismissed"}
    assert len(detail["series"]) == 24
    assert any(r["boost"] and r["boost"]["active"] for r in rows)
