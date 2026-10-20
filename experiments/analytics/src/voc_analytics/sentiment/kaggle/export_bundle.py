"""Paquete autocontenido para entrenar encoders en Kaggle (EPIC-5, 5.4).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.sentiment.kaggle.export_bundle

Escribe `data/kaggle_bundle/` (fuera de git), para subirlo como dataset
privado de Kaggle:

* `silver_rows.parquet`: lo que devuelve `silver_rows()` (plata sin
  `holdout_visto`, con texto, estrellas y etiqueta de Gemini);
* `gold_dev.parquet`: solo el oro *dev*. **El oro *test* no sale nunca**, por
  método: se evalúa una sola vez en 5.8;
* `gold_ids.parquet`: reseñas de todas las colas del oro, para excluirlas
  del entrenamiento;
* `code/`: los módulos de `voc_analytics` que usan los encoders (mismas
  rutas del paquete) y `requirements.txt`.

En Kaggle, `VOC_BUNDLE` apunta a esta carpeta y `VOC_PREDS` a
`/kaggle/working/preds`; las predicciones se descargan y `evaluate.py` corre
en el Mac. Decisión del autor (2026-10-19): entrenar en Kaggle sin
restricciones de volumen ni de PII (FMEA, F-13).
"""

import shutil
from pathlib import Path

import polars as pl

from voc_analytics.paths import DATA
from voc_analytics.sentiment.data import gold, gold_ids, silver_rows

OUT = DATA / "kaggle_bundle"
# Rutas relativas a `src/`; en Kaggle se corren con `python -m` desde `code/`.
CODE = [
    "voc_analytics/__init__.py",
    "voc_analytics/paths.py",
    "voc_analytics/sentiment/__init__.py",
    "voc_analytics/sentiment/data.py",
    "voc_analytics/sentiment/metrics.py",
    "voc_analytics/sentiment/encoder.py",
    "voc_analytics/sentiment/models/__init__.py",
    "voc_analytics/sentiment/models/finetune.py",
    "voc_analytics/sentiment/models/delora.py",
]
REQUIREMENTS = """polars>=1.20,<2
pyarrow>=17
scikit-learn>=1.5,<2
pysentimiento>=0.7,<1
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    silver_rows().write_parquet(OUT / "silver_rows.parquet")
    gold().filter(pl.col("particion") == "dev").write_parquet(
        OUT / "gold_dev.parquet"
    )
    pl.DataFrame({"id_resena": sorted(gold_ids())}).write_parquet(
        OUT / "gold_ids.parquet"
    )
    code = OUT / "code"
    code.mkdir(exist_ok=True)
    src = Path(__file__).resolve().parents[3]
    for name in CODE:
        (code / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / name, code / name)
    (code / "requirements.txt").write_text(REQUIREMENTS)
    for path in sorted(OUT.rglob("*")):
        if path.is_file():
            print(
                f"{path.relative_to(OUT)}  {path.stat().st_size / 2**20:.1f} MB"
            )


if __name__ == "__main__":
    main()
