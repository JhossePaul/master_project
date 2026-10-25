import pytest
from ml_inference.bq_io import merge_statement


def test_merge_inserta_las_columnas_por_nombre() -> None:
    sql = merge_statement("p.d.t", "p.d.s", ["a"], ["a", "reason", "b"])
    assert "INSERT ROW" not in sql
    assert (
        "INSERT (`a`, `reason`, `b`) VALUES (S.`a`, S.`reason`, S.`b`)" in sql
    )


def test_merge_cita_las_palabras_reservadas() -> None:
    sql = merge_statement("p.d.t", "p.d.s", ["item_id"], ["item_id", "at"])
    assert "INSERT (`item_id`, `at`) VALUES (S.`item_id`, S.`at`)" in sql
    assert "T.`item_id` = S.`item_id`" in sql


def test_merge_rechaza_columnas_invalidas() -> None:
    with pytest.raises(ValueError):
        merge_statement("p.d.t", "p.d.s", ["a"], ["a); DROP TABLE x; --"])
    with pytest.raises(ValueError):
        merge_statement("p.d.t", "p.d.s", ["a"], [])
