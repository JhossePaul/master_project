"""La lista cerrada de nombres de BigQuery."""

from pathlib import Path

import pytest
from api_backend.bq.names import ALLOWED_NAMES, ANALYTICS_V3_VIEWS, qualified
from voc_common import ANALYTICS_V3_TABLES

ROOT = Path(__file__).resolve().parents[3]


def test_son_28_tablas_10_vistas_y_2_del_tds() -> None:
    assert len(ANALYTICS_V3_TABLES) == 28
    assert len(ANALYTICS_V3_VIEWS) == 10
    assert len(ALLOWED_NAMES) == 40


def test_las_vistas_son_las_de_infra() -> None:
    sql = {p.stem for p in (ROOT / "infra/modules/sql").glob("*.sql")}

    assert set(ANALYTICS_V3_VIEWS) == sql


def test_nombre_permitido_se_califica() -> None:
    assert qualified("hitl_items", "p", "ds") == "`p.ds.hitl_items`"
    assert qualified("sanitized_reviews_tds", "p", "ds").endswith(
        "sanitized_reviews_tds`"
    )


@pytest.mark.parametrize(
    "name",
    ["otra", "", "hitl_items; DROP TABLE x", "`p.ds.hitl_items`", "_staging_x"],
)
def test_nombre_no_permitido_falla(name: str) -> None:
    with pytest.raises(ValueError, match="no permitida"):
        qualified(name, "p", "ds")
