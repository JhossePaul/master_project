"""Mide PII en las capturas crudas de `evidence/` (solo agregados).

Respalda la política de sanitización de EPIC-4 (ver README del servicio y la
Matriz Ethical FMEA). `evidence/` no se versiona porque contiene respuestas
crudas con nombres de usuario; este script no imprime ni guarda texto ni
nombres, solo conteos.

    uv run python experiments/pii_measurement/measure_pii.py [carpeta_evidence]

Cada `response_*.txt.gz` se parsea con el adaptador de ingesta y se deduplica
por `id_resena`. Sobre el texto del usuario aplica la regex local de
sanitización y busca candidatos que la regex no cubre. Sobre la respuesta de la
entidad cuenta cuántas saludan al autor por su nombre (coincidencia de tokens
con el nombre de usuario).
"""

import gzip
import re
import sys
from collections import Counter
from pathlib import Path

from ingestion_worker.playstore_protocol import parse_batchexecute_response
from sanitization_pipeline.dlp_transforms import (
    DLP_INFO_TYPE_TOKENS,
    LocalRegexFallbackSanitizer,
)
from voc_common import PLAYSTORE_BANK_APPS, BankKey

BANK = BankKey.BBVA
RESIDUAL = {
    "digitos >= 4": re.compile(r"(?<![\w\[])\d{4,}(?!\w)"),
    "url": re.compile(r"https?://|www\.", re.IGNORECASE),
    "@usuario": re.compile(r"(?<!\w)@\w{3,}"),
    "se presenta con nombre": re.compile(
        r"\b(me llamo|mi nombre es|soy)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+"
    ),
    "cierre con nombre": re.compile(
        r"\b(atte|att|atentamente|saludos)\b\W+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+",
        re.IGNORECASE,
    ),
}
GENERIC_TOKENS = {"usuario", "google", "del", "los", "las", "una"}


def tokens(text: str | None) -> set[str]:
    found = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", text or "")
    return {token.lower() for token in found}


def load(folder: Path) -> list[dict[str, str | None]]:
    unique: dict[str, dict[str, str | None]] = {}
    for path in sorted(folder.glob("response_*.txt.gz")):
        page = parse_batchexecute_response(
            gzip.open(path).read(),
            bank_id=BANK,
            app_id=PLAYSTORE_BANK_APPS[BANK],
        )
        for review in page.reviews:
            unique[review.id_resena] = {
                "usuario": review.usuario,
                "texto": review.texto,
                "respuesta": review.texto_respuesta,
            }
    return list(unique.values())


def main(folder: Path) -> None:
    rows = load(folder)
    total = len(rows)
    sanitizer = LocalRegexFallbackSanitizer()
    words = [len((row["texto"] or "").split()) for row in rows]
    print(f"resenas unicas: {total}")
    long_20 = sum(w >= 20 for w in words)
    long_40 = sum(w >= 40 for w in words)
    print(
        f"palabras: mediana={sorted(words)[total // 2]} "
        f">=20: {long_20} >=40: {long_40}"
    )

    hits: Counter[str] = Counter()
    rows_with_hit = 0
    cleaned: list[str] = []
    for row in rows:
        original = row["texto"] or ""
        clean = sanitizer.sanitize(original)
        cleaned.append(clean)
        added = {
            token: clean.count(token) - original.count(token)
            for token in DLP_INFO_TYPE_TOKENS
        }
        added = {token: n for token, n in added.items() if n > 0}
        rows_with_hit += bool(added)
        hits.update(added)
    print(f"texto del usuario con tokens PII (regex local): {rows_with_hit}")
    print(f"  por tipo: {dict(hits)}")
    for name, pattern in RESIDUAL.items():
        count = sum(bool(pattern.search(text)) for text in cleaned)
        print(f"candidato no cubierto '{name}': {count}")
    own_name = sum(
        bool(tokens(row["usuario"]) & tokens(row["texto"])) for row in rows
    )
    print(f"nombre de usuario dentro de su propio texto: {own_name}")

    replies = [row for row in rows if row["respuesta"]]
    greeted = sum(
        bool(
            (tokens(row["usuario"]) & tokens(row["respuesta"])) - GENERIC_TOKENS
        )
        for row in replies
    )
    print(f"respuestas de la entidad: {len(replies)}")
    print(f"  que contienen el nombre de pila del autor: {greeted}")
    if rows_with_hit == 0:
        print(
            "regla del tres (95 %): tasa de PII detectable en texto "
            f"< {3 / total:.2%}"
        )


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "evidence"))
