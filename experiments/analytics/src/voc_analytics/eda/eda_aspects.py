"""Proporción multi-aspecto de las reseñas negativas (EPIC-5 feature 5.2).

Informa la elección entre ABSA y tópicos de 5.5. Usa la plata `silver_v0`
(`prompt_v3`): solo las filas que Gemini etiquetó `NEG`.

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.eda.eda_aspects sample
    uv run python -m voc_analytics.eda.eda_aspects label \\
        [--prompt aspects_v1] [--max-cost 1.0]
    uv run python -m voc_analytics.eda.eda_aspects validation
    uv run python -m voc_analytics.eda.eda_aspects analyze [--prompt aspects_v1]

* **sample:** N extracciones con reemplazo de las filas `NEG` de la plata,
  con probabilidad proporcional a 1 / `prob_inclusion`. Cada extracción es
  una fila negativa elegible del corpus, así que las proporciones de la
  muestra estiman las de la población sin pesos.
* **label:** Gemini (Vertex AI dentro de GCP) codifica cada texto único con
  los aspectos de la queja, con el prompt `--prompt` (por defecto
  `aspects_v1`, que sigue
  `docs/analytics/eda/archive/eda_aspects_guideline_v1.md`);
  reutiliza `label_batch` de `labeling.label_gemini` sin modificarlo.
* **validation:** exporta a ciegas (sin la salida de Gemini) `VALIDATION_N`
  textos; el autor los codifica con `aspects_app.py`.
* **analyze:** proporciones con IC por bootstrap, por banco, estrellas y
  largo; la cota por palabras clave sobre todas las negativas de la plata y
  su acuerdo con Gemini; y el acuerdo autor–Gemini si ya hay
  codificaciones del autor.

Escribe en `data/eda/aspects_v0/` (fuera de git) y solo agregados en
`docs/analytics/eda/<prompt>_metrics.json`.
"""

import argparse
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
from google import genai
from google.genai import types
from sklearn.metrics import cohen_kappa_score

from voc_analytics.labeling.label_gemini import (
    LOCATION,
    MODEL,
    PRICE_IN,
    PRICE_OUT,
    PROJECT,
    THINKING,
    label_batch,
)
from voc_analytics.paths import DATA, DOCS, LABELS

SILVER = LABELS / "silver_v0"
OUT = DATA / "eda" / "aspects_v0"
PROMPTS = Path(__file__).parent / "prompts"
PROMPT_VERSIONS = ["aspects_v0", "aspects_v1"]
# `docs/analytics/eda/archive/eda_aspects_guideline_v1.md`; la sigue
# `aspects_v1`.
GUIDELINE = "aspects_guideline_v1"
# Codificaciones de `aspects_app.py`; gana la última fila por `item`.
ANNOTATIONS = OUT / "validation_annotations.csv"  # primera pasada, guía v0
ANNOTATIONS_V1 = OUT / "validation_annotations_v1.csv"  # guía v1; gana
SEED = 20261020
N_DRAWS = 1500
VALIDATION_N = 100
BOOT = 2000
BATCH = 100
CODES = ["AC", "FA", "LE", "TR", "DI", "PR", "AT", "DS", "CO", "OT"]
LINE = re.compile(r"^\s*(\d+)\s+(-|[A-Z]{2}(?:,[A-Z]{2})*)\s+([01])\s*$")
WORD_BUCKETS = [
    (1, 1, "1"),
    (2, 5, "2-5"),
    (6, 15, "6-15"),
    (16, 40, "16-40"),
    (41, 10**6, ">40"),
]

# Cota barata: familias por palabras clave sobre texto sin acentos.
STEMS = {
    "AC": [
        "entrar",
        "ingres",
        r"inicia\w* sesion",
        "sesion",
        "contrasen",
        "clave",
        "nip",
        "token",
        "huella",
        "biometr",
        "registr",
        "dar de alta",
        r"verifica\w*",
        "identidad",
        "bloque",
        "acceso",
        "acceder",
        "login",
        "usuario",
    ],
    "FA": [
        "error",
        "falla",
        "se cierra",
        "cierra sola",
        "no abre",
        "no carga",
        "se cae",
        "caid",
        "no funciona",
        "no sirve",
        "congela",
        "trabad",
        "pantalla en blanco",
    ],
    "LE": [
        "lent",
        "tarda",
        "demora",
        "carga mucho",
        "pesad",
    ],
    "TR": [
        "transfer",
        "spei",
        "pago",
        "pagar",
        "deposit",
        "retir",
        r"envi\w*",
        "codi",
        "dimo",
        "qr",
        "recarga",
    ],
    "DI": [
        "cobr",
        "cargo",
        "comision",
        "dinero",
        "saldo",
        "fraude",
        "robo",
        "robar",
        "reembolso",
        "descont",
        "me quitaron",
    ],
    "PR": [
        "tarjeta",
        "credito",
        "prestamo",
        "inversion",
        "limite",
        "solicitud",
        "aprob",
        "rechaz",
    ],
    "AT": [
        "atencion",
        "servicio al cliente",
        "sucursal",
        "ejecutiv",
        "call center",
        "llam",
        "chat",
        "soporte",
        "asesor",
        "respuesta",
        "responden",
    ],
    "DS": [
        "actualiza",
        "diseno",
        "interfaz",
        "antes era",
        "version anterior",
        "cambiaron",
        "quitaron",
        "complicad",
        "confus",
    ],
    "CO": [
        "celular",
        "telefono",
        "dispositivo",
        "android",
        "iphone",
        "root",
        "compatib",
        "sistema operativo",
        "permiso",
        "samsung",
        "huawei",
        "motorola",
        "xiaomi",
    ],
    "OT": [
        "publicidad",
        "anuncio",
        "notificacion",
        "idioma",
    ],
}
KEYWORDS = {c: r"\b(" + "|".join(v) + ")" for c, v in STEMS.items()}


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def keyword_codes(text: str) -> list[str]:
    t = plain(text)
    return [c for c, rx in KEYWORDS.items() if re.search(rx, t)]


def word_bucket() -> pl.Expr:
    expr = pl.lit(None, dtype=pl.String)
    for low, high, label in reversed(WORD_BUCKETS):
        expr = (
            pl.when(pl.col("palabras").is_between(low, high))
            .then(pl.lit(label))
            .otherwise(expr)
        )
    return expr


def negatives() -> pl.DataFrame:
    """Filas `NEG` de la plata con su texto y el peso 1 / π."""
    rows = pl.read_parquet(SILVER / "rows.parquet")
    labels = pl.read_parquet(SILVER / "labels_prompt_v3.parquet")
    texts = pl.read_parquet(
        SILVER / "texts.parquet", columns=["text_id", "texto_sanitizado"]
    )
    return (
        rows.join(labels.filter(pl.col("gemini_s") == "NEG"), on="text_id")
        .join(texts, on="text_id")
        .with_columns(
            peso=1 / pl.col("prob_inclusion"),
            palabras=pl.col("texto_sanitizado").str.count_matches(r"\S+"),
        )
        .with_columns(largo=word_bucket())
    )


def sample() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    neg = negatives()
    rng = np.random.default_rng(SEED)
    p = neg["peso"].to_numpy()
    idx = rng.choice(neg.height, size=N_DRAWS, replace=True, p=p / p.sum())
    draws = neg[idx].with_columns(extraccion=pl.int_range(N_DRAWS))
    draws.drop("texto_sanitizado").write_parquet(OUT / "draws.parquet")
    meta = {
        "seed": SEED,
        "draws": N_DRAWS,
        "unique_texts": draws["text_id"].n_unique(),
        "frame_neg_rows": neg.height,
        "frame_neg_rows_weighted": round(float(p.sum())),
    }
    (OUT / "sample_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(meta)


def parse(text: str) -> list[dict]:
    items = []
    for line in text.splitlines():
        if match := LINE.match(line):
            i, codes, m = match.groups()
            items.append(
                {
                    "i": int(i),
                    "codes": "" if codes == "-" else codes,
                    "m": m == "1",
                }
            )
    return items


def label(prompt: str, max_cost: float) -> None:
    draws = pl.read_parquet(OUT / "draws.parquet")
    texts = (
        pl.read_parquet(
            SILVER / "texts.parquet", columns=["text_id", "texto_sanitizado"]
        )
        .join(draws.select("text_id").unique(), on="text_id")
        .sort("text_id")
    )
    version = {
        "parse": parse,
        "config": types.GenerateContentConfig(
            system_instruction=(PROMPTS / f"{prompt}.md").read_text(),
            temperature=0,
            response_mime_type="text/plain",
            thinking_config=THINKING,
            max_output_tokens=4096,
        ),
    }
    client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out, batches, spent = [], [], 0.0
    for start in range(0, texts.height, BATCH):
        chunk = texts[start : start + BATCH]
        ids = chunk["text_id"].to_list()
        frame = pl.DataFrame(
            {
                "pilot_id": range(len(ids)),
                "texto_sanitizado": chunk["texto_sanitizado"],
            }
        )
        items, usage = label_batch(client, frame, version)
        spent += (
            usage["prompt"] * PRICE_IN
            + (usage["output"] + usage["thoughts"]) * PRICE_OUT
        ) / 1e6
        batches.append({"start": start, "texts": len(ids), **usage})
        out += [
            {"text_id": ids[x["i"]], "codes": x["codes"], "elogio": x["m"]}
            for x in items
        ]
        print(
            json.dumps(
                {
                    "start": start,
                    "error": usage["error"],
                    "spent_usd": round(spent, 4),
                }
            ),
            flush=True,
        )
        if spent > max_cost:
            print("tope de gasto alcanzado")
            break
    labels = pl.DataFrame(
        out,
        schema={"text_id": pl.UInt32, "codes": pl.String, "elogio": pl.Boolean},
    )
    labels.write_parquet(OUT / f"labels_{prompt}.parquet")
    meta = {
        "run": run,
        "model": MODEL,
        "location": LOCATION,
        "prompt": prompt,
        "texts": texts.height,
        "labeled": labels.height,
        "failed_batches": sum(1 for b in batches if b["error"]),
        "cost_usd": round(spent, 5),
        "model_version": next(
            (b.get("model_version") for b in batches if b.get("model_version")),
            None,
        ),
        "batches": batches,
    }
    (OUT / f"run_{run}.json").write_text(json.dumps(meta, indent=2) + "\n")
    print({k: v for k, v in meta.items() if k != "batches"})


def validation() -> None:
    """Primeros `VALIDATION_N` textos únicos por orden de extracción; ciegos."""
    draws = pl.read_parquet(OUT / "draws.parquet").sort("extraccion")
    ids = draws["text_id"].unique(maintain_order=True).head(VALIDATION_N)
    texts = pl.read_parquet(
        SILVER / "texts.parquet", columns=["text_id", "texto_sanitizado"]
    )
    queue = pl.DataFrame({"text_id": ids}).join(
        texts, on="text_id", how="left", maintain_order="left"
    )
    path = OUT / "validation.csv"
    if path.exists():
        raise SystemExit(f"{path} ya existe; no se sobrescribe")
    queue.with_columns(
        item=pl.int_range(1, queue.height + 1),
        codigos=pl.lit(""),
        elogio=pl.lit(""),
    ).select(
        "item", "text_id", "texto_sanitizado", "codigos", "elogio"
    ).write_csv(path)
    print(f"{queue.height} textos en {path}")


def codes_list(s: str | None) -> list[str]:
    if not s:
        return []
    return sorted(
        {
            c.strip().upper()
            for c in re.split(r"[,\s]+", s)
            if c.strip() and c.strip() != "-"
        }
    )


def prop_ci(x: np.ndarray, rng: np.random.Generator) -> dict:
    boots = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(BOOT)]
    return {
        "n": int(len(x)),
        "p": round(float(x.mean()), 4),
        "ic95": [
            round(float(np.quantile(boots, 0.025)), 4),
            round(float(np.quantile(boots, 0.975)), 4),
        ],
    }


def author_codes() -> pl.DataFrame | None:
    """Códigos del autor por `item`: gana la guía v1 sobre la primera pasada.

    Dentro de cada archivo gana la última fila por `item`. Si no hay
    codificaciones de la app, se leen las de `validation.csv`.
    """
    schema = {"codigos": pl.String, "elogio": pl.String}
    frames = []
    for path, guide in (
        (ANNOTATIONS, "aspects_guideline_v0"),
        (ANNOTATIONS_V1, GUIDELINE),
    ):
        if path.exists():
            frames.append(
                pl.read_csv(path, schema_overrides=schema)
                .with_row_index("fila")
                .sort("fila")
                .group_by("item")
                .last()
                .select("item", "text_id", "codigos", "elogio")
                .with_columns(guia=pl.lit(guide))
            )
    if frames:
        v = pl.concat(frames).group_by("item", maintain_order=True).last()
    elif (OUT / "validation.csv").exists():
        v = pl.read_csv(OUT / "validation.csv", schema_overrides=schema)
        v = v.with_columns(guia=pl.lit("aspects_guideline_v0"))
    else:
        return None
    return v.filter(
        pl.col("codigos").is_not_null()
        & (pl.col("codigos").str.strip_chars() != "")
    ).select(
        "item",
        pl.col("text_id").cast(pl.UInt32),
        "codigos",
        "elogio",
        "guia",
    )


def analyze(prompt: str) -> None:
    rng = np.random.default_rng(SEED)
    draws = pl.read_parquet(OUT / "draws.parquet")
    labels = pl.read_parquet(OUT / f"labels_{prompt}.parquet")
    texts = pl.read_parquet(
        SILVER / "texts.parquet", columns=["text_id", "texto_sanitizado"]
    )
    d = (
        draws.join(labels, on="text_id", how="inner")
        .join(texts, on="text_id")
        .with_columns(
            n_aspectos=pl.col("codes").map_elements(
                lambda s: len(codes_list(s)), return_dtype=pl.Int64
            ),
            kw=pl.col("texto_sanitizado").map_elements(
                lambda s: ",".join(keyword_codes(s)), return_dtype=pl.String
            ),
        )
        .with_columns(
            multi=pl.col("n_aspectos") >= 2,
            sin_aspecto=pl.col("n_aspectos") == 0,
            n_kw=pl.col("kw").map_elements(
                lambda s: len(codes_list(s)), return_dtype=pl.Int64
            ),
        )
    )
    m: dict = {
        "fuente": (
            "silver_v0 (prompt_v3), filas NEG; extracciones con "
            "reemplazo proporcionales a 1/pi"
        ),
        "prompt": prompt,
        "model": MODEL,
        "draws": draws.height,
        "draws_labeled": d.height,
        "unique_texts_labeled": labels.height,
        "codes": CODES,
    }
    m["poblacion_filas_neg"] = {
        "multi_aspecto": prop_ci(d["multi"].to_numpy(), rng),
        "un_aspecto": prop_ci((d["n_aspectos"] == 1).to_numpy(), rng),
        "sin_aspecto_concreto": prop_ci(d["sin_aspecto"].to_numpy(), rng),
        "elogio_concreto": prop_ci(d["elogio"].to_numpy(), rng),
        "n_aspectos_dist": d.group_by("n_aspectos")
        .len()
        .sort("n_aspectos")
        .to_dicts(),
    }
    m["por_codigo"] = [
        {
            "codigo": c,
            **prop_ci(
                d["codes"]
                .map_elements(
                    lambda s, c=c: c in codes_list(s), return_dtype=pl.Boolean
                )
                .to_numpy(),
                rng,
            ),
        }
        for c in CODES
    ]
    pairs: dict[str, int] = {}
    for s in d.filter(pl.col("multi"))["codes"]:
        cs = codes_list(s)
        for i, a in enumerate(cs):
            for b in cs[i + 1 :]:
                pairs[f"{a}+{b}"] = pairs.get(f"{a}+{b}", 0) + 1
    m["pares_frecuentes_en_multi"] = sorted(
        ({"par": k, "extracciones": v} for k, v in pairs.items()),
        key=lambda r: -r["extracciones"],
    )[:10]

    def by(col: str) -> list[dict]:
        out = []
        for key, g in d.sort(col).group_by(col, maintain_order=True):
            out.append(
                {
                    col: key[0],
                    "multi_aspecto": prop_ci(g["multi"].to_numpy(), rng),
                    "sin_aspecto_concreto": prop_ci(
                        g["sin_aspecto"].to_numpy(), rng
                    ),
                    "elogio_concreto": round(float(g["elogio"].mean()), 4),
                }
            )
        return sorted(out, key=lambda r: str(r[col]))

    m["por_banco"] = by("bank_id")
    m["por_estrellas"] = by("estrellas")
    m["por_largo_palabras"] = by("largo")
    # Multi-aspecto de las negativas con al menos k palabras
    # (umbral de TOPIC_TOO_SHORT).
    m["multi_desde_k_palabras"] = [
        {
            "k": k,
            "share_filas_neg": round(float((d["palabras"] >= k).mean()), 4),
            **prop_ci(
                d.filter(pl.col("palabras") >= k)["multi"].to_numpy(), rng
            ),
        }
        for k in (3, 5, 10, 20)
    ]

    # Cota por palabras clave: acuerdo con Gemini en la muestra y valor en
    # toda la plata NEG.
    kw_multi, gm = d["n_kw"].to_numpy() >= 2, d["multi"].to_numpy()
    m["palabras_clave"] = {
        "nota": (
            "Familias por expresiones regulares; cota barata, "
            "no medición validada"
        ),
        "en_muestra": {
            "multi_aspecto": prop_ci(kw_multi, rng),
            "kappa_multi_vs_gemini": round(
                float(cohen_kappa_score(gm, kw_multi)), 3
            ),
            "precision_multi": round(
                float((kw_multi & gm).sum() / max(kw_multi.sum(), 1)), 3
            ),
            "recall_multi": round(
                float((kw_multi & gm).sum() / max(gm.sum(), 1)), 3
            ),
        },
    }
    neg = negatives().with_columns(
        n_kw=pl.col("texto_sanitizado").map_elements(
            lambda s: len(keyword_codes(s)), return_dtype=pl.Int64
        )
    )
    w = neg["peso"].to_numpy()
    m["palabras_clave"]["toda_la_plata_neg"] = {
        "filas": neg.height,
        "multi_aspecto_ponderado": round(
            float((w * (neg["n_kw"].to_numpy() >= 2)).sum() / w.sum()), 4
        ),
    }

    # Acuerdo autor–Gemini (validación a ciegas), si ya está codificada.
    v = author_codes()
    if v is not None and v.height:
        v = v.join(labels, on="text_id")
        hum = [codes_list(s) for s in v["codigos"]]
        gem = [codes_list(s) for s in v["codes"]]
        hm = np.array([len(x) >= 2 for x in hum])
        gmv = np.array([len(x) >= 2 for x in gem])
        m["validacion_autor"] = {
            "items": v.height,
            "items_por_guia": dict(
                v.group_by("guia").len().sort("guia").iter_rows()
            ),
            "multi_autor": round(float(hm.mean()), 4),
            "multi_gemini": round(float(gmv.mean()), 4),
            "kappa_multi": round(float(cohen_kappa_score(hm, gmv)), 3),
            "acuerdo_multi": round(float((hm == gmv).mean()), 3),
            "kappa_elogio": round(
                float(
                    cohen_kappa_score(
                        (v["elogio"] == "1").to_numpy(),
                        v["elogio_right"].to_numpy(),
                    )
                ),
                3,
            ),
            "acuerdo_conjunto_exacto": round(
                float(np.mean([a == b for a, b in zip(hum, gem, strict=True)])),
                3,
            ),
            "kappa_por_codigo": {
                c: round(
                    float(
                        cohen_kappa_score(
                            [c in x for x in hum], [c in x for x in gem]
                        )
                    ),
                    3,
                )
                for c in CODES
                if any(c in x for x in hum + gem)
            },
        }
    (DOCS / "eda" / f"{prompt}_metrics.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: m[k]
                for k in (
                    "poblacion_filas_neg",
                    "multi_desde_k_palabras",
                    "palabras_clave",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample")
    lab = sub.add_parser("label")
    lab.add_argument("--prompt", choices=PROMPT_VERSIONS, default="aspects_v1")
    lab.add_argument("--max-cost", type=float, default=1.0)
    sub.add_parser("validation")
    ana = sub.add_parser("analyze")
    ana.add_argument("--prompt", choices=PROMPT_VERSIONS, default="aspects_v1")
    args = parser.parse_args()
    if args.cmd == "label":
        label(args.prompt, args.max_cost)
    elif args.cmd == "analyze":
        analyze(args.prompt)
    else:
        {"sample": sample, "validation": validation}[args.cmd]()


if __name__ == "__main__":
    main()
