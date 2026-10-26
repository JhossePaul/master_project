"""Id de petición, registro y encabezados."""

import json

import pytest
from api_backend.middleware import request_id_from
from api_backend.testing import local_app
from fastapi.testclient import TestClient


def test_usa_el_id_de_cloud_trace() -> None:
    response = TestClient(local_app()).get(
        "/api/v1/me", headers={"X-Cloud-Trace-Context": "abc123/456;o=1"}
    )

    assert response.headers["x-request-id"] == "abc123"


def test_sin_cloud_trace_genera_un_uuid_distinto() -> None:
    client = TestClient(local_app())

    a = client.get("/healthz").headers["x-request-id"]
    b = client.get("/healthz").headers["x-request-id"]

    assert a != b
    assert len(a) == 32


def test_trace_vacio_cae_en_uuid() -> None:
    assert len(request_id_from([(b"x-cloud-trace-context", b"/1")])) == 32


def test_encabezados_de_seguridad_y_no_store_en_api() -> None:
    client = TestClient(local_app())

    api = client.get("/api/v1/me")
    health = client.get("/healthz")

    csp = api.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert api.headers["x-content-type-options"] == "nosniff"
    assert api.headers["referrer-policy"] == "no-referrer"
    assert api.headers["cache-control"] == "no-store"
    assert "cache-control" not in health.headers


def test_registro_json_sin_cuerpo_ni_correo(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TestClient(local_app()).get(
        "/api/v1/me", headers={"X-Cloud-Trace-Context": "t1/2"}
    )

    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["severity"] == "INFO"
    assert line["request_id"] == "t1"
    assert line["route"] == "/api/v1/me"
    assert line["status"] == 200
    assert line["latency_ms"] >= 0
    assert line["actor_hash"]
    assert "ana@example.com" not in json.dumps(line)


def test_eventos_que_no_son_http_pasan_de_largo() -> None:
    with TestClient(local_app()) as client:  # abre y cierra el lifespan
        assert client.get("/healthz").status_code == 200


def test_error_con_la_respuesta_ya_iniciada_se_propaga() -> None:
    from api_backend.middleware import RequestContextMiddleware
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/flujo")
    def flujo() -> StreamingResponse:
        def chunks():
            yield b"ok"
            raise RuntimeError("a medias")

        return StreamingResponse(chunks())

    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/flujo").status_code == 200
