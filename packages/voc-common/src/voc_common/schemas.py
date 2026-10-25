"""Contratos de datos estrictos (Pydantic v2) entre capas de BBVA VoC Analyzer.

Flujo de modelos:

    IngestionRequestPayload / SequentialBatchIngestionRequest
        -> PlayStoreRpcCursor (scraper propio ``batchexecute``)
        -> RawReviewEvent (Pub/Sub + staging GCS, **pre-DLP**)
        -> SanitizedReviewRecord (BigQuery TDS, **post-DLP**)

Las salidas analíticas (predicciones, alertas de deriva y HITL) son los
contratos v3 de ``predictions_v3``, ``operations_v3``, ``policies`` y
``hitl_v3`` (EPIC-6, 6.1).

``IngestionWatermarkState`` describe el estado v2 persistido en
``gs://<bucket>/state/watermarks/{bank_id}.json``.

Todas las fechas se normalizan a UTC: las ``datetime`` *naive* se interpretan
como UTC y las *aware* se convierten a UTC.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from voc_common.constants import (
    BACKFILL_LOOKBACK_DAYS,
    DEFAULT_PLAYSTORE_COUNTRY,
    DEFAULT_PLAYSTORE_LANG,
    PLAYSTORE_BANK_APPS,
    PLAYSTORE_DEFAULT_PAGE_SIZE,
    PLAYSTORE_PAGE_SIZE_POLICY_LIMIT,
    UNKNOWN_APP_VERSION,
    BankKey,
    CoverageStatus,
    IngestionMode,
    PlayStoreSortOrder,
    ProcessingStatus,
    PublicationStatus,
    RecoveryStatus,
    RunAuditStatus,
    SanitizationStatus,
    ScanStatus,
)
from voc_common.text_utils import (
    contar_palabras,
    hash_username_pii,
    limpiar_texto_bancario,
)

# ---------------------------------------------------------------------------
# Helpers y tipos reutilizables
# ---------------------------------------------------------------------------


def ensure_utc(value: datetime) -> datetime:
    """Normaliza una ``datetime`` a UTC (las *naive* se asumen en UTC)."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utcnow() -> datetime:
    return datetime.now(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(ensure_utc)]
StarRating = Annotated[int, Field(ge=1, le=5)]


def _missing_to_none(value: Any) -> Any:
    """Convierte ``None``/``NaN``/``NaT`` (pandas) en ``None``."""
    if value is None or value != value:  # NaN y NaT no son iguales a sí mismos
        return None
    return value


def _dig(entry: Any, path: tuple[int, ...]) -> Any:
    """Navega índices anidados de la matriz JSON; ``None`` si no existe."""
    current = entry
    for index in path:
        if not isinstance(current, list | tuple) or index >= len(current):
            return None
        current = current[index]
    return current


def _from_epoch_seconds(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value, tz=UTC)


class _StrictModel(BaseModel):
    """Base común: rechaza campos no declarados en el contrato."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Solicitudes de ingesta y cursor RPC
# ---------------------------------------------------------------------------


class PlayStoreRpcCursor(_StrictModel):
    """Cursor de paginación del RPC ``oCPfdb`` de ``batchexecute``."""

    app_id: str = Field(..., min_length=1)
    lang: str = DEFAULT_PLAYSTORE_LANG
    country: str = DEFAULT_PLAYSTORE_COUNTRY
    sort_order: PlayStoreSortOrder = PlayStoreSortOrder.NEWEST
    # None consulta todas las estrellas; 1..5 particiona en FULL_BACKFILL.
    star_filter: int | None = Field(default=None, ge=1, le=5)
    # Cursor Base64 opaco devuelto por batchexecute.
    page_token: str | None = None


class IngestionRequestPayload(_StrictModel):
    """Solicitud de ingesta para un único banco."""

    bank_id: BankKey
    mode: IngestionMode = IngestionMode.INCREMENTAL
    page_size: int = Field(
        default=PLAYSTORE_DEFAULT_PAGE_SIZE,
        ge=1,
        le=PLAYSTORE_PAGE_SIZE_POLICY_LIMIT,
    )
    max_reviews_per_run: int = Field(default=5000, ge=1, le=250000)
    # Si es True en FULL_BACKFILL, extrae por separado 1, 2, 3, 4 y 5 estrellas.
    partition_by_stars: bool = False


class SequentialBatchIngestionRequest(_StrictModel):
    """Job Maestro Free Tier (``/api/v1/ingest/all``): bancos en secuencia."""

    banks: list[BankKey] = Field(default_factory=lambda: list(BankKey))
    mode: IngestionMode = IngestionMode.INCREMENTAL
    max_reviews_per_bank: int = Field(default=1000, ge=1, le=50000)
    inter_bank_delay_sec: float = Field(default=15.0, ge=1.0, le=120.0)


# ---------------------------------------------------------------------------
# Watermark bidireccional
# ---------------------------------------------------------------------------


class RawReviewEvent(_StrictModel):
    """Reseña cruda en tránsito hacia Pub/Sub / staging GCS (pre-DLP).

    Conserva ``usuario`` e ``imagen_usuario`` únicamente para que el pipeline
    de sanitización los hashee/descarte; nunca debe persistirse en BigQuery.
    """

    id_resena: str = Field(..., min_length=1)
    bank_id: BankKey
    app_id: str = Field(..., min_length=1)
    usuario: str = Field(..., min_length=1)
    imagen_usuario: str | None = None
    titulo: str | None = None
    texto: str = Field(..., min_length=1)
    estrellas: int = Field(..., ge=1, le=5)
    fecha: datetime
    version_app: str = Field(default=UNKNOWN_APP_VERSION)
    votos_utilidad: int = Field(default=0, ge=0)
    texto_respuesta: str | None = None
    fecha_respuesta: UtcDatetime | None = None
    ingested_at: UtcDatetime = Field(default_factory=_utcnow)

    @field_validator("fecha")
    @classmethod
    def _fecha_to_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("version_app", mode="before")
    @classmethod
    def _normalize_version_app(cls, value: Any) -> Any:
        value = _missing_to_none(value)
        if value is None or (isinstance(value, str) and not value.strip()):
            return UNKNOWN_APP_VERSION
        return value

    @classmethod
    def from_playstore_dict(
        cls, raw_dict: dict[str, Any], bank_id: BankKey, app_id: str
    ) -> Self:
        """Traduce un dict con llaves estilo ``google-play-scraper``.

        Ignora ``appVersion`` (duplicado de ``reviewCreatedVersion``) y fija
        ``titulo=None`` (Google Play no expone títulos de reseña).
        """

        def get(key: str) -> Any:
            return _missing_to_none(raw_dict.get(key))

        return cls.model_validate(
            {
                "id_resena": get("reviewId"),
                "bank_id": bank_id,
                "app_id": app_id,
                "usuario": get("userName"),
                "imagen_usuario": get("userImage"),
                "titulo": None,
                "texto": get("content"),
                "estrellas": get("score"),
                "fecha": get("at"),
                "version_app": get("reviewCreatedVersion"),
                "votos_utilidad": get("thumbsUpCount") or 0,
                "texto_respuesta": get("replyContent"),
                "fecha_respuesta": get("repliedAt"),
            }
        )

    @classmethod
    def from_batchexecute_entry(
        cls, raw_entry: list[Any], bank_id: BankKey, app_id: str
    ) -> Self:
        """Parsea una fila cruda de la matriz JSON del RPC ``oCPfdb``.

        Índices de la fila (protocolo interno de Google Play):

        ========================  ==================
        Campo                     Ruta
        ========================  ==================
        reviewId                  ``[0]``
        userName                  ``[1][0]``
        userImage                 ``[1][1][3][2]``
        score                     ``[2]``
        content                   ``[4]``
        at (epoch seg.)           ``[5][0]``
        thumbsUpCount             ``[6]``
        replyContent              ``[7][1]``
        repliedAt (epoch seg.)    ``[7][2][0]``
        reviewCreatedVersion      ``[10]``
        ========================  ==================
        """
        return cls.model_validate(
            {
                "id_resena": _dig(raw_entry, (0,)),
                "bank_id": bank_id,
                "app_id": app_id,
                "usuario": _dig(raw_entry, (1, 0)),
                "imagen_usuario": _dig(raw_entry, (1, 1, 3, 2)),
                "titulo": None,
                "texto": _dig(raw_entry, (4,)),
                "estrellas": _dig(raw_entry, (2,)),
                "fecha": _from_epoch_seconds(_dig(raw_entry, (5, 0))),
                "version_app": _dig(raw_entry, (10,)),
                "votos_utilidad": _dig(raw_entry, (6,)) or 0,
                "texto_respuesta": _dig(raw_entry, (7, 1)),
                "fecha_respuesta": _from_epoch_seconds(
                    _dig(raw_entry, (7, 2, 0))
                ),
            }
        )


# ---------------------------------------------------------------------------
# Registro sanitizado (post-DLP, BigQuery TDS)
# ---------------------------------------------------------------------------


class SanitizedReviewRecord(_StrictModel):
    """Registro curado de ``sanitized_reviews_tds`` (post-DLP).

    No existen campos ``usuario`` ni ``imagen_usuario``: ``extra="forbid"``
    impide reintroducirlos.
    """

    id_resena: str = Field(..., min_length=1)
    bank_id: BankKey
    app_id: str = Field(..., min_length=1)
    usuario_hash: str = Field(
        ..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    titulo: str | None = None
    texto_sanitizado: str = Field(..., min_length=1)
    # Sin filtro de longitud: el TDS conserva toda reseña con texto. El rango
    # del EDA (2 a 60 palabras) se aplica al analizar, con `conteo_palabras`.
    texto_limpio: str = Field(default="")
    conteo_palabras: int = Field(..., ge=0)
    pii_findings_count: int = Field(default=0, ge=0)
    estrellas: int = Field(..., ge=1, le=5)
    votos_utilidad: int = Field(default=0, ge=0)
    version_app: str = Field(default=UNKNOWN_APP_VERSION)
    fecha: UtcDatetime
    texto_respuesta_sanitizado: str | None = None
    fecha_respuesta: UtcDatetime | None = None
    sanitized_at: UtcDatetime = Field(default_factory=_utcnow)
    # Tiempo de captura en el origen (ingested_at del sobre crudo). Ordena
    # revisiones con igual ``fecha`` en el MERGE; sanitized_at es de proceso.
    source_observed_at: UtcDatetime

    @model_validator(mode="after")
    def _check_word_count_matches(self) -> Self:
        actual = contar_palabras(self.texto_limpio)
        if actual != self.conteo_palabras:
            raise ValueError(
                f"conteo_palabras={self.conteo_palabras} no coincide con "
                f"las {actual} palabras de texto_limpio"
            )
        return self

    @classmethod
    def from_raw_and_dlp(
        cls,
        raw: RawReviewEvent,
        texto_sanitizado: str,
        pii_findings_count: int,
        user_hash_salt: str,
        texto_respuesta_sanitizado: str | None = None,
    ) -> Self:
        """Construye el registro TDS a partir del evento crudo y la salida DLP.

        No filtra por longitud: toda reseña con texto produce un registro.
        """
        texto_limpio = limpiar_texto_bancario(texto_sanitizado)
        return cls(
            id_resena=raw.id_resena,
            bank_id=raw.bank_id,
            app_id=raw.app_id,
            usuario_hash=hash_username_pii(raw.usuario, user_hash_salt),
            titulo=raw.titulo,
            texto_sanitizado=texto_sanitizado,
            texto_limpio=texto_limpio,
            conteo_palabras=contar_palabras(texto_limpio),
            pii_findings_count=pii_findings_count,
            estrellas=raw.estrellas,
            votos_utilidad=raw.votos_utilidad,
            version_app=raw.version_app,
            fecha=raw.fecha,
            texto_respuesta_sanitizado=texto_respuesta_sanitizado,
            fecha_respuesta=raw.fecha_respuesta,
            source_observed_at=raw.ingested_at,
        )


# Contratos v2. El reducer y la escritura en GCS viven en sus servicios.
NonEmpty = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Counter = Annotated[int, Field(ge=0)]


class _StateV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[2] = 2


class _BankStateV2(_StateV2):
    bank_id: BankKey
    app_id: NonEmpty

    @model_validator(mode="after")
    def _bank_app(self) -> Self:
        if PLAYSTORE_BANK_APPS[self.bank_id] != self.app_id:
            raise ValueError("app_id does not match bank_id")
        return self


class LedgerReference(_StateV2):
    """Índice paginado completo; count no es una prueba de cobertura."""

    uri: Annotated[str, Field(pattern=r"^gs://[^/]+/.+")]
    generation: Annotated[int, Field(gt=0)]
    entry_count: Counter
    content_fingerprint: Digest


class ScanContext(_StateV2):
    app_id: NonEmpty
    lang: NonEmpty = DEFAULT_PLAYSTORE_LANG
    country: NonEmpty = DEFAULT_PLAYSTORE_COUNTRY
    sort_order: PlayStoreSortOrder = PlayStoreSortOrder.NEWEST
    star_filter: StarRating | None = None
    device_filter: NonEmpty | None = None
    page_size: Annotated[int, Field(gt=0)] = PLAYSTORE_DEFAULT_PAGE_SIZE
    protocol_version: NonEmpty

    @property
    def fingerprint(self) -> str:
        """Calcula el fingerprint del contexto completo."""
        payload = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class CompletionEvidence(_StateV2):
    coverage: CoverageStatus = CoverageStatus.UNVERIFIED
    checked_at: UtcDatetime
    manifest_ids: tuple[NonEmpty, ...] = ()
    boundary_ledger: LedgerReference | None = None
    source_exhausted_observed: bool = False
    continuity_checked: bool = False
    gaps_detected: bool = False

    @model_validator(mode="after")
    def _evidence(self) -> Self:
        if self.coverage == CoverageStatus.TRAVERSAL_OBSERVED and (
            not self.manifest_ids
            or not self.continuity_checked
            or self.gaps_detected
        ):
            raise ValueError("observed traversal requires continuity evidence")
        if (
            self.coverage == CoverageStatus.GAPS_DETECTED
            and not self.gaps_detected
        ):
            raise ValueError("gap coverage requires recorded gaps")
        return self


class PlanExtensionEvent(_StateV2):
    event_id: NonEmpty
    extended_at: UtcDatetime
    previous_lower_at: UtcDatetime
    requested_lower_at: None = None

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.previous_lower_at > self.extended_at:
            raise ValueError("extension cannot precede its former lower bound")
        return self


class IncrementalProgress(_StateV2):
    committed_high_at: UtcDatetime | None = None
    frontier_ledger: LedgerReference | None = None
    active_run_id: NonEmpty | None = None
    baseline_high_at: UtcDatetime | None = None
    candidate_high_at: UtcDatetime | None = None
    replay_from_at: UtcDatetime | None = None
    status: ScanStatus = ScanStatus.NOT_STARTED
    stream_id: NonEmpty | None = None

    @model_validator(mode="after")
    def _frontier(self) -> Self:
        if (self.committed_high_at is None) != (self.frontier_ledger is None):
            raise ValueError("committed frontier requires timestamp and ledger")
        if self.replay_from_at is not None and (
            self.committed_high_at is None
            or self.replay_from_at > self.committed_high_at
        ):
            raise ValueError(
                "replay must start at or before committed frontier"
            )
        if self.candidate_high_at is not None and (
            self.baseline_high_at is not None
            and self.candidate_high_at < self.baseline_high_at
        ):
            raise ValueError("candidate cannot precede baseline")
        if self.status == ScanStatus.RUNNING and (
            self.active_run_id is None or self.stream_id is None
        ):
            raise ValueError("running incremental requires run and stream")
        return self


class HistoricalPlan(_BankStateV2):
    plan_id: NonEmpty
    started_at: UtcDatetime
    upper_anchor_at: UtcDatetime
    requested_lower_at: UtcDatetime | None
    stream_ids: tuple[NonEmpty, ...] = ()
    status: ScanStatus = ScanStatus.NOT_STARTED
    completion_evidence: CompletionEvidence | None = None
    extension_events: tuple[PlanExtensionEvent, ...] = ()

    @model_validator(mode="after")
    def _plan(self) -> Self:
        if self.upper_anchor_at != self.started_at:
            raise ValueError("upper anchor must be frozen at plan start")
        cutoff = self.started_at - timedelta(days=BACKFILL_LOOKBACK_DAYS)
        if self.requested_lower_at not in (None, cutoff):
            raise ValueError("annual lower bound must equal T0 minus 365 days")
        if len(set(self.stream_ids)) != len(self.stream_ids):
            raise ValueError("duplicate stream references")
        if self.extension_events:
            if self.requested_lower_at is not None:
                raise ValueError(
                    "extended FULL plan cannot retain annual target"
                )
            for event in self.extension_events:
                if (
                    event.previous_lower_at != cutoff
                    or event.extended_at < self.started_at
                ):
                    raise ValueError(
                        "extension must preserve original annual cut"
                    )
        if self.status in (
            ScanStatus.TARGET_REACHED,
            ScanStatus.SOURCE_EXHAUSTED_OBSERVED,
        ):
            evidence = self.completion_evidence
            if (
                not self.stream_ids
                or evidence is None
                or evidence.coverage != CoverageStatus.TRAVERSAL_OBSERVED
            ):
                raise ValueError("completed plan requires traversal evidence")
            if self.status == ScanStatus.TARGET_REACHED and (
                self.requested_lower_at is None
            ):
                raise ValueError("FULL has no finite target")
            if (
                self.status == ScanStatus.SOURCE_EXHAUSTED_OBSERVED
                and not evidence.source_exhausted_observed
            ):
                raise ValueError("source exhaustion requires explicit evidence")
        return self


class ScanStreamState(_BankStateV2):
    stream_id: NonEmpty
    plan_id: NonEmpty | None = None
    context: ScanContext
    chain_epoch: Counter = 0
    status: ScanStatus = ScanStatus.NOT_STARTED
    frontier_page_id: NonEmpty | None = None
    frontier_oldest_at: UtcDatetime | None = None
    anchor_page_id: NonEmpty | None = None
    input_token: NonEmpty | None = Field(default=None, repr=False)
    output_token: NonEmpty | None = Field(default=None, repr=False)
    last_success_at: UtcDatetime | None = None
    recovery_status: RecoveryStatus = RecoveryStatus.NONE
    committed_pages: Counter = 0
    committed_reviews: Counter = 0
    frontier_ordinal: Counter | None = None

    @model_validator(mode="after")
    def _context(self) -> Self:
        if self.context.app_id != self.app_id:
            raise ValueError("stream and context apps differ")
        if (self.frontier_page_id is None) != (self.frontier_oldest_at is None):
            raise ValueError("frontier page and date must be paired")
        if self.status == ScanStatus.NOT_STARTED and any(
            x is not None
            for x in (
                self.frontier_page_id,
                self.anchor_page_id,
                self.input_token,
                self.output_token,
                self.last_success_at,
            )
        ):
            raise ValueError("unstarted stream cannot have progress")
        if self.status == ScanStatus.SOURCE_EXHAUSTED_OBSERVED and (
            self.output_token is not None or self.last_success_at is None
        ):
            raise ValueError("observed EOF requires success and no next cursor")
        return self


class PageManifest(_BankStateV2):
    """Versión inmutable; page_id no se deriva del token de paginación."""

    page_id: NonEmpty
    manifest_version: Annotated[int, Field(gt=0)] = 1
    fetch_attempt_id: NonEmpty
    run_id: NonEmpty
    plan_id: NonEmpty | None = None
    stream_id: NonEmpty
    chain_epoch: Counter
    ordinal: Counter
    previous_page_id: NonEmpty | None = None
    context: ScanContext
    input_token: NonEmpty | None = Field(default=None, repr=False)
    output_token: NonEmpty | None = Field(default=None, repr=False)
    fetched_at: UtcDatetime
    observed_min_at: UtcDatetime | None = None
    observed_max_at: UtcDatetime | None = None
    ledger: LedgerReference
    discard_ledger: LedgerReference | None = None
    raw_count: Counter
    valid_count: Counter
    discarded_count: Counter
    published_count: Counter = 0
    content_fingerprint: Digest
    backup_uri: Annotated[str, Field(pattern=r"^gs://[^/]+/.+")]
    backup_generation: Annotated[int, Field(gt=0)]
    publication_status: PublicationStatus = PublicationStatus.PENDING
    sanitization_status: SanitizationStatus = SanitizationStatus.PENDING
    source_evidence: CompletionEvidence | None = None

    @model_validator(mode="after")
    def _page(self) -> Self:
        if self.context.app_id != self.app_id:
            raise ValueError("page and context apps differ")
        if self.discard_ledger is not None and (
            self.discard_ledger.entry_count != self.discarded_count
        ):
            raise ValueError("discard ledger must contain all discarded rows")
        if self.raw_count != self.valid_count + self.discarded_count:
            raise ValueError("raw count must equal valid plus discarded")
        if self.ledger.entry_count != self.valid_count:
            raise ValueError("ledger must contain all accepted revisions")
        if self.published_count > self.valid_count:
            raise ValueError("published exceeds valid count")
        if self.publication_status == PublicationStatus.PUBLISHED and (
            self.published_count != self.valid_count
        ):
            raise ValueError("publication incomplete")
        if self.publication_status == PublicationStatus.PENDING and (
            self.published_count != 0
        ):
            raise ValueError("pending publication cannot have confirmations")
        if self.publication_status == PublicationStatus.PARTIAL and not (
            0 < self.published_count < self.valid_count
        ):
            raise ValueError(
                "partial publication requires partial confirmations"
            )
        if (self.observed_min_at is None) != (self.observed_max_at is None):
            raise ValueError("page bounds must be paired")
        if self.valid_count and self.observed_min_at is None:
            raise ValueError("valid reviews require observed bounds")
        if (
            self.observed_min_at is not None
            and self.observed_max_at is not None
            and self.observed_min_at > self.observed_max_at
        ):
            raise ValueError("reversed page bounds")
        return self


class ProcessingReceipt(_BankStateV2):
    receipt_id: NonEmpty
    event_id: Digest
    review_id: NonEmpty
    source_revision: Digest
    page_id: NonEmpty
    status: ProcessingStatus
    result_digest: Digest | None = None
    bigquery_job_ids: tuple[NonEmpty, ...] = ()
    error_code: NonEmpty | None = None
    processed_at: UtcDatetime

    @model_validator(mode="after")
    def _outcome(self) -> Self:
        if self.event_id != compute_event_id(
            self.bank_id,
            self.review_id,
            self.source_revision,
        ):
            raise ValueError("receipt event identity mismatch")
        if self.status == ProcessingStatus.TDS_COMMITTED and (
            self.result_digest is None or not self.bigquery_job_ids
        ):
            raise ValueError("TDS receipt requires durable result and job IDs")
        if (
            self.status
            in (ProcessingStatus.QUARANTINED, ProcessingStatus.RETRYABLE_ERROR)
            and self.error_code is None
        ):
            raise ValueError("failed outcome requires coded reason")
        return self

    @classmethod
    def from_event(
        cls,
        event: "RawReviewEnvelope",
        *,
        receipt_id: str,
        status: ProcessingStatus,
        processed_at: datetime,
        result_digest: str | None = None,
        bigquery_job_ids: tuple[str, ...] = (),
        error_code: str | None = None,
    ) -> Self:
        """Propaga la identidad, sin copiar textos ni usuarios al recibo."""
        return cls(
            receipt_id=receipt_id,
            event_id=event.event_id,
            bank_id=event.bank_id,
            app_id=event.app_id,
            review_id=event.review_id,
            source_revision=event.source_revision,
            page_id=event.page_id,
            status=status,
            processed_at=processed_at,
            result_digest=result_digest,
            bigquery_job_ids=bigquery_job_ids,
            error_code=error_code,
        )


class IngestionWatermarkState(_BankStateV2):
    """Raíz compacta del estado; el reducer avanza por página confirmada."""

    revision: Counter = 0
    updated_at: UtcDatetime = Field(default_factory=_utcnow)
    observed_min_at: UtcDatetime | None = None
    observed_max_at: UtcDatetime | None = None
    incremental: IncrementalProgress = Field(
        default_factory=IncrementalProgress
    )
    historical_plan_ids: tuple[NonEmpty, ...] = ()
    stream_ids: tuple[NonEmpty, ...] = ()
    manifest_ledger: LedgerReference | None = None
    coverage: CoverageStatus = CoverageStatus.UNVERIFIED

    @model_validator(mode="after")
    def _bounds(self) -> Self:
        if (self.observed_min_at is None) != (self.observed_max_at is None):
            raise ValueError("observed bounds must be paired")
        if (
            self.observed_min_at is not None
            and self.observed_max_at is not None
            and self.observed_min_at > self.observed_max_at
        ):
            raise ValueError("reversed observed bounds")
        if len(set(self.historical_plan_ids)) != len(
            self.historical_plan_ids
        ) or len(set(self.stream_ids)) != len(self.stream_ids):
            raise ValueError("duplicate references")
        if self.coverage != CoverageStatus.UNVERIFIED and (
            self.manifest_ledger is None
        ):
            raise ValueError("coverage requires manifest evidence")
        if (
            self.incremental.stream_id is not None
            and self.incremental.stream_id not in self.stream_ids
        ):
            raise ValueError("incremental stream missing from root references")
        return self


def _content_digest(value: Any) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_source_revision(raw: RawReviewEvent) -> str:
    """Digest de contenido normalizado del origen, sin timestamp de captura."""
    return _content_digest(raw.model_dump(mode="json", exclude={"ingested_at"}))


def compute_event_id(
    bank_id: BankKey,
    review_id: str,
    source_revision: str,
) -> str:
    """Identidad estable entre páginas, ejecuciones y redeliveries."""
    return _content_digest([bank_id.value, review_id, source_revision])


class RawReviewSnapshot(RawReviewEvent):
    """Copia inmutable del contenido usado para calcular la identidad."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class _ReviewEnvelopeV2(_BankStateV2):
    event_id: Digest
    review_id: NonEmpty
    source_revision: Digest
    page_id: NonEmpty
    plan_id: NonEmpty | None = None
    stream_id: NonEmpty

    @model_validator(mode="after")
    def _event_identity(self) -> Self:
        expected = compute_event_id(
            self.bank_id,
            self.review_id,
            self.source_revision,
        )
        if self.event_id != expected:
            raise ValueError("event_id does not match bank/review/revision")
        return self


class RawReviewEnvelope(_ReviewEnvelopeV2):
    """Sobre pre-DLP v2; ingested_at y page_id no modifican su identidad."""

    raw: RawReviewSnapshot = Field(repr=False)

    @model_validator(mode="after")
    def _source(self) -> Self:
        if (self.raw.bank_id, self.raw.app_id, self.raw.id_resena) != (
            self.bank_id,
            self.app_id,
            self.review_id,
        ):
            raise ValueError("raw payload identity differs from envelope")
        if self.source_revision != compute_source_revision(self.raw):
            raise ValueError("source_revision differs from raw content")
        return self

    @classmethod
    def from_raw(
        cls,
        raw: RawReviewEvent,
        *,
        page_id: str,
        stream_id: str,
        plan_id: str | None = None,
    ) -> Self:
        revision = compute_source_revision(raw)
        return cls(
            bank_id=raw.bank_id,
            app_id=raw.app_id,
            review_id=raw.id_resena,
            source_revision=revision,
            event_id=compute_event_id(raw.bank_id, raw.id_resena, revision),
            page_id=page_id,
            stream_id=stream_id,
            plan_id=plan_id,
            raw=RawReviewSnapshot.model_validate(raw.model_dump()),
        )


class SanitizedReviewSnapshot(SanitizedReviewRecord):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SanitizedReviewEnvelope(_ReviewEnvelopeV2):
    """Resultado sanitizado con identidad de origen, sin payload crudo."""

    record: SanitizedReviewSnapshot

    @model_validator(mode="after")
    def _record_identity(self) -> Self:
        if (self.record.bank_id, self.record.app_id, self.record.id_resena) != (
            self.bank_id,
            self.app_id,
            self.review_id,
        ):
            raise ValueError("sanitized identity differs from envelope")
        return self

    @classmethod
    def from_event(
        cls,
        event: RawReviewEnvelope,
        record: SanitizedReviewRecord,
    ) -> Self:
        for name in ("fecha", "estrellas", "votos_utilidad", "version_app"):
            if getattr(record, name) != getattr(event.raw, name):
                raise ValueError("sanitized source metadata changed")
        if record.source_observed_at != event.raw.ingested_at:
            raise ValueError("sanitized record must keep source observation")
        return cls(
            **event.model_dump(exclude={"raw"}),
            record=SanitizedReviewSnapshot.model_validate(record.model_dump()),
        )


class IngestionRunAudit(_BankStateV2):
    """Contrato de tabla ingestion_runs_log_v2 (la crea ``infra``)."""

    audit_event_id: NonEmpty
    run_id: NonEmpty
    mode_executed: IngestionMode
    status: RunAuditStatus
    updated_at: UtcDatetime
    plan_id: NonEmpty | None = None
    stream_id: NonEmpty | None = None
    reason: NonEmpty | None = None
    state_revision: Counter | None = None
    committed_high_at: UtcDatetime | None = None
    observed_min_at: UtcDatetime | None = None
    observed_max_at: UtcDatetime | None = None
    pages_committed: Counter | None = None
    reviews_extracted: Counter | None = None
    reviews_published: Counter | None = None
    reviews_discarded: Counter | None = None
    recovery_requests: Counter | None = None

    @model_validator(mode="after")
    def _audit_bounds(self) -> Self:
        if (
            self.observed_min_at is not None
            and self.observed_max_at is not None
            and self.observed_min_at > self.observed_max_at
        ):
            raise ValueError("reversed audit observations")
        if self.reviews_extracted is not None:
            outcomes = (self.reviews_published or 0) + (
                self.reviews_discarded or 0
            )
            if outcomes > self.reviews_extracted:
                raise ValueError("audit outcomes exceed extraction count")
        return self
