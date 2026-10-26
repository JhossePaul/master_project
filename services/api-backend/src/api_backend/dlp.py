"""Sanitización de los comentarios de los revisores con Cloud DLP."""

from typing import Any, Protocol

from google.api_core.exceptions import GoogleAPICallError, RetryError

from api_backend.errors import ApiError, ErrorCode
from api_backend.settings import ApiSettings

FAKE_NAME = "Juan Pérez"
FAKE_TOKEN = "[PERSON_NAME]"  # noqa: S105  # nosec B105


class CommentSanitizer(Protocol):
    def sanitize(self, text: str) -> str: ...


class DlpCommentSanitizer:
    """``deidentify_content`` con las plantillas de la sanitización.

    Son las de ``infra/modules/dlp.py``: incluyen los detectores de nombres y
    los bancarios. Si DLP falla no se devuelve el texto original: el comentario
    no se guarda.
    """

    def __init__(
        self,
        parent: str,
        inspect_template: str,
        deidentify_template: str,
        client: Any | None = None,
    ) -> None:
        self._parent = parent
        self._inspect = inspect_template
        self._deidentify = deidentify_template
        self._client = client

    def sanitize(self, text: str) -> str:
        try:
            if self._client is None:  # perezoso: abre credenciales al usarse
                from google.cloud import dlp_v2

                self._client = dlp_v2.DlpServiceClient()
            response = self._client.deidentify_content(
                request={
                    "parent": self._parent,
                    "inspect_template_name": self._inspect,
                    "deidentify_template_name": self._deidentify,
                    "item": {"value": text},
                }
            )
        except (GoogleAPICallError, RetryError) as exc:
            raise ApiError(
                ErrorCode.UPSTREAM,
                "No se pudo sanitizar el comentario; no se guardó nada",
            ) from exc
        return str(response.item.value)


class FixedNameSanitizer:
    """Doble de pruebas y del modo local: reemplaza un nombre fijo."""

    def sanitize(self, text: str) -> str:
        return text.replace(FAKE_NAME, FAKE_TOKEN)


def build_sanitizer(settings: ApiSettings) -> CommentSanitizer:
    if settings.portal_data == "fixtures":
        return FixedNameSanitizer()
    return DlpCommentSanitizer(
        f"projects/{settings.gcp_project_id}/locations/{settings.region}",
        settings.dlp_inspect_template,
        settings.dlp_deidentify_template,
    )
