"""Verificación del JWT que firma IAP (``x-goog-iap-jwt-assertion``)."""

from dataclasses import dataclass

from google.auth.transport import Request as TransportRequest
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from api_backend.errors import ApiError, ErrorCode

IAP_ISSUER = "https://cloud.google.com/iap"
IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"
IAP_JWT_HEADER = "x-goog-iap-jwt-assertion"


@dataclass(frozen=True)
class Identity:
    email: str  # en minúsculas


def verify_iap_jwt(
    token: str,
    audience: str,
    transport: TransportRequest | None = None,
) -> Identity:
    """Verifica firma, audiencia, emisor y vigencia del JWT de IAP.

    El correo sale del *claim* ``email`` firmado, nunca del encabezado
    ``x-goog-authenticated-user-email``, que falsifica quien llegue sin pasar
    por IAP. Lanza ``ApiError`` 401 si algo falla.
    """
    if not token:
        raise _unauthenticated("falta la aserción de IAP")
    try:
        claims = id_token.verify_token(
            token,
            transport or google_requests.Request(),
            audience=audience,
            certs_url=IAP_CERTS_URL,
        )
    except Exception as exc:  # noqa: BLE001  # firma, vigencia, red de claves
        raise _unauthenticated("aserción de IAP no válida") from exc
    if claims.get("iss") != IAP_ISSUER:
        raise _unauthenticated("emisor de IAP no válido")
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        raise _unauthenticated("la aserción de IAP no trae correo")
    return Identity(email=email.strip().lower())


def _unauthenticated(message: str) -> ApiError:
    return ApiError(ErrorCode.UNAUTHENTICATED, message)
