"""Cobertura de un léxico determinista para reseñas de una palabra (EPIC-5 5.2).

Insumo para la decisión de `TNSS_SINGLE_WORD` en 5.8: excluir esas filas o
asignarles sentimiento por léxico (`RULE_BASED`).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.eda.eda_lexicon data/tds_<SNAPSHOT>.parquet

* **Forma:** `texto_limpio` en minúsculas, sin acentos, solo letras y dígitos
  y sin letras repetidas seguidas ("Excelenteee!!" → "excelente").
* **Léxico:** formas de una palabra de la plata `silver_v0` (`prompt_v3`), sin
  reseñas del oro. Entra una forma con al menos `MIN_SUPPORT` filas de plata y
  pureza ponderada (1 / π) de al menos `MIN_PURITY`; su etiqueta es la
  mayoritaria. `NA` (no evaluable) también es una etiqueta posible.
* **Cobertura:** filas del corpus con `palabras = 1` y sin otra regla TNSS
  cuya forma está en el léxico, en total y por banco × periodo.
* **Exactitud:** contra el oro *dev* aleatorio de una palabra (el *test* se
  descarta antes de leer etiquetas).

Escribe solo agregados en `docs/analytics/eda/lexicon_metrics.json`. Las
formas publicadas son las de `MIN_PUBLIC_ROWS` filas o más del corpus, que no
pueden identificar a nadie.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

import polars as pl

from voc_analytics.labeling.eligibility import with_tnss_rule
from voc_analytics.paths import DOCS
from voc_analytics.sampling.strata import period
from voc_analytics.sentiment.data import gold, gold_ids, silver_rows

OUT = DOCS / "eda"
MIN_SUPPORT = 3
MIN_PURITY = 0.9
MIN_PUBLIC_ROWS = 500
TOP_K = [10, 50, 100, 500, 1000]


def form(text: str | None) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9ñ]+", "", t)
    return re.sub(r"(.)\1+", r"\1", t)


def with_form(df: pl.DataFrame) -> pl.DataFrame:
    keys = df.select(pl.col("texto_limpio").fill_null("").unique())
    keys = keys.with_columns(
        forma=pl.col("texto_limpio").map_elements(form, return_dtype=pl.String)
    )
    return df.with_columns(pl.col("texto_limpio").fill_null("")).join(
        keys, on="texto_limpio", how="left"
    )


def build_lexicon() -> tuple[pl.DataFrame, dict]:
    ids = gold_ids()
    rows = silver_rows().filter(
        (pl.col("palabras") == 1) & ~pl.col("id_resena").is_in(list(ids))
    )
    rows = with_form(rows)
    counts = (
        rows.group_by("forma", "plata")
        .agg(pl.len().alias("n"), pl.col("peso").sum().alias("w"))
        .with_columns(
            n_forma=pl.col("n").sum().over("forma"),
            pureza=pl.col("w") / pl.col("w").sum().over("forma"),
        )
    )
    lexicon = (
        counts.sort("pureza", descending=True)
        .group_by("forma")
        .first()
        .filter(
            (pl.col("n_forma") >= MIN_SUPPORT)
            & (pl.col("pureza") >= MIN_PURITY)
        )
        .select("forma", pl.col("plata").alias("lexico"), "pureza", "n_forma")
    )
    meta = {
        "silver_rows_single_word": rows.height,
        "silver_forms": counts["forma"].n_unique(),
        "forms_with_support": counts.filter(pl.col("n_forma") >= MIN_SUPPORT)[
            "forma"
        ].n_unique(),
        "lexicon_forms": lexicon.height,
        "lexicon_by_label": lexicon.group_by("lexico")
        .len()
        .sort("lexico")
        .to_dicts(),
    }
    return lexicon, meta


def coverage(df: pl.DataFrame) -> dict:
    n = df.height
    covered = df.filter(pl.col("lexico").is_not_null())
    return {
        "filas": n,
        "cubiertas": covered.height,
        "cobertura": round(covered.height / max(n, 1), 4),
        "cubiertas_na": int((covered["lexico"] == "NA").sum()),
    }


def main(path: str) -> None:
    lexicon, meta = build_lexicon()
    m: dict = {
        "snapshot_file": Path(path).name,
        "parametros": {"min_support": MIN_SUPPORT, "min_purity": MIN_PURITY},
        "lexico": meta,
    }

    snap = pl.read_parquet(
        path, columns=["bank_id", "fecha", "estrellas", "texto_limpio"]
    )
    snap = with_tnss_rule(snap).with_columns(periodo=period())
    eligible = snap.filter(pl.col("tnss_rule").is_null())
    single = with_form(eligible.filter(pl.col("palabras") == 1)).join(
        lexicon, on="forma", how="left"
    )
    m["corpus"] = {
        "filas_elegibles": eligible.height,
        "filas_una_palabra": single.height,
        "formas_distintas": single["forma"].n_unique(),
        **coverage(single),
    }
    m["por_banco"] = [
        {"bank_id": b[0], **coverage(g)} for b, g in single.group_by("bank_id")
    ]
    m["por_banco"].sort(key=lambda r: r["bank_id"])
    m["por_banco_periodo"] = [
        {"bank_id": b, "periodo": p, **coverage(g)}
        for (b, p), g in single.group_by("bank_id", "periodo")
    ]
    m["por_banco_periodo"].sort(key=lambda r: (r["bank_id"], r["periodo"]))
    m["por_estrellas"] = [
        {"estrellas": s[0], **coverage(g)}
        for s, g in single.group_by("estrellas")
    ]
    m["por_estrellas"].sort(key=lambda r: r["estrellas"])

    # Cuántas formas hacen falta: cobertura de las K formas más frecuentes.
    freq = single.group_by("forma").len().sort("len", descending=True)
    m["cobertura_top_k_formas"] = [
        {
            "k": k,
            "cobertura_maxima": round(
                freq.head(k)["len"].sum() / single.height, 4
            ),
        }
        for k in TOP_K
    ]
    m["formas_publicas"] = (
        freq.filter(pl.col("len") >= MIN_PUBLIC_ROWS)
        .head(30)
        .join(
            lexicon.select("forma", "lexico", "pureza"), on="forma", how="left"
        )
        .rename({"len": "filas"})
        .with_columns(pl.col("pureza").round(3))
        .to_dicts()
    )

    # Sesgo en estrellas: excluir todas las de una palabra contra excluir solo
    # las que el léxico no cubre.
    uncovered = single.filter(pl.col("lexico").is_null()).select(
        "bank_id", "estrellas"
    )
    m["estrellas_por_banco"] = []
    for (b,), g in eligible.group_by("bank_id"):
        u = uncovered.filter(pl.col("bank_id") == b)
        sw = g.filter(pl.col("palabras") == 1)
        base = g["estrellas"].mean()
        sin_una = g.filter(pl.col("palabras") > 1)["estrellas"].mean()
        con_lexico = (g["estrellas"].sum() - u["estrellas"].sum()) / (
            g.height - u.height
        )
        m["estrellas_por_banco"].append(
            {
                "bank_id": b,
                "todas": round(base, 3),
                "sin_una_palabra": round(sin_una, 3),
                "sin_no_cubiertas": round(con_lexico, 3),
                "sesgo_excluir_todas": round(sin_una - base, 3),
                "sesgo_excluir_no_cubiertas": round(con_lexico - base, 3),
                "una_palabra": sw.height,
            }
        )
    m["estrellas_por_banco"].sort(key=lambda r: r["bank_id"])

    # Exactitud contra el oro dev aleatorio de una palabra.
    g = gold().filter(
        (pl.col("particion") == "dev")
        & (pl.col("bloque_oro") == "aleatorio")
        & (pl.col("palabras") == 1)
    )
    g = with_form(g).join(lexicon, on="forma", how="left")
    cov = g.filter(pl.col("lexico").is_not_null())
    hit = cov["lexico"] == cov["oro"]
    m["oro_dev_una_palabra"] = {
        "items": g.height,
        "cubiertos": cov.height,
        "cobertura": round(cov.height / max(g.height, 1), 4),
        "cobertura_ponderada": round(
            float(cov["peso"].sum() / g["peso"].sum()), 4
        ),
        "exactitud": round(float(hit.mean()), 4) if cov.height else None,
        "exactitud_ponderada": round(
            float((cov["peso"] * hit).sum() / cov["peso"].sum()), 4
        )
        if cov.height
        else None,
        "errores": int((~hit).sum()),
        "oro_no_cubiertos": g.filter(pl.col("lexico").is_null())
        .group_by("oro")
        .len()
        .sort("oro")
        .to_dicts(),
    }

    (OUT / "lexicon_metrics.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=2, default=str) + "\n"
    )
    print(
        json.dumps(
            {
                k: m[k]
                for k in (
                    "lexico",
                    "corpus",
                    "por_banco",
                    "cobertura_top_k_formas",
                    "estrellas_por_banco",
                    "oro_dev_una_palabra",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main(sys.argv[1])
