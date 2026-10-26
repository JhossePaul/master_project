"""Archivos del portal y vuelta a ``index.html``."""

from pathlib import Path

import pytest
from api_backend.main import create_app
from api_backend.settings import ApiSettings
from fastapi.testclient import TestClient


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>portal</html>")
    (tmp_path / "assets" / "app-1a2b3c.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "secreto.txt").write_text("fuera de dist")
    return tmp_path


def client_for(static_dir: Path | str) -> TestClient:
    settings = ApiSettings.model_validate(
        {
            "environment": "local",
            "portal_auth_mode": "local",
            "portal_local_user": "ana@example.com",
            "portal_data": "fixtures",
            "static_dir": str(static_dir),
        }
    )
    return TestClient(create_app(settings))


@pytest.mark.parametrize("path", ["/", "/cockpit", "/hitl/sentimiento"])
def test_rutas_de_la_spa_devuelven_index(dist: Path, path: str) -> None:
    response = client_for(dist).get(path)

    assert response.status_code == 200
    assert response.text == "<html>portal</html>"
    assert response.headers["cache-control"] == "no-cache"


def test_assets_con_hash_son_inmutables(dist: Path) -> None:
    response = client_for(dist).get("/assets/app-1a2b3c.js")

    assert response.text == "console.log(1)"
    assert response.headers["cache-control"] == (
        "public, max-age=31536000, immutable"
    )


def test_otros_archivos_no_se_guardan_en_cache(dist: Path) -> None:
    response = client_for(dist).get("/favicon.svg")

    assert response.text == "<svg/>"
    assert response.headers["cache-control"] == "no-cache"


def test_api_inexistente_da_404_en_json_no_index(dist: Path) -> None:
    response = client_for(dist).get("/api/v1/nada")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.headers["cache-control"] == "no-store"


def test_no_sale_de_dist(dist: Path) -> None:
    response = client_for(dist).get("/..%2Fsecreto.txt")

    assert "fuera de dist" not in response.text


def test_sin_static_dir_la_raiz_da_404(tmp_path: Path) -> None:
    response = client_for(tmp_path / "no-existe").get("/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_encabezados_de_seguridad_tambien_en_el_portal(dist: Path) -> None:
    response = client_for(dist).get("/cockpit")

    assert (
        "frame-ancestors 'none'" in response.headers["content-security-policy"]
    )
