"""Datos sintéticos de la cola para diseñar el portal sin GCP."""

from datetime import UTC, datetime, timedelta

from voc_common import (
    DisplayMode,
    Guideline,
    HitlItem,
    HitlReason,
    HitlTask,
)
from voc_common.text_utils import text_key

from api_backend.sections.hitl.repository import InMemoryHitlRepository

MODEL = "sintetico_v1"
SAMPLE_GUIDELINE_URI = "sample_guideline.md"
SAMPLE_TEXTS: tuple[tuple[str, str, float, str], ...] = (
    # (texto, motivo, prioridad, etiqueta propuesta)
    ("No puedo entrar a la app desde ayer.", "low_confidence", 0.62, "NEG"),
    ("Todo bien, aunque tarda en abrir.", "low_confidence", 0.48, "NEU"),
    ("Me cobraron dos veces y nadie responde.", "low_confidence", 0.41, "NEG"),
    ("Muy buena, la uso todos los días.", "low_confidence", 0.35, "POS"),
    ("Funciona. Nada más que decir.", "monitor_sample", 2.0, "NEU"),
    ("Después de actualizar ya no abre.", "monitor_sample", 2.0, "NEG"),
)


def sample_repository(now: datetime | None = None) -> InMemoryHitlRepository:
    now = now or datetime.now(UTC)
    items: list[HitlItem] = []
    texts: dict[tuple[str, str], str] = {}
    for n, (text, reason, priority, label) in enumerate(SAMPLE_TEXTS, start=1):
        blind = reason == "monitor_sample"
        id_resena = f"syn-hitl-{n:04d}"
        prefix = (
            f"monitor_sample:2026Q3:{id_resena}"
            if blind
            else (f"sentiment:{id_resena}")
        )
        probs = {
            "NEG": (0.62, 0.25, 0.13),
            "NEU": (0.2, 0.55, 0.25),
            "POS": (0.1, 0.2, 0.7),
        }[label]
        items.append(
            HitlItem(
                item_id=f"{prefix}:{text_key(text)[:16]}:{MODEL}",
                id_resena=id_resena,
                bank_id="BANCO_A",
                task=HitlTask.SENTIMENT,
                reason=HitlReason(reason),
                display_mode=DisplayMode.BLIND
                if blind
                else DisplayMode.ASSISTED,
                model_version=MODEL,
                predicted={
                    "label": label,
                    "p_neg": probs[0],
                    "p_neu": probs[1],
                    "p_pos": probs[2],
                },
                priority=priority,
                created_at=now - timedelta(hours=n),
            )
        )
        texts[("BANCO_A", id_resena)] = text
    guideline = Guideline(
        guideline_version="v2.2",
        task=HitlTask.SENTIMENT,
        content_uri=SAMPLE_GUIDELINE_URI,
        valid_from=now - timedelta(days=30),
        published_by_hash="a" * 64,
    )
    return InMemoryHitlRepository(items, texts, [guideline])
