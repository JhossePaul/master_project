"""Prueba de Kaggle: autentica, crea un dataset privado mínimo y lo borra.

Corre en el Job de entrenamiento (``kaggle-check``) y no gasta nada: sirve
para ver la causa de un fallo de Kaggle antes de pagar la plata reciente de un
reentrenamiento. Imprime el usuario y el estado, nunca la clave.
"""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from ml_inference.rescore import KaggleClient, check_slug, wait_for

log = logging.getLogger(__name__)

TIMEOUT_SEC = 300.0


def run_check(
    kaggle: KaggleClient,
    workdir: Path,
    run: str,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Crea y borra un dataset de prueba; devuelve su referencia."""
    slug = check_slug(f"voc-kaggle-check-{run}")
    ref = f"{kaggle.user}/{slug}"
    log.info("kaggle-check: usuario %s", kaggle.user)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "check.txt").write_text("ok", encoding="utf-8")
    (workdir / "dataset-metadata.json").write_text(
        json.dumps({"title": slug, "id": ref, "licenses": [{"name": "other"}]}),
        encoding="utf-8",
    )
    kaggle.create_dataset(workdir)
    try:
        wait_for(
            lambda: kaggle.dataset_status(ref),
            TIMEOUT_SEC,
            "dataset",
            sleep,
            clock,
            first_delay=False,
        )
        log.info("kaggle-check: dataset %s listo", ref)
    finally:
        kaggle.delete_dataset(ref)
        log.info("kaggle-check: dataset %s borrado", ref)
    return ref
