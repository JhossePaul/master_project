"""Catálogo de constantes y enumeraciones compartidas de BBVA VoC Analyzer.

Incluye:
    * Bancos monitoreados y sus ``app_id`` en Google Play.
    * Modos de ingesta (incremental, backfill de 1 año y backfill total).
    * Parámetros del protocolo interno de Google Play (``batchexecute`` RPC).
    * Etiquetas de sentimiento y tópicos ABSA.
    * Umbrales derivados del EDA (filtrado de colas pesadas).
"""

from enum import Enum, StrEnum


class BankKey(StrEnum):
    """Instituciones bancarias monitoreadas."""

    BBVA = "BBVA"
    NUBANK = "NUBANK"
    SANTANDER = "SANTANDER"
    AZTECA = "AZTECA"
    BANORTE = "BANORTE"


PLAYSTORE_BANK_APPS: dict[BankKey, str] = {
    BankKey.BBVA: "com.bancomer.mbanking",
    BankKey.NUBANK: "com.nu.production",
    BankKey.SANTANDER: "mx.bancosantander.supermovil",
    # Corregidos el 2026-10-15: los IDs originales (`baz.app.bancoazteca`,
    # `com.banorte.movil`) no existen en Google Play y la primera corrida real
    # falló con `protocol_shape`. BBVA, Nu y Santander se validaron con datos.
    BankKey.AZTECA: "mx.com.bancoazteca.bazdigitalmovil",
    BankKey.BANORTE: (
        "org.microemu.android.model.common.VTUserApplicationBNRTMB"
    ),
}


class IngestionMode(StrEnum):
    """Modos de extracción soportados por el scraper propio."""

    # Extrae novedades hasta tocar max_review_timestamp
    INCREMENTAL = "INCREMENTAL"
    # Extrae hacia el pasado hasta (hoy - 365 dias)
    BACKFILL = "BACKFILL"
    # Extrae hacia el pasado hasta agotar tokens en Play Store
    FULL_BACKFILL = "FULL_BACKFILL"


class PlayStoreSortOrder(int, Enum):
    """Criterio de ordenamiento aceptado por el RPC ``oCPfdb``."""

    MOST_RELEVANT = 1
    NEWEST = 2
    RATING = 3


class SentimentLabel(StrEnum):
    """Etiquetas de sentimiento producidas por los modelos."""

    NEG = "NEG"
    NEU = "NEU"
    POS = "POS"


SENTIMENT_DISPLAY_MAP: dict[SentimentLabel, str] = {
    SentimentLabel.NEG: "Negativo",
    SentimentLabel.NEU: "Neutral",
    SentimentLabel.POS: "Positivo",
}


class ABSATopic(StrEnum):
    """Tópicos del análisis de sentimiento basado en aspectos (ABSA)."""

    BIOMETRIA_RECONOCIMIENTO = "BIOMETRIA_RECONOCIMIENTO"
    BLOQUEO_SEGURIDAD_3702 = "BLOQUEO_SEGURIDAD_3702"
    TRANSFERENCIAS_SPEI = "TRANSFERENCIAS_SPEI"
    RENDIMIENTO_CRASH_POST_RELEASE = "RENDIMIENTO_CRASH_POST_RELEASE"
    SALDOS_Y_APARTADOS = "SALDOS_Y_APARTADOS"
    # Etiqueta de tópico, no una credencial (falso positivo de B105/S105).
    TOKEN_Y_NOTIFICACIONES = "TOKEN_Y_NOTIFICACIONES"  # noqa: S105  # nosec B105
    UX_INTERFAZ_Y_PUBLICIDAD = "UX_INTERFAZ_Y_PUBLICIDAD"
    OTROS_SERVICIOS_GENERALES = "OTROS_SERVICIOS_GENERALES"


# Constantes del EDA (Filtrado de Colas Pesadas)
MIN_REVIEW_WORDS: int = 2
MAX_REVIEW_WORDS: int = 60
BACKFILL_LOOKBACK_DAYS: int = 365

# Normalización de reseñas
UNKNOWN_APP_VERSION: str = "UNKNOWN"

# Constantes del Protocolo Interno Google Play (batchexecute RPC)
PLAYSTORE_BATCHEXECUTE_URL: str = (
    "https://play.google.com/_/PlayStoreUi/data/batchexecute"
)
PLAYSTORE_REVIEWS_RPC_ID: str = "oCPfdb"
# Política local conservadora; no describe un máximo nativo del endpoint.
PLAYSTORE_DEFAULT_PAGE_SIZE: int = 199
PLAYSTORE_PAGE_SIZE_POLICY_LIMIT: int = 199
DEFAULT_PLAYSTORE_LANG: str = "es"
DEFAULT_PLAYSTORE_COUNTRY: str = "mx"

# Pool de User-Agents modernos para rotación Anti-Throttling
DEFAULT_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6_1) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.6; rv:129.0) "
    "Gecko/20100101 Firefox/129.0",
)


class ScanStatus(StrEnum):
    """Estado explícito: un cursor nulo no expresa inicio ni agotamiento."""

    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    TARGET_REACHED = "TARGET_REACHED"
    SOURCE_EXHAUSTED_OBSERVED = "SOURCE_EXHAUSTED_OBSERVED"
    BLOCKED = "BLOCKED"


class CoverageStatus(StrEnum):
    """Evidencia observada, nunca garantía de exhaustividad del origen."""

    UNVERIFIED = "UNVERIFIED"
    TRAVERSAL_OBSERVED = "TRAVERSAL_OBSERVED"
    GAPS_DETECTED = "GAPS_DETECTED"


class RecoveryStatus(StrEnum):
    NONE = "NONE"
    ANCHOR_REPLAY = "ANCHOR_REPLAY"
    EARLIER_ANCHOR = "EARLIER_ANCHOR"
    HEAD_RESCAN = "HEAD_RESCAN"
    BLOCKED = "BLOCKED"


class PublicationStatus(StrEnum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    PUBLISHED = "PUBLISHED"


class ProcessingStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    TDS_COMMITTED = "TDS_COMMITTED"
    FILTERED_LENGTH = "FILTERED_LENGTH"
    QUARANTINED = "QUARANTINED"
    RETRYABLE_ERROR = "RETRYABLE_ERROR"


class SanitizationStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    RESOLVED = "RESOLVED"
    GAPS_DETECTED = "GAPS_DETECTED"


class RunAuditStatus(StrEnum):
    """Eventos de auditoría; no sustituyen los estados transaccionales GCS."""

    STARTED = "STARTED"
    PAUSED = "PAUSED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
