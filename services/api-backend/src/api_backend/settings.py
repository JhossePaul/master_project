"""Configuración de la API y el portal (variables de entorno, sin prefijo)."""

from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from voc_common.config import DEV_USER_HASH_SALT

MIN_SALT_LENGTH = 16

Environment = Literal["local", "dev", "prod"]
AuthMode = Literal["iap", "local"]
DataSource = Literal["bigquery", "fixtures"]


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        populate_by_name=True,
        allow_inf_nan=False,
        frozen=True,
    )

    environment: Environment = "dev"
    gcp_project_id: str = ""
    region: str = Field(default="us-central1", validation_alias="GCP_REGION")
    bq_dataset_id: str = "bbva_voc_tds"
    user_hash_salt: str = DEV_USER_HASH_SALT

    iap_audience: str = ""
    portal_auth_mode: AuthMode = "iap"
    portal_local_user: str = ""
    # Se acepta "lector,analista"; los valida el cargador de roles.
    portal_local_roles: Annotated[list[str], NoDecode] = []
    # Nombre del secreto con el mapa de roles, no su contenido.
    portal_roles_secret: str = "voc-portal-roles"  # noqa: S105  # nosec B105
    portal_data: DataSource = "bigquery"

    bq_max_bytes_billed: int = Field(default=2_000_000_000, gt=0)
    cache_ttl_seconds: int = Field(default=600, ge=0)
    review_window_months: int = Field(default=12, gt=0)

    online_service_url: str = Field(
        default="",
        validation_alias=AliasChoices("ML_ONLINE_URL", "online_service_url"),
    )
    dlp_inspect_template: str = ""
    dlp_deidentify_template: str = ""

    # Guías de revisión: ``<guidelines_dir>/<content_uri>`` (copia la imagen).
    guidelines_dir: str = "/app/guidelines"
    static_dir: str = "/app/static"
    build_commit: str = "unknown"

    @field_validator("portal_local_roles", mode="before")
    @classmethod
    def _split_roles(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("user_hash_salt")
    @classmethod
    def _salt_length(cls, value: str) -> str:
        if len(value.strip()) < MIN_SALT_LENGTH:
            raise ValueError(
                f"USER_HASH_SALT requiere al menos {MIN_SALT_LENGTH} caracteres"
            )
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (
            self.environment == "prod"
            and self.user_hash_salt.strip() == DEV_USER_HASH_SALT
        ):
            raise ValueError(
                "USER_HASH_SALT de desarrollo no válido en producción"
            )
        if self.portal_auth_mode == "local":
            if self.environment != "local":
                raise ValueError(
                    "PORTAL_AUTH_MODE=local requiere ENVIRONMENT=local"
                )
            if not self.portal_local_user.strip():
                raise ValueError(
                    "PORTAL_AUTH_MODE=local requiere PORTAL_LOCAL_USER"
                )
        elif not self.iap_audience.strip():
            raise ValueError("PORTAL_AUTH_MODE=iap requiere IAP_AUDIENCE")
        if self.portal_data == "bigquery" and not self.gcp_project_id.strip():
            raise ValueError("PORTAL_DATA=bigquery requiere GCP_PROJECT_ID")
        return self

    @property
    def docs_enabled(self) -> bool:
        return self.environment == "local"


@lru_cache
def get_settings() -> ApiSettings:
    return ApiSettings()
