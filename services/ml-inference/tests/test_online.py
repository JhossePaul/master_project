"""``voc-ml-online`` con modelos falsos: contratos, tope y carga perezosa."""

from fastapi.testclient import TestClient
from ml_inference.online import OnlineLoaders, OnlineModels, create_app
from voc_common.operations_v3 import TokenAttribution


class FakeExplainer:
    def __init__(self, version: str) -> None:
        self.version = version
        self.calls: list[tuple[str, float]] = []

    def explain(
        self, text: str, temperature: float
    ) -> tuple[list[TokenAttribution], list[float]]:
        self.calls.append((text, temperature))
        return (
            [
                TokenAttribution(
                    start=0, end=2, d_neg=0.4, d_neu=-0.1, d_pos=-0.3
                )
            ],
            [0.7, 0.2, 0.1],
        )


class FakeEmbedder:
    def embed(self, text: str) -> list[float]:
        return [0.5] * 384


class Counters:
    def __init__(self) -> None:
        self.sentiment: list[str] = []
        self.embedders = 0
        self.explainers: dict[str, FakeExplainer] = {}


def build() -> tuple[TestClient, Counters]:
    counters = Counters()

    def sentiment(version: str) -> FakeExplainer:
        counters.sentiment.append(version)
        counters.explainers[version] = FakeExplainer(version)
        return counters.explainers[version]

    def embedder() -> tuple[str, FakeEmbedder]:
        counters.embedders += 1
        return "minilm-test", FakeEmbedder()

    loaders = OnlineLoaders(
        sentiment=sentiment,
        temperature=lambda version: 1.5 if version == "m1" else 2.0,
        embedder=embedder,
    )
    return TestClient(create_app(OnlineModels(loaders))), counters


def test_nada_se_carga_hasta_usarse() -> None:
    client, counters = build()

    assert client.get("/healthz").json() == {"status": "ok", "loaded": []}
    assert counters.sentiment == [] and counters.embedders == 0


def test_explain_devuelve_el_contrato_con_la_temperatura_de_la_version() -> (
    None
):
    client, counters = build()

    out = client.post(
        "/explain", json={"text": "la app no abre", "model_version": "m1"}
    ).json()

    assert out == {
        "model_version": "m1",
        "method": "occlusion_v2",
        "attributions": [
            {
                "start": 0,
                "end": 2,
                "weight": None,
                "d_neg": 0.4,
                "d_neu": -0.1,
                "d_pos": -0.3,
            }
        ],
        "p_neg": 0.7,
        "p_neu": 0.2,
        "p_pos": 0.1,
    }
    assert counters.explainers["m1"].calls == [("la app no abre", 1.5)]


def test_el_modelo_se_carga_una_vez_y_solo_hay_uno_en_memoria() -> None:
    client, counters = build()
    body = {"text": "hola", "model_version": "m1"}

    client.post("/explain", json=body)
    client.post("/explain", json=body)
    assert counters.sentiment == ["m1"]

    client.post("/explain", json={**body, "model_version": "m2"})
    assert counters.sentiment == ["m1", "m2"]
    assert client.get("/healthz").json()["loaded"] == ["sentiment:m2"]


def test_explain_tiene_tope_de_128_palabras() -> None:
    client, counters = build()
    ok = " ".join(["palabra"] * 128)
    too_long = " ".join(["palabra"] * 129)

    assert (
        client.post(
            "/explain", json={"text": ok, "model_version": "m1"}
        ).status_code
        == 200
    )
    response = client.post(
        "/explain", json={"text": too_long, "model_version": "m1"}
    )

    assert response.status_code == 422
    assert counters.explainers["m1"].calls == [(ok, 1.5)]


def test_explain_exige_texto_y_version() -> None:
    client, _ = build()

    assert (
        client.post(
            "/explain", json={"text": "", "model_version": "m1"}
        ).status_code
        == 422
    )
    assert client.post("/explain", json={"text": "hola"}).status_code == 422


def test_embed_devuelve_384_valores_y_el_nombre_del_modelo() -> None:
    client, counters = build()

    out = client.post("/embed", json={"text": "no llega el código"}).json()
    client.post("/embed", json={"text": "otra"})

    assert out["embedding_model"] == "minilm-test"
    assert len(out["embedding"]) == 384
    assert counters.embedders == 1
    assert client.get("/healthz").json()["loaded"] == ["embedder:minilm-test"]


def test_embed_rechaza_consultas_enormes() -> None:
    client, _ = build()

    assert client.post("/embed", json={"text": "x" * 1001}).status_code == 422
