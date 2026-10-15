"""Sanitización por regex local con Cloud DLP opcional (EPIC-4 4.2).

Política de minimización: solo el texto de la reseña llega al TDS. El título y
la respuesta de la entidad (que saluda al autor por su nombre en la mayoría de
los casos medidos) se descartan antes de sanitizar y nunca se persisten.

Flujo por microbatch: rechazo previo (fila sobredimensionada), empaquetado por
filas/bytes, Cloud DLP opcional con alineación posicional *sidecar*, regex
local, conteo de tokens introducidos (sin filtro de longitud) y construcción de
`SanitizedReviewEnvelope`. Con `use_cloud_dlp_api=True` el flujo es
*fail-closed*: si DLP no responde correctamente ningún evento sale por la
salida válida usando solo regex.
"""

import re
import secrets
import string
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import apache_beam as beam
from apache_beam import pvalue
from google.api_core import exceptions as gexc
from pydantic import ValidationError
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from voc_common import (
    ProcessingReceipt,
    ProcessingStatus,
    RawReviewEnvelope,
    SanitizedReviewEnvelope,
    SanitizedReviewRecord,
)

# Tokens exactos de voc-dlp-deidentify-template (infra/modules/dlp.py).
DLP_INFO_TYPE_TOKENS: tuple[str, ...] = (
    "[PERSON_NAME]",
    "[EMAIL_ADDRESS]",
    "[PHONE_NUMBER]",
    "[CREDIT_CARD_NUMBER]",
    "[MEXICO_CURP_NUMBER]",
    "[MX_CLABE_BANCARIA]",
    "[MX_RFC_TAX_ID]",
    "[BBVA_ACCOUNT_NUMBER]",
)
DIAGNOSTIC_PATTERN = re.compile(
    r"ref\s*:\s*\d{4}\s*:\s*[a-zA-Z0-9]+\s*:\s*[a-zA-Z0-9]+"
)
DLP_COLUMNS: tuple[str, str] = ("texto", "texto_respuesta")

OUTPUT_TAG_SANITIZED_VALID = "sanitized_valid"
OUTPUT_TAG_QUARANTINED = "quarantined"
OUTPUT_TAG_RETRYABLE_ERROR = "retryable_error"

# Códigos de recibo sin texto ni PII.
DLP_ROW_TOO_LARGE = "DLP_ROW_TOO_LARGE"
CONTRACT_VIOLATION = "CONTRACT_VIOLATION"
DLP_UNAVAILABLE = "DLP_UNAVAILABLE"
DLP_MISALIGNED = "DLP_MISALIGNED"

_TOKEN_PATTERN = re.compile(
    "|".join(re.escape(token) for token in DLP_INFO_TYPE_TOKENS)
)
# Delimitadores numéricos explícitos: `\b` no corta entre "_" y un dígito.
_D = r"(?<!\d)"
_E = r"(?!\d)"
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Email primero: las reglas numéricas no deben partir una dirección.
    (
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        "[EMAIL_ADDRESS]",
    ),
    (re.compile(_D + r"\d{18}" + _E), "[MX_CLABE_BANCARIA]"),
    (
        re.compile(
            r"(?<![A-Za-z0-9])[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}"
            r"[A-Z0-9]\d(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
        "[MEXICO_CURP_NUMBER]",
    ),
    (
        re.compile(_D + r"(?:\d{4}[ -]?){3}\d{4}" + _E),
        "[CREDIT_CARD_NUMBER]",
    ),
    (
        re.compile(
            r"(?<![A-Za-z0-9])[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
        "[MX_RFC_TAX_ID]",
    ),
    (
        re.compile(
            r"(?:\+52[ -]?)\d{10}"
            + _E
            + r"|"
            + _D
            + r"\d{2}[ -]\d{4}[ -]\d{4}"
            + _E
            + r"|"
            + _D
            + r"\d{3}[ -]\d{3}[ -]\d{4}"
            + _E
        ),
        "[PHONE_NUMBER]",
    ),
)
_TEN_DIGITS = re.compile(_D + r"\d{10}" + _E)
_PHONE_CONTEXT = re.compile(
    r"tel|cel|llam|whats|marc|n[uú]mero|contacto", re.IGNORECASE
)
_ACCOUNT_CONTEXT = re.compile(r"cuenta|cta|clabe|dep[oó]sit", re.IGNORECASE)
_CONTEXT_WINDOW = 40


def count_pii_tokens(text: str | None) -> int:
    return len(_TOKEN_PATTERN.findall(text or ""))


def count_introduced_pii_tokens(
    original: str | None, sanitized: str | None
) -> int:
    """Tokens agregados por DLP/regex; los literales del usuario no cuentan."""
    return max(0, count_pii_tokens(sanitized) - count_pii_tokens(original))


def _nonce(length: int = 16) -> str:
    # Solo letras: ninguna regla numérica puede alterar un placeholder.
    return "".join(secrets.choice(string.ascii_letters) for _ in range(length))


def _letters(index: int) -> str:
    digits = string.ascii_lowercase
    out = ""
    while True:
        index, rest = divmod(index, 26)
        out = digits[rest] + out
        if not index:
            return out


class LocalRegexFallbackSanitizer:
    """Segunda barrera determinista; nunca sustituye a Cloud DLP en prod."""

    def __init__(self, nonce: str | None = None) -> None:
        self.nonce = nonce or _nonce()
        if not self.nonce.isalpha():
            raise ValueError("placeholder nonce must contain letters only")

    def _protect(self, text: str) -> tuple[str, dict[str, str]]:
        saved: dict[str, str] = {}

        def keep(match: re.Match[str]) -> str:
            key = f"__VOCKEEP{self.nonce}{_letters(len(saved))}__"
            saved[key] = match.group(0)
            return key

        text = DIAGNOSTIC_PATTERN.sub(keep, text)
        return _TOKEN_PATTERN.sub(keep, text), saved

    @staticmethod
    def _ten_digits(text: str) -> str:
        def label(match: re.Match[str]) -> str:
            before = text[
                max(0, match.start() - _CONTEXT_WINDOW) : match.start()
            ]
            phone = [m.end() for m in _PHONE_CONTEXT.finditer(before)]
            account = [m.end() for m in _ACCOUNT_CONTEXT.finditer(before)]
            # La palabra de contexto más cercana decide; por defecto, cuenta.
            if phone and (not account or phone[-1] > account[-1]):
                return "[PHONE_NUMBER]"
            return "[BBVA_ACCOUNT_NUMBER]"

        return _TEN_DIGITS.sub(label, text)

    def sanitize(self, text: str) -> str:
        protected, saved = self._protect(text)
        for pattern, token in _RULES:
            protected = pattern.sub(token, protected)
        protected = self._ten_digits(protected)
        for key, value in saved.items():
            protected = protected.replace(key, value)
        return protected


# --------------------------------------------------------------- packing
def _row_bytes(envelope: RawReviewEnvelope) -> int:
    return len(envelope.raw.texto.encode("utf-8"))


@dataclass(frozen=True)
class PackedBatches:
    batches: list[list[RawReviewEnvelope]]
    oversized: list[RawReviewEnvelope]


class DlpRowBatchPacker:
    """Sub-lotes de como máximo `max_rows` filas y `max_bytes` de texto."""

    def __init__(self, max_rows: int = 250, max_bytes: int = 400_000) -> None:
        if max_rows <= 0 or max_bytes <= 0:
            raise ValueError("DLP batch limits must be positive")
        self.max_rows = max_rows
        self.max_bytes = max_bytes

    def pack(self, envelopes: Iterable[RawReviewEnvelope]) -> PackedBatches:
        batches: list[list[RawReviewEnvelope]] = []
        oversized: list[RawReviewEnvelope] = []
        current: list[RawReviewEnvelope] = []
        size = 0
        for envelope in envelopes:
            row = _row_bytes(envelope)
            if row > self.max_bytes:
                oversized.append(envelope)
                continue
            if current and (
                len(current) >= self.max_rows or size + row > self.max_bytes
            ):
                batches.append(current)
                current, size = [], 0
            current.append(envelope)
            size += row
        if current:
            batches.append(current)
        return PackedBatches(batches, oversized)


# ------------------------------------------------------------- Cloud DLP
class DlpTransientError(RuntimeError):
    """DLP no disponible tras reintentos: los eventos no se confirman."""


class DlpConfigurationError(RuntimeError):
    """Permisos o plantillas inválidos: detener la corrida (fail-closed)."""


class DlpMisalignedError(RuntimeError):
    """La respuesta no coincide con el sidecar: no se usa ninguna fila."""


Row = tuple[str, str | None]


class Deidentifier(Protocol):
    def deidentify(self, rows: Sequence[Row]) -> list[Row]: ...


_TRANSIENT = (
    gexc.ResourceExhausted,
    gexc.ServiceUnavailable,
    gexc.DeadlineExceeded,
    gexc.InternalServerError,
)
_CONFIGURATION = (
    gexc.PermissionDenied,
    gexc.Unauthenticated,
    gexc.InvalidArgument,
    gexc.NotFound,
    gexc.FailedPrecondition,
)


class CloudDlpDeidentifier:
    """Tabla de 2 columnas de texto libre; los IDs nunca viajan a DLP."""

    def __init__(
        self,
        client: Any,
        *,
        parent: str,
        inspect_template: str,
        deidentify_template: str,
        attempts: int = 4,
        wait_max_sec: float = 16.0,
        timeout_sec: float = 60.0,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        for kind, name in (
            ("inspectTemplates", inspect_template),
            ("deidentifyTemplates", deidentify_template),
        ):
            if not name.startswith(f"{parent}/{kind}/"):
                raise DlpConfigurationError(
                    f"DLP {kind} must belong to {parent}"
                )
        if attempts <= 0 or wait_max_sec < 0 or timeout_sec <= 0:
            raise ValueError("invalid DLP retry policy")
        self.client = client
        self.parent = parent
        self.inspect_template = inspect_template
        self.deidentify_template = deidentify_template
        self.attempts = attempts
        self.wait_max_sec = wait_max_sec
        self.timeout_sec = timeout_sec
        self.sleep = sleep

    def _request(self, rows: Sequence[Row]) -> dict[str, Any]:
        return {
            "parent": self.parent,
            "inspect_template_name": self.inspect_template,
            "deidentify_template_name": self.deidentify_template,
            "item": {
                "table": {
                    "headers": [{"name": name} for name in DLP_COLUMNS],
                    "rows": [
                        {
                            "values": [
                                {"string_value": texto},
                                {"string_value": respuesta or ""},
                            ]
                        }
                        for texto, respuesta in rows
                    ],
                }
            },
        }

    def deidentify(self, rows: Sequence[Row]) -> list[Row]:
        if not rows:
            return []
        request = self._request(rows)
        options: dict[str, Any] = {
            "stop": stop_after_attempt(self.attempts),
            "wait": wait_exponential(multiplier=1, max=self.wait_max_sec),
            "retry": retry_if_exception_type(_TRANSIENT),
            "reraise": True,
        }
        if self.sleep is not None:
            options["sleep"] = self.sleep
        try:
            for attempt in Retrying(**options):
                with attempt:
                    response = self.client.deidentify_content(
                        request=request, retry=None, timeout=self.timeout_sec
                    )
        except _TRANSIENT:
            raise DlpTransientError("Cloud DLP unavailable") from None
        except _CONFIGURATION:
            raise DlpConfigurationError("Cloud DLP rejected request") from None
        result = response.item.table.rows
        if len(result) != len(rows) or any(
            len(row.values) != len(DLP_COLUMNS) for row in result
        ):
            raise DlpMisalignedError("DLP response differs from sidecar")
        out: list[Row] = []
        for (_, original_reply), row in zip(rows, result, strict=True):
            texto = row.values[0].string_value
            reply = row.values[1].string_value
            out.append((texto, reply if original_reply is not None else None))
        return out


# ------------------------------------------------------- batch sanitizer
@dataclass
class SanitizedBatch:
    valid: list[SanitizedReviewEnvelope] = field(default_factory=list)
    quarantined: list[ProcessingReceipt] = field(default_factory=list)
    retryable: list[ProcessingReceipt] = field(default_factory=list)


class BatchSanitizer:
    """Lógica pura por microbatch; el DoFn de Beam solo la envuelve."""

    def __init__(
        self,
        *,
        user_hash_salt: str,
        deidentifier: Deidentifier | None = None,
        use_cloud_dlp_api: bool = False,
        packer: DlpRowBatchPacker | None = None,
        fallback: LocalRegexFallbackSanitizer | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if use_cloud_dlp_api and deidentifier is None:
            raise DlpConfigurationError("Cloud DLP is required (fail-closed)")
        self.salt = user_hash_salt
        self.deidentifier = deidentifier if use_cloud_dlp_api else None
        self.packer = packer or DlpRowBatchPacker()
        self.fallback = fallback or LocalRegexFallbackSanitizer()
        self.clock = clock

    def _receipt(
        self,
        event: RawReviewEnvelope,
        status: ProcessingStatus,
        error_code: str | None = None,
    ) -> ProcessingReceipt:
        return ProcessingReceipt.from_event(
            event,
            receipt_id=event.event_id,
            status=status,
            processed_at=self.clock(),
            error_code=error_code,
        )

    def sanitize(
        self, envelopes: Sequence[RawReviewEnvelope]
    ) -> SanitizedBatch:
        out = SanitizedBatch()
        packed = self.packer.pack(envelopes)
        out.quarantined.extend(
            self._receipt(e, ProcessingStatus.QUARANTINED, DLP_ROW_TOO_LARGE)
            for e in packed.oversized
        )
        for batch in packed.batches:
            # La respuesta no se procesa ni se persiste: segunda celda vacía.
            rows: list[Row] = [(e.raw.texto, None) for e in batch]
            if self.deidentifier is not None:
                try:
                    rows = self.deidentifier.deidentify(rows)
                except (DlpTransientError, DlpMisalignedError) as exc:
                    code = (
                        DLP_MISALIGNED
                        if isinstance(exc, DlpMisalignedError)
                        else DLP_UNAVAILABLE
                    )
                    out.retryable.extend(
                        self._receipt(e, ProcessingStatus.RETRYABLE_ERROR, code)
                        for e in batch
                    )
                    continue
            for event, (texto, _) in zip(batch, rows, strict=True):
                self._finish(out, event, texto)
        return out

    def _finish(
        self,
        out: SanitizedBatch,
        event: RawReviewEnvelope,
        texto: str,
    ) -> None:
        texto = self.fallback.sanitize(texto)
        findings = count_introduced_pii_tokens(event.raw.texto, texto)
        # Minimización: título y respuesta no llegan al registro curado.
        raw = event.raw.model_copy(
            update={
                "titulo": None,
                "texto_respuesta": None,
                "fecha_respuesta": None,
            }
        )
        try:
            record = SanitizedReviewRecord.from_raw_and_dlp(
                raw,
                texto_sanitizado=texto,
                pii_findings_count=findings,
                user_hash_salt=self.salt,
            )
            out.valid.append(SanitizedReviewEnvelope.from_event(event, record))
        except (ValidationError, ValueError):
            out.quarantined.append(
                self._receipt(
                    event, ProcessingStatus.QUARANTINED, CONTRACT_VIOLATION
                )
            )


# ------------------------------------------------------------ Beam DoFn
def _default_dlp_client() -> Any:
    from google.cloud import dlp_v2

    return dlp_v2.DlpServiceClient()


class BatchCloudDlpDeidentifyDoFn(beam.DoFn):
    """Cada elemento es un microbatch (lista de RawReviewEnvelope).

    Salida principal: SanitizedReviewEnvelope. Salidas etiquetadas:
    recibos QUARANTINED y RETRYABLE_ERROR.
    """

    def __init__(
        self,
        *,
        user_hash_salt: str,
        parent: str,
        inspect_template: str | None,
        deidentify_template: str | None,
        use_cloud_dlp_api: bool = False,
        max_rows: int = 250,
        max_bytes: int = 400_000,
        client_factory: Callable[[], Any] = _default_dlp_client,
        retry_sleep: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__()
        self.user_hash_salt = user_hash_salt
        self.parent = parent
        self.inspect_template = inspect_template
        self.deidentify_template = deidentify_template
        self.use_cloud_dlp_api = use_cloud_dlp_api
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.client_factory = client_factory
        self.retry_sleep = retry_sleep
        self.sanitizer: BatchSanitizer | None = None

    def setup(self) -> None:
        deidentifier = None
        if self.use_cloud_dlp_api:
            if not self.inspect_template or not self.deidentify_template:
                raise DlpConfigurationError("DLP templates are required")
            deidentifier = CloudDlpDeidentifier(
                self.client_factory(),
                parent=self.parent,
                inspect_template=self.inspect_template,
                deidentify_template=self.deidentify_template,
                sleep=self.retry_sleep,
            )
        self.sanitizer = BatchSanitizer(
            user_hash_salt=self.user_hash_salt,
            deidentifier=deidentifier,
            use_cloud_dlp_api=self.use_cloud_dlp_api,
            packer=DlpRowBatchPacker(self.max_rows, self.max_bytes),
        )

    def process(self, element: Sequence[RawReviewEnvelope]) -> Iterator[Any]:
        if self.sanitizer is None:
            raise RuntimeError("DoFn used before setup")
        result = self.sanitizer.sanitize(list(element))
        yield from result.valid
        for tag, receipts in (
            (OUTPUT_TAG_QUARANTINED, result.quarantined),
            (OUTPUT_TAG_RETRYABLE_ERROR, result.retryable),
        ):
            for receipt in receipts:
                yield pvalue.TaggedOutput(tag, receipt)
