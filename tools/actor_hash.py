"""Calcula el hash del actor de un correo para los argumentos `--actor-hash`.

Lee la sal de `USER_HASH_SALT` (la misma del despliegue; con Pulumi:
`pulumi config get user_hash_salt --stack dev`) y escribe solo el hash.

    USER_HASH_SALT=<sal> uv run python tools/actor_hash.py <correo>
"""

import os
import sys
from collections.abc import Mapping, Sequence

from voc_common.text_utils import actor_hash

MIN_SALT_LENGTH = 16


def main(
    argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if env is None else env
    if len(args) != 1 or "@" not in args[0]:
        print("uso: actor_hash.py <correo>", file=sys.stderr)
        return 2
    salt = environ.get("USER_HASH_SALT", "")
    if len(salt) < MIN_SALT_LENGTH:
        print(
            f"USER_HASH_SALT requiere al menos {MIN_SALT_LENGTH} caracteres",
            file=sys.stderr,
        )
        return 2
    print(actor_hash(args[0], salt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
