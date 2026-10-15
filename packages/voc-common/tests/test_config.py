"""Pruebas de la configuración centralizada de voc-common (Feature 1.4)."""

import importlib
from collections.abc import Iterator
from pathlib import Path

import pytest
import voc_common
from pydantic import ValidationError
from voc_common.config import DEV_USER_HASH_SALT, Settings, get_settings

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_EXAMPLE = _REPO_ROOT / ".env.example"


@pytest.fixture(autouse=True)
def _isolated_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    """Aísla cada prueba de variables del host y de un `.env` local."""
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults() -> None:
    settings = Settings()
    assert settings.environment == "dev"
    assert settings.free_tier_mode is True
    assert settings.gcp_project_id == "bbva-voc-analyzer-dev"
    assert settings.bq_sanitized_tds_table == "sanitized_reviews_tds"
    assert settings.dlp_inspect_template_id is None
    assert settings.user_hash_salt == DEV_USER_HASH_SALT
    assert settings.scraper_proxy_pool_urls == []
    assert settings.scraper_page_size == 199
    assert settings.hitl_entropy_threshold == 0.65
    assert settings.enable_dedicated_vertex_endpoints is False
    assert settings.is_production is False


def test_pulumi_env_vars_override(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        "GCP_PROJECT_ID": "bbva-voc-analyzer-prod",
        "GCS_RAW_DATALAKE_BUCKET": "voc-datalake-prod",
        "BQ_DATASET_ID": "tds_prod",
        "PUBSUB_RAW_SUBSCRIPTION": "sub-prod",
        "DLP_INSPECT_TEMPLATE_ID": "projects/p/inspectTemplates/i",
        "SCRAPER_PAGE_SIZE": "150",
        "SCRAPER_BASE_DELAY_SEC": "2.5",
        "SCRAPER_MAX_RETRIES": "7",
        "FREE_TIER_MODE": "false",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    settings = Settings()
    assert settings.gcp_project_id == "bbva-voc-analyzer-prod"
    assert settings.gcs_raw_datalake_bucket == "voc-datalake-prod"
    assert settings.bq_dataset_id == "tds_prod"
    assert settings.pubsub_raw_subscription == "sub-prod"
    assert settings.dlp_inspect_template_id == "projects/p/inspectTemplates/i"
    assert settings.scraper_page_size == 150
    assert settings.scraper_base_delay_sec == 2.5
    assert settings.scraper_max_retries == 7
    assert settings.free_tier_mode is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", []),
        ("   ", []),
        ("http://p1:8080", ["http://p1:8080"]),
        (
            "http://p1:8080, socks5://p2:1080,",
            ["http://p1:8080", "socks5://p2:1080"],
        ),
        (
            '["http://p1:8080","socks5://p2:1080"]',
            ["http://p1:8080", "socks5://p2:1080"],
        ),
    ],
)
def test_proxy_pool_parsing(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]
) -> None:
    monkeypatch.setenv("SCRAPER_PROXY_POOL_URLS", raw)
    assert Settings().scraper_proxy_pool_urls == expected


def test_proxy_pool_accepts_python_list() -> None:
    settings = Settings(scraper_proxy_pool_urls=["http://a:1"])
    assert settings.scraper_proxy_pool_urls == ["http://a:1"]


def test_blank_dlp_template_ids_become_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DLP_INSPECT_TEMPLATE_ID", "")
    monkeypatch.setenv("DLP_DEIDENTIFY_TEMPLATE_ID", "  ")
    settings = Settings()
    assert settings.dlp_inspect_template_id is None
    assert settings.dlp_deidentify_template_id is None


@pytest.mark.parametrize(
    ("env_var", "value"),
    [
        ("SCRAPER_PAGE_SIZE", "200"),
        ("SCRAPER_PAGE_SIZE", "0"),
        ("SCRAPER_TIMEOUT_SEC", "0"),
        ("SCRAPER_ROTATE_PROXY_EVERY_N_BATCHES", "0"),
        ("SCRAPER_BASE_DELAY_SEC", "inf"),
        ("SCRAPER_MAX_JITTER_SEC", "nan"),
        ("SCRAPER_TIMEOUT_SEC", "inf"),
        ("HITL_ENTROPY_THRESHOLD", "1.5"),
        ("USER_HASH_SALT", "short"),
        ("USER_HASH_SALT", " " * 16),
        ("USER_HASH_SALT", "short" + " " * 16),
    ],
)
def test_invalid_values_rejected(
    monkeypatch: pytest.MonkeyPatch, env_var: str, value: str
) -> None:
    monkeypatch.setenv(env_var, value)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("environment", ["prod", "PRODUCTION", " Prod "])
def test_dev_salt_forbidden_in_production(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("ENVIRONMENT", environment)
    with pytest.raises(ValidationError, match="USER_HASH_SALT"):
        Settings()

    monkeypatch.setenv("USER_HASH_SALT", "a-real-production-salt-value")
    settings = Settings()
    assert settings.is_production is True


def test_reads_dotenv_file_in_cwd(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "GCP_REGION=southamerica-east1\nUNRELATED_VAR=ignored\n",
        encoding="utf-8",
    )
    assert Settings().gcp_region == "southamerica-east1"


def test_environment_overrides_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text(
        'SCRAPER_PROXY_POOL_URLS=["http://dotenv:8080"]\n'
        "GCP_REGION=southamerica-east1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GCP_REGION", "us-central1")
    monkeypatch.setenv("SCRAPER_PROXY_POOL_URLS", "http://env:8080")
    settings = Settings()
    assert settings.gcp_region == "us-central1"
    assert settings.scraper_proxy_pool_urls == ["http://env:8080"]


@pytest.mark.parametrize("raw", ['["unterminated"', "[1]", '[{"url":"x"}]'])
def test_invalid_proxy_pool_rejected(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("SCRAPER_PROXY_POOL_URLS", raw)
    with pytest.raises(ValidationError):
        Settings()


def test_padded_dev_salt_forbidden_in_production() -> None:
    with pytest.raises(ValidationError, match="USER_HASH_SALT"):
        Settings(environment="prod", user_hash_salt=f" {DEV_USER_HASH_SALT} ")


def test_env_example_loads_and_covers_all_fields(tmp_path: Path) -> None:
    content = _ENV_EXAMPLE.read_text(encoding="utf-8")
    declared = {
        line.split("=", 1)[0].strip().lower()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert declared == set(Settings.model_fields)

    (tmp_path / ".env").write_text(content, encoding="utf-8")
    assert Settings() == Settings(_env_file=None)


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    first = get_settings()
    monkeypatch.setenv("GCP_REGION", "europe-west1")
    assert get_settings() is first
    get_settings.cache_clear()
    assert get_settings().gcp_region == "europe-west1"


def test_public_api_reexports_every_module() -> None:
    modules = (
        "constants",
        "text_utils",
        "schemas",
        "config",
        "ingestion_state",
    )
    for module_name in modules:
        module = importlib.import_module(f"voc_common.{module_name}")
        public = {
            name
            for name, obj in vars(module).items()
            if not name.startswith("_")
            and getattr(obj, "__module__", None) == module.__name__
        }
        missing = public - set(voc_common.__all__)
        assert not missing, f"{module_name} sin exportar: {sorted(missing)}"


def test_v2_settings_defaults_payloads_and_policy_are_coherent() -> None:
    settings = Settings()
    payload = voc_common.IngestionRequestPayload(
        bank_id=voc_common.BankKey.BBVA
    )
    assert settings.scraper_page_size == payload.page_size
    assert payload.page_size == voc_common.PLAYSTORE_DEFAULT_PAGE_SIZE == 199
    assert settings.ingestion_v2_enabled is False
    assert settings.ingestion_history_job_name is None
    assert settings.bq_ingestion_runs_log_table == "ingestion_runs_log_v2"
    assert (
        settings.ingestion_max_runtime_sec
        + (settings.ingestion_checkpoint_margin_sec)
        <= settings.ingestion_container_timeout_sec
    )
    with pytest.raises(ValueError, match="not enabled"):
        settings.require_ingestion_v2()
    incremental = Settings(ingestion_v2_enabled=True)
    incremental.require_ingestion_v2()
    with pytest.raises(ValueError, match="Pulumi Job output"):
        incremental.require_ingestion_v2(historical=True)
    historical = Settings(
        ingestion_v2_enabled=True,
        ingestion_history_job_name="projects/fixture/locations/us/jobs/history",
    )
    historical.require_ingestion_v2(historical=True)


@pytest.mark.parametrize(
    "changes",
    [
        {"ingestion_max_requests": 0},
        {"ingestion_max_response_bytes": -1},
        {"ingestion_max_runtime_sec": 0},
        {"ingestion_container_timeout_sec": 0},
        {"ingestion_checkpoint_margin_sec": 0},
        {"ingestion_lease_duration_sec": 0},
        {"ingestion_heartbeat_interval_sec": 0},
        {"ingestion_max_runtime_sec": 850},
        {"ingestion_heartbeat_interval_sec": 120},
        {"scraper_timeout_sec": 61},
        {"gcs_watermark_prefix": "/state/watermarks"},
        {"gcs_ingestion_state_prefix": "state//ingestion"},
        {"gcs_ingestion_ledgers_prefix": "state/ingestion/../ledger"},
        {"gcs_ingestion_manifests_prefix": "outside/manifests"},
        {"gcs_processing_receipts_prefix": "state/ingestion/ledgers/receipts"},
        {"gcs_watermark_prefix": "state"},
        {"gcs_raw_staging_prefix": "state"},
        {"bq_ingestion_runs_log_table": "dataset.table"},
    ],
)
def test_v2_invalid_config_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(**changes)


def test_v2_environment_overrides_and_custom_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in {
        "INGESTION_V2_ENABLED": "true",
        "INGESTION_HISTORY_JOB_NAME": "from-pulumi-output",
        "INGESTION_MAX_REQUESTS": "50",
        "INGESTION_MAX_RESPONSE_BYTES": "10000000",
        "BQ_INGESTION_RUNS_LOG_TABLE": "custom_runs_v2",
    }.items():
        monkeypatch.setenv(key, value)
    settings = Settings(
        gcs_watermark_prefix="metadata/watermarks",
        gcs_ingestion_state_prefix="metadata/ingestion",
        gcs_ingestion_manifests_prefix="metadata/ingestion/manifests",
        gcs_ingestion_ledgers_prefix="metadata/ingestion/ledgers",
        gcs_processing_receipts_prefix="metadata/ingestion/receipts",
    )
    settings.require_ingestion_v2(historical=True)
    assert settings.ingestion_max_requests == 50
    assert settings.ingestion_max_response_bytes == 10000000
    assert settings.bq_ingestion_runs_log_table == "custom_runs_v2"
