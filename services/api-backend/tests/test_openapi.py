"""``openapi.json`` está al día y el módulo ``app`` se crea al pedirlo."""

import json
from pathlib import Path

import pytest
from api_backend import main
from api_backend.openapi import build_schema

PUBLISHED = Path(__file__).resolve().parents[1] / "openapi.json"


def test_openapi_json_esta_al_dia() -> None:
    expected = json.dumps(
        build_schema(), indent=2, sort_keys=True, ensure_ascii=False
    )

    assert PUBLISHED.read_text() == expected + "\n"


def test_docs_solo_en_local(monkeypatch: pytest.MonkeyPatch) -> None:
    from api_backend.settings import ApiSettings

    prod = ApiSettings.model_validate(
        {
            "environment": "dev",
            "iap_audience": "/a",
            "portal_data": "fixtures",
        }
    )
    app = main.create_app(prod)

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_app_del_modulo_se_crea_al_pedirla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in {
        "ENVIRONMENT": "local",
        "PORTAL_AUTH_MODE": "local",
        "PORTAL_LOCAL_USER": "ana@example.com",
        "PORTAL_DATA": "fixtures",
    }.items():
        monkeypatch.setenv(name, value)
    main.get_settings.cache_clear()
    monkeypatch.delitem(vars(main), "app", raising=False)

    assert main.app.title == "BBVA VoC Analyzer"
    assert main.app is main.app
    with pytest.raises(AttributeError):
        main.nada  # noqa: B018
    main.get_settings.cache_clear()
