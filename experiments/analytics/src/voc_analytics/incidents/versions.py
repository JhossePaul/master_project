"""Vista descriptiva por versión de la app (5.9, P9-2).

Decisión del autor (2026-10-22): mostrarla en el dashboard, porque los datos
ya existen. Es descriptiva: proporción de `NEG` con su IC, marca `u` y
familias por banco y versión, sin pruebas de cambio de nivel.

* **Versión:** `release` normalizada por banco (`topics.versions.normalize`);
  las versiones con menos de `MIN_ROWS` reseñas con sentimiento se agrupan en
  `OTRAS` (`topics.versions.group_small`). `UNKNOWN` y las beta quedan como
  sin versión.
* **Sentimiento:** M4 `s1` y léxico (`incidents.prepare`), proporciones
  crudas como en el cockpit (P8-10), con IC de Wilson.
* **Marca `u` y familias:** entre las negativas para familias de la versión,
  con el backfill de familias (`incidents.backfill_aspects`).

Escribe `data/incidents/versions_v0.parquet` (fuera de git) y
`docs/analytics/incidents/versions_v0_metrics.json`, solo agregados.

    uv run python -m voc_analytics.incidents.versions
"""

import json
import math
from datetime import UTC, datetime

import polars as pl

from voc_analytics.incidents.backfill_aspects import OUT as ASPECTS
from voc_analytics.incidents.prepare import OUT
from voc_analytics.paths import DOCS
from voc_analytics.topics.aspects_scale import CODES, families
from voc_analytics.topics.versions import group_small, normalize

METRICS = DOCS / "incidents" / "versions_v0_metrics.json"
MIN_ROWS = 50
Z = 1.96
TOP = 3


def wilson(k: int, n: int) -> tuple[float, float]:
    p = k / n
    den = 1 + Z**2 / n
    mid = (p + Z**2 / (2 * n)) / den
    half = Z * math.sqrt(p * (1 - p) / n + Z**2 / (4 * n**2)) / den
    return mid - half, mid + half


def main() -> None:
    rows = pl.read_parquet(
        OUT / "rows_v0.parquet",
        columns=[
            "bank_id",
            "fecha",
            "version_app",
            "text_key",
            "sentimiento",
            "neg_familias",
        ],
    ).filter(pl.col("sentimiento").is_not_null())
    rows = group_small(normalize(rows), "release", MIN_ROWS)
    labels = pl.read_parquet(
        ASPECTS / "labels_by_key.parquet",
        columns=["text_key", "codes", "actualizacion"],
    ).with_columns(fam=families())
    neg = rows.filter(pl.col("neg_familias")).join(labels, on="text_key")

    key = ["bank_id", "release_agrupada"]
    base = (
        rows.filter(pl.col("release_agrupada").is_not_null())
        .group_by(key)
        .agg(
            primera_fecha=pl.col("fecha").min().dt.date(),
            ultima_fecha=pl.col("fecha").max().dt.date(),
            resenas=pl.len(),
            neg=(pl.col("sentimiento") == "NEG").sum(),
        )
        .with_columns(prop_neg=pl.col("neg") / pl.col("resenas"))
    )
    fam = neg.group_by(key).agg(
        neg_familias=pl.len(),
        u=pl.col("actualizacion").mean(),
        **{c: pl.col("fam").list.contains(c).mean() for c in CODES},
    )
    out = base.join(fam, on=key, how="left").sort("bank_id", "primera_fecha")
    ci = [wilson(k, n) for k, n in zip(out["neg"], out["resenas"], strict=True)]
    out = out.with_columns(
        ic_inf=pl.Series([c[0] for c in ci]),
        ic_sup=pl.Series([c[1] for c in ci]),
    ).rename({"release_agrupada": "version"})
    out.write_parquet(OUT / "versions_v0.parquet")

    named = out.filter(pl.col("version") != "OTRAS")
    result = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "min_resenas_por_version": MIN_ROWS,
        "resenas_con_sentimiento": rows.height,
        "con_version": round(float(rows["release"].is_not_null().mean()), 4),
        "por_banco": {
            b: {
                "versiones": g.height,
                "resenas_en_versiones": int(g["resenas"].sum()),
                "resenas_por_version_mediana": float(g["resenas"].median()),
                "prop_neg_mediana": round(float(g["prop_neg"].median()), 4),
                "u_mediana": round(float(g["u"].median()), 4),
                "versiones_con_mas_neg": [
                    {
                        "version": v,
                        "primera_fecha": f.isoformat(),
                        "resenas": n,
                        "prop_neg": round(p, 3),
                        "ic": [round(lo, 3), round(hi, 3)],
                        "u": round(u, 3),
                    }
                    for v, f, n, p, lo, hi, u in g.filter(
                        pl.col("resenas") >= 500
                    )
                    .sort("prop_neg", descending=True)
                    .head(TOP)
                    .select(
                        "version",
                        "primera_fecha",
                        "resenas",
                        "prop_neg",
                        "ic_inf",
                        "ic_sup",
                        "u",
                    )
                    .iter_rows()
                ],
            }
            for (b,), g in sorted(named.group_by("bank_id"), key=lambda x: x[0])
        },
    }
    METRICS.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
