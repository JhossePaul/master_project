"""Pruebas de ``text_key``, la clave del texto único del esquema v3 (6.1)."""

import voc_common
from voc_common.text_utils import text_key

# Calculado con ``TO_HEX(SHA256(texto))`` (bytes UTF-8 del STRING); el texto es
# sintético, con acentos, emoji y un token de sanitización.
_SYNTHETIC = "La app no abre 😡, ¿por qué? [PERSONA] ñandú"
_SYNTHETIC_KEY = (
    "fcb00c89f1bdf6eea3da9c092ea52ad4d3582b105934f9fa0174c5e3fe1eacdf"
)


def test_text_key_matches_bigquery_sha256() -> None:
    assert text_key(_SYNTHETIC) == _SYNTHETIC_KEY


def test_text_key_does_not_normalize() -> None:
    assert text_key("hola") != text_key("Hola")
    assert text_key("hola") != text_key("hola ")


def test_text_key_of_empty_text_is_sha256_of_nothing() -> None:
    assert text_key("") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_text_key_is_exported() -> None:
    assert "text_key" in voc_common.__all__
    assert voc_common.text_key is text_key
