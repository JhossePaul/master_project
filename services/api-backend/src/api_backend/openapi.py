"""Imprime el esquema OpenAPI sin levantar el servidor.

python -m api_backend.openapi > services/api-backend/openapi.json
"""

import json

from api_backend.main import create_app
from api_backend.settings import ApiSettings


def build_schema() -> dict[str, object]:
    settings = ApiSettings(
        environment="local",
        portal_auth_mode="local",
        portal_local_user="openapi@example.com",
        portal_data="fixtures",
    )
    return create_app(settings).openapi()


if __name__ == "__main__":  # pragma: no cover
    print(
        json.dumps(build_schema(), indent=2, sort_keys=True, ensure_ascii=False)
    )
