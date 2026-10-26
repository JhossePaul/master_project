"""Pruebas del cálculo del hash del actor (sin red)."""

import pytest
from voc_common.text_utils import hash_username_pii

from tools import actor_hash as ah

SALT = "s" * 16


def test_imprime_el_hash_con_sal(capsys: pytest.CaptureFixture[str]) -> None:
    code = ah.main(["Ana@Example.com "], {"USER_HASH_SALT": SALT})

    assert code == 0
    out = capsys.readouterr().out.strip()
    assert out == hash_username_pii("ana@example.com", SALT)


@pytest.mark.parametrize("argv", [[], ["a@b.c", "x"], ["sin-arroba"]])
def test_uso_incorrecto(argv: list[str]) -> None:
    assert ah.main(argv, {"USER_HASH_SALT": SALT}) == 2


@pytest.mark.parametrize("env", [{}, {"USER_HASH_SALT": "corta"}])
def test_sal_ausente_o_corta(
    env: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert ah.main(["a@b.c"], env) == 2
    assert "USER_HASH_SALT" in capsys.readouterr().err
