"""Formato de error con ``request_id`` y códigos."""

import pytest
from api_backend.errors import (
    STATUS_BY_CODE,
    ApiError,
    ErrorCode,
    error_body,
    install_error_handlers,
)
from api_backend.middleware import RequestContextMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    @app.get("/conflicto")
    def conflicto() -> None:
        raise ApiError(ErrorCode.CONFLICT, "La política cambió")

    @app.get("/caro")
    def caro() -> None:
        raise ApiError(ErrorCode.QUERY_TOO_EXPENSIVE, "Muy cara")

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secreto interno")

    @app.get("/numero")
    def numero(n: int) -> dict[str, int]:
        return {"n": n}

    return app


def test_codigos_y_estados() -> None:
    assert STATUS_BY_CODE[ErrorCode.UNAUTHENTICATED] == 401
    assert STATUS_BY_CODE[ErrorCode.FORBIDDEN] == 403
    assert STATUS_BY_CODE[ErrorCode.NOT_FOUND] == 404
    assert STATUS_BY_CODE[ErrorCode.CONFLICT] == 409
    assert STATUS_BY_CODE[ErrorCode.INVALID] == 422
    assert STATUS_BY_CODE[ErrorCode.QUERY_TOO_EXPENSIVE] == 503
    assert STATUS_BY_CODE[ErrorCode.UPSTREAM] == 502
    assert set(STATUS_BY_CODE) == set(ErrorCode)


def test_error_de_api_lleva_codigo_mensaje_y_request_id() -> None:
    response = TestClient(make_app()).get("/conflicto")

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "conflict",
            "message": "La política cambió",
            "request_id": response.headers["x-request-id"],
        }
    }
    assert TestClient(make_app()).get("/caro").status_code == 503


def test_ruta_inexistente_da_404_en_json() -> None:
    response = TestClient(make_app()).get("/nada")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_metodo_no_permitido_conserva_su_estado() -> None:
    response = TestClient(make_app()).post("/conflicto")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "invalid"


def test_validacion_da_422_con_los_campos() -> None:
    response = TestClient(make_app()).get("/numero", params={"n": "x"})

    error = response.json()["error"]
    assert response.status_code == 422
    assert error["code"] == "invalid"
    assert "n" in error["message"]


def test_error_no_controlado_da_500_sin_detalles() -> None:
    client = TestClient(make_app(), raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal"
    assert "secreto" not in response.text
    assert response.headers["x-request-id"]


def test_error_body_directo() -> None:
    assert (
        error_body(ErrorCode.FORBIDDEN, "no", "r1")["error"]["request_id"]
        == "r1"
    )


@pytest.mark.parametrize("path", ["/conflicto", "/nada"])
def test_los_errores_llevan_encabezados_de_seguridad(path: str) -> None:
    response = TestClient(make_app()).get(path)

    assert response.headers["x-content-type-options"] == "nosniff"
