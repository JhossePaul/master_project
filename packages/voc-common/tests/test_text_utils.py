"""Pruebas de utilidades de limpieza y hash de voc-common (Feature 1.2)."""

import re

import pytest
import voc_common
from voc_common.text_utils import (
    contar_palabras,
    cumple_umbral_palabras,
    hash_username_pii,
    limpiar_texto_bancario,
)

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def test_limpiar_texto_bancario_preserves_error_codes_and_emojis() -> None:
    raw = (
        "no me deja entrar me sale que restringieron mi cuenta por motivos "
        "de seguridad: ref: 3702:65c5:9xhchi. noooo sirveee 😡 "
        "http://spam.com @bbva #asco"
    )
    expected = (
        "no me deja entrar me sale que restringieron mi cuenta por motivos "
        "de seguridad: ref: 3702:65c5:9xhchi. noo sirvee 😡"
    )
    assert limpiar_texto_bancario(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HOLA Mundo", "hola mundo"),
        ("ver www.bbva.mx y https://x.co/a?b=1 ya", "ver y ya"),
        ("hola @soporte_bbva gracias", "hola gracias"),
        ("# suelto", "suelto"),
        ("!!!!! malísimaaaa 😡😡😡😡", "!! malísimaa 😡😡"),
        ("error 5000 y cobro de $1000", "error 5000 y cobro de $1000"),
        ("  \t muchos \n  espacios  ", "muchos espacios"),
        ("", ""),
    ],
)
def test_limpiar_texto_bancario_rules(raw: str, expected: str) -> None:
    assert limpiar_texto_bancario(raw) == expected


def test_limpiar_texto_bancario_is_idempotent() -> None:
    once = limpiar_texto_bancario("Nooooo FUNCIONA @x #y http://a.b !!!!")
    assert limpiar_texto_bancario(once) == once


@pytest.mark.parametrize(
    ("texto", "expected"),
    [("", 0), ("   ", 0), ("excelente", 1), (" muy  buena\tapp ", 3)],
)
def test_contar_palabras(texto: str, expected: int) -> None:
    assert contar_palabras(texto) == expected


@pytest.mark.parametrize(
    ("n_words", "expected"),
    [(0, False), (1, False), (2, True), (60, True), (61, False)],
)
def test_cumple_umbral_palabras(n_words: int, expected: bool) -> None:
    assert cumple_umbral_palabras(" ".join(["palabra"] * n_words)) is expected


def test_hash_username_pii_is_deterministic_and_normalized() -> None:
    salt = "unit-test-salt-1234"
    digest = hash_username_pii("Juan Pérez", salt)
    assert _SHA256_HEX.match(digest)
    assert digest == hash_username_pii("  juan pérez ", salt)
    assert "juan" not in digest


def test_hash_username_pii_depends_on_salt_and_user() -> None:
    base = hash_username_pii("usuario", "salt-aaaaaaaaaaaa")
    assert base != hash_username_pii("usuario", "salt-bbbbbbbbbbbb")
    assert base != hash_username_pii("usuario2", "salt-aaaaaaaaaaaa")


def test_hash_username_pii_known_vector() -> None:
    # sha256(b"s:abc")
    assert hash_username_pii("ABC", "s") == (
        "efff0385da714c8573aaf55138e8a03080e2d5666a680a6b017643d379019835"
    )


def test_text_utils_are_exported() -> None:
    for name in (
        "contar_palabras",
        "cumple_umbral_palabras",
        "hash_username_pii",
        "limpiar_texto_bancario",
    ):
        assert name in voc_common.__all__
        assert hasattr(voc_common, name)
