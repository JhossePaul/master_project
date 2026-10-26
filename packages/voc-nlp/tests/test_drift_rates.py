"""Tasas de alerta contra la línea base del análisis de escala."""

from voc_nlp.drift_rates import CEILING, REFERENCE, TOLERANCE, Rate, rates


def test_rates_per_year_and_tolerance() -> None:
    found = rates(
        [
            {
                "metric": "mean_words",
                "bank_id": "BBVA",
                "months": 60,
                "alerts": 5,
            },
            {
                "metric": "mean_words",
                "bank_id": "BBVA",
                "months": 60,
                "alerts": 0,
            },
            {
                "metric": "neg_share",
                "bank_id": "NUBANK",
                "months": 24,
                "alerts": 4,
            },
            {
                "metric": "family_FA",
                "bank_id": "BBVA",
                "months": 12,
                "alerts": 0,
            },
        ]
    )
    by_key = {(r.series, r.bank_id): r for r in found}
    words = by_key[("mean_words", "BBVA")]
    assert (words.months, words.alerts, words.per_year) == (120, 5, 0.5)
    assert words.reference == 1.0 and words.ok
    neg = by_key[("neg_share", "NUBANK")]
    assert neg.per_year == 2.0 and not neg.ok
    # Sin referencia, se juzga contra el techo del análisis.
    other = by_key[("family_FA", "BBVA")]
    assert other.reference is None and other.ok
    assert not Rate("x", "B", 12, 3, None).ok
    assert Rate("x", "B", 0, 0, 0.0).per_year == 0.0
    assert TOLERANCE == 0.5 and CEILING == 1.4
    assert all(len(v) == 5 for v in REFERENCE.values())
