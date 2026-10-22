"""Fase 2 de 5.5: unidad de análisis, lectura temporal y señal de incidentes.

Sobre los 5 bancos (textos `NEG` de la plata, `working_set`) y con MiniLM +
BERTopic (`min_samples` 10; `topics_design.md` §4–§8):

* **units:** compara tres unidades para recuperar el multi-aspecto:
  * `resena`: un tópico por reseña completa;
  * `clausulas`: BERTopic sobre los segmentos de `units` (`clauses_v0`); la
    reseña toma el conjunto de tópicos de sus segmentos;
  * `distribucion`: el modelo de `resena` con `approximate_distribution`; la
    reseña toma los tópicos con probabilidad ≥ umbral.

  Cada tópico se mapea a una familia de `REF` (`aspects_v2_1`, vigente) con la
  familia mayoritaria de los textos codificados que lo contienen, por
  validación cruzada de 5 particiones (el mapeo no ve el texto evaluado).
  Métricas: F1 micro de los conjuntos de familias, proporción multi-aspecto
  predicha contra la codificada y su κ, cobertura (reseñas con ≥ 1 tópico),
  número de tópicos y NPMI. Los textos codificados se ponderan por número de
  extracciones (ya son proporcionales a 1 / π); la cobertura, por 1 / π.
* **dynamics:** con la variante elegida, proporción de cada tópico por banco ×
  trimestre y banco × mes (filas `NEG` ponderadas por 1 / π), las hipótesis
  H-T1 a H-T3 por palabras clave en los términos de los tópicos, la señal de
  incidentes mensual (z robusto contra los 12 meses previos) probada hacia
  atrás con los picos de BBVA, y la divergencia entre versiones consecutivas.
* **families** (fase 3, vía B a escala): las familias `aspects_v2_1` de los
  40 382 textos (`aspects_scale`) como series por banco × trimestre y × mes,
  con la marca `u` como una serie más; la misma señal de incidentes que los
  tópicos (mismo z, línea base y mínimo de filas) para comparar recall,
  adelanto y falsas alarmas; y tópicos contra familias sobre los 40 382
  textos (F1 por familia con mapeo cruzado, pureza, tópicos no alineados),
  ponderados por 1 / π.
* **review** (fase 4): material para el autor en `data/topics/phase4_v0/`
  (fuera de git, porque lleva términos y ejemplos de reseñas): los
  `REVIEW_TOP` tópicos con más peso, los no alineados y las etiquetas de las
  hipótesis, con plantillas CSV para anotar.
* **ab** (fase 3): tópicos (vía A) contra familias (vía B) en las 1 500
  extracciones de 5.2: F1 por familia con el mapeo cruzado, pureza de los
  tópicos, tópicos candidatos a emergentes (mayoría "sin problema" u `OT`, o
  pureza < 0.5), proporción con problema concreto por largo (para
  `TOPIC_TOO_SHORT`) y H-T4 (marca `u` según los días desde la versión).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.topics.dynamics units
    uv run python -m voc_analytics.topics.dynamics dynamics \\
        --variant clausulas_mcs100
    uv run python -m voc_analytics.topics.dynamics ab
    uv run python -m voc_analytics.topics.dynamics families
    uv run python -m voc_analytics.topics.dynamics review

Escribe en `data/topics/phase2_v0/` (fuera de git: asignaciones, términos y
series por tópico) y solo agregados en
`docs/analytics/topics/topics_phase2_v0_metrics.json`.
"""

import argparse
import json
import re
import time
from datetime import UTC, datetime

import numpy as np
import polars as pl
from bertopic import BERTopic
from sklearn.metrics import cohen_kappa_score

from voc_analytics.paths import DATA, DOCS
from voc_analytics.topics.pilot import (
    ASPECTS,
    DRAWS,
    VIGENTE,
    fit,
    npmi,
    reduce,
)
from voc_analytics.topics.working_set import OUT as WORKING

OUT = DATA / "topics" / "phase2_v0"
METRICS = DOCS / "topics" / "topics_phase2_v0_metrics.json"
REF = VIGENTE
MCS = (50, 100, 150)
MS = 10
THRESHOLDS = (0.15, 0.3)  # `approximate_distribution`
FOLDS = 5
SEED = 0
# Picos de incidente del EDA (H5) para la prueba hacia atrás, por banco y mes.
INCIDENTS = {("BBVA", "2024-07"), ("BBVA", "2025-10"), ("BBVA", "2025-11")}
Z_ALERT = 3.0
BASELINE_MONTHS = 12
MIN_BASELINE = 6
MIN_ROWS_TOPIC = 10  # filas sin ponderar del tópico en el mes para alertar
# Hipótesis temporales (`topics_design.md` §8): patrones sobre los términos.
# Un tópico cuenta si el patrón aparece en sus `TOP_TERMS` primeros términos.
HYPOTHESES = {
    "H-T1 token": r"\btoken\b|llavero",
    "H-T1 wallet": r"\bwallet\b",
    "H-T2 biometria": r"facial|biometr|huella|rostro",
    "H-T2 alta digital": r"registr|\bine\b|verificacion|identidad",
}
TOP_TERMS = 3
PT_MARKERS = r"\b(?:nao|voce|obrigad[oa]|muito|aplicativo|cartao)\b"


# --------------------------------------------------------------------------
# Datos
# --------------------------------------------------------------------------


def load_texts() -> pl.DataFrame:
    texts = pl.read_parquet(WORKING / "texts.parquet").with_row_index("i")
    draws = (
        pl.read_parquet(DRAWS, columns=["text_id"])
        .group_by("text_id")
        .agg(extracciones=pl.len())
    )
    aspects = pl.read_parquet(ASPECTS[REF]).select(
        "text_id",
        pl.col("codes")
        .fill_null("")
        .str.split(",")
        .list.eval(pl.element().filter(pl.element() != ""))
        .alias("familias"),
    )
    return (
        texts.join(draws, on="text_id", how="left")
        .join(aspects, on="text_id", how="left")
        .sort("i")
    )


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------


def family_map(
    sets: list[list[int]], fams: list[list[str]], w: np.ndarray
) -> dict[int, str]:
    """Familia mayoritaria (o `SIN`) de cada tópico entre los textos dados."""
    acc: dict[int, dict[str, float]] = {}
    for ts, fs, wi in zip(sets, fams, w, strict=True):
        for t in ts:
            for f in fs or ["SIN"]:
                acc.setdefault(t, {}).setdefault(f, 0.0)
                acc[t][f] += wi
    return {t: max(c, key=c.get) for t, c in acc.items()}


def evaluate(sets: list[list[int]], df: pl.DataFrame) -> dict:
    """Recupera las familias de `REF` (mapeo cruzado tópico → familia)."""
    coded = df.with_columns(
        sets=pl.Series(sets, dtype=pl.List(pl.Int64))
    ).filter(
        pl.col("familias").is_not_null() & pl.col("extracciones").is_not_null()
    )
    rng = np.random.default_rng(SEED)
    fold = rng.integers(0, FOLDS, coded.height)
    s, f, w = (
        coded["sets"].to_list(),
        coded["familias"].to_list(),
        coded["extracciones"].to_numpy(),
    )
    pred: list[set[str]] = [set()] * coded.height
    for k in range(FOLDS):
        tr = np.flatnonzero(fold != k)
        fmap = family_map([s[i] for i in tr], [f[i] for i in tr], w[tr])
        for i in np.flatnonzero(fold == k):
            pred[i] = {fmap[t] for t in s[i] if t in fmap} - {"SIN"}
    tp = fp = fn = 0.0
    for p, g, wi in zip(pred, f, w, strict=True):
        g = set(g)
        tp += wi * len(p & g)
        fp += wi * len(p - g)
        fn += wi * len(g - p)
    multi_p = np.array([len(p) >= 2 for p in pred])
    multi_g = np.array([len(g) >= 2 for g in f])
    return {
        "n_codificados": coded.height,
        "f1_familias": round(2 * tp / (2 * tp + fp + fn), 4),
        "precision_familias": round(tp / (tp + fp), 4) if tp + fp else None,
        "recall_familias": round(tp / (tp + fn), 4),
        "multi_predicho": round(float((multi_p * w).sum() / w.sum()), 4),
        "multi_codificado": round(float((multi_g * w).sum() / w.sum()), 4),
        "kappa_multi": round(
            float(cohen_kappa_score(multi_g, multi_p, sample_weight=w)), 4
        ),
    }


def coverage(sets: list[list[int]], df: pl.DataFrame) -> float:
    w = df["peso"].to_numpy()
    has = np.array([len(x) > 0 for x in sets])
    return round(float((has * w).sum() / w.sum()), 4)


def save_sets(
    name: str, df: pl.DataFrame, sets: list[list[int]], model: BERTopic
) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.select("text_id").with_columns(
        topicos=pl.Series(sets, dtype=pl.List(pl.Int64))
    ).write_parquet(OUT / f"sets_{name}.parquet")
    terms = pl.DataFrame(
        {
            "topic": list(model.get_topics()),
            "terminos": [
                [w for w, _ in model.get_topic(t)] for t in model.get_topics()
            ],
        }
    ).filter(pl.col("topic") != -1)
    terms.write_parquet(OUT / f"terms_{name}.parquet")


def units() -> list[dict]:
    df = load_texts()
    docs = df["texto_sanitizado"].to_list()
    seg = pl.read_parquet(WORKING / "segments.parquet")
    seg_docs = seg["segmento"].to_list()
    red_r = reduce(np.load(WORKING / "emb_minilm.npy"), SEED)
    red_s = reduce(np.load(WORKING / "emb_segments_minilm.npy"), SEED)
    pos = {tid: j for j, tid in enumerate(df["text_id"].to_list())}
    results = []
    for mcs in MCS:
        t0 = time.perf_counter()
        m_r = fit(docs, red_r, mcs, MS)
        topics = np.array(m_r.topics_)
        sets_r = [[int(t)] if t != -1 else [] for t in topics]
        base = {
            "min_cluster_size": mcs,
            "topicos": int(topics.max() + 1),
            "npmi": round(npmi(m_r, docs)[0], 4),
        }
        results.append(
            {
                "variante": f"resena_mcs{mcs}",
                **base,
                "cobertura": coverage(sets_r, df),
                **evaluate(sets_r, df),
            }
        )
        save_sets(f"resena_mcs{mcs}", df, sets_r, m_r)
        distr, _ = m_r.approximate_distribution(
            docs, window=4, stride=1, batch_size=2000
        )
        for thr in THRESHOLDS:
            sets_d = [np.flatnonzero(row >= thr).tolist() for row in distr]
            name = f"distribucion_mcs{mcs}_p{thr}"
            results.append(
                {
                    "variante": name,
                    **base,
                    "cobertura": coverage(sets_d, df),
                    **evaluate(sets_d, df),
                }
            )
            save_sets(name, df, sets_d, m_r)

        m_s = fit(seg_docs, red_s, mcs, MS)
        st = np.array(m_s.topics_)
        by_text: list[set[int]] = [set() for _ in range(df.height)]
        for tid, t in zip(seg["text_id"].to_list(), st, strict=True):
            if t != -1:
                by_text[pos[tid]].add(int(t))
        sets_s = [sorted(x) for x in by_text]
        results.append(
            {
                "variante": f"clausulas_mcs{mcs}",
                "min_cluster_size": mcs,
                "topicos": int(st.max() + 1),
                "npmi": round(npmi(m_s, seg_docs)[0], 4),
                "ruido_segmentos": round(float((st == -1).mean()), 4),
                "cobertura": coverage(sets_s, df),
                **evaluate(sets_s, df),
            }
        )
        save_sets(f"clausulas_mcs{mcs}", df, sets_s, m_s)
        for r in results[-4:]:
            print(json.dumps(r, ensure_ascii=False), flush=True)
        print(f"mcs {mcs}: {time.perf_counter() - t0:.0f} s", flush=True)
    return results


# --------------------------------------------------------------------------
# dynamics
# --------------------------------------------------------------------------


def topic_rows(variant: str) -> pl.DataFrame:
    """Una fila por reseña `NEG` de la plata con sus tópicos, peso y fecha."""
    return period_rows(pl.read_parquet(OUT / f"sets_{variant}.parquet"))


def period_rows(sets: pl.DataFrame) -> pl.DataFrame:
    """Une `sets` (`text_id`, `topicos`) a las filas `NEG`."""
    rows = pl.read_parquet(
        WORKING / "rows.parquet",
        columns=[
            "id_resena",
            "text_id",
            "bank_id",
            "fecha",
            "peso",
            "release_agrupada",
        ],
    ).with_columns(
        mes=pl.col("fecha").dt.strftime("%Y-%m"),
        trimestre=pl.col("fecha").dt.year().cast(pl.String)
        + "T"
        + pl.col("fecha").dt.quarter().cast(pl.String),
    )
    return rows.join(sets, on="text_id")


def shares(tr: pl.DataFrame, period: str) -> pl.DataFrame:
    """Proporción ponderada de filas `NEG` por tópico, banco y periodo."""
    totals = tr.group_by("bank_id", period).agg(
        total=pl.col("peso").sum(), filas=pl.len()
    )
    per = (
        tr.explode("topicos")
        .filter(pl.col("topicos").is_not_null())
        .group_by("bank_id", period, "topicos")
        .agg(w=pl.col("peso").sum(), n=pl.len())
    )
    return per.join(totals, on=["bank_id", period]).with_columns(
        share=pl.col("w") / pl.col("total")
    )


def match_topics(terms: pl.DataFrame, pattern: str) -> list[int]:
    rx = re.compile(pattern, flags=re.IGNORECASE)
    return [
        t
        for t, ws in terms.iter_rows()
        if any(rx.search(w) for w in ws[:TOP_TERMS])
    ]


def hypotheses(tr: pl.DataFrame, terms: pl.DataFrame) -> dict:
    """Proporción de filas `NEG` con tópicos de cada hipótesis."""
    stage = (
        pl.when(pl.col("fecha").dt.year() <= 2017)
        .then(pl.lit("<=2017"))
        .when(pl.col("fecha").dt.year() <= 2020)
        .then(pl.lit("2018-2020"))
        .when(pl.col("fecha").dt.year() <= 2023)
        .then(pl.lit("2021-2023"))
        .otherwise(pl.lit("2024+"))
    )
    t = tr.with_columns(etapa=stage)
    out = {}
    for name, pattern in HYPOTHESES.items():
        ids = match_topics(terms, pattern)
        g = (
            t.with_columns(
                hit=pl.col("topicos")
                .list.eval(pl.element().is_in(ids))
                .list.any()
            )
            .group_by("bank_id", "etapa")
            .agg(
                share=(pl.col("hit").cast(pl.Float64) * pl.col("peso")).sum()
                / pl.col("peso").sum(),
                filas=pl.len(),
            )
            .sort("bank_id", "etapa")
        )
        out[name] = {
            "topicos": len(ids),
            "por_banco_etapa": [
                {"banco": b, "etapa": e, "share": round(s, 4), "filas": n}
                for b, e, s, n in g.iter_rows()
            ],
        }
    return out


def bank_specific(tr: pl.DataFrame, terms: pl.DataFrame) -> dict:
    """Tópicos concentrados en un banco (≥ 80 % de su peso) y marcas de PT."""
    per = (
        tr.explode("topicos")
        .filter(pl.col("topicos").is_not_null())
        .group_by("topicos", "bank_id")
        .agg(w=pl.col("peso").sum())
    )
    tot = per.group_by("topicos").agg(tw=pl.col("w").sum())
    top = (
        per.join(tot, on="topicos")
        .with_columns(frac=pl.col("w") / pl.col("tw"))
        .sort("frac", descending=True)
        .group_by("topicos")
        .first()
    )
    spec = (
        top.filter(pl.col("frac") >= 0.8)
        .group_by("bank_id")
        .len()
        .sort("bank_id")
    )
    pt = match_topics(terms, PT_MARKERS)
    return {
        "topicos": tot.height,
        "especificos_por_banco": dict(spec.iter_rows()),
        "topicos_con_marcas_de_portugues": len(pt),
    }


def signal(monthly: pl.DataFrame) -> pl.DataFrame:
    """z robusto de la proporción mensual de cada tópico (12 meses previos)."""
    months = sorted(monthly["mes"].unique().to_list())
    idx = {m: i for i, m in enumerate(months)}
    full = []
    for (bank, topic), g in monthly.group_by("bank_id", "topicos"):
        series = np.full(len(months), np.nan)
        counts = np.zeros(len(months))
        for m, s, n in g.select("mes", "share", "n").iter_rows():
            series[idx[m]] = s
            counts[idx[m]] = n
        # Meses con negativas del banco pero sin el tópico cuentan como 0.
        present = (
            monthly.filter(pl.col("bank_id") == bank)["mes"].unique().to_list()
        )
        for m in present:
            if np.isnan(series[idx[m]]):
                series[idx[m]] = 0.0
        for i, m in enumerate(months):
            hist = series[max(0, i - BASELINE_MONTHS) : i]
            hist = hist[~np.isnan(hist)]
            if np.isnan(series[i]) or len(hist) < MIN_BASELINE:
                continue
            med = np.median(hist)
            mad = 1.4826 * np.median(np.abs(hist - med))
            z = (series[i] - med) / max(mad, 0.01)
            full.append(
                (
                    bank,
                    topic,
                    m,
                    float(series[i]),
                    float(med),
                    float(z),
                    int(counts[i]),
                )
            )
    return pl.DataFrame(
        full,
        schema=["bank_id", "topicos", "mes", "share", "base", "z", "n"],
        orient="row",
    ).with_columns(
        alerta=(pl.col("z") >= Z_ALERT) & (pl.col("n") >= MIN_ROWS_TOPIC)
    )


def volume_signal(tr: pl.DataFrame) -> pl.DataFrame:
    """Referencia sin tópicos: z robusto del volumen `NEG` ponderado del mes."""
    v = (
        tr.group_by("bank_id", "mes")
        .agg(w=pl.col("peso").sum())
        .sort("bank_id", "mes")
    )
    out = []
    for bank, g in v.group_by("bank_id"):
        w = g.sort("mes")["w"].to_numpy()
        for i, m in enumerate(g.sort("mes")["mes"].to_list()):
            hist = w[max(0, i - BASELINE_MONTHS) : i]
            if len(hist) < MIN_BASELINE:
                continue
            med = np.median(hist)
            mad = 1.4826 * np.median(np.abs(hist - med))
            out.append((bank[0], m, float((w[i] - med) / max(mad, 1.0))))
    return pl.DataFrame(out, schema=["bank_id", "mes", "z"], orient="row")


def backtest(sig: pl.DataFrame, vol: pl.DataFrame) -> dict:
    alerts = sig.filter("alerta")
    by_month = alerts.group_by("bank_id", "mes").agg(topicos=pl.len())
    evaluable = sig.select("bank_id", "mes").unique()
    inc = []
    for bank, mes in sorted(INCIDENTS):
        y, mm = map(int, mes.split("-"))
        prev = f"{y - (mm == 1)}-{(mm - 2) % 12 + 1:02d}"
        here = by_month.filter(
            (pl.col("bank_id") == bank) & (pl.col("mes") == mes)
        )
        before = by_month.filter(
            (pl.col("bank_id") == bank) & (pl.col("mes") == prev)
        )
        vz = vol.filter((pl.col("bank_id") == bank) & (pl.col("mes") == mes))[
            "z"
        ]
        vzp = vol.filter((pl.col("bank_id") == bank) & (pl.col("mes") == prev))[
            "z"
        ]
        inc.append(
            {
                "banco": bank,
                "mes": mes,
                "topicos_en_alerta": int(here["topicos"].sum())
                if here.height
                else 0,
                "topicos_en_alerta_mes_previo": int(before["topicos"].sum())
                if before.height
                else 0,
                "z_volumen": round(float(vz[0]), 2) if len(vz) else None,
                "z_volumen_mes_previo": round(float(vzp[0]), 2)
                if len(vzp)
                else None,
            }
        )
    others = by_month.filter(
        ~pl.struct("bank_id", "mes").is_in(
            [{"bank_id": b, "mes": m} for b, m in INCIDENTS]
        )
    )
    n_other = evaluable.height - len(INCIDENTS)
    vol_alerts = vol.filter(pl.col("z") >= Z_ALERT)
    return {
        "z_alerta": Z_ALERT,
        "min_filas_topico": MIN_ROWS_TOPIC,
        "incidentes": inc,
        "meses_banco_evaluables": evaluable.height,
        "meses_sin_incidente_con_alerta": others.height,
        "tasa_meses_con_alerta_fuera_de_incidentes": round(
            others.height / n_other, 4
        ),
        "meses_con_alerta_de_volumen": vol_alerts.height,
        "meses_con_alerta_de_volumen_fuera_de_incidentes": vol_alerts.filter(
            ~pl.struct("bank_id", "mes").is_in(
                [{"bank_id": b, "mes": m} for b, m in INCIDENTS]
            )
        ).height,
    }


def _kl(p: np.ndarray, q: np.ndarray) -> float:
    return float(np.sum(p[p > 0] * np.log2(p[p > 0] / q[p > 0])))


def versions(tr: pl.DataFrame) -> dict:
    """Divergencia de Jensen-Shannon entre versiones consecutivas con masa."""
    t = tr.filter(
        pl.col("release_agrupada").is_not_null()
        & (pl.col("release_agrupada") != "OTRAS")
    )
    first = t.group_by("bank_id", "release_agrupada").agg(
        desde=pl.col("fecha").min(), filas=pl.len()
    )
    dist = (
        t.explode("topicos")
        .with_columns(pl.col("topicos").fill_null(-1))
        .group_by("bank_id", "release_agrupada", "topicos")
        .agg(w=pl.col("peso").sum())
    )
    out = {}
    for (bank,), g in first.sort("desde").group_by(
        "bank_id", maintain_order=True
    ):
        rels = g.sort("desde")["release_agrupada"].to_list()
        js = []
        for a, b in zip(rels, rels[1:], strict=False):
            pa = dist.filter(
                (pl.col("bank_id") == bank) & (pl.col("release_agrupada") == a)
            )
            pb = dist.filter(
                (pl.col("bank_id") == bank) & (pl.col("release_agrupada") == b)
            )
            keys = sorted(set(pa["topicos"]) | set(pb["topicos"]))
            va = np.array(
                [pa.filter(pl.col("topicos") == k)["w"].sum() for k in keys],
                dtype=float,
            )
            vb = np.array(
                [pb.filter(pl.col("topicos") == k)["w"].sum() for k in keys],
                dtype=float,
            )
            va, vb = va / va.sum(), vb / vb.sum()
            m = (va + vb) / 2
            js.append(0.5 * _kl(va, m) + 0.5 * _kl(vb, m))
        if js:
            out[bank] = {
                "versiones_con_masa": len(rels),
                "js_mediana": round(float(np.median(js)), 4),
                "js_p90": round(float(np.quantile(js, 0.9)), 4),
            }
    return out


def dynamics(variant: str) -> dict:
    tr = topic_rows(variant)
    terms = pl.read_parquet(OUT / f"terms_{variant}.parquet")
    quarterly = shares(tr, "trimestre")
    monthly = shares(tr, "mes")
    quarterly.write_parquet(OUT / f"quarterly_{variant}.parquet")
    sig = signal(monthly)
    sig.write_parquet(OUT / f"signal_{variant}.parquet")
    vol = volume_signal(tr)
    # Persistencia: trimestres (con ≥ 30 filas del banco) en que cada tópico
    # supera el 1 %.
    q = quarterly.filter(pl.col("filas") >= 30)
    nq = q.select("bank_id", "trimestre").unique().height
    persist = (
        q.filter(pl.col("share") >= 0.01)
        .group_by("topicos")
        .agg(trimestres=pl.len())
    )
    frac = (persist["trimestres"] / nq).to_numpy()
    res = {
        "variante": variant,
        "trimestres_banco_evaluables": nq,
        "persistencia_topicos": {
            "estables_>=50%_de_trimestres": int((frac >= 0.5).sum()),
            "intermitentes_10-50%": int(((frac >= 0.1) & (frac < 0.5)).sum()),
            "raros_<10%": int((frac < 0.1).sum()),
        },
        "hipotesis": hypotheses(tr, terms),
        "especificidad_por_banco": bank_specific(tr, terms),
        "senal_incidentes": backtest(sig, vol),
        "versiones": versions(tr),
    }
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return res


# --------------------------------------------------------------------------
# ab (fase 3)
# --------------------------------------------------------------------------

AB_VARIANTS = ("clausulas_mcs100", "resena_mcs100")
MIN_SUPPORT = 10  # extracciones de un tópico para medir su pureza
LENGTH_BANDS = ((1, 1), (2, 2), (3, 5), (6, 10), (11, 10_000))
DAY_BANDS = ((0, 3), (4, 7), (8, 14), (15, 30), (31, 100_000))


def coded_draws() -> pl.DataFrame:
    """Una fila por extracción de 5.2, con familias y marcas de `REF`."""
    draws = pl.read_parquet(
        DRAWS,
        columns=[
            "text_id",
            "bank_id",
            "fecha",
            "palabras",
            "dias_desde_version",
        ],
    )
    labels = pl.read_parquet(ASPECTS[REF]).select(
        "text_id",
        pl.col("codes")
        .fill_null("")
        .str.split(",")
        .list.eval(pl.element().filter(pl.element() != ""))
        .alias("familias"),
        pl.col("actualizacion").alias("u"),
    )
    return draws.join(labels, on="text_id")


def wilson(k: float, n: float, z: float = 1.96) -> list[float]:
    if n == 0:
        return [float("nan"), float("nan")]
    p = k / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return [round(float(c - h), 4), round(float(c + h), 4)]


def per_family(variant: str, d: pl.DataFrame) -> dict:
    """F1 por familia y pureza de tópicos (mapeo cruzado tópico → familia)."""
    sets = pl.read_parquet(OUT / f"sets_{variant}.parquet")
    x = d.join(sets, on="text_id")
    s, f = x["topicos"].to_list(), x["familias"].to_list()
    w = np.ones(x.height)
    fold = np.random.default_rng(SEED).integers(0, FOLDS, x.height)
    pred: list[set[str]] = [set()] * x.height
    for k in range(FOLDS):
        tr = np.flatnonzero(fold != k)
        fmap = family_map([s[i] for i in tr], [f[i] for i in tr], w[tr])
        for i in np.flatnonzero(fold == k):
            pred[i] = {fmap[t] for t in s[i] if t in fmap} - {"SIN"}
    fams = sorted({c for g in f for c in g})
    by_fam = {}
    for c in fams:
        tp = sum(c in p and c in g for p, g in zip(pred, f, strict=True))
        fp = sum(c in p and c not in g for p, g in zip(pred, f, strict=True))
        fn = sum(c not in p and c in g for p, g in zip(pred, f, strict=True))
        by_fam[c] = {
            "soporte": tp + fn,
            "f1": round(2 * tp / (2 * tp + fp + fn), 3)
            if tp + fp + fn
            else None,
        }
    # Pureza de cada tópico con su familia mayoritaria (todos los textos).
    rows = [
        (t, c)
        for ts, g in zip(s, f, strict=True)
        for t in ts
        for c in (g or ["SIN"])
    ]
    per_text = (
        x.select("topicos")
        .explode("topicos")
        .drop_nulls()
        .group_by("topicos")
        .len()
    )
    counts = (
        pl.DataFrame(rows, schema=["topic", "familia"], orient="row")
        .group_by("topic", "familia")
        .len()
        .join(per_text, left_on="topic", right_on="topicos", suffix="_textos")
        .with_columns(pureza=pl.col("len") / pl.col("len_textos"))
        .sort("pureza", descending=True)
        .group_by("topic")
        .first()
        .filter(pl.col("len_textos") >= MIN_SUPPORT)
    )
    emergent = counts.filter(
        pl.col("familia").is_in(["SIN", "OT"]) | (pl.col("pureza") < 0.5)
    )
    return {
        "f1_por_familia": by_fam,
        "topicos_con_soporte": counts.height,
        "pureza": {
            ">=0.7": counts.filter(pl.col("pureza") >= 0.7).height,
            "0.5-0.7": counts.filter(
                pl.col("pureza").is_between(0.5, 0.7, "left")
            ).height,
            "<0.5": counts.filter(pl.col("pureza") < 0.5).height,
        },
        "familia_mayoritaria": dict(
            counts.group_by("familia").len().sort("familia").iter_rows()
        ),
        "familias_sin_topico_mayoritario": sorted(
            set(fams) - set(counts["familia"].to_list())
        ),
        "candidatos_emergentes": emergent.height,
        "_emergentes": emergent["topic"].to_list(),
    }


def emergent_share(variant: str, ids: list[int]) -> float:
    """Peso de las filas `NEG` con algún tópico candidato a emergente."""
    tr = topic_rows(variant).with_columns(
        hit=pl.col("topicos").list.eval(pl.element().is_in(ids)).list.any()
    )
    return round(
        float(
            (tr["hit"].cast(pl.Float64) * tr["peso"]).sum() / tr["peso"].sum()
        ),
        4,
    )


def ab() -> dict:
    d = coded_draws()
    out: dict = {"extracciones": d.height, "textos": d["text_id"].n_unique()}
    for v in AB_VARIANTS:
        r = per_family(v, d)
        r["peso_filas_neg_en_emergentes"] = emergent_share(
            v, r.pop("_emergentes")
        )
        out[v] = r
    lengths = {}
    for lo, hi in LENGTH_BANDS:
        g = d.filter(pl.col("palabras").is_between(lo, hi))
        k = g.filter(pl.col("familias").list.len() > 0).height
        m = g.filter(pl.col("familias").list.len() > 1).height
        lengths[
            f"{lo}" if lo == hi else f"{lo}-{hi}" if hi < 10_000 else f"{lo}+"
        ] = {
            "n": g.height,
            "con_problema": round(k / g.height, 4),
            "ic95": wilson(k, g.height),
            "multi": round(m / g.height, 4),
        }
    out["problema_por_largo"] = lengths
    days = {}
    for lo, hi in DAY_BANDS:
        g = d.filter(pl.col("dias_desde_version").is_between(lo, hi))
        k = g.filter(pl.col("u")).height
        key = f"{lo}-{hi}" if hi < 100_000 else f"{lo}+"
        days[key] = {
            "n": g.height,
            "u": round(k / g.height, 4),
            "ic95": wilson(k, g.height),
        }
    inc = d.with_columns(mes=pl.col("fecha").dt.strftime("%Y-%m")).with_columns(
        incidente=pl.struct("bank_id", "mes").is_in(
            [{"bank_id": b, "mes": m} for b, m in INCIDENTS]
        )
    )
    u_inc = {}
    for flag, g in inc.group_by("incidente"):
        k = g.filter(pl.col("u")).height
        u_inc["incidente" if flag[0] else "resto"] = {
            "n": g.height,
            "u": round(k / g.height, 4),
            "ic95": wilson(k, g.height),
        }
    out["h_t4_u_por_dias_desde_version"] = days
    out["h_t4_u_en_incidentes"] = u_inc
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


# --------------------------------------------------------------------------
# families (vía B a escala) y review (fase 4)
# --------------------------------------------------------------------------

VARIANT = "clausulas_mcs100"  # elegida en la fase 2
FAMILY_CODES = [
    "AC",
    "TR",
    "DI",
    "PR",
    "AT",
    "FA",
    "LE",
    "CO",
    "DV",
    "UX",
    "OT",
]
CAUTION = ("DV", "OT")  # κ entre corridas de Gemini 0.58 y 0.22
MIN_TOPIC_TEXTS = 100  # textos para medir la pureza de un tópico a escala
REVIEW_TOP = 20
REVIEW_UNALIGNED = 15  # opcionales, por peso
REVIEW_EXAMPLES = 5
REVIEW_OUT = DATA / "topics" / "phase4_v0"


def scale_labels() -> pl.DataFrame:
    """Familias (y `u` como código) de los 40 382 textos de la vía B."""
    from voc_analytics.topics.aspects_scale import OUT as SCALE
    from voc_analytics.topics.aspects_scale import PROMPT

    return pl.read_parquet(SCALE / f"labels_{PROMPT}.parquet").select(
        "text_id",
        pl.col("codes")
        .fill_null("")
        .str.split(",")
        .list.eval(pl.element().filter(pl.element() != ""))
        .alias("familias"),
        pl.col("actualizacion").alias("u"),
    )


def signal_summary(sig: pl.DataFrame, vol: pl.DataFrame, series: int) -> dict:
    b = backtest(sig, vol)
    inc = b["incidentes"]
    return {
        "series": series,
        "incidentes_detectados": sum(i["topicos_en_alerta"] > 0 for i in inc),
        "incidentes_con_aviso_el_mes_previo": sum(
            i["topicos_en_alerta_mes_previo"] > 0 for i in inc
        ),
        "tasa_meses_con_alerta_fuera_de_incidentes": b[
            "tasa_meses_con_alerta_fuera_de_incidentes"
        ],
        "alertas_por_serie_y_mes": round(
            float(sig["alerta"].sum()) / max(sig.height, 1), 4
        ),
        "detalle": inc,
    }


def scale_alignment(fams: pl.DataFrame) -> dict:
    """Tópicos contra familias en los 40 382 textos, ponderados por 1 / π."""
    texts = pl.read_parquet(
        WORKING / "texts.parquet", columns=["text_id", "peso"]
    )
    sets = pl.read_parquet(OUT / f"sets_{VARIANT}.parquet")
    x = sets.join(fams, on="text_id").join(texts, on="text_id")
    s, f = x["topicos"].to_list(), x["familias"].to_list()
    w = x["peso"].to_numpy()
    fold = np.random.default_rng(SEED).integers(0, FOLDS, x.height)
    pred: list[set[str]] = [set()] * x.height
    for k in range(FOLDS):
        tr = np.flatnonzero(fold != k)
        fmap = family_map([s[i] for i in tr], [f[i] for i in tr], w[tr])
        for i in np.flatnonzero(fold == k):
            pred[i] = {fmap[t] for t in s[i] if t in fmap} - {"SIN"}
    by_fam = {}
    for c in FAMILY_CODES:
        tp = sum(
            wi for p, g, wi in zip(pred, f, w, strict=True) if c in p and c in g
        )
        fp = sum(
            wi
            for p, g, wi in zip(pred, f, w, strict=True)
            if c in p and c not in g
        )
        fn = sum(
            wi
            for p, g, wi in zip(pred, f, w, strict=True)
            if c not in p and c in g
        )
        by_fam[c] = round(2 * tp / (2 * tp + fp + fn), 3) if tp + fn else None
    pairs = (
        x.select("topicos", "familias", "peso")
        .explode("topicos")
        .drop_nulls("topicos")
        .with_columns(
            pl.when(pl.col("familias").list.len() == 0)
            .then(pl.lit(["SIN"]))
            .otherwise(pl.col("familias"))
            .alias("familias")
        )
    )
    tot = pairs.group_by("topicos").agg(
        textos=pl.len(), w_total=pl.col("peso").sum()
    )
    best = (
        pairs.explode("familias")
        .group_by("topicos", "familias")
        .agg(w=pl.col("peso").sum())
        .join(tot, on="topicos")
        .with_columns(pureza=pl.col("w") / pl.col("w_total"))
        .sort("pureza", descending=True)
        .group_by("topicos")
        .first()
        .filter(pl.col("textos") >= MIN_TOPIC_TEXTS)
    )
    best.write_parquet(OUT / f"alignment_scale_{VARIANT}.parquet")
    unaligned = best.filter(
        pl.col("familias").is_in(["SIN", "OT"]) | (pl.col("pureza") < 0.5)
    )
    return {
        "textos": x.height,
        "f1_por_familia": by_fam,
        "topicos_con_soporte": best.height,
        "pureza": {
            ">=0.7": best.filter(pl.col("pureza") >= 0.7).height,
            "0.5-0.7": best.filter(
                pl.col("pureza").is_between(0.5, 0.7, "left")
            ).height,
            "<0.5": best.filter(pl.col("pureza") < 0.5).height,
        },
        "familia_mayoritaria": dict(
            best.group_by("familias").len().sort("familias").iter_rows()
        ),
        "topicos_no_alineados": unaligned.height,
        "peso_filas_neg_en_no_alineados": emergent_share(
            VARIANT, unaligned["topicos"].to_list()
        ),
    }


def families() -> dict:
    fams = scale_labels()
    codes = fams.select(
        "text_id",
        pl.when(pl.col("u"))
        .then(pl.col("familias").list.concat(pl.lit(["u"])))
        .otherwise(pl.col("familias"))
        .alias("topicos"),
    )
    tr = period_rows(codes)
    quarterly = shares(tr, "trimestre")
    quarterly.write_parquet(OUT / "quarterly_familias.parquet")
    monthly = shares(tr, "mes")
    vol = volume_signal(tr)
    sig_f = signal(monthly)
    sig_f.write_parquet(OUT / "signal_familias.parquet")
    sig_t = pl.read_parquet(OUT / f"signal_{VARIANT}.parquet")
    n_topics = pl.read_parquet(OUT / f"terms_{VARIANT}.parquet").height
    year = (
        tr.with_columns(anio=pl.col("fecha").dt.year())
        .explode("topicos")
        .group_by("anio", "topicos")
        .agg(w=pl.col("peso").sum())
        .join(
            tr.with_columns(anio=pl.col("fecha").dt.year())
            .group_by("anio")
            .agg(total=pl.col("peso").sum()),
            on="anio",
        )
        .with_columns(share=(pl.col("w") / pl.col("total")).round(4))
        .drop_nulls("topicos")
        .sort("anio")
    )
    por_anio = {
        c: {
            str(a): sh
            for a, sh in year.filter(pl.col("topicos") == c)
            .select("anio", "share")
            .iter_rows()
        }
        for c in [*FAMILY_CODES, "u"]
    }
    alerts_inc = (
        sig_f.filter(
            pl.col("alerta")
            & pl.struct("bank_id", "mes").is_in(
                [{"bank_id": b, "mes": m} for b, m in INCIDENTS]
            )
        )
        .select(
            "bank_id",
            "mes",
            "topicos",
            pl.col("z").round(1),
            pl.col("share").round(3),
            pl.col("base").round(3),
        )
        .sort("mes")
    )
    res = {
        "textos": fams.height,
        "cautela": list(CAUTION),
        "proporcion_por_anio_todos_los_bancos": por_anio,
        "senal": {
            "familias_y_u": signal_summary(sig_f, vol, len(FAMILY_CODES) + 1),
            "solo_u": signal_summary(
                sig_f.filter(pl.col("topicos") == "u"), vol, 1
            ),
            "topicos": signal_summary(sig_t, vol, n_topics),
        },
        "alertas_de_familias_en_incidentes": alerts_inc.to_dicts(),
        "alineacion_a_escala": scale_alignment(fams),
    }
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return res


def review() -> dict:
    """Material de la fase 4 para el autor, fuera de git."""
    tr = topic_rows(VARIANT)
    terms = pl.read_parquet(OUT / f"terms_{VARIANT}.parquet")
    align = pl.read_parquet(OUT / f"alignment_scale_{VARIANT}.parquet")
    sig = pl.read_parquet(OUT / f"signal_{VARIANT}.parquet")
    total = tr["peso"].sum()
    per = (
        tr.explode("topicos")
        .drop_nulls("topicos")
        .group_by("topicos")
        .agg(w=pl.col("peso").sum())
        .with_columns(peso_neg=(pl.col("w") / total).round(4))
        .sort("w", descending=True)
    )
    unaligned = align.filter(
        pl.col("familias").is_in(["SIN", "OT"]) | (pl.col("pureza") < 0.5)
    )["topicos"].to_list()
    top = per.head(REVIEW_TOP)["topicos"].to_list()
    extra = [
        t for t in per["topicos"].to_list() if t in unaligned and t not in top
    ][:REVIEW_UNALIGNED]
    chosen = top + extra
    texts = pl.read_parquet(
        WORKING / "texts.parquet",
        columns=["text_id", "texto_sanitizado", "palabras"],
    )
    sets = pl.read_parquet(OUT / f"sets_{VARIANT}.parquet")
    hyp = {name: match_topics(terms, pat) for name, pat in HYPOTHESES.items()}
    REVIEW_OUT.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Revisión de tópicos (5.5, fase 4)",
        "",
        "Material local, fuera de git: lleva términos y ejemplos de reseñas.",
        "Anota en `revision_topicos.csv` y `revision_hipotesis.csv`.",
        "",
    ]

    def card(t: int, group: str) -> tuple[list[str], dict]:
        ws = terms.filter(pl.col("topic") == t)["terminos"][0]
        a = align.filter(pl.col("topicos") == t)
        fam = a["familias"][0] if a.height else "—"
        pur = round(float(a["pureza"][0]), 2) if a.height else None
        banks = (
            tr.filter(pl.col("topicos").list.contains(t))
            .group_by("bank_id")
            .agg(w=pl.col("peso").sum())
            .with_columns(p=(pl.col("w") / pl.col("w").sum() * 100).round(0))
            .sort("p", descending=True)
        )
        months = (
            sig.filter(pl.col("alerta") & (pl.col("topicos") == t))
            .select("bank_id", "mes")
            .sort("mes")
        )
        pool = (
            sets.filter(pl.col("topicos").list.contains(t))
            .join(texts, on="text_id")
            .filter(pl.col("palabras").is_between(4, 30))
        )
        ex = pool.sample(
            n=min(REVIEW_EXAMPLES, pool.height), seed=SEED, shuffle=True
        )
        share = per.filter(pl.col("topicos") == t)["peso_neg"][0]
        lines = [
            f"## Tópico {t} ({group})",
            "",
            f"* Términos: {', '.join(ws[:10])}",
            f"* Peso en las negativas: {share * 100:.1f} %",
            f"* Familia mayoritaria (`v2.1`): {fam} (pureza {pur})",
            "* Bancos: "
            + ", ".join(f"{b} {p:.0f} %" for b, _, p in banks.iter_rows()),
            "* Meses en alerta: "
            + (
                ", ".join(f"{b} {m}" for b, m in months.iter_rows())
                or "ninguno"
            ),
            "* Ejemplos:",
            *[f"  * {x}" for x in ex["texto_sanitizado"].to_list()],
            "",
        ]
        row = {
            "topico": t,
            "grupo": group,
            "terminos": ", ".join(ws[:10]),
            "peso_neg_pct": round(share * 100, 1),
            "familia_mayoritaria": fam,
            "pureza": pur,
            "nombre_propuesto": "",
            "coherencia_1a5": "",
            "util_para_producto_si_no": "",
            "familia_correcta": "",
            "tema_nuevo_si_no": "",
            "comentario": "",
        }
        return lines, row

    rows = []
    for t in chosen:
        block, row = card(
            t, "principal" if t in top else "no alineado (opcional)"
        )
        lines += block
        rows.append(row)
    (REVIEW_OUT / "revision_topicos.md").write_text("\n".join(lines) + "\n")
    hlines = [
        "# Tópicos de las hipótesis temporales (5.5, fase 4)",
        "",
        "Material local, fuera de git. Fichas de los tópicos de",
        "`revision_hipotesis.csv` (H-T1 y H-T2, `topics_design.md` §8).",
        "",
    ]
    for name, ids in hyp.items():
        for t in ids:
            hlines += card(t, name)[0]
    (REVIEW_OUT / "revision_hipotesis.md").write_text("\n".join(hlines) + "\n")
    hrows = [
        {
            "hipotesis": name,
            "topico": t,
            "terminos": ", ".join(
                terms.filter(pl.col("topic") == t)["terminos"][0][:10]
            ),
            "corresponde_si_no": "",
            "comentario": "",
        }
        for name, ids in hyp.items()
        for t in ids
    ]
    # Las plantillas no se sobrescriben: pueden tener las respuestas del autor.
    for name, frame in (
        ("revision_topicos.csv", pl.DataFrame(rows)),
        ("revision_hipotesis.csv", pl.DataFrame(hrows)),
    ):
        if not (REVIEW_OUT / name).exists():
            frame.write_csv(REVIEW_OUT / name)
    return {
        "variante": VARIANT,
        "topicos_principales": len(top),
        "topicos_no_alineados_adicionales": len(chosen) - len(top),
        "peso_neg_de_los_principales": round(
            float(per.head(REVIEW_TOP)["peso_neg"].sum()), 4
        ),
        "filas_hipotesis": len(hrows),
        "ejemplos_por_topico": REVIEW_EXAMPLES,
        "ubicacion": "data/topics/phase4_v0/ (fuera de git)",
    }


def write(key: str, value) -> None:
    metrics = json.loads(METRICS.read_text()) if METRICS.exists() else {}
    metrics.update(
        {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "source": "topics_working_v0 (plata NEG), 5 bancos; MiniLM; "
            "min_samples 10",
            "aspects_reference": f"{REF} (vigente; las claves sin sufijo "
            "usan aspects_v2 provisional)",
            key: value,
        }
    )
    METRICS.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("units")
    d = sub.add_parser("dynamics")
    d.add_argument("--variant", required=True)
    sub.add_parser("ab")
    sub.add_parser("families")
    sub.add_parser("review")
    a = p.parse_args()
    if a.cmd == "units":
        write(
            f"units_{REF}",
            {
                "params": {
                    "mcs": MCS,
                    "ms": MS,
                    "umbrales": THRESHOLDS,
                    "folds": FOLDS,
                },
                "results": units(),
            },
        )
    elif a.cmd == "ab":
        write(f"ab_{REF}", ab())
    elif a.cmd == "families":
        write(f"families_{REF}", families())
    elif a.cmd == "review":
        write("review_material", review())
    else:
        write(f"dynamics_{a.variant}", dynamics(a.variant))


if __name__ == "__main__":
    main()
