"""Segunda ronda del oro, `gold_v1` (EPIC-5, feature 5.3, punto 3).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.sampling.sample_gold_v1 plan
    uv run python -m voc_analytics.sampling.sample_gold_v1 queue --option B

* `plan` no gasta ni arma cola: calcula el marco, la asignación de cada
  opción de tamaño, las bolsas de candidatos del bloque dirigido, el tiempo
  esperado y el IC de κ esperado. Escribe solo agregados en
  `data/labels/gold_v1/plan.json` (fuera de git).
* `queue` arma la cola de la opción elegida y etiqueta el bloque aleatorio con
  `prompt_v3` (~$0.05). Solo se corre tras elegir la opción.

Diseño (ver `docs/backlog/epic_5.md`, 5.3):

1. `aleatorio`: muestreo estratificado de filas elegibles del corpus completo,
   con probabilidad de inclusión registrada. Es el único bloque válido para
   cifras poblacionales.
   * Marco: filas elegibles sin las reseñas de `gold_v0` ni las filas
     `holdout_visto` de la plata.
   * Estratos: banco × periodo (los de `gold_v0`) × grupo de estrellas (1–2,
     3–4, 5). Igual tamaño por banco; dentro del banco, proporcional a la raíz
     cuadrada del estrato, con al menos 2 por estrato. Sobremuestrea 3–4★,
     donde están el ruido y los `NEU`, sin perder la validez poblacional.
   * Partición: dentro de cada estrato, una fracción fija va a *dev* y el
     resto a *test*.
2. `dirigido`: solo *dev* (o análisis), nunca *test* ni cifras poblacionales.
   Sale de la plata (`entrenamiento` y `holdout_nuevo`), que ya tiene Gemini.
   Un texto por clave, sin claves del oro ni del bloque aleatorio. Criterios,
   en orden de selección: `neu` (Gemini o M1 dicen `NEU`), `cinco_neg` (5★ y
   Gemini `NEG`), `pico_3_4` (3–4★ en día pico de volumen), `desacuerdo` (M1
   distinto de Gemini) e `incertidumbre_m1` (5 % de menor margen de M1). M1
   usa predicciones fuera de partición para los textos de entrenamiento.
3. `a2`: subconjunto del bloque aleatorio para un segundo anotador
   independiente, en su propia carpeta (`gold_v1_a2`).
4. `reanotacion`: 5 % del bloque aleatorio, repetido al final.

Todo va a ciegas y en un orden aleatorio que mezcla los bloques. La cola
(`queue.parquet`) solo lleva lo que la app necesita; el diseño (estrato,
probabilidad, partición, criterio, Gemini, M1) va aparte en `design.parquet`.
"""

import argparse
import json
import pickle
import sys
from datetime import UTC, datetime

import numpy as np
import polars as pl

from voc_analytics.labeling.eligibility import RULES_VERSION, with_tnss_rule
from voc_analytics.paths import LABELS, MODELS
from voc_analytics.sampling.strata import period
from voc_analytics.sentiment.data import (
    SNAPSHOT,
    gold,
    gold_ids,
    silver_rows,
    stars_class,
    training_texts,
    words,
)

SEED = 20261020
OUT = LABELS / "gold_v1"
OUT_A2 = LABELS / "gold_v1_a2"
OOF_CACHE = MODELS / "m1_oof.parquet"
PROMPT_VERSION = "prompt_v3"
MAX_COST_USD = 1.0
MIN_PER_STRATUM = 2
REANNOTATION_SHARE = 0.05
UNCERTAIN_QUANTILE = 0.05
# Opciones de tamaño; `dev` es la fracción del bloque aleatorio que va a dev.
OPTIONS = {
    "A": {"aleatorio": 600, "dev": 0.5, "dirigido": 200, "a2": 100},
    "B": {"aleatorio": 1000, "dev": 0.6, "dirigido": 300, "a2": 100},
    "C": {"aleatorio": 1200, "dev": 0.6, "dirigido": 370, "a2": 100},
}
# Reparto del bloque dirigido, en orden de selección.
DIRECTED = {
    "neu": 0.20,
    "cinco_neg": 0.15,
    "pico_3_4": 0.15,
    "desacuerdo": 0.25,
    "incertidumbre_m1": 0.25,
}
LENGTHS = [(1, 3), (4, 10), (11, 30), (31, None)]


def stars_group() -> pl.Expr:
    return (
        pl.when(pl.col("estrellas") <= 2)
        .then(pl.lit("1-2"))
        .when(pl.col("estrellas") <= 4)
        .then(pl.lit("3-4"))
        .otherwise(pl.lit("5"))
        .alias("grupo_estrellas")
    )


def length_group() -> pl.Expr:
    expr = pl.lit(None, dtype=pl.String)
    for lo, hi in reversed(LENGTHS):
        cond = pl.col("palabras") >= lo
        if hi is not None:
            cond &= pl.col("palabras") <= hi
        expr = (
            pl.when(cond)
            .then(pl.lit(f"{lo}-{hi}" if hi else f"{lo}+"))
            .otherwise(expr)
        )
    return expr.alias("longitud")


def largest_remainder(quota: np.ndarray, total: int) -> np.ndarray:
    """Redondea `quota` a enteros que suman `total`."""
    base = np.floor(quota).astype(int)
    order = np.argsort(-(quota - base), kind="stable")
    base[order[: int(total) - int(base.sum())]] += 1
    return base


# --- Bloque aleatorio ---


def sampling_frame() -> pl.DataFrame:
    df = with_tnss_rule(
        pl.read_parquet(
            SNAPSHOT,
            columns=[
                "id_resena",
                "bank_id",
                "texto_sanitizado",
                "texto_limpio",
                "estrellas",
                "fecha",
            ],
        )
    ).filter(pl.col("tnss_rule").is_null())
    seen_holdout = pl.read_parquet(
        LABELS / "silver_v0" / "rows.parquet", columns=["id_resena", "split"]
    ).filter(pl.col("split") == "holdout_visto")["id_resena"]
    excluded = gold_ids() | set(seen_holdout)
    return (
        df.filter(~pl.col("id_resena").is_in(list(excluded)))
        .with_columns(periodo=period(), grupo=stars_group())
        .with_columns(
            estrato=pl.format("{}|{}|{}", "bank_id", "periodo", "grupo")
        )
        .drop("tnss_rule")
    )


def allocate(frame: pl.DataFrame, total: int, dev_share: float) -> pl.DataFrame:
    """`n_h` por estrato: igual por banco, raíz cuadrada dentro del banco."""
    sizes = (
        frame.group_by("bank_id", "periodo", "grupo", "estrato")
        .len("N_h")
        .sort("estrato")
    )
    banks = sizes["bank_id"].unique().sort().to_list()
    per_bank = largest_remainder(np.full(len(banks), total / len(banks)), total)
    parts = []
    for bank, n_bank in zip(banks, per_bank, strict=True):
        cells = sizes.filter(pl.col("bank_id") == bank)
        floor = np.minimum(cells["N_h"].to_numpy(), MIN_PER_STRATUM)
        root = np.sqrt(cells["N_h"].to_numpy())
        rest = n_bank - floor.sum()
        n_h = floor + largest_remainder(root / root.sum() * rest, rest)
        if (n_h > cells["N_h"].to_numpy()).any():
            raise ValueError(
                f"{bank}: un estrato pide más filas de las que tiene"
            )
        parts.append(cells.with_columns(n_h=pl.Series(n_h)))
    alloc = pl.concat(parts)
    dev = largest_remainder(
        alloc["n_h"].to_numpy() * dev_share, round(total * dev_share)
    )
    return alloc.with_columns(
        n_dev=pl.Series(np.minimum(dev, alloc["n_h"].to_numpy())),
        prob_inclusion=pl.col("n_h") / pl.col("N_h"),
    )


def random_block(frame: pl.DataFrame, alloc: pl.DataFrame) -> pl.DataFrame:
    return (
        frame.join(
            alloc.select("estrato", "n_h", "n_dev", "prob_inclusion"),
            on="estrato",
        )
        .with_columns(
            orden=pl.col("id_resena").hash(SEED).rank("ordinal").over("estrato")
        )
        .filter(pl.col("orden") <= pl.col("n_h"))
        .with_columns(
            r=pl.col("id_resena").hash(SEED + 1).rank("ordinal").over("estrato")
        )
        .with_columns(
            particion=pl.when(pl.col("r") <= pl.col("n_dev"))
            .then(pl.lit("dev"))
            .otherwise(pl.lit("test")),
            bloque=pl.lit("aleatorio"),
        )
        .drop("orden", "r", "n_h", "n_dev")
    )


# --- M1 y bloque dirigido ---


def load_m1():
    """M1 se pickleó desde `__main__` de `baselines.py`."""
    import __main__
    from voc_analytics.sentiment.models.baselines import TfidfLR

    __main__.TfidfLR = TfidfLR
    # Artefacto local de `baselines.py`, no datos externos.
    return pickle.loads((MODELS / "m1_tfidf_lr.pkl").read_bytes())  # noqa: S301


def m1_out_of_fold(train: pl.DataFrame, params: dict) -> pl.DataFrame:
    """Probabilidades de M1 fuera de partición (misma CV que `baselines.py`)."""
    if OOF_CACHE.exists():
        return pl.read_parquet(OOF_CACHE)
    from sklearn.model_selection import StratifiedGroupKFold

    from voc_analytics.sentiment.models.baselines import FOLDS, TfidfLR
    from voc_analytics.sentiment.models.baselines import SEED as CV_SEED

    texts = train["texto_sanitizado"].to_numpy()
    y = train["plata"].to_numpy()
    strata = (
        train["bank_id"] + "|" + train["periodo"] + "|" + train["plata"]
    ).to_numpy()
    probs = np.zeros((train.height, 3))
    folds = StratifiedGroupKFold(FOLDS, shuffle=True, random_state=CV_SEED)
    for k, (fit, held) in enumerate(
        folds.split(texts, strata, train["clave"].to_numpy())
    ):
        model = TfidfLR(**params).fit(texts[fit], y[fit])
        probs[held] = model.predict_proba(texts[held])
        print(f"OOF partición {k + 1}/{FOLDS}", flush=True)
    oof = train.select("text_id").with_columns(
        p_NEG=probs[:, 0], p_NEU=probs[:, 1], p_POS=probs[:, 2]
    )
    oof.write_parquet(OOF_CACHE)
    return oof


def directed_pool(exclude_claves: set[str]) -> pl.DataFrame:
    """Filas candidatas de la plata con Gemini, M1 y las marcas de criterio."""
    rows = silver_rows()
    train = training_texts(rows)
    model = load_m1()
    oof = m1_out_of_fold(train, model.params)
    hold = (
        rows.filter(pl.col("split") == "holdout_nuevo")
        .group_by("text_id")
        .agg(pl.col("texto_sanitizado").first())
    )
    p = model.predict_proba(hold["texto_sanitizado"].to_numpy())
    m1 = pl.concat(
        [
            oof.with_columns(m1_fuente=pl.lit("oof")),
            hold.select("text_id").with_columns(
                p_NEG=p[:, 0],
                p_NEU=p[:, 1],
                p_POS=p[:, 2],
                m1_fuente=pl.lit("completo"),
            ),
        ]
    )
    extra = pl.read_parquet(
        LABELS / "silver_v0" / "rows.parquet",
        columns=["id_resena", "dia_pico_total"],
    )
    gem = pl.read_parquet(
        LABELS / "silver_v0" / "labels_prompt_v3.parquet",
        columns=["text_id", "gemini_falla"],
    )
    probs = pl.concat_list("p_NEG", "p_NEU", "p_POS")
    pool = (
        rows.filter(
            ~pl.col("id_resena").is_in(list(gold_ids()))
            & (pl.col("plata") != "NA")
            & ~pl.col("clave").is_in(list(exclude_claves))
        )
        .join(m1, on="text_id")
        .join(extra, on="id_resena")
        .join(gem, on="text_id")
        .with_columns(
            m1=pl.concat_list(
                pl.lit("NEG"), pl.lit("NEU"), pl.lit("POS")
            ).list.get(probs.list.arg_max()),
            margen_m1=probs.list.sort(descending=True).list.get(0)
            - probs.list.sort(descending=True).list.get(1),
            estrellas_clase=stars_class(),
        )
    )
    cut = pool.unique("text_id")["margen_m1"].quantile(UNCERTAIN_QUANTILE)
    return pool.with_columns(
        c_neu=(pl.col("plata") == "NEU") | (pl.col("m1") == "NEU"),
        c_cinco_neg=(pl.col("estrellas") == 5) & (pl.col("plata") == "NEG"),
        c_pico_3_4=pl.col("estrellas").is_in([3, 4]) & pl.col("dia_pico_total"),
        c_desacuerdo=pl.col("m1") != pl.col("plata"),
        c_incertidumbre_m1=pl.col("margen_m1") <= cut,
    )


def directed_block(pool: pl.DataFrame, total: int) -> tuple[pl.DataFrame, dict]:
    quotas = largest_remainder(np.array(list(DIRECTED.values())) * total, total)
    taken: set[str] = set()
    picked, stats = [], {}
    for (name, _), quota in zip(DIRECTED.items(), quotas, strict=True):
        cands = (
            pool.filter(
                pl.col(f"c_{name}") & ~pl.col("clave").is_in(list(taken))
            )
            .sort(pl.col("id_resena").hash(SEED + 2))
            .unique("clave", keep="first", maintain_order=True)
        )
        take = cands.head(quota).with_columns(criterio=pl.lit(name))
        taken |= set(take["clave"])
        picked.append(take)
        stats[name] = {"cuota": int(quota), "candidatos": cands.height}
    block = pl.concat(picked).with_columns(
        bloque=pl.lit("dirigido"), particion=pl.lit("dev")
    )
    return block, stats


# --- Plan: tiempos, NEU e IC esperados ---


def seconds_by_length() -> dict[str, float]:
    """Segundos medios (truncados a 120) del bloque a ciegas de `gold_v0`."""
    snap = pl.read_parquet(SNAPSHOT, columns=["id_resena", "texto_limpio"])
    ann = (
        pl.read_csv(
            LABELS / "gold_v0" / "annotations.csv", infer_schema_length=0
        )
        .filter((pl.col("bloque") == "aleatorio") & (pl.col("modo") == "ciego"))
        .unique("item_id", keep="first")
        .join(snap, on="id_resena")
        .with_columns(
            palabras=words(), s=pl.col("segundos").cast(pl.Float64).clip(0, 120)
        )
        .with_columns(length_group())
    )
    return dict(ann.group_by("longitud").agg(pl.col("s").mean()).iter_rows())


def expected_seconds(block: pl.DataFrame, secs: dict[str, float]) -> float:
    return float(
        block.with_columns(palabras=words())
        .with_columns(length_group())
        .select(pl.col("longitud").replace_strict(secs).sum())
        .item()
    )


def kappa_half_width(sizes: list[int], reps: int = 1000) -> dict[int, dict]:
    """Semiamplitud del IC 95 % remuestreando *dev* (199) a otros tamaños."""
    from sklearn.metrics import cohen_kappa_score

    preds = MODELS / "preds"
    dev = (
        gold()
        .filter((pl.col("particion") == "dev") & (pl.col("oro") != "NA"))
        .join(
            pl.read_parquet(preds / "M1__dev.parquet").select(
                "item_id", pl.col("pred").alias("m1")
            ),
            on="item_id",
        )
    )
    y, m0, m1 = (dev[c].to_numpy() for c in ("oro", "estrellas_clase", "m1"))
    rng = np.random.default_rng(SEED)
    out = {}
    for n in sizes:
        k1, d = [], []
        for _ in range(reps):
            i = rng.integers(0, len(y), n)
            a = cohen_kappa_score(y[i], m1[i])
            k1.append(a)
            d.append(a - cohen_kappa_score(y[i], m0[i]))
        hw = lambda v: float(np.diff(np.percentile(v, [2.5, 97.5]))[0] / 2)  # noqa: E731
        out[n] = {"kappa_m1": round(hw(k1), 3), "m1_menos_m0": round(hw(d), 3)}
    return out


def kish(weights: np.ndarray) -> float:
    return float(len(weights) * (weights**2).sum() / weights.sum() ** 2)


def neu_rates() -> dict[str, float]:
    """Tasa poblacional de `NEU` de Gemini por grupo de estrellas (plata)."""
    rows = (
        pl.read_parquet(LABELS / "silver_v0" / "rows.parquet")
        .filter(pl.col("split") != "holdout_visto")
        .join(
            pl.read_parquet(LABELS / "silver_v0" / "labels_prompt_v3.parquet"),
            on="text_id",
        )
        .with_columns(stars_group(), w=1 / pl.col("prob_inclusion"))
    )
    return dict(
        rows.group_by("grupo_estrellas")
        .agg(
            ((pl.col("gemini_s") == "NEU") * pl.col("w")).sum()
            / pl.col("w").sum()
        )
        .iter_rows()
    )


def plan() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frame = sampling_frame()
    secs = seconds_by_length()
    rates = neu_rates()
    dev_now = gold().filter(pl.col("particion") == "dev")
    neu_now = dev_now.filter(pl.col("oro") == "NEU").height
    # Precisión de Gemini `NEU` contra el oro *dev* (5 de 7); fuera de `NEU`,
    # la tasa de `NEU` del oro en lo que Gemini no llama `NEU` (2 de 192).
    gem_neu_prec, other_neu = 5 / 7, 2 / 192
    result = {
        "creado": datetime.now(UTC).isoformat(),
        "marco_filas": frame.height,
        "estratos": frame["estrato"].n_unique(),
        "segundos_por_longitud": {k: round(v, 1) for k, v in secs.items()},
        "neu_gemini_por_estrellas": {k: round(v, 4) for k, v in rates.items()},
        "dev_actual": {"items": dev_now.height, "neu": neu_now},
        "opciones": {},
    }
    claves_gold = set(
        pl.read_parquet(
            LABELS / "gold_v0" / "queue.parquet", columns=["id_resena"]
        )
        .join(
            pl.read_parquet(SNAPSHOT, columns=["id_resena", "texto_limpio"]),
            on="id_resena",
        )
        .select(
            pl.col("texto_limpio")
            .str.to_lowercase()
            .str.replace_all(r"[^\p{L}\p{N}]+", "")
        )
        .to_series()
    )
    pool = None
    for name, opt in OPTIONS.items():
        alloc = allocate(frame, opt["aleatorio"], opt["dev"])
        block = random_block(frame, alloc)
        claves = set(
            block.select(
                pl.col("texto_limpio")
                .str.to_lowercase()
                .str.replace_all(r"[^\p{L}\p{N}]+", "")
            ).to_series()
        )
        if pool is None:
            pool = directed_pool(claves_gold)
        directed, stats = directed_block(
            pool.filter(~pl.col("clave").is_in(list(claves))), opt["dirigido"]
        )
        dev_rand = block.filter(pl.col("particion") == "dev")
        neu_rand = float(
            dev_rand.select(pl.col("grupo").replace_strict(rates).sum()).item()
        ) * (2.5 / 1.86)  # el oro tiene más `NEU` que Gemini (2.5 % vs 1.86 %)
        neu_dir = float(
            directed.select(
                pl.when(pl.col("plata") == "NEU")
                .then(gem_neu_prec)
                .otherwise(other_neu)
                .sum()
            ).item()
        )
        repeats = round(block.height * REANNOTATION_SHARE)
        t_main = expected_seconds(block, secs) + expected_seconds(
            directed, secs
        )
        t_rep = repeats * float(np.mean(list(secs.values())))
        t_a2 = expected_seconds(block.head(opt["a2"]), secs)
        w = 1 / block["prob_inclusion"].to_numpy()
        n_dev = dev_now.height + dev_rand.height
        result["opciones"][name] = {
            **opt,
            "dev_aleatorio": n_dev,
            "dev_total": n_dev + directed.height,
            "test": 201 + block.height - dev_rand.height,
            "kish_deff_aleatorio": round(kish(w), 2),
            "grupo_estrellas_aleatorio": dict(
                block["grupo"].value_counts().iter_rows()
            ),
            "neu_esperados_dev": {
                "actuales": neu_now,
                "aleatorio": round(neu_rand, 1),
                "dirigido": round(neu_dir, 1),
                "total": round(neu_now + neu_rand + neu_dir, 1),
            },
            "dirigido": stats,
            "dirigido_longitud": dict(
                directed.with_columns(palabras=words())
                .with_columns(length_group())["longitud"]
                .value_counts()
                .iter_rows()
            ),
            "reanotacion": repeats,
            "minutos_autor": round((t_main + t_rep) / 60, 1),
            "minutos_a2": round(t_a2 / 60, 1),
        }
        print(
            name,
            json.dumps(result["opciones"][name], ensure_ascii=False),
            flush=True,
        )
    sizes = sorted(
        {199}
        | {o["dev_aleatorio"] for o in result["opciones"].values()}
        | {o["test"] for o in result["opciones"].values()}
    )
    result["ic_kappa_semiamplitud"] = kappa_half_width(sizes)
    result["candidatos_dirigido_textos"] = {
        c: pool.filter(pl.col(f"c_{c}"))["clave"].n_unique() for c in DIRECTED
    }
    (OUT / "plan.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "opciones"},
            ensure_ascii=False,
            indent=2,
        )
    )


# --- Cola ---


def queue(option: str) -> None:
    from voc_analytics.labeling.label_gemini import label_frame

    if (OUT / "annotations.csv").exists() or (
        OUT_A2 / "annotations.csv"
    ).exists():
        sys.exit("Ya hay anotaciones en gold_v1; no se regenera la cola.")
    opt = OPTIONS[option]
    OUT.mkdir(parents=True, exist_ok=True)
    OUT_A2.mkdir(parents=True, exist_ok=True)
    frame = sampling_frame()
    alloc = allocate(frame, opt["aleatorio"], opt["dev"])
    block = random_block(frame, alloc).with_columns(
        clave=pl.col("texto_limpio")
        .str.to_lowercase()
        .str.replace_all(r"[^\p{L}\p{N}]+", "")
    )
    claves_gold = set(
        pl.read_parquet(
            LABELS / "gold_v0" / "queue.parquet", columns=["id_resena"]
        )
        .join(
            pl.read_parquet(SNAPSHOT, columns=["id_resena", "texto_limpio"]),
            on="id_resena",
        )
        .select(
            pl.col("texto_limpio")
            .str.to_lowercase()
            .str.replace_all(r"[^\p{L}\p{N}]+", "")
        )
        .to_series()
    )
    pool = directed_pool(claves_gold | set(block["clave"]))
    directed, stats = directed_block(pool, opt["dirigido"])

    # Segundo anotador: proporcional a `n_h` dentro del bloque aleatorio.
    share = opt["a2"] / block.height
    per = alloc.with_columns(
        n_a2=pl.Series(
            largest_remainder(alloc["n_h"].to_numpy() * share, opt["a2"])
        )
    ).select("estrato", "n_a2")
    block = (
        block.join(per, on="estrato")
        .with_columns(
            r=pl.col("id_resena").hash(SEED + 3).rank("ordinal").over("estrato")
        )
        .with_columns(a2=pl.col("r") <= pl.col("n_a2"))
        .drop("r", "n_a2")
    )

    labels, run_meta = label_frame(
        block.select("id_resena", "texto_sanitizado"),
        PROMPT_VERSION,
        id_col="id_resena",
        max_cost_usd=MAX_COST_USD,
    )
    block = block.join(
        labels.select(
            "id_resena", pl.col("gemini_s").alias("plata"), "gemini_falla"
        ),
        on="id_resena",
        how="left",
    )

    # `plata` es la etiqueta de Gemini (`prompt_v3`): de la plata en el
    # dirigido y de la corrida de arriba en el aleatorio.
    design_cols = (
        ["bloque", "particion"]
        + [
            "estrato",
            "prob_inclusion",
            "plata",
            "gemini_falla",
            "criterio",
            "p_NEG",
            "p_NEU",
            "p_POS",
            "m1",
            "margen_m1",
            "m1_fuente",
            "a2",
        ]
        + [f"c_{c}" for c in DIRECTED]
    )
    both = (
        pl.concat([block, directed], how="diagonal_relaxed")
        .sample(fraction=1.0, shuffle=True, seed=SEED)
        .with_row_index("n", offset=1)
        .with_columns(
            item_id=pl.format("G{}", pl.col("n").cast(pl.String).str.zfill(4)),
            modo=pl.lit("ciego"),
        )
        .drop("n")
    )
    repeats = (
        both.filter(pl.col("bloque") == "aleatorio")
        .sample(round(block.height * REANNOTATION_SHARE), seed=SEED)
        .with_row_index("n", offset=1)
        .with_columns(
            repite_item=pl.col("item_id"),
            item_id=pl.format("R{}", pl.col("n").cast(pl.String).str.zfill(3)),
            bloque=pl.lit("reanotacion"),
        )
    )
    app_cols = [
        "item_id",
        "bloque",
        "modo",
        "id_resena",
        "bank_id",
        "texto_sanitizado",
    ]
    q = pl.concat(
        [both.select(app_cols), repeats.select(app_cols)]
    ).with_row_index("orden")
    q.write_parquet(OUT / "queue.parquet")
    pl.concat(
        [
            both.select(
                "item_id", *[c for c in design_cols if c in both.columns]
            ),
            repeats.select("item_id", "repite_item", "bloque"),
        ],
        how="diagonal_relaxed",
    ).write_parquet(OUT / "design.parquet")
    a2 = (
        both.filter(pl.col("a2"))
        .sample(fraction=1.0, shuffle=True, seed=SEED + 4)
        .with_columns(origen_item=pl.col("item_id"), bloque=pl.lit("a2"))
        .drop("n", strict=False)
        .with_row_index("n", offset=1)
        .with_columns(
            item_id=pl.format("S{}", pl.col("n").cast(pl.String).str.zfill(3))
        )
        .select(
            "item_id",
            "origen_item",
            "bloque",
            "modo",
            "id_resena",
            "bank_id",
            "texto_sanitizado",
        )
        .with_row_index("orden")
    )
    a2.write_parquet(OUT_A2 / "queue.parquet")
    (OUT / f"run_{run_meta['run']}.json").write_text(
        json.dumps(run_meta, indent=2) + "\n"
    )
    meta = {
        "option": option,
        **opt,
        "snapshot_file": SNAPSHOT.name,
        "rules_version": RULES_VERSION,
        "seed": SEED,
        "created_at": datetime.now(UTC).isoformat(),
        "marco": "elegibles sin gold_v0 ni silver_v0 holdout_visto",
        "gemini_prompt": PROMPT_VERSION,
        "gemini_run": run_meta["run"],
        "gemini_cost_usd": run_meta["cost_usd"],
        "items": dict(
            q.group_by("bloque", maintain_order=True).len().iter_rows()
        ),
        "aleatorio_por_particion": dict(
            block["particion"].value_counts().iter_rows()
        ),
        "dirigido": stats,
        "a2": a2.height,
        "strata": alloc.to_dicts(),
    }
    (OUT / "queue_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {k: v for k, v in meta.items() if k != "strata"},
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    q = sub.add_parser("queue")
    q.add_argument("--option", choices=sorted(OPTIONS), required=True)
    args = parser.parse_args()
    if args.cmd == "plan":
        plan()
    else:
        queue(args.option)


if __name__ == "__main__":
    main()
