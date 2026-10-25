import pytest
from ml_inference.bq_io import merge_statement


def test_merge_inserta_las_columnas_por_nombre() -> None:
    sql = merge_statement("p.d.t", "p.d.s", ["a"], ["a", "reason", "b"])
    assert "INSERT ROW" not in sql
    assert "INSERT (a, reason, b) VALUES (S.a, S.reason, S.b)" in sql


def test_merge_rechaza_columnas_invalidas() -> None:
    with pytest.raises(ValueError):
        merge_statement("p.d.t", "p.d.s", ["a"], ["a); DROP TABLE x; --"])
    with pytest.raises(ValueError):
        merge_statement("p.d.t", "p.d.s", ["a"], [])
