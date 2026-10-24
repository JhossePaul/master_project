"""Sentimiento con Gemini en Vertex AI (extra ``[gemini]``).

Es el mismo etiquetado con el que se armó la plata que entrenó al modelo de
sentimiento (RoBERTuito ajustado): el prompt ``sentiment_v3.md`` es el
original sin cambios, con temperatura 0. Sirve para vigilar que el modelo
siga de acuerdo con Gemini en las reseñas nuevas.

Cada línea de entrada es ``i<TAB>texto`` y cada línea de salida
``i etiqueta f``, con etiqueta ``NEG``, ``NEU``, ``POS`` o ``NA`` (no
evaluable). Como en las familias (``voc_nlp.aspects``), si la respuesta
omite algunos textos se aceptan los presentes y los que faltan se
reintentan en lotes más chicos; una respuesta inválida (sin líneas válidas,
o con índices repetidos o que no se pidieron) se reintenta hasta tres
veces, y lo que siga sin etiqueta queda fuera.
"""

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from google import genai
from google.genai import types

from voc_nlp.aspects import MAX_ATTEMPTS, Usage, as_line, generation_config

PROMPT_PATH: Final = Path(__file__).parent / "prompts" / "sentiment_v3.md"
PROMPT_VERSION: Final = "sentiment_v3"
MODEL: Final = "gemini-3.6-flash"
BATCH_SIZE: Final = 100
NOT_EVALUABLE: Final = "NA"

LINE: Final = re.compile(r"^\s*(\d+)\s+(NEG|NEU|POS|NA)\s+([01])\s*$")


@dataclass(frozen=True)
class GeminiSentiment:
    """Etiqueta de un texto; ``key`` es el identificador del llamador."""

    key: str
    label: str
    # El texto describe un problema concreto de funcionamiento o servicio.
    problem: bool


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def parse(text: str) -> dict[int, tuple[str, bool]] | None:
    """Líneas válidas por índice; ``None`` si un índice se repite."""
    parsed: dict[int, tuple[str, bool]] = {}
    for line in text.splitlines():
        match = LINE.match(line)
        if match is None:
            continue
        i, label, problem = match.groups()
        if int(i) in parsed:
            return None
        parsed[int(i)] = (label, problem == "1")
    return parsed


def label_texts(
    client: genai.Client,
    items: Sequence[tuple[str, str]],
    prompt: str,
    model: str = MODEL,
    *,
    batch_size: int = BATCH_SIZE,
    usage: Usage | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[GeminiSentiment]:
    """Etiqueta ``(key, texto)`` en lotes; omite los que no obtuvieron
    etiqueta."""
    usage = usage if usage is not None else Usage()
    config = generation_config(prompt)
    labels: list[GeminiSentiment] = []
    pending = [
        list(items[i : i + batch_size])
        for i in range(0, len(items), batch_size)
    ]
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
) -> list[GeminiSentiment]:
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
            GeminiSentiment(batch[i][0], label, problem)
            for i, (label, problem) in sorted(parsed.items())
        ]
    return []
