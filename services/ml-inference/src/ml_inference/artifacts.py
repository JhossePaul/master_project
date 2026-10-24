"""Artefactos de modelos en ``gs://<bucket>/ml_artifacts/`` (D4, D11).

Disposición: ``sentiment/<model_version>/`` (pesos de RoBERTuito),
``topics/<topic_model_version>/`` (``umap.pkl`` y ``bertopic``) y
``embeddings/<nombre>/`` (MiniLM). El Job los baja a disco local antes de
cargarlos; nada se descarga de Hugging Face en producción.
"""

from pathlib import Path
from typing import Final

from google.cloud import storage

SENTIMENT: Final = "sentiment"
TOPICS: Final = "topics"
EMBEDDINGS: Final = "embeddings"
MINILM: Final = "paraphrase-multilingual-MiniLM-L12-v2"


def artifact_prefix(root: str, kind: str, name: str) -> str:
    return f"{root.strip('/')}/{kind}/{name}/"


def gcs_uri(bucket: str, prefix: str) -> str:
    return f"gs://{bucket}/{prefix}"


def download_prefix(
    client: storage.Client, bucket: str, prefix: str, dest: Path
) -> Path:
    """Baja todos los objetos de ``prefix`` a ``dest``; falla si no hay."""
    blobs = [b for b in client.list_blobs(bucket, prefix=prefix)]
    files = [b for b in blobs if not b.name.endswith("/")]
    if not files:
        raise FileNotFoundError(f"no artifacts under gs://{bucket}/{prefix}")
    for blob in files:
        target = dest / blob.name.removeprefix(prefix)
        target.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(target))
    return dest


def upload_dir(
    client: storage.Client, bucket: str, source: Path, prefix: str
) -> int:
    """Sube ``source`` recursivamente bajo ``prefix``; devuelve los archivos."""
    target = client.bucket(bucket)
    count = 0
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        relative = path.relative_to(source).as_posix()
        target.blob(f"{prefix}{relative}").upload_from_filename(str(path))
        count += 1
    if count == 0:
        raise FileNotFoundError(f"nothing to upload in {source}")
    return count
