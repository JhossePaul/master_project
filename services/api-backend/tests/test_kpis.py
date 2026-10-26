"""``/api/v1/kpis/*`` con repositorios en memoria y un lector falso."""

from datetime import UTC, date, datetime

import pytest
from api_backend.sections.kpis import service
from api_backend.sections.kpis.repository import (
    BigQueryKpisRepository,
    FamilyDrift,
    FamilyLevel,
    InMemoryKpisRepository,
    KpiRow,
    ThemeRow,
    TopicRow,
    VersionFamily,
    VersionTotals,
    sample_repository,
)
from api_backend.sections.kpis.schemas import DailyPoint, PromptChange
from api_backend.sections.kpis.stats import wilson
from api_backend.sections.kpis.versions import group_small, normalize
from api_backend.settings import ApiSettings
from api_backend.testing import local_app
from fastapi.testclient import TestClient
from voc_nlp.ppi import TEXT_SCORE, targets

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


def kpi(
    metric: str,
    bank: str,
    period: str,
    value: float = 0.2,
    method: str = "ppi",
) -> KpiRow:
    return KpiRow(
        metric=metric,
        bank_id=bank,
        period=period,
        method=method,
        estimate=value,
        ci_low=value - 0.01 if method == "ppi" else None,
        ci_high=value + 0.01 if method == "ppi" else None,
        n_gold=100 if method == "ppi" else None,
        n_unlabeled=1000,
        model_version="m1",
        gold_version="g1" if method == "ppi" else None,
    )


def client(repo: InMemoryKpisRepository, roles: str = "lector") -> TestClient:
    app = local_app(roles)
    app.state.kpis_repository = repo
    return TestClient(app)


def point(bank: str, dia: str, **kw: object) -> DailyPoint:
    base = dict(
        bank_id=bank,
        dia=date.fromisoformat(dia),
        filas=11,
        predichas=10,
        neg=3,
        neu=2,
        pos=5,
        no_predichas=1,
        gap_crudo=-0.5,
        texto_peor=2,
        texto_mejor=1,
        neg_4_5=1,
    )
    return DailyPoint(**{**base, **kw})  # type: ignore[arg-type]


# --- tarjetas -------------------------------------------------------------


def test_cards_toma_el_ultimo_mes_y_el_del_anio_anterior() -> None:
    repo = InMemoryKpisRepository(
        kpis=[
            kpi("neg", "BBVA", "2026-09", 0.2),
            kpi("gap_estrellas", "BBVA", "2026-09", -0.3),
            kpi("estrellas_POS_texto_NEG", "BBVA", "2026-09", 0.05),
            kpi("neg", "BBVA", "2025-09", 0.25),
            kpi("neg", "BBVA", "2026-09", 0.3, method="raw"),
        ],
        alerts={"BBVA": 2},
    )

    body = (
        client(repo).get("/api/v1/kpis/cards", params={"banks": "BBVA"}).json()
    )

    card = body[0]
    assert card["period"] == "2026-09"
    assert card["neg"]["estimate"] == 0.2 and card["neg"]["method"] == "ppi"
    assert card["quejas_4_5"]["estimate"] == 0.05
    assert card["previous_year"]["period"] == "2025-09"
    assert card["previous_year"]["neg"]["estimate"] == 0.25
    assert card["previous_year"]["gap_estrellas"] is None
    assert card["open_alerts"] == 2
    assert card["model_version"] == "m1" and card["gold_version"] == "g1"


def test_cards_cae_al_mes_anterior_si_a_un_banco_le_falta() -> None:
    repo = InMemoryKpisRepository(
        kpis=[
            kpi("neg", "BBVA", "2026-09"),
            kpi("neg", "AZTECA", "2026-08"),
        ]
    )

    cards = {
        c.bank_id: c
        for c in service.cards(repo, ["BBVA", "AZTECA", "NUBANK"], None)
    }

    assert cards["BBVA"].period == "2026-09"
    assert cards["AZTECA"].period == "2026-08"
    assert cards["NUBANK"].period is None and cards["NUBANK"].neg is None


def test_cards_con_period_usa_el_ultimo_mes_hasta_ese() -> None:
    repo = InMemoryKpisRepository(
        kpis=[kpi("neg", "BBVA", "2026-09"), kpi("neg", "BBVA", "2026-07")]
    )

    cards = service.cards(repo, ["BBVA"], "2026-08")

    assert cards[0].period == "2026-07"


def test_cards_rechaza_un_periodo_mal_escrito() -> None:
    response = client(InMemoryKpisRepository()).get(
        "/api/v1/kpis/cards", params={"period": "2026-13"}
    )

    assert response.status_code == 422


# --- serie diaria ---------------------------------------------------------


def test_daily_filtra_por_banco_y_rango() -> None:
    repo = InMemoryKpisRepository(
        daily_rows=[
            point("BBVA", "2026-10-01"),
            point("BBVA", "2026-10-02"),
            point("AZTECA", "2026-10-01"),
        ]
    )

    body = (
        client(repo)
        .get(
            "/api/v1/kpis/daily",
            params={
                "banks": "BBVA",
                "date_from": "2026-10-02",
                "date_to": "2026-10-05",
            },
        )
        .json()
    )

    assert [(r["bank_id"], r["dia"]) for r in body] == [("BBVA", "2026-10-02")]


def test_daily_sin_fechas_usa_90_dias_y_rechaza_rangos_absurdos() -> None:
    http = client(InMemoryKpisRepository())

    assert http.get("/api/v1/kpis/daily").status_code == 200
    bad = http.get(
        "/api/v1/kpis/daily",
        params={"date_from": "2026-10-05", "date_to": "2026-10-01"},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "invalid"


def test_el_signo_del_gap_crudo_coincide_con_voc_nlp() -> None:
    # La consulta resta 1, 3 o 5 según la clase: el puntaje de targets().
    stars = [1, 2, 3, 4, 5, 5, 1]
    text = ["POS", "NEG", "NEU", "NEG", "POS", "NEU", "NEG"]
    expected = targets(stars, text)["gap_estrellas"]

    manual = [s - TEXT_SCORE[t] for s, t in zip(stars, text, strict=True)]

    assert manual == list(expected)
    repo, reader = bq_repo([])
    repo.daily(["BBVA"], date(2026, 1, 1), date(2026, 1, 2))
    assert "WHEN 'NEG' THEN 1 WHEN 'NEU' THEN 3 ELSE 5 END" in reader.sql[0]
    assert "DATE(fecha) AS dia" in reader.sql[0]


# --- temas del día --------------------------------------------------------


def theme(tipo: str, rango: int, codigo: str, **kw: object) -> ThemeRow:
    base = dict(
        bank_id="BBVA",
        dia=date(2026, 10, 1),
        n_neg=40,
        tipo=tipo,
        rango=rango,
        codigo=codigo,
        nombre=f"Nombre {codigo}",
        filas=10,
        participacion=0.25,
        habitual=0.2,
        aspects_prompt_version="aspects_v2_1" if tipo == "familia" else None,
        topic_model_version="t1" if tipo == "topico" else None,
    )
    return ThemeRow(**{**base, **kw})  # type: ignore[arg-type]


def test_daily_topics_separa_familias_y_topicos_en_orden() -> None:
    repo = InMemoryKpisRepository(
        themes=[
            theme("familia", 2, "LE"),
            theme("familia", 1, "AC"),
            theme("topico", 1, "7"),
            theme("familia", 1, "AC", dia=date(2026, 10, 2)),
        ]
    )

    body = (
        client(repo)
        .get(
            "/api/v1/kpis/daily-topics",
            params={"bank": "BBVA", "day": "2026-10-01"},
        )
        .json()
    )

    assert body["n_neg"] == 40
    assert [f["codigo"] for f in body["familias"]] == ["AC", "LE"]
    assert [t["codigo"] for t in body["topicos"]] == ["7"]
    assert body["aspects_prompt_version"] == "aspects_v2_1"
    assert body["topic_model_version"] == "t1"
    assert body["familias"][0]["habitual"] == 0.2


def test_daily_topics_de_un_dia_sin_datos_va_vacio() -> None:
    body = (
        client(InMemoryKpisRepository())
        .get(
            "/api/v1/kpis/daily-topics",
            params={"bank": "BBVA", "day": "2026-10-01"},
        )
        .json()
    )

    assert (
        body["n_neg"] == 0 and body["familias"] == [] and body["topicos"] == []
    )


# --- mensuales y matriz ---------------------------------------------------


def test_monthly_junta_ppi_y_crudo() -> None:
    repo = InMemoryKpisRepository(
        kpis=[
            kpi("neg", "BBVA", "2026-09", 0.2),
            kpi("neg", "BBVA", "2026-09", 0.22, method="raw"),
            kpi("neg", "BBVA", "2026-08", 0.3, method="raw"),
            kpi("neg", "BBVA", "2026-05"),
        ]
    )
    http = client(repo)

    body = http.get(
        "/api/v1/kpis/monthly",
        params={
            "metrics": "neg",
            "date_from": "2026-06-01",
            "date_to": "2026-09-30",
        },
    ).json()

    assert [
        (r["period"], r["ppi"] is None, r["raw"] is None) for r in body
    ] == [
        ("2026-08", True, False),
        ("2026-09", False, False),
    ]
    assert (
        http.get("/api/v1/kpis/monthly", params={"metrics": "x"}).status_code
        == 422
    )


def test_matrix_toma_el_ultimo_mes_con_ppi() -> None:
    repo = InMemoryKpisRepository(
        kpis=[
            kpi("estrellas_NEG_texto_NEG", "BBVA", "2026-09", 0.1),
            kpi(
                "estrellas_NEG_texto_NEG", "BBVA", "2026-09", 0.12, method="raw"
            ),
            kpi("estrellas_POS_texto_NEG", "BBVA", "2026-08", 0.05),
        ]
    )
    http = client(repo)

    body = http.get("/api/v1/kpis/matrix").json()
    older = http.get("/api/v1/kpis/matrix", params={"period": "2026-08"}).json()

    assert len(body) == 1
    assert body[0]["stars_class"] == "NEG" and body[0]["text_class"] == "NEG"
    assert body[0]["raw"]["estimate"] == 0.12
    assert (
        older[0]["stars_class"] == "POS" and older[0]["ppi"]["estimate"] == 0.05
    )
    assert (
        http.get("/api/v1/kpis/matrix", params={"period": "2020-01"}).json()
        == []
    )
    assert service.matrix(InMemoryKpisRepository(), ["BBVA"], None) == []


# --- familias y tópicos ---------------------------------------------------


def test_families_une_nivel_z_y_cambios_de_prompt() -> None:
    repo = InMemoryKpisRepository(
        levels=[
            FamilyLevel("BBVA", "2026-09", "AC", 20, 100),
            FamilyLevel("BBVA", "2026-09", "u", 10, 100),
            FamilyLevel("BBVA", "2026-08", "AC", 5, 0),
        ],
        drift=[
            FamilyDrift("BBVA", "2026-09", "family_AC", 4.5, 4.0, True),
            FamilyDrift(
                "BBVA", "2026-09", "flag_update_share", 1.0, None, False
            ),
            FamilyDrift("BBVA", "2026-09", "otra_metrica", 9.0, 4.0, True),
        ],
        prompts=[PromptChange(prompt_version="p1", first_labeled_at=NOW)],
    )

    body = client(repo).get("/api/v1/kpis/families").json()

    by = {(r["period"], r["family"]): r for r in body["series"]}
    assert by[("2026-09", "AC")]["share"] == 0.2
    assert (
        by[("2026-09", "AC")]["z"] == 4.5
        and by[("2026-09", "AC")]["alert"] is True
    )
    assert by[("2026-09", "u")]["threshold"] is None
    assert (
        by[("2026-08", "AC")]["z"] is None
        and by[("2026-08", "AC")]["share"] == 0
    )
    assert body["prompt_changes"][0]["prompt_version"] == "p1"


def test_topics_calcula_la_participacion() -> None:
    repo = InMemoryKpisRepository(
        topics=[
            TopicRow(
                "BBVA",
                "2026-09",
                3,
                "Login",
                "ingenieria",
                ["AC"],
                25,
                100,
                "t1",
            ),
            TopicRow("BBVA", "2026-09", 4, "Vacío", "producto", [], 5, 0, "t1"),
        ]
    )

    body = client(repo).get("/api/v1/kpis/topics").json()

    assert [(t["topic_id"], t["share"]) for t in body] == [(3, 0.25), (4, 0.0)]
    assert body[0]["topic_model_version"] == "t1"


# --- versiones ------------------------------------------------------------


@pytest.mark.parametrize(
    ("bank", "raw", "expected"),
    [
        ("BANORTE", "7.0.9.45841", "7.0.9"),
        ("BBVA", "11.33.210429", "11.33"),
        ("BBVA", "25.60.10", "25.60.10"),
        ("BBVA", "10.90", "10.90"),
        ("NUBANK", "9.38.75-minApi28", "9.38.75"),
        ("AZTECA", "2.6.2 - BETA", None),
        ("AZTECA", "2.3.15", "2.3.15"),
        ("SANTANDER", "UNKNOWN", None),
        ("SANTANDER", "v5", None),
        ("SANTANDER", None, None),
        ("BANORTE", "7.0", None),
    ],
)
def test_normalize_reproduce_los_ejemplos_del_original(
    bank: str, raw: str | None, expected: str | None
) -> None:
    assert normalize(bank, raw) == expected


def test_group_small_manda_a_otras_las_de_menos_de_50_negativas() -> None:
    assert group_small({"1.0": 49, "2.0": 50}) == {"1.0": "OTRAS", "2.0": "2.0"}


def test_wilson_contra_valores_de_referencia() -> None:
    low, high = wilson(10, 100)
    assert (round(low, 4), round(high, 4)) == (0.0552, 0.1744)
    low, high = wilson(0, 50)
    assert round(low, 6) == 0.0 and round(high, 4) == 0.0713
    low, high = wilson(50, 50)
    assert round(high, 6) == 1.0 and round(low, 4) == 0.9287
    assert wilson(0, 0) == (0.0, 1.0)


def vt(version: str | None, filas: int, neg: int, u: int = 0) -> VersionTotals:
    return VersionTotals(
        version, filas, neg, u, date(2026, 1, 1), date(2026, 2, 1)
    )


def test_versions_agrupa_normaliza_y_reporta_la_cobertura() -> None:
    repo = InMemoryKpisRepository(
        totals={
            "BBVA": [
                vt("11.33.210429", 600, 200, 40),
                vt("11.33.210501", 400, 100, 20),  # misma release 11.33
                vt("10.90", 100, 10, 1),  # menos de 50: OTRAS
                vt("10.80", 50, 5, 1),  # también OTRAS
                vt("UNKNOWN", 150, 30),  # sin versión
                vt("2.6 BETA", 100, 20),
            ]
        },
        version_fams={
            "BBVA": [
                VersionFamily("11.33.210429", "FA", 90),
                VersionFamily("11.33.210501", "FA", 60),
                VersionFamily("11.33.210501", "AC", 30),
                VersionFamily("10.90", "FA", 5),
                VersionFamily("UNKNOWN", "FA", 7),
            ]
        },
    )

    body = (
        client(repo)
        .get("/api/v1/kpis/versions", params={"bank": "BBVA"})
        .json()
    )

    rows = {r["release"]: r for r in body["rows"]}
    assert set(rows) == {"11.33", "OTRAS"}
    assert body["rows"][-1]["release"] == "OTRAS"
    assert rows["11.33"]["filas"] == 1000 and rows["11.33"]["neg"] == 300
    assert rows["11.33"]["neg_share"] == 0.3
    assert rows["11.33"]["neg_ci_low"] < 0.3 < rows["11.33"]["neg_ci_high"]
    assert rows["11.33"]["u_share"] == pytest.approx(60 / 300)
    assert list(rows["11.33"]["families"]) == ["FA", "AC"]
    assert rows["11.33"]["families"]["FA"] == 0.5
    assert rows["OTRAS"]["filas"] == 150 and rows["OTRAS"]["neg"] == 15
    assert body["coverage"] == pytest.approx(1150 / 1400)
    assert body["median_neg_share"] is not None


def test_versions_de_un_banco_sin_datos() -> None:
    body = (
        client(InMemoryKpisRepository())
        .get("/api/v1/kpis/versions", params={"bank": "BBVA"})
        .json()
    )

    assert body["rows"] == [] and body["coverage"] == 0
    assert body["median_neg_share"] is None


def test_un_banco_desconocido_da_422() -> None:
    http = client(InMemoryKpisRepository())

    assert (
        http.get("/api/v1/kpis/versions", params={"bank": "X"}).status_code
        == 422
    )
    assert (
        http.get("/api/v1/kpis/cards", params={"banks": "X"}).status_code == 422
    )


# --- roles y datos de muestra ---------------------------------------------


def test_el_cockpit_exige_estar_en_el_mapa_de_roles() -> None:
    app = local_app("lector")
    app.state.kpis_repository = InMemoryKpisRepository()

    assert TestClient(app).get("/api/v1/kpis/cards").status_code == 200


def test_el_repositorio_de_muestra_sirve_todas_las_rutas() -> None:
    http = TestClient(local_app("lector"))
    for path, params in [
        ("cards", {}),
        ("daily", {}),
        ("monthly", {}),
        ("families", {}),
        ("topics", {}),
        ("matrix", {}),
        ("versions", {"bank": "BBVA"}),
        ("model-changes", {}),
    ]:
        response = http.get(f"/api/v1/kpis/{path}", params=params)
        assert response.status_code == 200, path
        assert response.json(), path
    cards = http.get("/api/v1/kpis/cards").json()
    assert len(cards) == 5 and all(c["previous_year"] for c in cards)
    sample = sample_repository(NOW)
    day = sample.daily_rows[-1].dia
    themes = http.get(
        "/api/v1/kpis/daily-topics", params={"bank": "BBVA", "day": str(day)}
    ).json()
    assert len(themes["familias"]) == 5 and len(themes["topicos"]) == 5


# --- BigQuery -------------------------------------------------------------


class FakeReader:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows_out = rows
        self.sql: list[str] = []
        self.params: list[object] = []

    def rows(self, sql: str, params: object, **_: object) -> list[dict]:
        self.sql.append(sql)
        self.params.append(params)
        return self.rows_out


def bq_repo(
    rows: list[dict[str, object]],
) -> tuple[BigQueryKpisRepository, FakeReader]:
    reader = FakeReader(rows)
    settings = ApiSettings.model_validate(
        {"gcp_project_id": "p", "bq_dataset_id": "d", "iap_audience": "/a"}
    )
    return BigQueryKpisRepository(reader, settings), reader  # type: ignore[arg-type]


def test_bigquery_kpis_convierte_filas_y_usa_la_ultima_corrida() -> None:
    row = {
        "metric": "neg",
        "bank_id": "BBVA",
        "period": "2026-09",
        "method": "ppi",
        "estimate": 0.2,
        "ci_low": 0.19,
        "ci_high": 0.21,
        "n_gold": 10,
        "n_unlabeled": 100,
        "model_version": "m1",
        "gold_version": "g1",
    }
    repo, reader = bq_repo([row])

    assert repo.kpi_rows(["neg"], ["BBVA"])[0].estimate == 0.2
    assert "`p.d.kpi_estimates`" in reader.sql[0]
    assert "ORDER BY computed_at DESC" in reader.sql[0]
    alerts, _ = bq_repo([{"bank_id": "BBVA", "n": 2}])
    assert alerts.open_alerts() == {"BBVA": 2}


def test_bigquery_serie_y_temas_del_dia() -> None:
    repo, reader = bq_repo([point("BBVA", "2026-10-01").model_dump()])
    assert (
        repo.daily(["BBVA"], date(2026, 10, 1), date(2026, 10, 2))[0].neg == 3
    )
    assert "`p.d.review_predictions_current`" in reader.sql[0]

    theme_row = {
        k: getattr(theme("familia", 1, "AC"), k)
        for k in theme("familia", 1, "AC").__dataclass_fields__
    }
    repo, reader = bq_repo([theme_row])
    assert repo.daily_themes("BBVA", date(2026, 10, 1))[0].codigo == "AC"
    assert "`p.d.daily_topic_labels`" in reader.sql[0]


def test_bigquery_familias_y_deriva() -> None:
    repo, reader = bq_repo(
        [
            {
                "bank_id": "BBVA",
                "period": "2026-09",
                "family": "AC",
                "neg_count": 2,
                "base": 9,
            }
        ]
    )
    assert repo.family_levels(["BBVA"])[0].base == 9
    assert "`p.d.review_aspects`" in reader.sql[0]
    assert "UNION ALL" in reader.sql[0]

    repo, reader = bq_repo(
        [
            {
                "bank_id": "BBVA",
                "period": "2026-09",
                "metric": "family_AC",
                "z": 1.0,
                "threshold": None,
                "alert": None,
            }
        ]
    )
    assert repo.family_drift(["BBVA"])[0].metric == "family_AC"
    assert "`p.d.drift_metrics`" in reader.sql[0]

    repo, _ = bq_repo([{"prompt_version": "p1", "first_labeled_at": NOW}])
    assert repo.prompt_changes()[0].prompt_version == "p1"


def test_bigquery_topicos_versiones_y_modelo() -> None:
    repo, reader = bq_repo(
        [
            {
                "bank_id": "BBVA",
                "period": "2026-09",
                "topic_id": 1,
                "nombre": "Login",
                "audience": "ingenieria",
                "families": ["AC"],
                "filas": 3,
                "base": 10,
                "topic_model_version": "t1",
            }
        ]
    )
    assert repo.topic_months(["BBVA"])[0].families == ["AC"]
    assert "`p.d.topic_model_current`" in reader.sql[0]
    assert "`p.d.curation_topics`" in reader.sql[0]

    repo, reader = bq_repo(
        [
            {
                "version_app": "1.0",
                "filas": 10,
                "neg": 2,
                "neg_u": 1,
                "first_seen": date(2026, 1, 1),
                "last_seen": date(2026, 1, 2),
            }
        ]
    )
    assert repo.version_totals("BBVA")[0].neg == 2
    repo, _ = bq_repo([{"version_app": "1.0", "family": "AC", "n": 3}])
    assert repo.version_families("BBVA")[0].n == 3

    repo, reader = bq_repo([{"model_version": "m1", "promoted_at": NOW}])
    assert repo.model_changes()[0].model_version == "m1"
    assert "`p.d.model_versions`" in reader.sql[0]
