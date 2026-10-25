"""Ejecución de Jobs de Cloud Run con argumentos propios.

La usan el delta (backfill de tópicos) y, después, el monitor, el
entrenamiento y la API de EPIC-7. Llama a la API REST v2 de Cloud Run con
las credenciales del Job (``voc-sa-ml-backend``), que tiene
``roles/run.developer`` solo sobre los Jobs que lanza: ``run.invoker`` no
deja cambiar los argumentos.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

API: Final = "https://run.googleapis.com/v2"
TIMEOUT_SEC: Final = 60
_JOB = re.compile(r"[a-z][a-z0-9-]{0,62}")
_PROJECT = re.compile(r"[a-z][a-z0-9-]{0,29}")
_REGION = re.compile(r"[a-z]+-[a-z]+[0-9]")


class JobRunner(Protocol):
    def execute(self, job: str, args: Sequence[str]) -> str: ...


def _session() -> Any:  # pragma: no cover - credenciales reales
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return AuthorizedSession(credentials)


@dataclass
class CloudRunJobs:
    project: str
    region: str
    session: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not _PROJECT.fullmatch(self.project):
            raise ValueError("invalid project id")
        if not _REGION.fullmatch(self.region):
            raise ValueError("invalid region")

    def _url(self, job: str) -> str:
        if not _JOB.fullmatch(job):
            raise ValueError(f"invalid job name: {job}")
        return (
            f"{API}/projects/{self.project}/locations/{self.region}/jobs/{job}"
        )

    def _http(self) -> Any:
        if self.session is None:
            self.session = _session()
        return self.session

    def execute(self, job: str, args: Sequence[str]) -> str:
        """Lanza una ejecución con ``args`` y devuelve el nombre de la
        operación; no espera a que termine."""
        response = self._http().post(
            f"{self._url(job)}:run",
            json={"overrides": {"containerOverrides": [{"args": list(args)}]}},
            timeout=TIMEOUT_SEC,
        )
        response.raise_for_status()
        return str(response.json()["name"])
