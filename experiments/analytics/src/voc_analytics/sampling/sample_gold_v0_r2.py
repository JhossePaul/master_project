"""Cola de re-anotación a ciegas del oro (EPIC-5, feature 5.3).

**Histórico:** re-anotación `gold_v0_r2`, superada por `sample_gold_v1`; se
conserva para reproducir sus reportes.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.sampling.sample_gold_v0_r2

Toma la cola `gold_v0` y arma `data/labels/gold_v0_r2/queue.parquet` (fuera
de git) para re-anotar con la guía vigente, todo a ciegas y en un orden nuevo:

1. `r2_ciego`: el bloque aleatorio que ya fue a ciegas (201);
2. `r2_asistido`: el bloque aleatorio que fue asistido (199), ahora sin
   propuesta, para quitarle el anclaje;
3. `r2_calibracion`: los 30 de calibración, sin retroalimentación.

Cada sección sirve por sí sola si la anotación se detiene antes del final.
`origen_item` enlaza con el `item_id` de `gold_v0`.
"""

import json
import sys
from datetime import UTC, datetime

import polars as pl

from voc_analytics.paths import LABELS

SEED = 20261019
SOURCE = LABELS / "gold_v0"
OUT = LABELS / "gold_v0_r2"
SECTIONS = [
    (
        "r2_ciego",
        (pl.col("bloque") == "aleatorio") & (pl.col("modo") == "ciego"),
    ),
    (
        "r2_asistido",
        (pl.col("bloque") == "aleatorio") & (pl.col("modo") == "asistido"),
    ),
    ("r2_calibracion", pl.col("bloque") == "calibracion"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "annotations.csv").exists():
        sys.exit("Ya hay anotaciones en gold_v0_r2; no se regenera la cola.")
    source = pl.read_parquet(SOURCE / "queue.parquet")
    parts = []
    for name, condition in SECTIONS:
        parts.append(
            source.filter(condition)
            .sample(fraction=1.0, shuffle=True, seed=SEED)
            .select(
                pl.col("item_id").alias("origen_item"),
                pl.lit(name).alias("bloque"),
                pl.lit("ciego").alias("modo"),
                "id_resena",
                "bank_id",
                "texto_sanitizado",
            )
        )
    queue = (
        pl.concat(parts)
        .with_row_index("orden")
        .with_columns(
            item_id=pl.format(
                "B{}", (pl.col("orden") + 1).cast(pl.String).str.zfill(3)
            )
        )
    )
    queue.write_parquet(OUT / "queue.parquet")
    meta = {
        "source": "gold_v0",
        "seed": SEED,
        "created_at": datetime.now(UTC).isoformat(),
        "items": dict(
            queue.group_by("bloque", maintain_order=True).len().iter_rows()
        ),
    }
    (OUT / "queue_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
