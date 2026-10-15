"""Logs estructurados de una línea para Cloud Logging, sin datos personales.

Cloud Run interpreta una línea JSON en stdout: `severity` fija la severidad,
`message` el texto y el resto queda en `jsonPayload`, consultable con
`gcloud logging read 'jsonPayload.message="..."'` o enrutable a BigQuery.

Reglas de uso: un evento por unidad de trabajo (corrida, banco, solicitud,
microbatch, página), nunca por reseña. Los campos con texto de usuarios, nombres
o cursores de paginación se descartan aunque un llamador los pase por error.
"""

import json
import sys
from typing import Any

# Campos que nunca deben llegar a los logs: contenido de reseñas, identidad de
# autores y tokens de paginación (opacos pero ligados a la sesión de origen).
FORBIDDEN_FIELDS = frozenset(
    {
        "texto",
        "texto_limpio",
        "texto_sanitizado",
        "texto_respuesta",
        "texto_respuesta_sanitizado",
        "titulo",
        "usuario",
        "imagen_usuario",
        "usuario_hash",
        "output_token",
        "input_token",
        "next_token",
        "cursor",
        "token",
        "body",
        "raw_body",
        "payload",
    }
)
MAX_STRING_LENGTH = 300


def _bounded(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
        return value[:MAX_STRING_LENGTH] + "…"
    if isinstance(value, dict):
        return {str(k): _bounded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_bounded(v) for v in value]
    return value


def build_event(severity: str, message: str, **fields: Any) -> dict[str, Any]:
    """Arma el registro: descarta campos prohibidos y acota las cadenas."""
    record: dict[str, Any] = {"severity": severity, "message": message}
    dropped = sorted(name for name in fields if name in FORBIDDEN_FIELDS)
    for name, value in fields.items():
        if name in FORBIDDEN_FIELDS:
            continue
        record[name] = _bounded(value)
    if dropped:
        record["dropped_fields"] = dropped
    return record


def log_event(severity: str, message: str, **fields: Any) -> dict[str, Any]:
    """Escribe el evento como una línea JSON y lo devuelve (útil en pruebas)."""
    record = build_event(severity, message, **fields)
    print(
        json.dumps(record, default=str, ensure_ascii=False),
        file=sys.stdout,
        flush=True,
    )
    return record
