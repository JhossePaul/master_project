"""Temperatura y diagrama de confiabilidad de una versión del modelo.

Salen del ``training_manifest.json`` que el entrenamiento guarda junto a los
pesos (``ml_artifacts/sentiment/<versión>/``). La versión que se registró
desde los experimentos no tiene manifiesto: para esa se leen las métricas de
calibración de ``docs/analytics/calibration/`` y la respuesta dice de dónde
vienen.
"""

import json
from pathlib import Path
from typing import Any, Final, Protocol

from api_backend.sections.mlops.schemas import CalibrationOut, ReliabilityBin

MANIFEST_FILE: Final = "training_manifest.json"
# Versión registrada desde los experimentos → su entrada en el JSON de
# calibración (RoBERTuito, semilla 1, con pesos).
EXPERIMENT_MODELS: Final[dict[str, str]] = {
    "robertuito_sentiment_v1": "M4_robertuito_s1_ppi"
}
DOCS_LABEL: Final = (
    "docs/analytics/calibration/calibration_v0_metrics.json "
    "(oro dev de los experimentos)"
)


class ManifestSource(Protocol):
    def manifest(self, model_version: str) -> dict[str, Any] | None:
        """El manifiesto de entrenamiento, o ``None`` si no existe."""


class GcsManifests:
    def __init__(self, client: Any, bucket: str, prefix: str) -> None:
        self._client = client
        self._bucket = bucket
        self._prefix = prefix.strip("/")

    def manifest(self, model_version: str) -> dict[str, Any] | None:
        path = f"{self._prefix}/sentiment/{model_version}/{MANIFEST_FILE}"
        blob = self._client.bucket(self._bucket).blob(path)
        if not blob.exists():
            return None
        loaded = json.loads(blob.download_as_text())
        return loaded if isinstance(loaded, dict) else None


class NoManifests:
    """Sin bucket (fixtures o local): solo los JSON de los experimentos."""

    def manifest(self, model_version: str) -> dict[str, Any] | None:
        return None


def _bin(raw: dict[str, Any]) -> ReliabilityBin:
    if "bin" in raw:  # JSON de los experimentos
        low, high = raw["bin"]
        return ReliabilityBin(
            low=low,
            high=high,
            n=raw["n"],
            weight=raw["peso"],
            confidence=raw["confianza"],
            accuracy=raw["acierto"],
        )
    return ReliabilityBin.model_validate(raw)


def from_manifest(
    model_version: str, manifest: dict[str, Any]
) -> CalibrationOut | None:
    calibration = manifest.get("calibration")
    if not isinstance(calibration, dict):
        return None
    return CalibrationOut(
        model_version=model_version,
        source="manifest",
        source_label=(
            f"ml_artifacts/sentiment/{model_version}/{MANIFEST_FILE}"
        ),
        temperature=calibration.get("temperature"),
        ece_raw=calibration.get("raw_ece_dev"),
        ece_calibrated=calibration.get("ece_dev"),
        raw=[_bin(b) for b in calibration.get("raw", [])],
        calibrated=[_bin(b) for b in calibration.get("calibrated", [])],
    )


def from_docs(model_version: str, path: Path) -> CalibrationOut | None:
    key = EXPERIMENT_MODELS.get(model_version)
    if key is None or not path.is_file():
        return None
    entry = json.loads(path.read_text("utf-8"))["modelos"].get(key)
    if entry is None:
        return None
    raw, calibrated = entry["sin_calibrar"], entry["temperature"]
    after = calibrated["dev_fuera_de_particion"]
    return CalibrationOut(
        model_version=model_version,
        source="docs",
        source_label=DOCS_LABEL,
        temperature=calibrated.get("temperatura"),
        ece_raw=raw.get("ece"),
        ece_calibrated=after.get("ece"),
        raw=[_bin(b) for b in raw["fiabilidad"]],
        calibrated=[_bin(b) for b in after["fiabilidad"]],
    )


def calibration_of(
    model_version: str, manifests: ManifestSource, docs_path: Path
) -> CalibrationOut | None:
    """Del manifiesto si existe; si no, de los experimentos; si no, ``None``."""
    manifest = manifests.manifest(model_version)
    found = from_manifest(model_version, manifest) if manifest else None
    return found or from_docs(model_version, docs_path)
