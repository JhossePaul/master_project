"""Reseñas sintéticas para diseñar el Explorador sin GCP."""

from datetime import UTC, datetime, timedelta

from voc_common.text_utils import text_key

from api_backend.online import FakeOnlineClient
from api_backend.sections.reviews.repository import (
    InMemoryReviewsRepository,
    SampleReview,
)
from api_backend.sections.reviews.schemas import (
    HitlReviewRef,
    ReviewRow,
    TopicRef,
)

MODEL = "sintetico_v1"
BANKS = ("BBVA", "AZTECA", "SANTANDER", "NUBANK", "BANORTE")
# (texto, sentimiento, estrellas, familias, marca u, tópico)
TEXTS: tuple[tuple[str, str, int, tuple[str, ...], bool, int | None], ...] = (
    ("No llega el código para entrar a la app.", "NEG", 1, ("AC",), False, 0),
    ("Después de actualizar ya no abre.", "NEG", 1, ("FA", "CO"), True, 1),
    ("Me cobraron dos veces la comisión.", "NEG", 2, ("DI",), False, 2),
    (
        "La transferencia tarda mucho y marca error.",
        "NEG",
        2,
        ("TR",),
        False,
        3,
    ),
    (
        "Todo bien, aunque a veces tarda en abrir.",
        "NEU",
        3,
        ("LE",),
        False,
        None,
    ),
    ("Funciona. Nada más que decir.", "NEU", 3, (), False, None),
    ("Muy buena app, la uso todos los días.", "POS", 5, (), False, None),
    ("Excelente atención en el chat.", "POS", 5, ("AT",), False, None),
    ("Me gustó el nuevo diseño.", "POS", 4, ("DV",), True, None),
    (
        "No puedo ver mis movimientos desde ayer.",
        "NEG",
        1,
        ("PR", "FA"),
        False,
        1,
    ),
)
TOPICS = {
    0: "Código de acceso",
    1: "Falla tras actualizar",
    2: "Cobros dobles",
    3: "Transferencias lentas",
}


def sample_repository(now: datetime | None = None) -> InMemoryReviewsRepository:
    now = now or datetime.now(UTC)
    embedder = FakeOnlineClient()
    reviews: list[SampleReview] = []
    n = 0
    for day in range(0, 330, 3):
        for bank_index, bank in enumerate(BANKS):
            text, sentiment, stars, families, update, topic = TEXTS[
                (day // 3 + bank_index) % len(TEXTS)
            ]
            n += 1
            probs = {
                "NEG": (0.8, 0.15, 0.05),
                "NEU": (0.2, 0.6, 0.2),
                "POS": (0.05, 0.15, 0.8),
            }[sentiment]
            fecha = (now - timedelta(days=day)).date()
            reviewed = n % 7 == 0
            row = ReviewRow(
                id_resena=f"syn-exp-{n:05d}",
                bank_id=bank,
                text_key=text_key(text),
                fecha=fecha,
                version_app=f"9.{(day // 60) % 5}.0",
                estrellas=stars,
                text=text,
                sentiment=sentiment,
                p_neg=probs[0],
                p_neu=probs[1],
                p_pos=probs[2],
                confidence=max(probs) - (n % 5) / 50,
                model_version=MODEL,
                families=list(families),
                flag_update=update,
                flag_security=False,
                topics=[TopicRef(topic_id=topic, name=TOPICS[topic])]
                if topic is not None
                else [],
                hitl_reviewed=reviewed,
            )
            reviews.append(
                SampleReview(
                    row=row,
                    prompt_version="aspects_v2_1",
                    embedding=embedder.embed(text).embedding,
                    hitl=[
                        HitlReviewRef(
                            outcome="confirmed",
                            validated_label=sentiment,
                            review_round=1,
                            submitted_at=now - timedelta(days=day),
                        )
                    ]
                    if reviewed
                    else [],
                )
            )
    return InMemoryReviewsRepository(reviews)
