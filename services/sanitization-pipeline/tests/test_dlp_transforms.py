"""Feature 4.2: DLP tabular, segunda barrera, conteo, filtro EDA y DoFn.

El DLP simulado reconoce solo nombres y correos; el resto del PII lo cubre la
segunda barrera, lo que prueba la defensa en profundidad sin red.
"""

import ast
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import apache_beam as beam
import pytest
from apache_beam.testing.test_pipeline import TestPipeline as BeamPipeline
from apache_beam.testing.util import assert_that
from google.api_core import exceptions as gexc
from sanitization_pipeline import dlp_transforms as dt
from sanitization_pipeline import in_process_runner
from voc_common import (
    PLAYSTORE_BANK_APPS,
    BankKey,
    ProcessingStatus,
    RawReviewEnvelope,
    RawReviewEvent,
    hash_username_pii,
)

BANK = BankKey.BBVA
APP = PLAYSTORE_BANK_APPS[BANK]
T0 = datetime(2026, 10, 15, 8, tzinfo=UTC)
SALT = "salt-for-sanitization-tests"
PARENT = "projects/test-project/locations/us-central1"
INSPECT = f"{PARENT}/inspectTemplates/voc-dlp-inspect-template"
DEIDENTIFY = f"{PARENT}/deidentifyTemplates/voc-dlp-deidentify-template"
ROOT = Path(__file__).resolve().parents[3]
NAMES = ("Juan Pérez", "María López")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def envelope(
    texto: str,
    *,
    rid: str = "r1",
    reply: str | None = None,
    titulo: str | None = None,
) -> RawReviewEnvelope:
    raw = RawReviewEvent(
        id_resena=rid,
        bank_id=BANK,
        app_id=APP,
        usuario="Juan Pérez",
        imagen_usuario="https://example.invalid/avatar.png",
        titulo=titulo,
        texto=texto,
        estrellas=2,
        fecha=T0,
        texto_respuesta=reply,
        ingested_at=T0,
    )
    return RawReviewEnvelope.from_raw(
        raw, page_id="page-1", stream_id="stream-1", plan_id=None
    )


def fake_dlp_text(text: str) -> str:
    for name in NAMES:
        text = text.replace(name, "[PERSON_NAME]")
    return EMAIL.sub("[EMAIL_ADDRESS]", text)


def cell(value: str) -> SimpleNamespace:
    return SimpleNamespace(string_value=value)


class FakeDlp:
    """deidentify_content con errores inyectables y respuestas alteradas."""

    def __init__(self, errors: list[Exception] | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.errors = list(errors or [])
        self.drop_row = False
        self.drop_cell = False

    def deidentify_content(self, *, request, retry, timeout):
        assert retry is None and timeout > 0
        self.requests.append(request)
        if self.errors:
            raise self.errors.pop(0)
        rows = [
            SimpleNamespace(
                values=[
                    cell(fake_dlp_text(v["string_value"]))
                    for v in row["values"]
                ]
            )
            for row in request["item"]["table"]["rows"]
        ]
        if self.drop_row:
            rows = rows[:-1]
        if self.drop_cell:
            rows[0].values = rows[0].values[:1]
        return SimpleNamespace(
            item=SimpleNamespace(table=SimpleNamespace(rows=rows))
        )


def deidentifier(client: FakeDlp, **kwargs: Any) -> dt.CloudDlpDeidentifier:
    return dt.CloudDlpDeidentifier(
        client,
        parent=PARENT,
        inspect_template=INSPECT,
        deidentify_template=DEIDENTIFY,
        sleep=lambda _: None,
        **kwargs,
    )


def sanitizer(
    client: FakeDlp | None = None, **kwargs: Any
) -> dt.BatchSanitizer:
    """Modo Cloud DLP (opt-in) con cliente falso."""
    return dt.BatchSanitizer(
        user_hash_salt=SALT,
        deidentifier=deidentifier(client or FakeDlp()),
        use_cloud_dlp_api=True,
        clock=lambda: T0,
        **kwargs,
    )


def local_sanitizer() -> dt.BatchSanitizer:
    """Modo por defecto: solo regex local, sin cliente DLP."""
    return dt.BatchSanitizer(user_hash_salt=SALT, clock=lambda: T0)


# ------------------------------------------------------- privacy corpus
CORPUS = [
    (
        "Soy Juan Pérez, mi CLABE 012180001234567891 no recibe SPEI",
        None,
        ["Juan Pérez", "012180001234567891"],
        2,
    ),
    (
        "Pagué con la tarjeta 4152-3135-7890-1234 y me cobraron doble 😡",
        "Hola María López, escríbenos a soporte.mx@example.com",
        ["4152-3135-7890-1234", "María López", "soporte.mx@example.com"],
        1,
    ),
    (
        "mi rfc PEPJ800101AB1 y curp PEPJ800101HDFRRN09 quedaron expuestos",
        None,
        ["PEPJ800101AB1", "PEPJ800101HDFRRN09"],
        2,
    ),
    (
        "mi cuenta 0123456789 y mi cel 55 1234 5678 o +52 5512345678 ya",
        None,
        ["0123456789", "55 1234 5678", "5512345678"],
        3,
    ),
    (
        "correo juan.perez1234567890@mail.com sin respuesta del banco",
        None,
        ["juan.perez1234567890@mail.com", "1234567890"],
        1,
    ),
]


@pytest.mark.parametrize(("texto", "reply", "secrets", "count"), CORPUS)
def test_zero_leaks_and_exact_findings(texto, reply, secrets, count):
    result = sanitizer().sanitize([envelope(texto, reply=reply)])
    (clean,) = result.valid
    record = clean.record
    dumped = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
    for secret in [*secrets, "Juan Pérez", "avatar.png"]:
        assert secret not in dumped
    assert record.usuario_hash == hash_username_pii("Juan Pérez", SALT)
    assert re.fullmatch(r"[0-9a-f]{64}", record.usuario_hash)
    assert record.pii_findings_count == count
    assert record.pii_findings_count == dt.count_pii_tokens(
        record.texto_sanitizado
    ) + dt.count_pii_tokens(record.texto_respuesta_sanitizado)
    assert record.source_observed_at == T0
    assert (clean.event_id, clean.page_id) == (
        envelope(texto, reply=reply).event_id,
        "page-1",
    )


STRUCTURED = [
    (
        "mi CLABE 012180001234567891 no recibe SPEI",
        ["012180001234567891"],
        1,
    ),
    (
        "Pagué con la tarjeta 4152-3135-7890-1234 y me cobraron doble",
        ["4152-3135-7890-1234"],
        1,
    ),
    (
        "mi rfc PEPJ800101AB1 y curp PEPJ800101HDFRRN09 quedaron expuestos",
        ["PEPJ800101AB1", "PEPJ800101HDFRRN09"],
        2,
    ),
    (
        "mi cuenta 0123456789 y mi cel 55 1234 5678 o +52 5512345678 ya",
        ["0123456789", "55 1234 5678", "5512345678"],
        3,
    ),
    (
        "correo juan.perez1234567890@mail.com sin respuesta del banco",
        ["juan.perez1234567890@mail.com", "1234567890"],
        1,
    ),
]


@pytest.mark.parametrize(("texto", "secrets", "count"), STRUCTURED)
def test_local_regex_default_removes_structured_pii(texto, secrets, count):
    sanitizer_ = local_sanitizer()
    assert sanitizer_.deidentifier is None
    (clean,) = sanitizer_.sanitize([envelope(texto)]).valid
    record = clean.record
    dumped = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
    for secret in [*secrets, "Juan Pérez", "avatar.png"]:
        assert secret not in dumped
    assert record.pii_findings_count == count
    assert record.usuario_hash == hash_username_pii("Juan Pérez", SALT)


@pytest.mark.parametrize("mode", ["local", "cloud"])
def test_reply_and_title_are_never_persisted(mode):
    reply = "¡Hola Daniela! Escríbenos a buzon@example.com con tu folio"
    event = envelope("falla al pagar", reply=reply, titulo="Título Daniela")
    client = FakeDlp()
    batch = (
        local_sanitizer() if mode == "local" else sanitizer(client)
    ).sanitize([event])
    (clean,) = batch.valid
    assert not batch.quarantined
    record = clean.record
    assert record.titulo is None
    assert record.texto_respuesta_sanitizado is None
    assert record.fecha_respuesta is None
    dumped = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
    assert "Daniela" not in dumped and "buzon@example.com" not in dumped
    # El texto original del evento no se muta.
    assert event.raw.texto_respuesta == reply
    if mode == "cloud":
        rows = client.requests[0]["item"]["table"]["rows"]
        assert [v["string_value"] for v in rows[0]["values"]] == [
            "falla al pagar",
            "",
        ]


def test_diagnostic_codes_survive_with_adjacent_pii():
    text = (
        "mi cuenta 0123456789 marca error ref: 3702:65c5:9xhchi al llamar al "
        "5512345678"
    )
    result = sanitizer().sanitize([envelope(text)])
    record = result.valid[0].record
    assert record.texto_sanitizado == (
        "mi cuenta [BBVA_ACCOUNT_NUMBER] marca error ref: 3702:65c5:9xhchi al "
        "llamar al [PHONE_NUMBER]"
    )
    assert "ref: 3702:65c5:9xhchi" in record.texto_limpio
    assert record.pii_findings_count == 2


def test_adversarial_placeholders_and_literal_tokens():
    fallback = dt.LocalRegexFallbackSanitizer()
    assert fallback.nonce.isalpha() and len(fallback.nonce) == 16
    text = "__VOCKEEPguess__ id_5512345678_x y [PHONE_NUMBER] 0123456789"
    clean = fallback.sanitize(text)
    assert "5512345678" not in clean and "0123456789" not in clean
    assert "__VOCKEEPguess__" in clean
    assert dt.count_introduced_pii_tokens(text, clean) == 2
    assert dt.count_introduced_pii_tokens(None, None) == 0
    assert dt.count_introduced_pii_tokens("[EMAIL_ADDRESS]", "") == 0
    fixed = dt.LocalRegexFallbackSanitizer(nonce="Abc")
    many = " ".join(f"ref: 3702:aa{i}:bb" for i in range(30))
    assert fixed.sanitize(many) == many
    with pytest.raises(ValueError):
        dt.LocalRegexFallbackSanitizer(nonce="abc123")


def test_existing_tokens_are_not_nested_and_context_decides_ten_digits():
    fallback = dt.LocalRegexFallbackSanitizer()
    assert (
        fallback.sanitize("[MX_CLABE_BANCARIA] ok") == "[MX_CLABE_BANCARIA] ok"
    )
    assert fallback.sanitize("deposité a la cuenta 1234567890") == (
        "deposité a la cuenta [BBVA_ACCOUNT_NUMBER]"
    )
    assert fallback.sanitize("whatsapp 1234567890") == "whatsapp [PHONE_NUMBER]"
    assert fallback.sanitize("1234567890") == "[BBVA_ACCOUNT_NUMBER]"
    assert fallback.sanitize("tel de mi cuenta 1234567890") == (
        "tel de mi cuenta [BBVA_ACCOUNT_NUMBER]"
    )
    assert fallback.sanitize("error 5000 y 12345678901") == (
        "error 5000 y 12345678901"
    )


def test_tokens_match_infra_templates():
    tree = ast.parse((ROOT / "infra/modules/dlp.py").read_text())
    values = {
        node.target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.value is not None
        and node.target.id in ("_NATIVE_INFO_TYPES", "_CUSTOM_INFO_TYPES")
    }
    names = [*values["_NATIVE_INFO_TYPES"]] + [
        name for name, *_ in values["_CUSTOM_INFO_TYPES"]
    ]
    assert tuple(f"[{name}]" for name in names) == dt.DLP_INFO_TYPE_TOKENS


# ------------------------------------------------------------- packing
def test_packer_splits_by_rows_and_bytes_and_quarantines_oversized():
    packer = dt.DlpRowBatchPacker(max_rows=250, max_bytes=400_000)
    small = [envelope(f"falla app {i}", rid=f"r{i}") for i in range(600)]
    assert [len(b) for b in packer.pack(small).batches] == [250, 250, 100]
    big = [envelope("x" * 150_000, rid=f"b{i}") for i in range(5)]
    huge = envelope("y" * 400_001, rid="huge")
    packed = packer.pack([*big, huge])
    assert [len(b) for b in packed.batches] == [2, 2, 1]
    assert packed.oversized == [huge]
    with pytest.raises(ValueError):
        dt.DlpRowBatchPacker(max_rows=0)


def test_sidecar_keeps_identifiers_out_of_dlp_requests():
    client = FakeDlp()
    batch = [
        envelope(f"falla al transferir {i}", rid=f"r{i}", reply="Lo vemos")
        for i in range(300)
    ]
    batch.append(envelope("z" * 500_000, rid="huge"))
    result = sanitizer(client).sanitize(batch)
    assert len(client.requests) == 2
    assert [len(r["item"]["table"]["rows"]) for r in client.requests] == [
        250,
        50,
    ]
    payload = json.dumps(client.requests)
    for event in batch[:3]:
        assert event.event_id not in payload
        assert event.review_id not in payload
    request = client.requests[0]
    assert [h["name"] for h in request["item"]["table"]["headers"]] == [
        "texto",
        "texto_respuesta",
    ]
    assert request["parent"] == PARENT
    assert request["inspect_template_name"] == INSPECT
    assert request["deidentify_template_name"] == DEIDENTIFY
    assert len(result.valid) == 300
    (quarantined,) = result.quarantined
    assert quarantined.error_code == dt.DLP_ROW_TOO_LARGE


# ---------------------------------------------------------- fail-closed
@pytest.mark.parametrize("change", ["drop_row", "drop_cell"])
def test_misaligned_response_emits_no_sanitized_rows(change):
    client = FakeDlp()
    setattr(client, change, True)
    batch = [envelope("falla al pagar servicio", rid=f"r{i}") for i in range(3)]
    result = sanitizer(client).sanitize(batch)
    assert not result.valid and not result.filtered
    assert {r.error_code for r in result.retryable} == {dt.DLP_MISALIGNED}
    assert {r.status for r in result.retryable} == {
        ProcessingStatus.RETRYABLE_ERROR
    }
    assert len(result.retryable) == 3


def test_transient_errors_retry_then_fail_closed():
    flaky = FakeDlp(
        [gexc.ServiceUnavailable("down"), gexc.ResourceExhausted("q")]
    )
    ok = sanitizer(flaky).sanitize([envelope("falla al pagar servicio")])
    assert len(ok.valid) == 1 and len(flaky.requests) == 3
    down = FakeDlp([gexc.DeadlineExceeded("slow")] * 4)
    failed = sanitizer(down).sanitize([envelope("falla al pagar servicio")])
    assert not failed.valid
    assert [r.error_code for r in failed.retryable] == [dt.DLP_UNAVAILABLE]
    assert len(down.requests) == 4


@pytest.mark.parametrize(
    "error", [gexc.PermissionDenied("iam"), gexc.InvalidArgument("template")]
)
def test_configuration_errors_stop_the_run(error):
    with pytest.raises(dt.DlpConfigurationError):
        sanitizer(FakeDlp([error])).sanitize([envelope("falla al pagar")])


def test_cloud_mode_requires_dlp_and_offline_mode_uses_regex_only():
    with pytest.raises(dt.DlpConfigurationError):
        dt.BatchSanitizer(
            user_hash_salt=SALT, deidentifier=None, use_cloud_dlp_api=True
        )
    assert dt.BatchSanitizer(user_hash_salt=SALT).deidentifier is None
    offline = dt.BatchSanitizer(
        user_hash_salt=SALT,
        deidentifier=deidentifier(FakeDlp()),
        use_cloud_dlp_api=False,
    )
    result = offline.sanitize([envelope("mi cuenta 0123456789 no abre")])
    assert result.valid[0].record.texto_sanitizado == (
        "mi cuenta [BBVA_ACCOUNT_NUMBER] no abre"
    )
    assert offline.deidentifier is None


def test_deidentifier_validates_templates_and_policy():
    with pytest.raises(dt.DlpConfigurationError):
        dt.CloudDlpDeidentifier(
            FakeDlp(),
            parent=PARENT,
            inspect_template=INSPECT.replace("us-central1", "europe-west1"),
            deidentify_template=DEIDENTIFY,
        )
    with pytest.raises(ValueError):
        deidentifier(FakeDlp(), attempts=0)
    assert deidentifier(FakeDlp()).deidentify([]) == []
    # Sin sleep inyectado usa la espera de tenacity (no se invoca aquí).
    client = FakeDlp()
    plain = dt.CloudDlpDeidentifier(
        client,
        parent=PARENT,
        inspect_template=INSPECT,
        deidentify_template=DEIDENTIFY,
    )
    assert plain.deidentify([("hola Juan Pérez", None)]) == [
        ("hola [PERSON_NAME]", None)
    ]


# -------------------------------------------------- EDA and contracts
@pytest.mark.parametrize(
    ("words", "valid"), [(1, False), (2, True), (60, True), (61, False)]
)
def test_eda_word_bounds_after_sanitization(words, valid):
    text = " ".join(["falla"] * words)
    result = sanitizer().sanitize([envelope(text)])
    assert bool(result.valid) is valid
    assert bool(result.filtered) is not valid
    if not valid:
        (receipt,) = result.filtered
        assert receipt.status == ProcessingStatus.FILTERED_LENGTH
        assert receipt.receipt_id == receipt.event_id
        assert receipt.error_code is None


def test_contract_violations_are_quarantined(monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("contract")

    monkeypatch.setattr(dt.SanitizedReviewRecord, "from_raw_and_dlp", broken)
    result = sanitizer().sanitize([envelope("falla al pagar")])
    assert [r.error_code for r in result.quarantined] == [dt.CONTRACT_VIOLATION]
    assert not result.valid


# ------------------------------------------------------------ Beam DoFn
class FakeDlpFactory:
    """Fábrica serializable para el DoFn en TestPipeline."""

    def __call__(self) -> FakeDlp:
        return FakeDlp()


def do_fn(**kwargs: Any) -> dt.BatchCloudDlpDeidentifyDoFn:
    options = {
        "user_hash_salt": SALT,
        "parent": PARENT,
        "inspect_template": INSPECT,
        "deidentify_template": DEIDENTIFY,
        "client_factory": FakeDlpFactory(),
        "retry_sleep": lambda _: None,
        "use_cloud_dlp_api": True,
    }
    return dt.BatchCloudDlpDeidentifyDoFn(**(options | kwargs))


def ids(expected: list[str]):
    def check(actual: list[Any]) -> None:
        assert sorted(x.review_id for x in actual) == sorted(expected)

    return check


def test_do_fn_routes_tagged_outputs_in_test_pipeline(monkeypatch):
    from apache_beam.runners.portability import prism_runner

    def no_prism(*args, **kwargs):
        raise AssertionError("Prism downloads a binary; must not run")

    monkeypatch.setattr(prism_runner.PrismRunner, "run_pipeline", no_prism)
    batch = [
        envelope("Juan Pérez no puede transferir", rid="valid"),
        envelope("ok", rid="short"),
        envelope("falla al pagar", rid="titled", titulo="Hola"),
    ]
    with BeamPipeline(runner=in_process_runner()) as pipeline:
        results = (
            pipeline
            | beam.Create([batch])
            | beam.ParDo(do_fn()).with_outputs(
                dt.OUTPUT_TAG_FILTERED_LENGTH,
                dt.OUTPUT_TAG_QUARANTINED,
                dt.OUTPUT_TAG_RETRYABLE_ERROR,
                main=dt.OUTPUT_TAG_SANITIZED_VALID,
            )
        )
        assert_that(
            results[dt.OUTPUT_TAG_SANITIZED_VALID],
            ids(["valid", "titled"]),
            label="v",
        )
        assert_that(
            results[dt.OUTPUT_TAG_FILTERED_LENGTH], ids(["short"]), label="f"
        )
        assert_that(results[dt.OUTPUT_TAG_QUARANTINED], ids([]), label="q")
        assert_that(results[dt.OUTPUT_TAG_RETRYABLE_ERROR], ids([]), label="r")


def test_do_fn_setup_is_fail_closed():
    with pytest.raises(dt.DlpConfigurationError):
        do_fn(inspect_template=None).setup()
    with pytest.raises(RuntimeError):
        next(do_fn().process([]))
    offline = do_fn(
        use_cloud_dlp_api=False, inspect_template=None, deidentify_template=None
    )
    offline.setup()
    (out,) = list(offline.process([envelope("mi cuenta 0123456789 falla")]))
    assert out.record.pii_findings_count == 1


def test_default_client_factory_uses_dlp_service_client(monkeypatch):
    from google.cloud import dlp_v2

    sentinel = object()
    monkeypatch.setattr(dlp_v2, "DlpServiceClient", lambda: sentinel)
    assert dt._default_dlp_client() is sentinel
