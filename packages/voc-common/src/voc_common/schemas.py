"""Contratos de datos estrictos (Pydantic v2) entre capas de BBVA VoC Analyzer.

Flujo de modelos:

    IngestionRequestPayload / SequentialBatchIngestionRequest
        -> PlayStoreRpcCursor (scraper propio ``batchexecute``)
        -> RawReviewEvent (Pub/Sub + staging GCS, **pre-DLP**)
        -> SanitizedReviewRecord (BigQuery TDS, **post-DLP**)
        -> AnalyzedReviewPrediction -> IncidentAlertMessage
        -> HitlTriageAuditRecord

``IngestionWatermarkState`` modela el checkpoint bidireccional persistido en
``gs://<bucket>/state/watermarks/{bank_id}.json``.

Todas las fechas se normalizan a UTC: las ``datetime`` *naive* se interpretan
como UTC y las *aware* se convierten a UTC.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from voc_common.constants import (
    BACKFILL_LOOKBACK_DAYS,
    DEFAULT_PLAYSTORE_COUNTRY,
    DEFAULT_PLAYSTORE_LANG,
    MAX_REVIEW_WORDS,
    MIN_REVIEW_WORDS,
    PLAYSTORE_MAX_PAGE_SIZE,
    UNKNOWN_APP_VERSION,
    WATERMARK_MAX_FRONTIER_IDS,
    ABSATopic,
    BankKey,
    IngestionMode,
    PlayStoreSortOrder,
    SentimentLabel,
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


def _add_bounded(ids: set[str], review_id: str) -> None:
    if len(ids) < WATERMARK_MAX_FRONTIER_IDS:
        ids.add(review_id)


class _StrictModel(BaseModel):
    """Base común: rechaza campos no declarados en el contrato."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Tarea 1.3.1: Solicitudes de ingesta y cursor RPC
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
        default=PLAYSTORE_MAX_PAGE_SIZE, ge=1, le=PLAYSTORE_MAX_PAGE_SIZE
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
# Tarea 1.3.2: Watermark bidireccional
# ---------------------------------------------------------------------------


class IngestionWatermarkState(_StrictModel):
    """Checkpoint bidireccional de extracción por banco.

    Nota de uso (INCREMENTAL): el scraper recorre de la reseña más nueva a la
    más antigua; ``should_stop_incremental`` debe evaluarse contra una copia
    congelada del estado al inicio de la ejecución
    (``state.model_copy(deep=True)``), porque ``update_bounds`` desplaza
    ``max_review_timestamp`` en cuanto se procesa la primera reseña nueva.
    """

    bank_id: BankKey
    app_id: str = Field(..., min_length=1)
    max_review_timestamp: UtcDatetime | None = None
    min_review_timestamp: UtcDatetime | None = None
    recent_review_ids: set[str] = Field(default_factory=set)
    oldest_review_ids: set[str] = Field(default_factory=set)
    oldest_page_token: str | None = None
    star_partition_tokens: dict[StarRating, str | None] = Field(
        default_factory=dict
    )
    backfill_one_year_completed: bool = False
    full_backfill_completed: bool = False
    total_extracted_count: int = Field(default=0, ge=0)
    updated_at: UtcDatetime = Field(default_factory=_utcnow)

    @field_serializer("recent_review_ids", "oldest_review_ids")
    def _serialize_id_sets(self, ids: set[str]) -> list[str]:
        # Orden determinista para checkpoints JSON reproducibles.
        return sorted(ids)

    def should_stop_incremental(
        self, review_id: str, review_date: datetime
    ) -> bool:
        """``True`` si la reseña ya fue extraída en una ejecución previa."""
        review_date = ensure_utc(review_date)
        if review_id in self.recent_review_ids:
            return True
        return (
            self.max_review_timestamp is not None
            and review_date < self.max_review_timestamp
        )

    def has_reached_one_year_backfill(
        self, review_date: datetime, reference_now: datetime | None = None
    ) -> bool:
        """``True`` si la reseña cae en o antes del corte de 365 días."""
        now = ensure_utc(reference_now) if reference_now else _utcnow()
        cutoff = now - timedelta(days=BACKFILL_LOOKBACK_DAYS)
        return ensure_utc(review_date) <= cutoff

    def update_bounds(
        self,
        review_id: str,
        review_date: datetime,
        next_page_token: str | None = None,
    ) -> None:
        """Desplaza las fronteras superior/inferior con una reseña extraída."""
        review_date = ensure_utc(review_date)

        if (
            self.max_review_timestamp is None
            or review_date > self.max_review_timestamp
        ):
            self.max_review_timestamp = review_date
            self.recent_review_ids = {review_id}
        elif review_date == self.max_review_timestamp:
            _add_bounded(self.recent_review_ids, review_id)

        if (
            self.min_review_timestamp is None
            or review_date < self.min_review_timestamp
        ):
            self.min_review_timestamp = review_date
            self.oldest_review_ids = {review_id}
        elif review_date == self.min_review_timestamp:
            _add_bounded(self.oldest_review_ids, review_id)

        if next_page_token is not None:
            self.oldest_page_token = next_page_token

        self.total_extracted_count += 1
        self.updated_at = _utcnow()

    def update_star_partition_token(
        self, star: int, next_page_token: str | None
    ) -> None:
        """Registra el token de continuación de una partición 1..5."""
        if not 1 <= star <= 5:
            raise ValueError(f"star debe estar en 1..5, se recibió {star}")
        self.star_partition_tokens[star] = next_page_token
        self.updated_at = _utcnow()


# ---------------------------------------------------------------------------
# Tarea 1.3.3: Carga cruda (pre-DLP)
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
# Tarea 1.3.4: Registro sanitizado (post-DLP, BigQuery TDS)
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
    texto_limpio: str = Field(..., min_length=1)
    conteo_palabras: int = Field(..., ge=MIN_REVIEW_WORDS, le=MAX_REVIEW_WORDS)
    pii_findings_count: int = Field(default=0, ge=0)
    estrellas: int = Field(..., ge=1, le=5)
    votos_utilidad: int = Field(default=0, ge=0)
    version_app: str = Field(default=UNKNOWN_APP_VERSION)
    fecha: UtcDatetime
    texto_respuesta_sanitizado: str | None = None
    fecha_respuesta: UtcDatetime | None = None
    sanitized_at: UtcDatetime = Field(default_factory=_utcnow)

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

        Lanza ``ValidationError`` si el texto limpio queda fuera de [2, 60]
        palabras.
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
        )


# ---------------------------------------------------------------------------
# Tarea 1.3.5: Predicción, alertas y auditoría HITL
# ---------------------------------------------------------------------------


class AnalyzedReviewPrediction(_StrictModel):
    """Salida del modelo DeLoRA para una reseña sanitizada."""

    id_resena: str = Field(..., min_length=1)
    bank_id: BankKey
    version_app: str
    fecha: UtcDatetime
    estrellas: int = Field(..., ge=1, le=5)
    votos_utilidad: int = Field(default=0, ge=0)
    sentimiento_roberta: SentimentLabel
    tnss_score: SentimentLabel
    tnss_numeric_calibrated: float = Field(..., ge=1.0, le=5.0)
    # Calculado automáticamente: estrellas >= 4 y tnss_score == NEG.
    is_obligatory_5_star_bias: bool = False
    topico: ABSATopic
    priority_weight_score: float = Field(..., ge=0.0)
    prediction_entropy: float = Field(..., ge=0.0, le=1.0)
    requires_hitl: bool
    embedding_vector: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def _compute_5_star_bias(self) -> Self:
        self.is_obligatory_5_star_bias = (
            self.estrellas >= 4 and self.tnss_score == SentimentLabel.NEG
        )
        return self


class IncidentAlertMessage(_StrictModel):
    """Alerta de pico de reseñas negativas por versión y tópico."""

    alert_id: str = Field(..., min_length=1)
    bank_id: BankKey
    version_app: str
    topico: ABSATopic
    negative_reviews_spike_count: int = Field(..., ge=1)
    accumulated_utility_votes: int = Field(..., ge=0)
    sample_review_ids: list[str]
    triggered_at: UtcDatetime = Field(default_factory=_utcnow)


class HitlTriageAuditRecord(_StrictModel):
    """Espejo de la tabla ``hitl_triage_audit_log`` (Épica 2)."""

    audit_id: str = Field(..., min_length=1)
    id_resena: str = Field(..., min_length=1)
    bank_id: BankKey
    original_tnss: SentimentLabel
    validated_tnss: SentimentLabel
    original_topic: ABSATopic
    validated_topic: ABSATopic
    reviewer_email_hash: str = Field(..., min_length=1)
    backlog_jira_ticket: str | None = None
    reviewed_at: UtcDatetime = Field(default_factory=_utcnow)
