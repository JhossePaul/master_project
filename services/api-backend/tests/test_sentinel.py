"""Ninguna ruta de rol lector entrega texto de reseñas.

Recorre ``ROUTE_ROLES`` y llama a cada ``GET`` de rol lector contra los datos
sintéticos, que llevan el centinela en reseñas, comentarios y notas. Una ruta
de lector sin entrada en ``SAMPLE_PARAMS`` hace fallar la prueba: cada paso la
extiende al agregar sus rutas.
"""

from api_backend.auth.deps import ROUTE_ROLES
from api_backend.auth.roles import Role
from api_backend.fixtures import SENTINEL, load_sample
from api_backend.main import create_app  # noqa: F401  # registra los routers
from api_backend.testing import local_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

# (método, ruta registrada) -> parámetros de consulta con los que se llama.
SAMPLE_PARAMS: dict[tuple[str, str], dict[str, str]] = {
    ("GET", "/api/v1/me"): {},
    ("GET", "/api/v1/landing"): {},
}


def reader_get_routes() -> list[tuple[str, str]]:
    return sorted(
        key
        for key, role in ROUTE_ROLES.items()
        if role is Role.LECTOR and key[0] == "GET"
    )


def leaks_sentinel(client: TestClient, route: tuple[str, str]) -> bool:
    _, path = route
    response = client.get(path, params=SAMPLE_PARAMS[route])
    return response.status_code == 200 and SENTINEL in response.text


def test_los_datos_sinteticos_traen_el_centinela() -> None:
    texts = [str(r["texto_sanitizado"]) for r in load_sample("reviews")]
    notes = [str(n["comment"]) for n in load_sample("reviewer_notes")]

    assert SENTINEL in texts and SENTINEL in notes


def test_toda_ruta_de_lector_tiene_parametros_de_muestra() -> None:
    missing = [r for r in reader_get_routes() if r not in SAMPLE_PARAMS]

    assert missing == [], f"agrega {missing} a SAMPLE_PARAMS"


def test_ninguna_ruta_de_lector_entrega_el_centinela() -> None:
    client = TestClient(local_app(roles="lector"))
    routes = reader_get_routes()

    assert routes, "ROUTE_ROLES no tiene rutas de lector"
    assert [r for r in routes if leaks_sentinel(client, r)] == []


def test_la_prueba_detecta_una_ruta_que_filtra() -> None:
    app = FastAPI()

    @app.get("/api/v1/filtra")
    def filtra() -> dict[str, str]:
        return {"texto": SENTINEL}

    route = ("GET", "/api/v1/filtra")
    SAMPLE_PARAMS[route] = {}
    try:
        assert leaks_sentinel(TestClient(app), route)
    finally:
        del SAMPLE_PARAMS[route]
