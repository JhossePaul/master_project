"""Utilidades puras y deterministas de limpieza de texto y anonimización.

Replica la pre-limpieza validada en el notebook del EDA para textos
bancarios ultracortos y la anonimización irreversible (SHA-256 con sal)
del ``userName`` de Google Play.
"""

import hashlib
import re

from voc_common.constants import MAX_REVIEW_WORDS, MIN_REVIEW_WORDS

_URL_REGEX = re.compile(r"http\S+|www\S+|https\S+", flags=re.MULTILINE)
# Menciones completas (@usuario) y hashtags completos (#etiqueta) o '#' suelto.
_MENTION_HASHTAG_REGEX = re.compile(r"@\w+|#\w*")
# 3+ caracteres no numéricos idénticos consecutivos. Se excluyen dígitos para
# no alterar códigos técnicos ni montos (ej. 'error 5000', '$1000').
_REPEATED_CHARS_REGEX = re.compile(r"(\D)\1{2,}")
_WHITESPACE_REGEX = re.compile(r"\s+")


def limpiar_texto_bancario(texto: str) -> str:
    """
    Pipeline de limpieza ajustado a textos ultracortos bancarios (EDA):
    1. Convierte a minúsculas.
    2. Elimina URLs (http, https, www), preservando signos de puntuación,
       códigos ref: 3702 y emojis.
    3. Elimina menciones (@usuario) y hashtags (#etiqueta).
    4. Reduce caracteres repetidos excesivos (3 o más idénticos a 2,
       ej. 'noooo sirveee' -> 'noo sirvee'); los dígitos no se alteran.
    5. Colapsa espacios internos y elimina espacios iniciales/finales.
    """
    cleaned = str(texto).lower()
    cleaned = _URL_REGEX.sub("", cleaned)
    cleaned = _MENTION_HASHTAG_REGEX.sub("", cleaned)
    cleaned = _REPEATED_CHARS_REGEX.sub(r"\1\1", cleaned)
    cleaned = _WHITESPACE_REGEX.sub(" ", cleaned)
    return cleaned.strip()


def contar_palabras(texto: str) -> int:
    """Calcula la cantidad de palabras separadas por espacios."""
    stripped = str(texto).strip()
    if not stripped:
        return 0
    return len(stripped.split())


def cumple_umbral_palabras(texto: str) -> bool:
    """Indica si el texto está dentro del rango del EDA (2 a 60 palabras)."""
    return MIN_REVIEW_WORDS <= contar_palabras(texto) <= MAX_REVIEW_WORDS


def hash_username_pii(username: str, salt: str) -> str:
    """Genera un digest SHA-256 irreversible a partir del userName y la sal."""
    normalized = f"{salt}:{username.strip().lower()}".encode()
    return hashlib.sha256(normalized).hexdigest()
