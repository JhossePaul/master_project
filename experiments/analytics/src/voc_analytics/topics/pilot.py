"""Piloto de BERTopic en dos bancos (5.5, fase 1; `topics_design.md` §4.2 y §5).

Sobre los textos `NEG` de la plata de BBVA y NUBANK (conjunto de trabajo de
`working_set`), compara:

* **embeddings:** MiniLM multilingüe contra RoBERTuito base;
* **HDBSCAN:** `min_cluster_size` × `min_samples`, con 3 semillas de UMAP;
* **`TOPIC_TOO_SHORT`:** k = 0 (sin regla) y k ∈ `K_SWEEP`, re-ajustando con
  la mejor configuración.

UMAP se calcula una vez por embedding × semilla (× k) y HDBSCAN + c-TF-IDF se
corren sobre esa reducción. Métricas, ponderadas por 1 / π cuando son
proporciones:

* ruido de HDBSCAN (y tras `reduce_outliers`), número de tópicos;
* coherencia NPMI de las 10 palabras principales y diversidad de tópicos;
* estabilidad: ARI entre semillas (sin el ruido);
* alineación con las familias de `aspects_v1`, `aspects_v2` y `aspects_v2_1`
  (5.2) en los textos codificados: pureza y NMI contra la familia principal,
  ponderadas por número de extracciones (ya son proporcionales a 1 / π);
* para cada k: filas excluidas y, entre ellas, la proporción con un problema
  concreto según `aspects_v2_1` (vigente).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.topics.pilot grid
    uv run python -m voc_analytics.topics.pilot short \\
        [--emb minilm --mcs 50 --ms 10 --banks piloto|todos]

Escribe en `data/topics/pilot_v0/` (fuera de git: asignaciones y palabras de
cada tópico, que pueden contener nombres no sanitizados, FMEA F-01) y solo
agregados en `docs/analytics/topics/topics_pilot_v0_metrics.json`.
"""

import argparse
import itertools
import json
import time
import unicodedata
from datetime import UTC, datetime

import numpy as np
import polars as pl
from bertopic import BERTopic
from bertopic.dimensionality import BaseDimensionalityReduction
from hdbscan import HDBSCAN
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
from spacy.lang.es.stop_words import STOP_WORDS
from umap import UMAP

from voc_analytics.paths import DATA, DOCS
from voc_analytics.topics.working_set import OUT as WORKING

BANKS = ("BBVA", "NUBANK")
ALL_BANKS = ("AZTECA", "BANORTE", "BBVA", "NUBANK", "SANTANDER")
# Referencias de familias (5.2). `aspects_v2_1` es la vigente (validada por el
# autor); `aspects_v2` fue la provisional de la fase 1.
# Extracciones de 5.2: ya son proporcionales a 1 / π, así que las métricas sobre
# textos codificados se ponderan por número de extracciones, no por `peso`.
DRAWS = DATA / "eda" / "aspects_v0" / "draws.parquet"
ASPECTS = {
    "aspects_v1": DATA / "eda" / "aspects_v0" / "labels_aspects_v1.parquet",
    "aspects_v2": DATA
    / "eda"
    / "aspects_v2"
    / "labels_aspects_v2_extracciones.parquet",
    "aspects_v2_1": DATA
    / "eda"
    / "aspects_v2"
    / "labels_aspects_v2_1_extracciones.parquet",
}
VIGENTE = "aspects_v2_1"
OUT = DATA / "topics" / "pilot_v0"
METRICS = DOCS / "topics" / "topics_pilot_v0_metrics.json"
SEEDS = (0, 1, 2)
MCS = (25, 50, 100)
MS = (5, 10, None)  # None = igual a min_cluster_size (valor por defecto)
K_SWEEP = (0, 2, 3, 5, 6, 8, 10)
TOP_N = 10


def strip_accents(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


# Las negaciones distinguen quejas ("no abre", "sin servicio"): no son
# stopwords.
# Sin acentos, porque el vectorizador los quita ("número" y "numero" se unen).
STOP = sorted(
    {strip_accents(w) for w in STOP_WORDS}
    - {"no", "sin", "nunca", "nada", "ningun", "ninguna"}
)


def vectorizer(**kw) -> CountVectorizer:
    return CountVectorizer(strip_accents="unicode", **kw)


def load(
    k: int = 0, banks: tuple[str, ...] = BANKS
) -> tuple[pl.DataFrame, dict[str, np.ndarray]]:
    """Textos del piloto (con `palabras > k`) y sus embeddings alineados."""
    texts = pl.read_parquet(WORKING / "texts.parquet").with_row_index("i")
    rows = pl.read_parquet(
        WORKING / "rows.parquet", columns=["text_id", "bank_id", "peso"]
    )
    pilot = (
        rows.filter(pl.col("bank_id").is_in(banks))
        .group_by("text_id")
        .agg(peso=pl.col("peso").sum())
    )
    df = (
        texts.drop("peso")
        .join(pilot, on="text_id")
        .filter(pl.col("palabras") > k)
        .sort("i")
    )
    draws = (
        pl.read_parquet(DRAWS, columns=["text_id", "bank_id"])
        .filter(pl.col("bank_id").is_in(banks))
        .group_by("text_id")
        .agg(extracciones=pl.len())
    )
    df = df.join(draws, on="text_id", how="left")
    for name, path in ASPECTS.items():
        if path.exists():
            aspects = pl.read_parquet(path).select(
                "text_id",
                pl.col("codes")
                .fill_null("")
                .str.split(",")
                .list.eval(pl.element().filter(pl.element() != ""))
                .alias(name),
            )
            df = df.join(aspects, on="text_id", how="left")
    idx = df["i"].to_numpy()
    embs = {
        m: np.load(WORKING / f"emb_{m}.npy")[idx]
        for m in ("minilm", "robertuito")
    }
    return df, embs


def reduce(emb: np.ndarray, seed: int) -> np.ndarray:
    return UMAP(
        n_components=5,
        n_neighbors=15,
        min_dist=0.0,
        metric="cosine",
        random_state=seed,
        low_memory=True,
    ).fit_transform(emb)


def fit(docs: list[str], red: np.ndarray, mcs: int, ms: int | None) -> BERTopic:
    model = BERTopic(
        umap_model=BaseDimensionalityReduction(),
        hdbscan_model=HDBSCAN(
            min_cluster_size=mcs, min_samples=ms, prediction_data=True
        ),
        # c-TF-IDF ajusta el vectorizador sobre un documento por tópico:
        # `min_df` cuenta tópicos, y un valor > 1 quitaría justo los
        # términos exclusivos de un tópico.
        vectorizer_model=vectorizer(
            stop_words=STOP, ngram_range=(1, 2), min_df=1
        ),
        # Con "english", BERTopic borra todo lo que no sea A-Z
        # ("crédito" → "crdito").
        language="multilingual",
        top_n_words=TOP_N,
        calculate_probabilities=False,
    )
    model.fit(docs, embeddings=red)
    return model


def npmi(model: BERTopic, docs: list[str]) -> tuple[float, float]:
    """NPMI medio de las palabras principales (unigramas) y diversidad."""
    tops = [
        [w for w, _ in model.get_topic(t) if " " not in w][:TOP_N]
        for t in model.get_topics()
        if t != -1
    ]
    vocab = sorted({w for top in tops for w in top})
    if not vocab:
        return float("nan"), float("nan")
    x = vectorizer(vocabulary=vocab, binary=True).fit_transform(docs).tocsc()
    n = x.shape[0]
    p = np.asarray(x.sum(axis=0)).ravel() / n
    pos = {w: j for j, w in enumerate(vocab)}
    scores = []
    for top in tops:
        for a, b in itertools.combinations(top, 2):
            i, j = pos[a], pos[b]
            pij = x[:, i].multiply(x[:, j]).sum() / n
            if pij == 0:
                scores.append(-1.0)
            else:
                scores.append(np.log(pij / (p[i] * p[j])) / -np.log(pij))
    words = [w for top in tops for w in top]
    return float(np.mean(scores)), len(set(words)) / max(len(words), 1)


def alignment(topics: np.ndarray, df: pl.DataFrame, ref: str) -> dict:
    """Pureza ponderada y NMI de los tópicos contra las familias de `ref`."""
    d = (
        df.rename({ref: "familias"})
        .with_columns(topic=pl.Series(topics))
        .filter(
            pl.col("familias").is_not_null()
            & pl.col("extracciones").is_not_null()
            & (pl.col("topic") != -1)
        )
        .with_columns(peso=pl.col("extracciones").cast(pl.Float64))
    )
    if d.height == 0:
        return {"n": 0}
    exploded = d.explode("familias", empty_as_null=True).with_columns(
        pl.col("familias").fill_null("SIN")
    )
    majority = (
        exploded.group_by("topic", "familias")
        .agg(w=pl.col("peso").sum())
        .sort("w", descending=True)
        .group_by("topic")
        .first()
        .select("topic", mayoritaria="familias")
    )
    hit = d.join(majority, on="topic").with_columns(
        acierto=pl.when(pl.col("familias").list.len() == 0)
        .then(pl.col("mayoritaria") == "SIN")
        .otherwise(pl.col("familias").list.contains(pl.col("mayoritaria")))
    )
    purity = (hit["acierto"].cast(pl.Float64) * hit["peso"]).sum() / hit[
        "peso"
    ].sum()
    principal = d["familias"].map_elements(
        lambda f: f[0] if len(f) else "SIN", return_dtype=pl.String
    )
    return {
        "n": d.height,
        "pureza": round(float(purity), 4),
        "nmi": round(
            float(normalized_mutual_info_score(principal, d["topic"])), 4
        ),
    }


def noise_by_length(topics: np.ndarray, df: pl.DataFrame) -> dict:
    """Ruido ponderado por banda de palabras (¿son quejas cortas genéricas?)."""
    d = df.with_columns(ruido=pl.Series(topics) == -1).with_columns(
        banda=pl.when(pl.col("palabras") <= 5)
        .then(pl.lit("1-5"))
        .when(pl.col("palabras") <= 15)
        .then(pl.lit("6-15"))
        .when(pl.col("palabras") <= 40)
        .then(pl.lit("16-40"))
        .otherwise(pl.lit("41+"))
    )
    g = d.group_by("banda").agg(
        r=(pl.col("ruido").cast(pl.Float64) * pl.col("peso")).sum()
        / pl.col("peso").sum()
    )
    return {b: round(float(r), 4) for b, r in g.sort("banda").iter_rows()}


def summarize(
    model: BERTopic, topics: np.ndarray, df: pl.DataFrame, docs: list[str]
) -> dict:
    w = df["peso"].to_numpy()
    noise = float(w[topics == -1].sum() / w.sum())
    reduced = (
        np.array(
            model.reduce_outliers(
                docs, topics, strategy="c-tf-idf", threshold=0.1
            )
        )
        if (topics == -1).any()
        else topics
    )
    coh, div = npmi(model, docs)
    return {
        "topicos": int(topics.max() + 1),
        "ruido": round(noise, 4),
        "ruido_tras_reduce_outliers": round(
            float(w[reduced == -1].sum() / w.sum()), 4
        ),
        "ruido_por_largo": noise_by_length(topics, df),
        "npmi": round(coh, 4),
        "diversidad": round(div, 4),
        **{
            f"alineacion_{ref}": alignment(topics, df, ref)
            for ref in ASPECTS
            if ref in df.columns
        },
    }


def grid() -> list[dict]:
    df, embs = load()
    docs = df["texto_sanitizado"].to_list()
    results = []
    for emb_name, emb in embs.items():
        reds = {s: reduce(emb, s) for s in SEEDS}
        for mcs, ms in itertools.product(MCS, MS):
            t0 = time.perf_counter()
            runs = {}
            for s, red in reds.items():
                model = fit(docs, red, mcs, ms)
                runs[s] = (model, np.array(model.topics_))
            base_model, base = runs[SEEDS[0]]
            aris = []
            for s in SEEDS[1:]:
                other = runs[s][1]
                keep = (base != -1) & (other != -1)
                aris.append(adjusted_rand_score(base[keep], other[keep]))
            res = {
                "emb": emb_name,
                "min_cluster_size": mcs,
                "min_samples": ms,
                **summarize(base_model, base, df, docs),
                "ruido_semillas": [
                    round(
                        float(
                            df["peso"].to_numpy()[r[1] == -1].sum()
                            / df["peso"].sum()
                        ),
                        4,
                    )
                    for r in runs.values()
                ],
                "ari_semillas": round(float(np.mean(aris)), 4),
                "segundos": round(time.perf_counter() - t0, 1),
            }
            print(json.dumps(res, ensure_ascii=False), flush=True)
            results.append(res)
    return results


def short(
    emb_name: str, mcs: int, ms: int | None, banks: tuple[str, ...] = BANKS
) -> list[dict]:
    """Barrido de `TOPIC_TOO_SHORT`: re-ajusta con `palabras > k`."""
    full, _ = load(banks=banks)
    total = full["peso"].sum()
    out = []
    for k in K_SWEEP:
        df, embs = load(k, banks)
        docs = df["texto_sanitizado"].to_list()
        model = fit(docs, reduce(embs[emb_name], SEEDS[0]), mcs, ms)
        topics = np.array(model.topics_)
        excl = full.filter(pl.col("palabras") <= k)
        ref = VIGENTE if VIGENTE in full.columns else "aspects_v1"
        coded = excl.filter(
            pl.col(ref).is_not_null() & pl.col("extracciones").is_not_null()
        ).with_columns(peso=pl.col("extracciones").cast(pl.Float64))
        res = {
            "k": k,
            "excluidas": round(float(excl["peso"].sum() / total), 4),
            "referencia_problema": ref,
            "excluidas_codificadas": coded.height,
            "excluidas_con_problema": (
                round(
                    float(
                        coded.filter(pl.col(ref).list.len() > 0)["peso"].sum()
                        / coded["peso"].sum()
                    ),
                    4,
                )
                if coded.height
                else None
            ),
            **summarize(model, topics, df, docs),
        }
        print(json.dumps(res, ensure_ascii=False), flush=True)
        out.append(res)
        if k == 0:
            OUT.mkdir(parents=True, exist_ok=True)
            tag = f"{emb_name}_mcs{mcs}_ms{ms}_{len(banks)}bancos_k0"
            df.select("text_id", "peso").with_columns(
                topic=pl.Series(topics)
            ).write_parquet(OUT / f"assign_{tag}.parquet")
            info = model.get_topic_info().drop(
                columns=["Representative_Docs"], errors="ignore"
            )
            pl.from_pandas(info).write_parquet(OUT / f"topics_{tag}.parquet")
    return out


def write(
    key: str, value: list[dict], params: dict, banks: tuple[str, ...] = BANKS
) -> None:
    metrics = json.loads(METRICS.read_text()) if METRICS.exists() else {}
    metrics.update(
        {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "source": "topics_working_v0 (plata NEG); bancos en cada params",
            "aspects_reference": "aspects_v1, aspects_v2 (provisional) y "
            "aspects_v2_1 (vigente) de 5.2",
            "bancos_ultima_corrida": list(banks),
            key: {"params": params, "results": value},
        }
    )
    METRICS.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("grid")
    s = sub.add_parser("short")
    s.add_argument("--emb", choices=("minilm", "robertuito"), default="minilm")
    s.add_argument("--mcs", type=int, default=50)
    s.add_argument("--ms", type=int, default=10)
    s.add_argument("--banks", choices=("piloto", "todos"), default="piloto")
    a = p.parse_args()
    if a.cmd == "grid":
        write(
            "grid",
            grid(),
            {
                "seeds": SEEDS,
                "mcs": MCS,
                "ms": MS,
                "umap": "5d, 15 vecinos, coseno",
            },
        )
    else:
        banks = ALL_BANKS if a.banks == "todos" else BANKS
        suffix = "_5bancos" if a.banks == "todos" else ""
        write(
            f"short_{a.emb}_mcs{a.mcs}_ms{a.ms}{suffix}",
            short(a.emb, a.mcs, a.ms, banks),
            {
                "emb": a.emb,
                "mcs": a.mcs,
                "ms": a.ms,
                "k": K_SWEEP,
                "bancos": list(banks),
            },
            banks,
        )


if __name__ == "__main__":
    main()
