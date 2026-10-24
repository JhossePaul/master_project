"""Consolida un export Parquet del TDS en un único archivo verificado.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.snapshot.consolidate_tds_snapshot <SNAPSHOT>

Lee `experiments/analytics/data/raw/<SNAPSHOT>/*.parquet` (salida de
`bq extract`), escribe `data/tds_<SNAPSHOT>.parquet` (zstd) y un manifiesto
JSON con conteos y checksum. Falla si hay claves duplicadas. Los datos
contienen texto de reseñas: nunca se versionan (ver .gitignore).
"""

import hashlib
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from voc_analytics.paths import DATA


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(snapshot: str) -> None:
    raw = DATA / "raw" / snapshot
    table = ds.dataset(raw, format="parquet").to_table()
    keys = pc.binary_join_element_wise(
        table["bank_id"], table["id_resena"], "\x1f"
    )
    duplicates = len(keys) - len(pc.unique(keys))
    if duplicates:
        raise SystemExit(f"{duplicates} claves (bank_id, id_resena) repetidas")
    table = table.sort_by([("bank_id", "ascending"), ("fecha", "ascending")])
    out = DATA / f"tds_{snapshot}.parquet"
    pq.write_table(table, out, compression="zstd", row_group_size=250_000)
    banks = table.group_by("bank_id").aggregate([("id_resena", "count")])
    manifest = {
        "snapshot": snapshot,
        "source": "project-7bafd424-a385-4c05-b5b.bbva_voc_tds."
        "sanitized_reviews_tds",
        "file": out.name,
        "sha256": sha256(out),
        "bytes": out.stat().st_size,
        "rows": table.num_rows,
        "shards": len(list(raw.glob("*.parquet"))),
        "rows_by_bank": dict(
            zip(
                banks["bank_id"].to_pylist(),
                banks["id_resena_count"].to_pylist(),
                strict=True,
            )
        ),
        "fecha_min": str(pc.min(table["fecha"]).as_py()),
        "fecha_max": str(pc.max(table["fecha"]).as_py()),
        "schema": [f"{f.name}:{f.type}" for f in table.schema],
    }
    (DATA / f"tds_{snapshot}.manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    pa.set_cpu_count(8)
    main(sys.argv[1])
