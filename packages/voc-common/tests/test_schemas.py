"""Pruebas de los contratos Pydantic de voc-common."""

import json
import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError
from voc_common.constants import (
    PLAYSTORE_BANK_APPS,
    BankKey,
    IngestionMode,
    PlayStoreSortOrder,
)
from voc_common.schemas import (
    IngestionRequestPayload,
    PlayStoreRpcCursor,
    RawReviewEvent,
    SanitizedReviewRecord,
    SequentialBatchIngestionRequest,
    ensure_utc,
)
from voc_common.text_utils import hash_username_pii, limpiar_texto_bancario

SALT = "unit-test-salt-0123456789"
APP_ID = PLAYSTORE_BANK_APPS[BankKey.BBVA]
NOTEBOOK_TEXT = (
    "no me deja entrar me sale que restringieron mi cuenta por motivos de "
    "seguridad: ref: 3702:65c5:9xhchi. noooo sirveee 😡 "
    "http://spam.com @bbva #asco"
)
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _raw_event(**overrides: Any) -> RawReviewEvent:
    data: dict[str, Any] = {
        "id_resena": "gp:AOqpTOE-1",
        "bank_id": BankKey.BBVA,
        "app_id": APP_ID,
        "usuario": "Juan Pérez",
        "imagen_usuario": "https://play-lh.googleusercontent.com/a/x",
        "texto": NOTEBOOK_TEXT,
        "estrellas": 1,
        "fecha": T0,
    }
    data.update(overrides)
    return RawReviewEvent(**data)


def test_ensure_utc_naive_and_aware() -> None:
    naive = datetime(2026, 1, 1, 10, 0)
    assert ensure_utc(naive) == datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    cdmx = timezone(timedelta(hours=-6))
    aware = datetime(2026, 1, 1, 10, 0, tzinfo=cdmx)
    converted = ensure_utc(aware)
    assert converted.tzinfo is UTC
    assert converted.hour == 16


# ---------------------------------------------------------------------------
# Solicitudes de ingesta y cursor RPC
# ---------------------------------------------------------------------------


def test_rpc_cursor_defaults_and_star_bounds() -> None:
    cursor = PlayStoreRpcCursor(app_id=APP_ID)
    assert (cursor.lang, cursor.country) == ("es", "mx")
    assert cursor.sort_order is PlayStoreSortOrder.NEWEST
    assert cursor.star_filter is None and cursor.page_token is None

    cursor_b64 = "CpEBCo4BKmsKaRIA"  # Base64 opaco
    restored = PlayStoreRpcCursor.model_validate_json(
        PlayStoreRpcCursor(
            app_id=APP_ID, star_filter=3, page_token=cursor_b64
        ).model_dump_json()
    )
    assert restored.page_token == cursor_b64 and restored.star_filter == 3

    for bad in (0, 6):
        with pytest.raises(ValidationError):
            PlayStoreRpcCursor(app_id=APP_ID, star_filter=bad)


def test_ingestion_request_payload_bounds() -> None:
    payload = IngestionRequestPayload(bank_id=BankKey.NUBANK)
    assert payload.mode is IngestionMode.INCREMENTAL
    assert payload.page_size == 500
    assert payload.max_reviews_per_run == 5000
    assert payload.partition_by_stars is False
    with pytest.raises(ValidationError):
        IngestionRequestPayload(bank_id=BankKey.BBVA, page_size=501)
    with pytest.raises(ValidationError):
        IngestionRequestPayload(bank_id=BankKey.BBVA, max_reviews_per_run=0)
    with pytest.raises(ValidationError):
        IngestionRequestPayload.model_validate(
            {"bank_id": "BBVA", "unexpected": 1}
        )


def test_sequential_batch_request_defaults() -> None:
    req = SequentialBatchIngestionRequest()
    assert req.banks == list(BankKey)
    assert req.max_reviews_per_bank == 1000
    assert req.inter_bank_delay_sec == 15.0
    with pytest.raises(ValidationError):
        SequentialBatchIngestionRequest(inter_bank_delay_sec=0.5)
    with pytest.raises(ValidationError):
        SequentialBatchIngestionRequest(banks=["HSBC"])


# ---------------------------------------------------------------------------
# Eventos crudos de reseñas
# ---------------------------------------------------------------------------


def test_raw_review_from_playstore_dict() -> None:
    raw_dict = {
        "reviewId": "gp:AOqpTOH",
        "userName": "María López",
        "userImage": "https://play-lh.googleusercontent.com/a/abc",
        "content": "La app se cierra al abrir transferencias",
        "score": 2,
        "thumbsUpCount": 14,
        "reviewCreatedVersion": "10.21.1",
        "at": datetime(2026, 9, 30, 8, 15),  # naive -> UTC
        "replyContent": "Hola, escríbenos por DM",
        "repliedAt": datetime(2026, 9, 30, 9, 0),
        "appVersion": "10.21.1",
    }
    event = RawReviewEvent.from_playstore_dict(raw_dict, BankKey.BBVA, APP_ID)

    assert event.id_resena == "gp:AOqpTOH"
    assert event.usuario == "María López"
    assert event.imagen_usuario == raw_dict["userImage"]
    assert event.texto == raw_dict["content"]
    assert event.estrellas == 2
    assert event.votos_utilidad == 14
    assert event.version_app == "10.21.1"
    assert event.fecha == datetime(2026, 9, 30, 8, 15, tzinfo=UTC)
    assert event.texto_respuesta == "Hola, escríbenos por DM"
    assert event.fecha_respuesta is not None
    assert event.fecha_respuesta.tzinfo is UTC
    assert event.titulo is None
    assert "appVersion" not in event.model_dump()
    assert "app_version" not in event.model_dump()


@pytest.mark.parametrize("missing", [None, "", "   ", float("nan")])
def test_raw_review_version_app_normalized(missing: Any) -> None:
    raw_dict = {
        "reviewId": "id",
        "userName": "u",
        "content": "texto",
        "score": 5,
        "at": T0,
        "reviewCreatedVersion": missing,
        "thumbsUpCount": None,
        "replyContent": float("nan"),
    }
    event = RawReviewEvent.from_playstore_dict(raw_dict, BankKey.AZTECA, "a")
    assert event.version_app == "UNKNOWN"
    assert event.votos_utilidad == 0
    assert event.texto_respuesta is None


def test_raw_review_rejects_invalid_payloads() -> None:
    with pytest.raises(ValidationError):
        _raw_event(estrellas=6)
    with pytest.raises(ValidationError):
        _raw_event(texto="")
    with pytest.raises(ValidationError):
        _raw_event(usuario="")
    with pytest.raises(ValidationError):
        RawReviewEvent.from_playstore_dict(
            {"reviewId": "x"}, BankKey.BBVA, APP_ID
        )


def test_raw_review_fecha_converted_to_utc() -> None:
    cdmx = timezone(timedelta(hours=-6))
    event = _raw_event(fecha=datetime(2026, 10, 1, 6, 0, tzinfo=cdmx))
    assert event.fecha == T0
    assert event.fecha.tzinfo is UTC
    assert event.ingested_at.tzinfo is UTC


def test_raw_review_from_batchexecute_entry() -> None:
    at = int(T0.timestamp())
    entry: list[Any] = [
        "gp:AOqpTOF",
        ["Pedro", [None, 2, None, [None, None, "https://img/p.png"]]],
        4,
        None,
        "Muy buena app pero el token falla",
        [at, 123000000],
        7,
        [None, "Gracias por tu comentario", [at + 3600, 0]],
        None,
        None,
        "10.22.0",
    ]
    event = RawReviewEvent.from_batchexecute_entry(entry, BankKey.BBVA, APP_ID)
    assert event.id_resena == "gp:AOqpTOF"
    assert event.usuario == "Pedro"
    assert event.imagen_usuario == "https://img/p.png"
    assert event.estrellas == 4
    assert event.texto == "Muy buena app pero el token falla"
    assert event.fecha == T0
    assert event.votos_utilidad == 7
    assert event.texto_respuesta == "Gracias por tu comentario"
    assert event.fecha_respuesta == T0 + timedelta(hours=1)
    assert event.version_app == "10.22.0"
    assert event.titulo is None


def test_raw_review_from_batchexecute_entry_sparse_row() -> None:
    at = int(T0.timestamp())
    entry: list[Any] = ["id", ["Ana"], 1, None, "No sirve", [at], None]
    event = RawReviewEvent.from_batchexecute_entry(entry, BankKey.BBVA, APP_ID)
    assert event.imagen_usuario is None
    assert event.votos_utilidad == 0
    assert event.texto_respuesta is None and event.fecha_respuesta is None
    assert event.version_app == "UNKNOWN"

    for broken in (["id", ["Ana"], 1, None, "x", ["no-epoch"]], ["id"], []):
        with pytest.raises(ValidationError):
            RawReviewEvent.from_batchexecute_entry(broken, BankKey.BBVA, "a")


# ---------------------------------------------------------------------------
# Registro sanitizado
# ---------------------------------------------------------------------------


def test_sanitized_review_record_keeps_every_length() -> None:
    """El TDS no filtra por longitud: el rango del EDA se aplica al analizar."""
    raw = _raw_event()

    for n_words in (1, 2, 60, 61, 500):
        record = SanitizedReviewRecord.from_raw_and_dlp(
            raw, " ".join(["mal"] * n_words), 0, SALT
        )
        assert record.conteo_palabras == n_words
        assert re.fullmatch(r"[0-9a-f]{64}", record.usuario_hash)
    # Un texto que la limpieza deja vacío tampoco se descarta.
    empty = SanitizedReviewRecord.from_raw_and_dlp(raw, "...", 0, SALT)
    assert empty.conteo_palabras == len(empty.texto_limpio.split())


def test_sanitized_review_record_from_raw_and_dlp() -> None:
    raw = _raw_event(version_app=None, votos_utilidad=3)
    texto_dlp = (
        "Soy [PERSON_NAME] y mi CLABE [MX_CLABE_BANCARIA] no recibe SPEI. "
        "ref: 3702 !!!!"
    )
    record = SanitizedReviewRecord.from_raw_and_dlp(
        raw,
        texto_sanitizado=texto_dlp,
        pii_findings_count=2,
        user_hash_salt=SALT,
        texto_respuesta_sanitizado="Hola [PERSON_NAME]",
    )
    dumped = record.model_dump()

    assert "usuario" not in dumped and "imagen_usuario" not in dumped
    assert raw.usuario not in json.dumps(dumped, default=str)
    assert record.usuario_hash == hash_username_pii(raw.usuario, SALT)
    assert record.texto_sanitizado == texto_dlp
    assert record.texto_limpio == limpiar_texto_bancario(texto_dlp)
    assert "ref: 3702" in record.texto_limpio
    assert "[person_name]" in record.texto_limpio
    assert record.pii_findings_count == 2
    assert record.version_app == "UNKNOWN"
    assert record.votos_utilidad == 3
    assert record.fecha == raw.fecha
    assert record.texto_respuesta_sanitizado == "Hola [PERSON_NAME]"
    assert record.sanitized_at.tzinfo is UTC
    assert record.source_observed_at == raw.ingested_at
    without = record.model_dump(exclude={"source_observed_at"})
    with pytest.raises(ValidationError):
        SanitizedReviewRecord.model_validate(without)


def test_sanitized_review_record_rejects_pii_and_inconsistency() -> None:
    record = SanitizedReviewRecord.from_raw_and_dlp(
        _raw_event(), "no funciona", 0, SALT
    )
    base = record.model_dump()

    with pytest.raises(ValidationError):
        SanitizedReviewRecord(**{**base, "usuario": "Juan Pérez"})
    with pytest.raises(ValidationError):
        SanitizedReviewRecord(**{**base, "usuario_hash": "Z" * 64})
    with pytest.raises(ValidationError, match="conteo_palabras"):
        SanitizedReviewRecord(**{**base, "conteo_palabras": 3})
