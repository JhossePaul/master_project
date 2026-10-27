"""Lanzador de los Jobs de EPIC-6 que el portal puede ejecutar.

Es una copia mínima de ``ml_inference.jobs.CloudRunJobs.execute``:
``ml-inference`` arrastra PyTorch y Gemini, y la API no. La prueba fija la
misma petición que la de ``ml-inference`` (``POST .../jobs/<job>:run`` con
``overrides.containerOverrides[].args``).

La lista es cerrada: solo cuatro Jobs, cada uno con su subcomando. Los
argumentos los arma el servidor; nunca vienen del cliente.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

API: Final = "https://run.googleapis.com/v2"
TIMEOUT_SEC: Final = 60
# Job de Cloud Run → único subcomando que el portal le pasa.
ALLOWED_JOBS: Final[dict[str, str]] = {
    "voc-ml-training": "train",
    "voc-ml-rescoring": "rescore",
    "voc-ml-promote": "promote",
    "voc-ml-topics-refit": "topics-refit",
}
_PROJECT = re.compile(r"[a-z][a-z0-9-]{0,29}")
_REGION = re.compile(r"[a-z]+-[a-z]+[0-9]")


class JobRunner(Protocol):
    def execute(self, job: str, args: Sequence[str]) -> str:
        """Lanza el Job y devuelve el nombre de la operación."""


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

    def execute(self, job: str, args: Sequence[str]) -> str:
        """Lanza una ejecución con ``args``; no espera a que termine."""
        command = ALLOWED_JOBS.get(job)
        if command is None:
            raise ValueError(f"job not allowed: {job}")
        if not args or args[0] != command:
            raise ValueError(f"{job} only runs the {command!r} command")
        if self.session is None:
            self.session = _session()
        url = (
            f"{API}/projects/{self.project}/locations/{self.region}"
            f"/jobs/{job}:run"
        )
        response = self.session.post(
            url,
            json={"overrides": {"containerOverrides": [{"args": list(args)}]}},
            timeout=TIMEOUT_SEC,
        )
        response.raise_for_status()
        return str(response.json()["name"])
