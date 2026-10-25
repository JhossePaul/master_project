"""Familias ``aspects_v2_1`` con Gemini en Vertex AI (extra ``[gemini]``).

Port de ``voc_analytics.labeling.label_gemini`` (lote, reintentos y costo),
``voc_analytics.topics.aspects_scale`` (cliente y configuración) y
``voc_analytics.eda.eda_aspects_v2.parse``. Cada línea de entrada es
``i<TAB>texto`` y cada línea de salida ``i CÓDIGOS u s m``.

Diferencia con los experimentos: si la respuesta omite algunos ids,
se aceptan los presentes y los que faltan se reintentan en lotes más chicos;
un texto que sigue sin etiqueta queda pendiente (no se guarda vacío). Una
respuesta sin líneas válidas, con ids que no se pidieron, repetidos o con
códigos desconocidos se descarta entera y se reintenta hasta tres veces,
como en los experimentos.
"""

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from google import genai
from google.genai import types
from voc_common.analytics_codes import AspectFamily

PROMPT_PATH: Final = Path(__file__).parent / "prompts" / "aspects_v2_1.md"
PROMPT_VERSION: Final = "aspects_v2_1"
GUIDELINE_VERSION: Final = "v2.1"
MODEL: Final = "gemini-3.6-flash"
LOCATION: Final = "global"
BATCH_SIZE: Final = 100
MAX_TEXT_CHARS: Final = 2000
MAX_ATTEMPTS: Final = 3
# USD por millón de tokens al medir los experimentos (precio introductorio,
# vigente hasta el 2026-12-31); los *thoughts* se cobran como salida. En
# producción el precio llega de la configuración (``Usage(price_in=...)``).
PRICE_IN: Final = 0.75
PRICE_OUT: Final = 3.75

LINE: Final = re.compile(
    r"^\s*(\d+)\s+(-|[A-Z]{2}(?:,[A-Z]{2})*)\s+([01])\s+([01])\s+([01])\s*$"
)
_CODES: Final = frozenset(family.value for family in AspectFamily)


@dataclass(frozen=True)
class AspectLabel:
    """Etiqueta de un texto; ``key`` es el identificador del llamador."""

    key: str
    families: tuple[AspectFamily, ...]
    flag_update: bool
    flag_security: bool
    praise: bool


@dataclass
class Usage:
    """Tokens y llamadas de una corrida, para ``inference_runs.cost_usd``."""

    prompt: int = 0
    output: int = 0
    thoughts: int = 0
    calls: int = 0
    errors: list[str] = field(default_factory=list)
    price_in: float = PRICE_IN
    price_out: float = PRICE_OUT

    @property
    def cost_usd(self) -> float:
        return (
            self.prompt * self.price_in
            + (self.output + self.thoughts) * self.price_out
        ) / 1_000_000


@dataclass(frozen=True)
class _Parsed:
    families: tuple[AspectFamily, ...]
    u: bool
    s: bool
    m: bool


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def make_client(project: str, location: str = LOCATION) -> genai.Client:
    """Cliente de Gemini en Vertex AI dentro del proyecto: el texto no sale de
    GCP."""
    return genai.Client(vertexai=True, project=project, location=location)


def generation_config(prompt: str) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=prompt,
        temperature=0,
        response_mime_type="text/plain",
        thinking_config=types.ThinkingConfig(thinking_level="minimal"),
        max_output_tokens=4096,
    )


def parse(text: str) -> dict[int, _Parsed] | None:
    """Líneas válidas por índice; ``None`` si la respuesta no es usable.

    Las líneas que no tienen el formato se ignoran, como en los experimentos. Un
    índice repetido o un código fuera de las 11 familias invalida la
    respuesta.
    """
    parsed: dict[int, _Parsed] = {}
    for line in text.splitlines():
        match = LINE.match(line)
        if match is None:
            continue
        i, codes, u, s, m = match.groups()
        families = () if codes == "-" else tuple(codes.split(","))
        if int(i) in parsed or not set(families) <= _CODES:
            return None
        parsed[int(i)] = _Parsed(
            tuple(AspectFamily(c) for c in families),
            u == "1",
            s == "1",
            m == "1",
        )
    return parsed


def as_line(i: int, text: str) -> str:
    flat = " ".join(text.split())[:MAX_TEXT_CHARS]
    return f"{i}\t{flat}"


def label_batch(
    client: genai.Client,
    items: Sequence[tuple[str, str]],
    prompt: str,
    model: str = MODEL,
    *,
    usage: Usage | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[AspectLabel]:
    """Etiqueta ``(key, texto)``; devuelve solo los textos que obtuvieron
    etiqueta. Los que faltan quedan pendientes para la siguiente corrida.
    """
    usage = usage if usage is not None else Usage()
    config = generation_config(prompt)
    labels: list[AspectLabel] = []
    pending = [list(items)]
    while pending:
        batch = pending.pop(0)
        got = _attempt(client, batch, config, model, usage, sleep)
        labels.extend(got)
        done = {label.key for label in got}
        missing = [item for item in batch if item[0] not in done]
        if missing and len(missing) < len(batch):
            pending.append(missing)
        elif missing and len(missing) > 1:
            half = len(missing) // 2
            pending.extend([missing[:half], missing[half:]])
    return labels


def _attempt(
    client: genai.Client,
    batch: list[tuple[str, str]],
    config: types.GenerateContentConfig,
    model: str,
    usage: Usage,
    sleep: Callable[[float], None],
) -> list[AspectLabel]:
    contents = "\n".join(as_line(i, text) for i, (_, text) in enumerate(batch))
    for attempt in range(1, MAX_ATTEMPTS + 1):
        usage.calls += 1
        try:
            response = client.models.generate_content(
                model=model, contents=contents, config=config
            )
        except Exception as exc:  # noqa: BLE001 - se registra y se reintenta
            usage.errors.append(f"{type(exc).__name__}: {str(exc)[:200]}")
            sleep(2**attempt)
            continue
        meta = response.usage_metadata
        if meta is not None:
            usage.prompt += meta.prompt_token_count or 0
            usage.output += meta.candidates_token_count or 0
            usage.thoughts += meta.thoughts_token_count or 0
        parsed = parse(response.text or "")
        if not parsed or not set(parsed) <= set(range(len(batch))):
            usage.errors.append("salida inválida")
            continue
        return [
            AspectLabel(batch[i][0], p.families, p.u, p.s, p.m)
            for i, p in sorted(parsed.items())
        ]
    return []
