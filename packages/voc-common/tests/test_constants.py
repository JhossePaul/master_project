"""Pruebas del catálogo de constantes de voc-common (Feature 1.1)."""

import json

import voc_common
from voc_common.constants import (
    BACKFILL_LOOKBACK_DAYS,
    DEFAULT_USER_AGENTS,
    MAX_REVIEW_WORDS,
    MIN_REVIEW_WORDS,
    PLAYSTORE_BANK_APPS,
    PLAYSTORE_BATCHEXECUTE_URL,
    PLAYSTORE_DEFAULT_PAGE_SIZE,
    PLAYSTORE_REVIEWS_RPC_ID,
    SENTIMENT_DISPLAY_MAP,
    ABSATopic,
    BankKey,
    IngestionMode,
    PlayStoreSortOrder,
    SentimentLabel,
)


def test_every_bank_has_playstore_app_id() -> None:
    assert set(PLAYSTORE_BANK_APPS) == set(BankKey)
    assert PLAYSTORE_BANK_APPS[BankKey.BBVA] == "com.bancomer.mbanking"
    # IDs corregidos tras la primera corrida real (`protocol_shape`): los
    # originales no existen en Google Play.
    assert PLAYSTORE_BANK_APPS[BankKey.AZTECA] == (
        "mx.com.bancoazteca.bazdigitalmovil"
    )
    assert PLAYSTORE_BANK_APPS[BankKey.BANORTE] == (
        "org.microemu.android.model.common.VTUserApplicationBNRTMB"
    )
    assert "baz.app.bancoazteca" not in PLAYSTORE_BANK_APPS.values()
    assert "com.banorte.movil" not in PLAYSTORE_BANK_APPS.values()
    assert len(set(PLAYSTORE_BANK_APPS.values())) == len(BankKey)


def test_str_enums_are_json_serializable() -> None:
    payload = json.dumps(
        {"bank": BankKey.NUBANK, "mode": IngestionMode.BACKFILL}
    )
    assert payload == '{"bank": "NUBANK", "mode": "BACKFILL"}'
    assert BankKey("BBVA") is BankKey.BBVA


def test_str_enum_renders_plain_value_in_paths() -> None:
    path = f"state/watermarks/{BankKey.BBVA}.json"
    assert path == "state/watermarks/BBVA.json"


def test_ingestion_modes() -> None:
    assert {m.value for m in IngestionMode} == {
        "INCREMENTAL",
        "BACKFILL",
        "FULL_BACKFILL",
    }


def test_playstore_sort_order_values() -> None:
    assert PlayStoreSortOrder.MOST_RELEVANT == 1
    assert PlayStoreSortOrder.NEWEST == 2
    assert PlayStoreSortOrder.RATING == 3


def test_sentiment_display_map_covers_all_labels() -> None:
    assert set(SENTIMENT_DISPLAY_MAP) == set(SentimentLabel)
    assert SENTIMENT_DISPLAY_MAP[SentimentLabel.NEG] == "Negativo"


def test_absa_topics_catalog() -> None:
    assert len(ABSATopic) == 8
    assert ABSATopic.BLOQUEO_SEGURIDAD_3702.value == "BLOQUEO_SEGURIDAD_3702"


def test_eda_and_rpc_constants() -> None:
    assert (MIN_REVIEW_WORDS, MAX_REVIEW_WORDS) == (2, 60)
    assert BACKFILL_LOOKBACK_DAYS == 365
    assert PLAYSTORE_BATCHEXECUTE_URL == (
        "https://play.google.com/_/PlayStoreUi/data/batchexecute"
    )
    assert PLAYSTORE_REVIEWS_RPC_ID == "oCPfdb"
    assert PLAYSTORE_DEFAULT_PAGE_SIZE == 199


def test_user_agents_pool() -> None:
    assert len(DEFAULT_USER_AGENTS) >= 4
    assert all(ua.startswith("Mozilla/5.0 (") for ua in DEFAULT_USER_AGENTS)
    assert all("  " not in ua for ua in DEFAULT_USER_AGENTS)


def test_public_api_exports() -> None:
    for name in voc_common.__all__:
        assert hasattr(voc_common, name)
