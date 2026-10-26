"""``/api/v1/reviews`` y ``/api/v1/explanations`` en memoria."""

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from api_backend.online import FakeOnlineClient
from api_backend.sections.explanations.repository import (
    InMemoryExplanationsRepository,
)
from api_backend.sections.reviews.filters import months_back, resolve_window
from api_backend.sections.reviews.repository import (
    BigQueryReviewsRepository,
    InMemoryReviewsRepository,
    VectorHit,
)
from api_backend.sections.reviews.sample import sample_repository
from api_backend.sections.reviews.schemas import ReviewRow
from api_backend.settings import ApiSettings
from api_backend.testing import local_app
from fastapi.testclient import TestClient
from voc_common.text_utils import text_key

TODAY = datetime.now(UTC).date()
ROUTES = (
    ("GET", "/api/v1/reviews"),
    ("GET", "/api/v1/reviews/facets"),
    ("GET", "/api/v1/reviews/BBVA/x"),
    ("POST", "/api/v1/reviews/search"),
    ("GET", f"/api/v1/explanations/{'a' * 64}"),
    ("POST", f"/api/v1/explanations/{'a' * 64}"),
)


def client(roles: str = "analista") -> tuple[TestClient, Any]:
    app = local_app(roles)
    return TestClient(app), app


@pytest.mark.parametrize("roles", ["lector", "revisor"])
@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_lector_y_revisor_reciben_403(
    roles: str, method: str, path: str
) -> None:
    c, _ = client(roles)

    response = c.request(method, path, json={})

    assert response.status_code == 403


def test_el_administrador_incluye_al_analista() -> None:
    c, _ = client("administrador")

    assert c.get("/api/v1/reviews").status_code == 200


# -- ventana ---------------------------------------------------------------


def test_la_ventana_recorta_el_rango_y_lo_dice() -> None:
    start, end, window = resolve_window(
        date(2026, 10, 26), 12, date(2024, 1, 1), None
    )

    assert start == date(2025, 10, 1) and end == date(2026, 10, 26)
    assert window.clipped is True and window.months == 12


def test_sin_fechas_la_ventana_por_defecto_no_cuenta_como_recorte() -> None:
    _, _, window = resolve_window(date(2026, 10, 26), 12, None, None)

    assert window.clipped is False and window.date_from == date(2025, 10, 1)


def test_months_back_cruza_el_año() -> None:
    assert months_back(date(2026, 2, 10), 3) == date(2025, 11, 1)
    assert months_back(date(2026, 10, 26), 12) == date(2025, 10, 1)


def test_la_api_informa_el_recorte() -> None:
    c, _ = client()

    page = c.get("/api/v1/reviews", params={"date_from": "2020-01-01"}).json()

    assert page["window_applied"]["clipped"] is True
    assert page["window_applied"]["months"] == 12
    assert all(
        r["fecha"] >= page["window_applied"]["date_from"] for r in page["rows"]
    )


def test_un_rango_invertido_es_422() -> None:
    c, _ = client()

    response = c.get(
        "/api/v1/reviews",
        params={"date_from": "2026-05-01", "date_to": "2026-04-01"},
    )

    assert response.status_code == 422


# -- tabla y facets --------------------------------------------------------


def test_los_filtros_se_combinan() -> None:
    c, _ = client()

    page = c.get(
        "/api/v1/reviews",
        params={
            "banks": ["BBVA", "AZTECA"],
            "sentiment": "NEG",
            "stars": [1, 2],
            "page_size": 200,
        },
    ).json()

    assert page["total"] > 0
    assert {r["bank_id"] for r in page["rows"]} <= {"BBVA", "AZTECA"}
    assert {r["sentiment"] for r in page["rows"]} == {"NEG"}
    assert {r["estrellas"] for r in page["rows"]} <= {1, 2}


def test_familia_marca_topico_y_hitl() -> None:
    c, _ = client()

    by_family = c.get(
        "/api/v1/reviews", params={"families": "AC", "page_size": 200}
    ).json()
    flagged = c.get(
        "/api/v1/reviews", params={"flag_update": True, "page_size": 200}
    ).json()
    topic = c.get(
        "/api/v1/reviews", params={"topic_id": 2, "page_size": 200}
    ).json()
    reviewed = c.get(
        "/api/v1/reviews", params={"hitl_reviewed": True, "page_size": 200}
    ).json()

    assert by_family["total"] and all(
        "AC" in r["families"] for r in by_family["rows"]
    )
    assert flagged["total"] and all(r["flag_update"] for r in flagged["rows"])
    assert topic["total"] and all(
        2 in [t["topic_id"] for t in r["topics"]] for r in topic["rows"]
    )
    assert reviewed["total"] and all(
        r["hitl_reviewed"] for r in reviewed["rows"]
    )


def test_paginacion_y_orden() -> None:
    c, _ = client()

    first = c.get("/api/v1/reviews", params={"page_size": 10}).json()
    second = c.get(
        "/api/v1/reviews", params={"page_size": 10, "page": 2}
    ).json()
    by_stars = c.get(
        "/api/v1/reviews", params={"sort": "estrellas_asc", "page_size": 5}
    ).json()
    by_confidence = c.get(
        "/api/v1/reviews", params={"sort": "confidence_asc", "page_size": 20}
    ).json()

    assert len(first["rows"]) == 10 and first["total"] == second["total"]
    assert not {r["id_resena"] for r in first["rows"]} & {
        r["id_resena"] for r in second["rows"]
    }
    dates = [r["fecha"] for r in first["rows"]]
    assert dates == sorted(dates, reverse=True)
    assert [r["estrellas"] for r in by_stars["rows"]] == [1] * 5
    conf = [r["confidence"] for r in by_confidence["rows"]]
    assert conf == sorted(conf)


def test_el_tamano_de_pagina_tiene_tope() -> None:
    c, _ = client()

    assert (
        c.get("/api/v1/reviews", params={"page_size": 201}).status_code == 422
    )
    assert c.get("/api/v1/reviews", params={"page": 0}).status_code == 422


def test_los_facets_responden_a_los_filtros_y_no_traen_texto() -> None:
    c, _ = client()
    all_rows = c.get("/api/v1/reviews/facets").json()
    neg = c.get("/api/v1/reviews/facets", params={"sentiment": "NEG"}).json()

    assert neg["total"] < all_rows["total"]
    assert {f["key"] for f in neg["by_sentiment"]} == {"NEG"}
    assert sum(f["n"] for f in neg["by_bank"]) == neg["total"]
    months = [f["key"] for f in all_rows["by_month"]]
    assert months == sorted(months)
    assert len(all_rows["by_topic"]) <= 20
    assert {f["label"] for f in all_rows["by_topic"]} >= {"Código de acceso"}
    # Ningún texto de reseña en los agregados.
    body = json.dumps(all_rows)
    assert not any(
        t in body for t in ("No llega el código", "Excelente atención")
    )


def test_facets_y_tabla_cuentan_lo_mismo() -> None:
    c, _ = client()
    params = {"banks": "NUBANK", "stars": 5}

    facets = c.get("/api/v1/reviews/facets", params=params).json()
    page = c.get("/api/v1/reviews", params=params).json()

    assert facets["total"] == page["total"] > 0


# -- ficha -----------------------------------------------------------------


def test_la_ficha_trae_hitl_sin_revisor_y_la_explicacion_disponible() -> None:
    c, app = client()
    reviewed = c.get(
        "/api/v1/reviews", params={"hitl_reviewed": True, "page_size": 1}
    ).json()["rows"][0]

    detail = c.get(
        f"/api/v1/reviews/{reviewed['bank_id']}/{reviewed['id_resena']}"
    ).json()

    assert detail["row"]["text"] == reviewed["text"]
    assert detail["aspects_prompt_version"] == "aspects_v2_1"
    assert detail["explanation"] is None
    assert detail["hitl_reviews"][0]["outcome"] == "confirmed"
    assert "reviewer" not in json.dumps(detail["hitl_reviews"]).lower()


def test_ficha_de_una_reseña_que_no_existe_es_404() -> None:
    c, _ = client()

    assert c.get("/api/v1/reviews/BBVA/no-existe").status_code == 404
    assert c.get("/api/v1/reviews/OTRO/x").status_code == 422


# -- búsqueda --------------------------------------------------------------


def test_la_busqueda_deduplica_por_texto_y_banco_y_ordena_por_distancia() -> (
    None
):
    c, _ = client()

    out = c.post(
        "/api/v1/reviews/search",
        json={"query": "Después de actualizar ya no abre.", "k": 10},
    ).json()

    hits = out["hits"]
    assert out["embedding_model"] == "sintetico-minilm"
    assert out["months_searched"] == 12
    assert out["bytes_billed"] > 0
    assert hits[0]["distance"] == pytest.approx(0, abs=1e-9)
    assert hits[0]["example"]["text"] == "Después de actualizar ya no abre."
    distances = [h["distance"] for h in hits]
    assert distances == sorted(distances)
    keys = [(h["text_key"], h["bank_id"]) for h in hits]
    assert len(keys) == len(set(keys))
    assert (
        hits[0]["n_reviews"] > 1
    )  # varias reseñas con ese texto en la ventana


def test_la_busqueda_respeta_bancos_k_y_meses() -> None:
    c, _ = client()
    body = {"query": "no abre la app", "banks": ["BBVA"], "k": 3, "months": 3}

    out = c.post("/api/v1/reviews/search", json=body).json()

    assert len(out["hits"]) <= 3
    assert {h["bank_id"] for h in out["hits"]} == {"BBVA"}
    assert out["months_searched"] == 3
    floor = months_back(TODAY, 3).isoformat()
    assert all(h["example"]["fecha"] >= floor for h in out["hits"])


@pytest.mark.parametrize(
    "body",
    [
        {"query": "ab"},
        {"query": "x" * 301},
        {"query": "no abre", "k": 51},
        {"query": "no abre", "months": 13},
        {"query": "no abre", "banks": ["OTRO"]},
    ],
)
def test_la_busqueda_valida_la_consulta(body: dict[str, Any]) -> None:
    c, _ = client()

    assert c.post("/api/v1/reviews/search", json=body).status_code == 422


def test_la_consulta_no_aparece_en_los_registros(
    capsys: pytest.CaptureFixture[str],
) -> None:
    c, _ = client()
    secret = "consulta-secreta-del-analista"  # noqa: S105

    c.post("/api/v1/reviews/search", json={"query": secret})
    c.post(
        "/api/v1/reviews/search", json={"query": secret, "months": 99}
    )  # también el error

    out = capsys.readouterr()
    assert secret not in out.out + out.err
    assert "/api/v1/reviews/search" in out.out


def test_la_busqueda_manda_la_consulta_al_servicio_en_linea() -> None:
    c, app = client()
    online = FakeOnlineClient()
    app.state.online_client = online

    c.post("/api/v1/reviews/search", json={"query": "no llega el código"})

    assert online.embedded == ["no llega el código"]


# -- explicaciones ---------------------------------------------------------


def one_review() -> tuple[ReviewRow, InMemoryReviewsRepository]:
    repo = sample_repository()
    return repo.reviews[0].row, repo


def explain_app() -> tuple[TestClient, Any, ReviewRow, FakeOnlineClient]:
    row, _ = one_review()
    c, app = client()
    online = FakeOnlineClient()
    app.state.online_client = online
    return c, app, row, online


def test_calcular_guarda_on_demand_y_no_recalcula() -> None:
    c, app, row, online = explain_app()
    url = f"/api/v1/explanations/{row.text_key}"
    body = {"bank_id": row.bank_id, "id_resena": row.id_resena}

    first = c.post(url, json=body)
    again = c.post(url, json=body)

    assert first.status_code == 200
    out = first.json()
    assert out["method"] == "occlusion_v2" and out["source"] == "on_demand"
    assert out["model_version"] == "sintetico_v1"
    assert out["attributions"][0]["d_neg"] is not None
    assert again.json() == out
    assert len(online.explained) == 1  # la segunda salió de lo guardado
    repo: InMemoryExplanationsRepository = app.state.explanations_repository
    assert [e.source.value for e in repo.saved] == ["on_demand"]
    assert online.explained[0][0] == row.text  # el texto actual del TDS


def test_calcular_verifica_que_el_text_key_sea_el_actual() -> None:
    c, app, row, online = explain_app()
    body = {"bank_id": row.bank_id, "id_resena": row.id_resena}

    stale = c.post(f"/api/v1/explanations/{'b' * 64}", json=body)
    repo: InMemoryExplanationsRepository = c.app.state.explanations_repository  # type: ignore[attr-defined]
    repo.texts[(row.bank_id, row.id_resena)] = "Texto editado después"
    edited = c.post(f"/api/v1/explanations/{row.text_key}", json=body)

    assert stale.status_code == 409 and edited.status_code == 409
    assert online.explained == []


def test_calcular_una_reseña_inexistente_es_404() -> None:
    c, _, row, _ = explain_app()

    response = c.post(
        f"/api/v1/explanations/{row.text_key}",
        json={"bank_id": "BBVA", "id_resena": "no-existe"},
    )

    assert response.status_code == 404


def test_consultar_la_explicacion_guardada_y_el_404() -> None:
    c, app, row, _ = explain_app()
    url = f"/api/v1/explanations/{row.text_key}"
    assert c.get(url).status_code == 404

    c.post(url, json={"bank_id": row.bank_id, "id_resena": row.id_resena})

    out = c.get(url, params={"model_version": "sintetico_v1"}).json()
    assert out["source"] == "on_demand"
    assert c.get(url, params={"model_version": "otro"}).status_code == 404


def test_si_el_servicio_en_linea_falla_es_502_y_no_se_guarda() -> None:
    from api_backend.errors import ApiError, ErrorCode

    class Down(FakeOnlineClient):
        def explain(self, text: str, model_version: str) -> Any:
            raise ApiError(ErrorCode.UPSTREAM, "no respondió")

    c, app, row, _ = explain_app()
    app.state.online_client = Down()

    response = c.post(
        f"/api/v1/explanations/{row.text_key}",
        json={"bank_id": row.bank_id, "id_resena": row.id_resena},
    )

    assert response.status_code == 502
    assert app.state.explanations_repository.saved == []


def test_la_ficha_ve_la_explicacion_guardada() -> None:
    c, app, row, _ = explain_app()
    c.post(
        f"/api/v1/explanations/{row.text_key}",
        json={"bank_id": row.bank_id, "id_resena": row.id_resena},
    )
    # El repositorio de reseñas conoce las explicaciones por text_key.
    stored = app.state.explanations_repository.saved[0]
    from api_backend.sections.reviews.schemas import ExplanationRef

    reviews = (
        app.state.reviews_repository
        if hasattr(app.state, "reviews_repository")
        else None
    )
    c.get("/api/v1/reviews")  # crea el repositorio de reseñas
    reviews = app.state.reviews_repository
    reviews.explanations[row.text_key] = ExplanationRef(
        method=stored.method,
        model_version=stored.model_version,
        source=stored.source.value,
    )

    detail = c.get(f"/api/v1/reviews/{row.bank_id}/{row.id_resena}").json()

    assert detail["explanation"] == {
        "method": "occlusion_v2",
        "model_version": "sintetico_v1",
        "source": "on_demand",
    }


# -- SQL -------------------------------------------------------------------


class RecordingReader:
    def __init__(
        self, rows: dict[str, list[dict[str, Any]]] | None = None
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []
        self.answers = rows or {}

    def rows(self, sql: str, params: Any, *, name: str = "q", **_: Any) -> Any:
        self.calls.append((sql, {p.name: p.value for p in params}, name))
        return self.answers.get(name, [])


def bq_repo(reader: RecordingReader) -> BigQueryReviewsRepository:
    settings = ApiSettings.model_validate(
        {
            "environment": "local",
            "portal_auth_mode": "local",
            "portal_local_user": "x@example.com",
            "gcp_project_id": "p",
            "user_hash_salt": "s" * 16,
        }
    )
    return BigQueryReviewsRepository(reader, settings)  # type: ignore[arg-type]


def test_el_sql_de_la_tabla_poda_particiones_y_parametriza_todo() -> None:
    from api_backend.sections.reviews.filters import ReviewFilters

    reader = RecordingReader({"reviews_count": [{"total": 0}]})
    repo = bq_repo(reader)
    f = ReviewFilters(
        banks=("BBVA",),
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        sentiment=("NEG",),
        families=("AC",),
        topic_id=3,
        hitl_reviewed=True,
        version="9.1.0",
    )

    repo.page(f, "fecha_desc", 1, 50)

    sql, params, _ = reader.calls[0]
    assert "p.fecha >= @from_ts" in sql and "p.fecha < @to_ts" in sql
    assert "DATE(p.fecha)" not in sql
    assert "fecha >= @from_ts AND fecha < @to_ts" in sql  # aspectos y tópicos
    assert "LIMIT @size OFFSET @offset" in sql
    assert "BBVA" not in sql and "9.1.0" not in sql  # solo parámetros
    assert params["banks"] == ["BBVA"] and params["version"] == "9.1.0"
    assert "sanitized_reviews_tds" not in sql  # el texto va en otra consulta


def test_el_texto_se_pide_solo_de_la_pagina_con_la_fecha_acotada() -> None:
    from api_backend.sections.reviews.filters import ReviewFilters

    when = datetime(2026, 1, 15, tzinfo=UTC)
    row = {
        "id_resena": "r1",
        "bank_id": "BBVA",
        "text_key": text_key("hola"),
        "fecha": when,
        "version_app": None,
        "estrellas": 1,
        "sentiment": "NEG",
        "p_neg": 0.9,
        "p_neu": 0.05,
        "p_pos": 0.05,
        "confidence": 0.9,
        "model_version": "m",
        "families": [],
        "flag_update": None,
        "flag_security": None,
        "prompt_version": None,
        "topic_ids": [],
        "hitl_reviewed": False,
        "total": 1,
    }
    reader = RecordingReader(
        {
            "reviews_page": [row],
            "reviews_texts": [
                {
                    "id_resena": "r1",
                    "bank_id": "BBVA",
                    "texto_sanitizado": "hola",
                    "text_key": text_key("hola"),
                },
                {
                    "id_resena": "r1",
                    "bank_id": "BBVA",
                    "texto_sanitizado": "otra versión",
                    "text_key": text_key("otra versión"),
                },
            ],
        }
    )
    f = ReviewFilters(
        banks=("BBVA",), date_from=date(2026, 1, 1), date_to=date(2026, 1, 31)
    )

    rows, total = bq_repo(reader).page(f, "fecha_desc", 1, 50)

    assert (
        total == 1 and rows[0].text == "hola"
    )  # solo el que coincide con el hash
    sql, params, _ = reader.calls[1]
    assert "fecha >= @first" in sql and params["ids"] == ["r1"]
    assert params["first"] == when


def test_el_sql_de_la_busqueda_poda_por_mes() -> None:
    reader = RecordingReader(
        {
            "reviews_search": [
                {"text_key": "a", "bank_id": "BBVA", "distance": 0.1},
                {"text_key": "a", "bank_id": "BBVA", "distance": 0.2},
                {"text_key": "b", "bank_id": "BBVA", "distance": 0.3},
            ]
        }
    )
    stats: dict[str, int] = {}

    hits = bq_repo(reader).vector_search(
        [0.1] * 384, ["BBVA"], date(2026, 1, 1), 2, stats
    )

    sql, params, _ = reader.calls[0]
    assert "VECTOR_SEARCH" in sql and "WHERE mes >= @from_month" in sql
    assert "top_k => @k_raw" in sql and params["k_raw"] == 6
    assert "COSINE" in sql
    assert hits == [VectorHit("a", "BBVA", 0.1), VectorHit("b", "BBVA", 0.3)]
