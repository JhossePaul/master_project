"""Verificación del JWT de IAP con claves de prueba (sin red)."""

import pytest
from api_backend.auth.iap import Identity, verify_iap_jwt
from api_backend.errors import ApiError, ErrorCode
from api_backend.testing import AUDIENCE, IapKit


def test_jwt_valido_da_el_correo_en_minusculas(iap_kit: IapKit) -> None:
    identity = verify_iap_jwt(iap_kit.sign(), AUDIENCE, iap_kit.transport)

    assert identity == Identity(email="ana@example.com")


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "/projects/1/other"},
        {"iss": "https://accounts.google.com"},
        {"exp": 1, "iat": 0},
        {"email": None},
        {"email": "sin-arroba"},
    ],
)
def test_jwt_incorrecto_da_401(
    iap_kit: IapKit, overrides: dict[str, object]
) -> None:
    token = iap_kit.sign(**overrides)

    with pytest.raises(ApiError) as caught:
        verify_iap_jwt(token, AUDIENCE, iap_kit.transport)

    assert caught.value.code is ErrorCode.UNAUTHENTICATED
    assert caught.value.status_code == 401


def test_firma_de_otra_llave_da_401(iap_kit: IapKit) -> None:
    with pytest.raises(ApiError) as caught:
        verify_iap_jwt(iap_kit.sign(), AUDIENCE, iap_kit.other_transport)

    assert caught.value.status_code == 401


@pytest.mark.parametrize("token", ["", "no-es-un-jwt"])
def test_sin_token_o_roto_da_401(iap_kit: IapKit, token: str) -> None:
    with pytest.raises(ApiError) as caught:
        verify_iap_jwt(token, AUDIENCE, iap_kit.transport)

    assert caught.value.status_code == 401
