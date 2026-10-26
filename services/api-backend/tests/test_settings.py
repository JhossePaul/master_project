"""Pruebas de la configuración de la API (sin red ni archivos .env)."""

import pytest
from api_backend.settings import ApiSettings, get_settings
from pydantic import ValidationError
from voc_common.config import DEV_USER_HASH_SALT

SALT = "s" * 16
LOCAL = {
    "environment": "local",
    "portal_auth_mode": "local",
    "portal_local_user": "ana@example.com",
    "portal_data": "fixtures",
}
IAP = {"iap_audience": "/projects/1/locations/us-central1/services/voc-api"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ENVIRONMENT",
        "GCP_PROJECT_ID",
        "GCP_REGION",
        "USER_HASH_SALT",
        "IAP_AUDIENCE",
        "PORTAL_AUTH_MODE",
        "PORTAL_LOCAL_USER",
        "PORTAL_LOCAL_ROLES",
        "PORTAL_DATA",
        "ML_ONLINE_URL",
        "BQ_MAX_BYTES_BILLED",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def make(**values: object) -> ApiSettings:
    return ApiSettings.model_validate(values)


def test_valores_por_defecto() -> None:
    settings = make(gcp_project_id="p", **IAP)

    assert settings.environment == "dev"
    assert settings.region == "us-central1"
    assert settings.bq_dataset_id == "bbva_voc_tds"
    assert settings.portal_roles_secret == "voc-portal-roles"  # noqa: S105
    assert settings.bq_max_bytes_billed == 2_000_000_000
    assert settings.cache_ttl_seconds == 600
    assert settings.review_window_months == 12
    assert settings.static_dir == "/app/static"
    assert settings.build_commit == "unknown"
    assert settings.docs_enabled is False


def test_modo_local_falla_fuera_de_environment_local() -> None:
    with pytest.raises(ValidationError, match="ENVIRONMENT=local"):
        make(**{**LOCAL, "environment": "dev"})


def test_modo_local_requiere_usuario() -> None:
    with pytest.raises(ValidationError, match="PORTAL_LOCAL_USER"):
        make(**{**LOCAL, "portal_local_user": " "})


def test_modo_local_valido_habilita_docs() -> None:
    settings = make(**LOCAL)

    assert settings.docs_enabled is True


def test_iap_requiere_audiencia() -> None:
    with pytest.raises(ValidationError, match="IAP_AUDIENCE"):
        make(gcp_project_id="p")


def test_bigquery_requiere_proyecto() -> None:
    with pytest.raises(ValidationError, match="GCP_PROJECT_ID"):
        make(**IAP)


def test_fixtures_no_requiere_proyecto() -> None:
    assert make(portal_data="fixtures", **IAP).gcp_project_id == ""


def test_sal_de_desarrollo_no_se_acepta_en_prod() -> None:
    with pytest.raises(ValidationError, match="producción"):
        make(environment="prod", gcp_project_id="p", **IAP)
    prod = make(
        environment="prod", gcp_project_id="p", user_hash_salt=SALT, **IAP
    )
    assert prod.user_hash_salt == SALT


def test_sal_de_desarrollo_se_acepta_fuera_de_prod() -> None:
    settings = make(gcp_project_id="p", **IAP)

    assert settings.user_hash_salt == DEV_USER_HASH_SALT


def test_sal_corta_se_rechaza() -> None:
    with pytest.raises(ValidationError, match="16 caracteres"):
        make(gcp_project_id="p", user_hash_salt="corta", **IAP)


def test_lee_variables_de_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("PORTAL_AUTH_MODE", "local")
    monkeypatch.setenv("PORTAL_LOCAL_USER", "ana@example.com")
    monkeypatch.setenv("PORTAL_LOCAL_ROLES", "lector, analista ,")
    monkeypatch.setenv("PORTAL_DATA", "fixtures")
    monkeypatch.setenv("GCP_REGION", "us-east1")
    monkeypatch.setenv("ML_ONLINE_URL", "https://online.example")
    monkeypatch.setenv("BQ_MAX_BYTES_BILLED", "1000")

    settings = get_settings()

    assert settings.portal_local_roles == ["lector", "analista"]
    assert settings.region == "us-east1"
    assert settings.online_service_url == "https://online.example"
    assert settings.bq_max_bytes_billed == 1000
    assert get_settings() is settings


@pytest.mark.parametrize(
    "field", ["bq_max_bytes_billed", "review_window_months"]
)
def test_limites_positivos(field: str) -> None:
    with pytest.raises(ValidationError):
        make(gcp_project_id="p", **{field: 0}, **IAP)
