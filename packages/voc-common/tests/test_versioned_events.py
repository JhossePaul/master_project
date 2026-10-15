"""Feature 1.8: identidades, sobres pre/post-DLP y fixtures."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import voc_common as vc
from pydantic import ValidationError

FIXTURES = Path(__file__).with_name("fixtures") / "ingestion"


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def event() -> vc.RawReviewEnvelope:
    return vc.RawReviewEnvelope.model_validate(fixture("raw_envelope_v2"))


@pytest.mark.parametrize(
    "changes",
    [
        {"texto": "otro problema"},
        {"estrellas": 2},
        {"votos_utilidad": 4},
        {"version_app": "2.0"},
        {"texto_respuesta": "respuesta del banco"},
        {"fecha_respuesta": "2026-10-15T00:00:00Z"},
        {"titulo": "titulo"},
        {"usuario": "otro_usuario"},
        {"imagen_usuario": "https://example.test/image"},
        {"fecha": "2026-10-13T00:00:00Z"},
    ],
)
def test_source_updates_create_distinct_revisions(
    changes: dict[str, Any],
) -> None:
    original = event()
    raw = vc.RawReviewEvent.model_validate(
        {**original.raw.model_dump(), **changes}
    )
    changed = vc.RawReviewEnvelope.from_raw(
        raw, page_id="another-page", stream_id="another-stream"
    )
    assert changed.source_revision != original.source_revision
    assert changed.event_id != original.event_id


def test_capture_time_page_plan_and_stream_do_not_change_identity() -> None:
    original = event()
    data = original.raw.model_dump()
    data["ingested_at"] += timedelta(days=2)
    raw = vc.RawReviewEvent(**data)
    repeated = vc.RawReviewEnvelope.from_raw(
        raw, page_id="new-page", stream_id="new-stream"
    )
    assert repeated.event_id == original.event_id
    assert repeated.source_revision == original.source_revision
    assert repeated.plan_id is None
    # La copia del sobre no cambia al modificar el modelo de entrada.
    raw.texto = "mutacion posterior"
    assert repeated.raw.texto == original.raw.texto
    with pytest.raises(ValidationError):
        repeated.raw.texto = "otra mutacion"
    assert "fixture_user" not in repr(repeated)
    with pytest.raises(ValidationError):
        vc.RawReviewEnvelope.model_validate(
            {
                **original.model_dump(),
                "schema_version": 3,
            }
        )


@pytest.mark.parametrize(
    "change",
    [
        {"event_id": "a" * 64},
        {"source_revision": "b" * 64},
        {"review_id": "wrong-id"},
    ],
)
def test_envelope_rejects_wrong_identity(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        vc.RawReviewEnvelope.model_validate({**event().model_dump(), **change})


def test_raw_payload_identity_is_checked_independently() -> None:
    original = event()
    data = original.model_dump()
    data["raw"]["id_resena"] = "other-review"
    with pytest.raises(ValidationError, match="payload identity"):
        vc.RawReviewEnvelope.model_validate(data)


def test_sanitized_result_and_receipt_keep_revision_without_raw_fields() -> (
    None
):
    original = event()
    clean = vc.SanitizedReviewEnvelope.model_validate(
        fixture("sanitized_envelope_v2")
    )
    built = vc.SanitizedReviewEnvelope.from_event(original, clean.record)
    assert built == clean
    assert built.event_id == original.event_id
    assert built.source_revision == original.source_revision
    assert "raw" not in built.model_dump()
    assert "usuario" not in built.record.model_dump()
    assert "imagen_usuario" not in built.record.model_dump()
    committed = vc.ProcessingReceipt.model_validate(fixture("receipt_v2"))
    receipt = vc.ProcessingReceipt.from_event(
        original,
        receipt_id=committed.receipt_id,
        status=committed.status,
        processed_at=committed.processed_at,
        result_digest=committed.result_digest,
        bigquery_job_ids=committed.bigquery_job_ids,
    )
    assert receipt == committed
    assert receipt.event_id == clean.event_id
    for status in vc.ProcessingStatus:
        if status == vc.ProcessingStatus.TDS_COMMITTED:
            continue
        result = vc.ProcessingReceipt.from_event(
            original,
            receipt_id=f"receipt-{status.value}",
            status=status,
            processed_at=committed.processed_at,
            error_code="FIXTURE_REASON"
            if status
            in (
                vc.ProcessingStatus.QUARANTINED,
                vc.ProcessingStatus.RETRYABLE_ERROR,
            )
            else None,
        )
        assert result.status != vc.ProcessingStatus.TDS_COMMITTED
        assert result.bigquery_job_ids == ()
    with pytest.raises(ValidationError):
        vc.ProcessingReceipt.model_validate(
            {
                **receipt.model_dump(),
                "event_id": "a" * 64,
            }
        )
    with pytest.raises(ValueError, match="metadata changed"):
        vc.SanitizedReviewEnvelope.from_event(
            original,
            vc.SanitizedReviewRecord.model_validate(
                {
                    **clean.record.model_dump(),
                    "estrellas": 2,
                }
            ),
        )
    data = clean.model_dump()
    data["record"]["id_resena"] = "wrong"
    with pytest.raises(ValidationError):
        vc.SanitizedReviewEnvelope.model_validate(data)
    with pytest.raises(ValidationError):
        built.record.texto_limpio = "changed result"


def test_audit_contract_is_independent_and_consistent() -> None:
    audit = vc.IngestionRunAudit.model_validate(fixture("audit_v2"))
    assert audit.pages_committed == 1
    for forbidden in ("raw", "texto", "usuario", "output_token", "input_token"):
        with pytest.raises(ValidationError):
            vc.IngestionRunAudit.model_validate(
                {
                    **audit.model_dump(),
                    forbidden: "not permitted",
                }
            )
    for changes in (
        {"reviews_published": 2},
        {"reviews_discarded": -1},
        {"observed_min_at": audit.updated_at + timedelta(days=1)},
    ):
        with pytest.raises(ValidationError):
            vc.IngestionRunAudit.model_validate(
                {**audit.model_dump(), **changes}
            )
    started = vc.IngestionRunAudit(
        audit_event_id="start",
        bank_id=audit.bank_id,
        app_id=audit.app_id,
        run_id=audit.run_id,
        mode_executed=audit.mode_executed,
        status=vc.RunAuditStatus.STARTED,
        updated_at=audit.updated_at,
    )
    assert started.reviews_published is None


def test_shared_fixtures_roundtrip() -> None:
    models = {
        "raw_envelope_v2": vc.RawReviewEnvelope,
        "sanitized_envelope_v2": vc.SanitizedReviewEnvelope,
        "receipt_v2": vc.ProcessingReceipt,
        "audit_v2": vc.IngestionRunAudit,
        "watermark_v2": vc.IngestionWatermarkState,
    }
    for name, model in models.items():
        instance = model.model_validate(fixture(name))
        assert model.model_validate_json(instance.model_dump_json()) == instance


def test_revision_is_checked_against_content_even_with_valid_event_digest() -> (
    None
):
    original = event()
    bogus_revision = "b" * 64
    with pytest.raises(ValidationError, match="differs from raw content"):
        vc.RawReviewEnvelope.model_validate(
            {
                **original.model_dump(),
                "source_revision": bogus_revision,
                "event_id": vc.compute_event_id(
                    original.bank_id,
                    original.review_id,
                    bogus_revision,
                ),
            }
        )
