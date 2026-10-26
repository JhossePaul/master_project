"""Cliente de ``voc-ml-online``: explicación y embedding bajo pedido.

Llama con un ID token de la cuenta de la API (``run.invoker`` solo para ella).
Ni el texto ni la consulta se registran.
"""

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

import requests
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as AuthRequest
from google.oauth2 import id_token
from voc_common.operations_v3 import TokenAttribution

from api_backend.errors import ApiError, ErrorCode

TIMEOUT_SECONDS = 90
EMBEDDING_SIZE = 384
FAKE_EMBEDDING_MODEL = "sintetico-minilm"


@dataclass(frozen=True)
class OnlineExplanation:
    model_version: str
    method: str
    attributions: list[TokenAttribution]
    p_neg: float
    p_neu: float
    p_pos: float


@dataclass(frozen=True)
class OnlineEmbedding:
    embedding_model: str
    embedding: list[float]


class OnlineClient(Protocol):
    def explain(self, text: str, model_version: str) -> OnlineExplanation: ...

    def embed(self, text: str) -> OnlineEmbedding: ...


class HttpOnlineClient:
    def __init__(self, base_url: str, session: Any | None = None) -> None:
        self._url = base_url.rstrip("/")
        self._session = session or requests.Session()

    def _post(self, path: str, body: dict[str, str]) -> dict[str, Any]:
        try:
            token = id_token.fetch_id_token(AuthRequest(), self._url)
            response = self._session.post(
                f"{self._url}{path}",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return dict(response.json())
        except (requests.RequestException, GoogleAuthError, ValueError) as exc:
            # Sin el cuerpo ni la respuesta: traen el texto.
            raise ApiError(
                ErrorCode.UPSTREAM,
                "El servicio de explicación no respondió; intenta de nuevo",
            ) from exc

    def explain(self, text: str, model_version: str) -> OnlineExplanation:
        data = self._post(
            "/explain", {"text": text, "model_version": model_version}
        )
        return OnlineExplanation(
            model_version=str(data["model_version"]),
            method=str(data["method"]),
            attributions=[
                TokenAttribution.model_validate(a) for a in data["attributions"]
            ],
            p_neg=float(data["p_neg"]),
            p_neu=float(data["p_neu"]),
            p_pos=float(data["p_pos"]),
        )

    def embed(self, text: str) -> OnlineEmbedding:
        data = self._post("/embed", {"text": text})
        return OnlineEmbedding(
            embedding_model=str(data["embedding_model"]),
            embedding=[float(x) for x in data["embedding"]],
        )


class FakeOnlineClient:
    """Doble de pruebas y de ``PORTAL_DATA=fixtures``: respuestas fijas."""

    def __init__(self) -> None:
        self.explained: list[tuple[str, str]] = []
        self.embedded: list[str] = []

    def explain(self, text: str, model_version: str) -> OnlineExplanation:
        self.explained.append((text, model_version))
        attributions = []
        position = 0
        for word in text.split():
            start = text.index(word, position)
            position = start + len(word)
            negative = word.lower().strip(".,") in {"no", "mal", "error"}
            attributions.append(
                TokenAttribution(
                    start=start,
                    end=position,
                    d_neg=0.3 if negative else -0.02,
                    d_neu=-0.1 if negative else 0.01,
                    d_pos=-0.2 if negative else 0.01,
                )
            )
        return OnlineExplanation(
            model_version=model_version,
            method="occlusion_v2",
            attributions=attributions,
            p_neg=0.7,
            p_neu=0.2,
            p_pos=0.1,
        )

    def embed(self, text: str) -> OnlineEmbedding:
        self.embedded.append(text)
        seed = hashlib.sha256(text.encode()).digest()
        values = [seed[i % len(seed)] / 255 for i in range(EMBEDDING_SIZE)]
        return OnlineEmbedding(FAKE_EMBEDDING_MODEL, values)


def build_online_client(online_url: str, portal_data: str) -> OnlineClient:
    if portal_data == "fixtures":
        return FakeOnlineClient()
    if not online_url:
        raise ApiError(
            ErrorCode.UPSTREAM, "El servicio de explicación no está configurado"
        )
    return HttpOnlineClient(online_url)
