"""Aspectos de las negativas con la guía `v2` (EPIC-5, 5.2 reabierta por 5.5).

`DS` de `v1` (κ 0.39) se parte en `DV`, `UX` y `FQ`, y la regla 3 de `v1`
pasa a la marca ortogonal `u` (problema atribuido a una actualización). La
marca ortogonal `s` señala las quejas de seguridad (hackeo, fraude con la
app, desconfianza, biometría como seguridad). Guía:
`docs/analytics/eda/eda_aspects_guideline.md`; prompt `aspects_v2` (el de la
primera ronda de calibración está congelado en `aspects_v2_r1`).

Uso (desde experiments/analytics), en este orden:
    uv run python -m voc_analytics.eda.eda_aspects_v2 calibration
    uv run python -m voc_analytics.eda.eda_aspects_v2 label --set calibracion
    uv run python -m voc_analytics.eda.eda_aspects_v2 disagreements \\
        --set calibracion
    uv run python -m voc_analytics.eda.eda_aspects_v2 calibration-round \\
        --ronda 2   # y luego label y disagreements con --set calibracion2
    uv run python -m voc_analytics.eda.eda_aspects_v2 calibration-round \\
        --ronda 3   # y luego label y disagreements con --set calibracion3
    uv run python -m voc_analytics.eda.eda_aspects_v2 sample
    uv run python -m voc_analytics.eda.eda_aspects_v2 label --set muestra
    uv run python -m voc_analytics.eda.eda_aspects_v2 label --set extracciones
    uv run python -m voc_analytics.eda.eda_aspects_v2 recode-v21 --min-dias 0.5
    uv run python -m voc_analytics.eda.eda_aspects_v2 label --set muestra \\
        --prompt aspects_v2_1   # y lo mismo con --set extracciones
    uv run python -m voc_analytics.eda.eda_aspects_v2 analyze

* **calibration:** `CALIB_N` textos de diseño (mitad con `DS` de Gemini en
  `aspects_v1`, mitad por palabras clave) para que el autor calibre la guía.
* **calibration-round:** rondas siguientes, con los textos por origen de
  `CALIB_ROUNDS` y ninguno ya visto. La 2 suma seguridad para probar la
  marca `s`; la 3 suma lo que en `v1` caía en `OT` (publicidad,
  notificaciones, cajeros, puntos, espacio), que ahora tiene familia.
* **sample:** la muestra de la regla de decisión: `ENRICHED_N` textos
  enriquecidos con casos de diseño (mitad y mitad, como la calibración) y
  `RANDOM_N` aleatorios, que son los siguientes textos únicos de las
  extracciones representativas de `v1` en su orden. Se baraja para que el
  autor no vea bloques.
* **label:** Gemini (Vertex AI dentro de GCP) con `aspects_v2` sobre la
  calibración, la muestra o los textos de las 1 500 extracciones de `v1`;
  reutiliza `label_batch` de `labeling.label_gemini` sin modificarlo.
* **disagreements:** tabla de desacuerdos autor–Gemini (con texto, fuera de
  git) para revisar la calibración.
* **recode:** `RECODE_N` textos de la muestra ya codificados (mitad
  enriquecidos, mitad aleatorios), a ciegas, solo si su primera
  codificación tiene al menos `--min-dias` días (por defecto
  `RECODE_MIN_DAYS`, el de la regla; uno menor es una desviación que se
  documenta).
* **recode-v21:** los mismos textos de la muestra, en otro orden, para que
  el autor los vuelva a codificar con la guía `v2.1` (taxonomía final:
  `FQ` dentro de `UX`, instalación y actualización en `CO`, token en `AC`)
  y las casillas agrupadas en orden de decisión. Sustituye a `recode`
  (decisión del autor, 2026-10-21): da el κ de la taxonomía final y la
  estabilidad intra-autor en los códigos que no cambiaron de definición.
* **analyze:** κ por código (autor–Gemini e intra-autor), confusiones,
  prevalencias, multi-aspecto recalculado y la regla de decisión de la
  sección 6 de la guía `v2` en `docs/analytics/eda/aspects_v2_metrics.json`;
  la taxonomía final en `aspects_v2_1_metrics.json`.

Ninguno de los 100 textos de la validación de `v1` entra en la calibración
ni en la muestra. Escribe en `data/eda/aspects_v2/` (fuera de git) y solo
agregados en `docs/analytics/eda/`.
"""

import argparse
import json
import re
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
from google import genai
from google.genai import types
from sklearn.metrics import cohen_kappa_score

from voc_analytics.eda.eda_aspects import (
    OUT as OUT_V1,
)
from voc_analytics.eda.eda_aspects import (
    PROMPTS,
    SILVER,
    STEMS,
    codes_list,
    negatives,
    plain,
    prop_ci,
)
from voc_analytics.labeling.label_gemini import (
    LOCATION,
    MODEL,
    PRICE_IN,
    PRICE_OUT,
    PROJECT,
    THINKING,
    label_batch,
)
from voc_analytics.paths import DATA, DOCS

OUT = DATA / "eda" / "aspects_v2"
PROMPT = "aspects_v2"
# Congelada tras tres rondas de calibración (2026-10-20).
GUIDELINE = "aspects_guideline_v2"
# Taxonomía final, decidida por el autor tras codificar la muestra con `v2`
# (2026-10-21): `FQ` dentro de `UX`, instalación y actualización en `CO`,
# token y códigos en `AC`. Ver la guía, estado.
PROMPT_V21 = "aspects_v2_1"
GUIDELINE_V21 = "aspects_guideline_v2.1"
PROMPT_VERSIONS = [PROMPT, PROMPT_V21]
SEED = 20261021
CALIB_N = 30
CALIB_ROUNDS = {
    2: {"enriquecida_v1": 7, "enriquecida_kw": 7, "enriquecida_seg": 6},
    3: {
        "enriquecida_v1": 8,
        "enriquecida_kw": 8,
        "enriquecida_ot": 8,
        "enriquecida_seg": 6,
    },
}
ENRICHED_N = 150
RANDOM_N = 150
RECODE_N = 50
RECODE_MIN_DAYS = 7
BATCH = 100
CODES = [
    "AC", "FA", "LE", "TR", "DI", "PR", "AT", "DV", "UX", "FQ", "CO", "OT",
]  # fmt: skip
# En el orden de decisión de la guía `v2.1`.
CODES_V21 = ["AC", "TR", "DI", "PR", "AT", "FA", "LE", "CO", "DV", "UX", "OT"]
# Códigos y marcas cuya definición no cambió de `v2` a `v2.1`: en ellos, la
# muestra recodificada con `v2.1` mide la estabilidad intra-autor.
STABLE_CODES = ["LE", "DI", "AT", "DV", "OT"]
RECODE_V21_MIN_DAYS = 0.5
CALIB_QUEUES = ["calibracion"] + [f"calibracion{r}" for r in CALIB_ROUNDS]
SETS = [*CALIB_QUEUES, "muestra", "extracciones"]
QUEUES = [*CALIB_QUEUES, "muestra", "recodificacion", "muestra_v21"]
# Cola del autor → (conjunto que etiquetó Gemini, prompt, guía, códigos).
QUEUE_VERSION = {
    "muestra_v21": ("muestra", PROMPT_V21, GUIDELINE_V21, CODES_V21),
}


def queue_version(queue: str) -> tuple[str, str, str, list[str]]:
    return QUEUE_VERSION.get(queue, (queue, PROMPT, GUIDELINE, CODES))


# i CÓDIGOS u s m
LINE = re.compile(
    r"^\s*(\d+)\s+(-|[A-Z]{2}(?:,[A-Z]{2})*)\s+([01])\s+([01])\s+([01])\s*$"
)
# Palabras clave de seguridad para la segunda ronda de calibración.
# Lo que en `v1` caía en `OT` y en `v2` tiene familia (ronda 3).
FORMER_OT = (
    r"\b(publicidad|anuncio|promocion|spam|notifica|idioma|ingles|cajero|"
    r"puntos|recompensa|espacio|memoria|bateria|(obliga|pide|forz)\w* "
    r"(a )?actualiz)"
)
SECURITY = (
    r"\b(hacke|jaque|vulner|insegur|segur|suplant|clonar|robo de (cuenta|"
    r"identidad|datos)|entraron a mi cuenta|mis datos|huella|reconocimiento "
    r"facial)"
)
# Palabras clave de diseño para enriquecer: las de `DS` de `v1` y más.
DESIGN = (
    r"\b("
    + "|".join(
        STEMS["DS"]
        + [
            r"nueva version",
            r"colou?r",
            "letra",
            "icono",
            r"se ve",
            "modo oscuro",
            "elimin",
            r"ya no (aparece|esta|existe|se puede|hay)",
            "opcion",
            "menu",
            "pasos",
            "intuitiv",
            "dificil",
            "no encuentro",
        ]
    )
    + ")"
)
# Regla de decisión (guía, sección 6), fijada antes de codificar.
RULE = {
    "kappa_intra_autor_min": 0.70,
    "kappa_autor_gemini_min": 0.60,
    "confusion_max": 0.20,
    "prevalencia_min": 0.02,
    "kappa_fusion_min": 0.60,
    # `u` y `s` no entran en la regla: 5.5 las usa si su κ autor–Gemini
    # llega a este mínimo.
    "kappa_marca_min": 0.60,
}
# Código que se evalúa → códigos con los que se mide su confusión y
# código con el que se fusiona si falla.
SPLITS = {
    "DV": {"contra": ["UX"], "fusion": ("DU", ("DV", "UX"))},
    "UX": {"contra": ["DV"], "fusion": ("DU", ("DV", "UX"))},
    "FQ": {"contra": ["UX", "FA"], "fusion": ("UX", ("UX", "FQ"))},
}
FIELDS = [
    "item",
    "text_id",
    "codigos",
    "u",
    "s",
    "elogio",
    "guia",
    "inicio",
    "fin",
    "segundos",
    "comentario",
]


def queue_path(queue: str):
    return OUT / f"{queue}.csv"


def annotations_path(queue: str):
    return OUT / f"{queue}_annotations.csv"


def texts() -> pl.DataFrame:
    return pl.read_parquet(
        SILVER / "texts.parquet", columns=["text_id", "texto_sanitizado"]
    )


def write_queue(frame: pl.DataFrame, queue: str) -> None:
    path = queue_path(queue)
    if path.exists():
        raise SystemExit(f"{path} ya existe; no se sobrescribe")
    OUT.mkdir(parents=True, exist_ok=True)
    frame.join(texts(), on="text_id", how="left", maintain_order="left").select(
        pl.int_range(1, frame.height + 1).alias("item"),
        "text_id",
        "origen",
        "texto_sanitizado",
    ).write_csv(path)
    print(f"{frame.height} textos en {path}")


def seen_v1() -> set[int]:
    """Los 100 textos de la validación de `v1`: el autor ya los vio."""
    return set(pl.read_csv(OUT_V1 / "validation.csv")["text_id"].to_list())


def design_pools(exclude: set[int]) -> dict[str, list[int]]:
    """Textos únicos de diseño: `DS` de Gemini en `v1` y palabras clave."""
    v1 = pl.read_parquet(OUT_V1 / "labels_aspects_v1.parquet")
    ds = {
        t
        for t, c in v1.select("text_id", "codes").iter_rows()
        if "DS" in codes_list(c)
    } - exclude
    neg = negatives().unique("text_id").sort("text_id")
    kw = (
        {
            t
            for t, s in neg.select("text_id", "texto_sanitizado").iter_rows()
            if re.search(DESIGN, plain(s))
        }
        - exclude
        - ds
    )
    sec = (
        {
            t
            for t, s in neg.select("text_id", "texto_sanitizado").iter_rows()
            if re.search(SECURITY, plain(s))
        }
        - exclude
        - ds
        - kw
    )
    # Se calcula después de los otros para no cambiar los pools ya usados.
    ot = (
        {
            t
            for t, s in neg.select("text_id", "texto_sanitizado").iter_rows()
            if re.search(FORMER_OT, plain(s))
        }
        - exclude
        - ds
        - kw
        - sec
    )
    return {
        "enriquecida_v1": sorted(ds),
        "enriquecida_kw": sorted(kw),
        "enriquecida_seg": sorted(sec),
        "enriquecida_ot": sorted(ot),
    }


def pick(
    pools: dict[str, list[int]], n: int | dict[str, int], rng
) -> pl.DataFrame:
    """`n` textos, mitad de `enriquecida_v1` y mitad de `enriquecida_kw`, o
    `n[origen]` de cada origen."""
    if isinstance(n, int):
        n = {"enriquecida_v1": n // 2, "enriquecida_kw": n - n // 2}
    rows = []
    for origen, k in n.items():
        pool = pools[origen]
        if len(pool) < k:
            raise SystemExit(f"{origen}: {len(pool)} textos, se piden {k}")
        rows += [(int(t), origen) for t in rng.choice(pool, k, replace=False)]
    return pl.DataFrame(
        rows, schema={"text_id": pl.UInt32, "origen": pl.String}, orient="row"
    )


def calibration() -> None:
    rng = np.random.default_rng(SEED)
    calib = pick(design_pools(seen_v1()), CALIB_N, rng)
    write_queue(
        calib.sample(fraction=1, shuffle=True, seed=SEED), "calibracion"
    )


def calibration_round(ronda: int) -> None:
    """Ronda `ronda` de calibración, sin textos de colas anteriores."""
    previous = [q for q in (*CALIB_QUEUES, "muestra") if queue_path(q).exists()]
    exclude = seen_v1() | {
        t for q in previous for t in pl.read_csv(queue_path(q))["text_id"]
    }
    rng = np.random.default_rng(SEED + 1 + ronda)
    calib = pick(design_pools(exclude), CALIB_ROUNDS[ronda], rng)
    write_queue(
        calib.sample(fraction=1, shuffle=True, seed=SEED),
        f"calibracion{ronda}",
    )


def sample() -> None:
    calib = pl.read_csv(queue_path("calibracion"))
    exclude = seen_v1() | set(calib["text_id"].to_list())
    rng = np.random.default_rng(SEED + 1)
    enriched = pick(design_pools(exclude), ENRICHED_N, rng)
    exclude |= set(enriched["text_id"].to_list())
    order = (
        pl.read_parquet(OUT_V1 / "draws.parquet")
        .sort("extraccion")["text_id"]
        .unique(maintain_order=True)
    )
    random = [t for t in order.to_list() if t not in exclude][:RANDOM_N]
    both = pl.concat(
        [
            enriched,
            pl.DataFrame(
                {"text_id": random, "origen": "aleatoria"},
                schema={"text_id": pl.UInt32, "origen": pl.String},
            ),
        ]
    ).sample(fraction=1, shuffle=True, seed=SEED)
    write_queue(both, "muestra")
    meta = {
        "seed": SEED,
        "por_origen": dict(
            both.group_by("origen").len().sort("origen").iter_rows()
        ),
        "excluidos_validacion_v1": len(seen_v1()),
        "excluidos_calibracion": calib.height,
    }
    (OUT / "muestra_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(meta)


def parse(text: str) -> list[dict]:
    items = []
    for line in text.splitlines():
        if match := LINE.match(line):
            i, codes, u, sec, m = match.groups()
            items.append(
                {
                    "i": int(i),
                    "codes": "" if codes == "-" else codes,
                    "u": u == "1",
                    "s": sec == "1",
                    "m": m == "1",
                }
            )
    return items


def set_texts(name: str) -> pl.DataFrame:
    if name == "extracciones":
        ids = (
            pl.read_parquet(OUT_V1 / "draws.parquet").select("text_id").unique()
        )
    else:
        ids = pl.read_csv(queue_path(name)).select(
            pl.col("text_id").cast(pl.UInt32)
        )
    return texts().join(ids, on="text_id").sort("text_id")


def label(
    name: str, max_cost: float, missing: bool = False, prompt: str = PROMPT
) -> None:
    """Etiqueta el conjunto; con `missing`, solo los textos que aún no tienen
    etiqueta (por ejemplo, tras un lote fallido) y los agrega a los previos."""
    frame = set_texts(name)
    previous = gemini(name, prompt) if missing else None
    if previous is not None:
        frame = frame.join(previous.select("text_id"), on="text_id", how="anti")
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
    for start in range(0, frame.height, BATCH):
        chunk = frame[start : start + BATCH]
        ids = chunk["text_id"].to_list()
        batch = pl.DataFrame(
            {
                "pilot_id": range(len(ids)),
                "texto_sanitizado": chunk["texto_sanitizado"],
            }
        )
        items, usage = label_batch(client, batch, version)
        spent += (
            usage["prompt"] * PRICE_IN
            + (usage["output"] + usage["thoughts"]) * PRICE_OUT
        ) / 1e6
        batches.append({"start": start, "texts": len(ids), **usage})
        out += [
            {
                "text_id": ids[x["i"]],
                "codes": x["codes"],
                "actualizacion": x["u"],
                "seguridad": x["s"],
                "elogio": x["m"],
            }
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
        schema={
            "text_id": pl.UInt32,
            "codes": pl.String,
            "actualizacion": pl.Boolean,
            "seguridad": pl.Boolean,
            "elogio": pl.Boolean,
        },
    )
    if previous is not None:
        labels = pl.concat([previous.select(labels.columns), labels])
    labels.write_parquet(OUT / f"labels_{prompt}_{name}.parquet")
    meta = {
        "run": run,
        "model": MODEL,
        "location": LOCATION,
        "prompt": prompt,
        "set": name,
        "texts": frame.height,
        "labeled": labels.height,
        "failed_batches": sum(1 for b in batches if b["error"]),
        "cost_usd": round(spent, 5),
        "model_version": next(
            (b.get("model_version") for b in batches if b.get("model_version")),
            None,
        ),
        "batches": batches,
    }
    (OUT / f"run_{prompt}_{name}_{run}.json").write_text(
        json.dumps(meta, indent=2) + "\n"
    )
    print({k: v for k, v in meta.items() if k != "batches"})


def gemini(name: str, prompt: str = PROMPT) -> pl.DataFrame | None:
    """Etiquetas de Gemini; la ronda 1 (`aspects_v2_r1`) no tiene `s`."""
    path = OUT / f"labels_{prompt}_{name}.parquet"
    if not path.exists():
        return None
    g = pl.read_parquet(path)
    if "seguridad" not in g.columns:
        g = g.with_columns(seguridad=pl.lit(None, dtype=pl.Boolean))
    return g


def author(queue: str) -> pl.DataFrame | None:
    """Última codificación del autor por `item` de una cola."""
    path = annotations_path(queue)
    if not path.exists():
        return None
    a = pl.read_csv(path, schema_overrides={"codigos": pl.String})
    if "s" not in a.columns:  # ronda 1 de calibración, antes de la marca `s`
        a = a.with_columns(s=pl.lit(None, dtype=pl.Int64))
    return (
        a.with_row_index("fila")
        .group_by("item")
        .last()
        .sort("item")
        .with_columns(
            pl.col("text_id").cast(pl.UInt32),
            (pl.col("u") == 1).alias("u"),
            (pl.col("s") == 1).alias("s"),
            (pl.col("elogio") == 1).alias("elogio"),
        )
        .select("item", "text_id", "codigos", "u", "s", "elogio", "guia", "fin")
    )


def kappa(a: list, b: list) -> float | None:
    """κ binario; `None` sin positivos o si falta una marca (ronda 1)."""
    if None in a or None in b or (not any(a) and not any(b)):
        return None
    return round(float(cohen_kappa_score(a, b)), 3)


def agreement(left: list[list[str]], right: list[list[str]], codes) -> dict:
    return {
        c: kappa([c in x for x in left], [c in x for x in right]) for c in codes
    }


def fused(
    sets: list[list[str]], into: str, members: tuple[str, ...]
) -> list[list[str]]:
    return [sorted({into if c in members else c for c in s}) for s in sets]


def confusion(hum, gem, code: str, contra: list[str]) -> dict:
    """Parte de los desacuerdos en `code` que son un cambio por `contra`."""
    disagree = [
        (h, g)
        for h, g in zip(hum, gem, strict=True)
        if (code in h) != (code in g)
    ]
    swaps = sum(
        1
        for h, g in disagree
        if (
            code in h
            and code not in g
            and any(c in g and c not in h for c in contra)
        )
        or (
            code in g
            and code not in h
            and any(c in h and c not in g for c in contra)
        )
    )
    return {
        "desacuerdos": len(disagree),
        "cambios": swaps,
        "proporcion": round(swaps / len(disagree), 3) if disagree else 0.0,
    }


def disagreements(name: str) -> None:
    labeled, prompt, _, codes = queue_version(name)
    a, g = author(name), gemini(labeled, prompt)
    if a is None or g is None:
        raise SystemExit("faltan las codificaciones del autor o de Gemini")
    d = a.join(g, on="text_id", suffix="_gemini").join(texts(), on="text_id")
    hum = [codes_list(s) for s in d["codigos"]]
    gem = [codes_list(s) for s in d["codes"]]
    print(
        json.dumps(
            {
                "items": d.height,
                "kappa_por_codigo": agreement(hum, gem, codes),
                "kappa_u": kappa(
                    d["u"].to_list(), d["actualizacion"].to_list()
                ),
                "kappa_s": kappa(d["s"].to_list(), d["seguridad"].to_list()),
                "acuerdo_conjunto_exacto": round(
                    float(
                        np.mean([h == x for h, x in zip(hum, gem, strict=True)])
                    ),
                    3,
                ),
            },
            indent=2,
        )
    )
    rows = d.with_columns(
        autor=pl.Series([",".join(x) or "-" for x in hum]),
        gemini=pl.Series([",".join(x) or "-" for x in gem]),
        u_autor=pl.col("u").cast(pl.Int8),
        u_gemini=pl.col("actualizacion").cast(pl.Int8),
        s_autor=pl.col("s").cast(pl.Int8),
        s_gemini=pl.col("seguridad").cast(pl.Int8),
    ).filter(
        (pl.col("autor") != pl.col("gemini"))
        | (pl.col("u_autor") != pl.col("u_gemini"))
        | pl.col("s_autor").ne_missing(pl.col("s_gemini"))
    )
    path = OUT / f"desacuerdos_{name}.csv"
    rows.select(
        "item",
        "text_id",
        "autor",
        "gemini",
        "u_autor",
        "u_gemini",
        "s_autor",
        "s_gemini",
        "texto_sanitizado",
    ).write_csv(path)
    print(f"{rows.height} desacuerdos en {path}")


def recode(min_days: float = RECODE_MIN_DAYS) -> None:
    a = author("muestra")
    if a is None:
        raise SystemExit("la muestra aún no está codificada")
    origen = pl.read_csv(queue_path("muestra")).select(
        pl.col("text_id").cast(pl.UInt32), "origen"
    )
    a = a.join(origen, on="text_id").with_columns(
        fin=pl.col("fin").str.to_datetime(time_zone="UTC")
    )
    ready = a.filter(
        pl.col("fin") <= datetime.now(UTC) - timedelta(days=min_days)
    )
    rng = np.random.default_rng(SEED + 2)
    chosen = []
    for enriched, k in (
        (True, RECODE_N // 2),
        (False, RECODE_N - RECODE_N // 2),
    ):
        pool = ready.filter((pl.col("origen") != "aleatoria") == enriched)
        if pool.height < k:
            first = a["fin"].min() + timedelta(days=min_days)
            raise SystemExit(
                f"solo {pool.height} textos "
                f"{'enriquecidos' if enriched else 'aleatorios'} tienen "
                f"{min_days} días o más (se piden {k}); los primeros "
                f"estarán listos el {first:%Y-%m-%d}"
            )
        chosen += [
            int(t)
            for t in rng.choice(pool["text_id"].to_list(), k, replace=False)
        ]
    frame = (
        pl.DataFrame({"text_id": chosen}, schema={"text_id": pl.UInt32})
        .join(origen, on="text_id")
        .sample(fraction=1, shuffle=True, seed=SEED)
    )
    write_queue(frame, "recodificacion")


def recode_v21(min_days: float = RECODE_V21_MIN_DAYS) -> None:
    """Los textos de la muestra, en otro orden, para codificarlos con `v2.1`.

    Exige que la última codificación con `v2` tenga al menos `min_days`.
    """
    a = author("muestra")
    if a is None:
        raise SystemExit("la muestra aún no está codificada")
    last = a["fin"].str.to_datetime(time_zone="UTC").max()
    ready = last + timedelta(days=min_days)
    if datetime.now(UTC) < ready:
        local = ready.astimezone()
        raise SystemExit(
            f"la última codificación con v2 es de {last:%Y-%m-%d %H:%M} UTC; "
            f"con {min_days} días, la cola estará lista el "
            f"{local:%Y-%m-%d %H:%M} (hora local)"
        )
    frame = (
        pl.read_csv(queue_path("muestra"))
        .select(pl.col("text_id").cast(pl.UInt32), "origen")
        .sample(fraction=1, shuffle=True, seed=SEED + 21)
    )
    write_queue(frame, "muestra_v21")


def pending(step: str) -> dict:
    return {"estado": "pendiente", "paso": step}


OUTPUT_SCHEMA = {
    "text_id": "UInt32; texto único de silver_v0",
    "codes": (
        "String; familias separadas por comas, vacío si no hay problema "
        "concreto"
    ),
    "actualizacion": "Boolean; marca u (problema atribuido a actualización)",
    "seguridad": "Boolean; marca s (queja de seguridad o privacidad)",
    "elogio": "Boolean; elogio concreto",
}


def population(g_ext: pl.DataFrame, codes: list[str], rng) -> dict:
    """Prevalencias y multi-aspecto en las extracciones representativas."""
    d = (
        pl.read_parquet(OUT_V1 / "draws.parquet")
        .join(g_ext, on="text_id", how="inner")
        .with_columns(
            n_aspectos=pl.col("codes").map_elements(
                lambda s: len(codes_list(s)), return_dtype=pl.Int64
            )
        )
        .with_columns(multi=pl.col("n_aspectos") >= 2)
    )
    sets = [codes_list(s) for s in d["codes"]]
    v1 = json.loads((DOCS / "eda" / "aspects_v1_metrics.json").read_text())
    return {
        "extracciones": d.height,
        "multi_aspecto": prop_ci(d["multi"].to_numpy(), rng),
        "multi_aspecto_v1": v1["poblacion_filas_neg"]["multi_aspecto"],
        "sin_aspecto_concreto": prop_ci((d["n_aspectos"] == 0).to_numpy(), rng),
        "actualizacion_u": prop_ci(d["actualizacion"].to_numpy(), rng),
        "seguridad_s": prop_ci(d["seguridad"].to_numpy(), rng),
        "elogio_concreto": prop_ci(d["elogio"].to_numpy(), rng),
        "por_codigo": [
            {"codigo": c, **prop_ci(np.array([c in s for s in sets]), rng)}
            for c in codes
        ],
        "multi_por_largo": [
            {"largo": k[0], **prop_ci(g["multi"].to_numpy(), rng)}
            for k, g in d.sort("palabras").group_by(
                "largo", maintain_order=True
            )
        ],
        "multi_desde_k_palabras": [
            {
                "k": k,
                **prop_ci(
                    d.filter(pl.col("palabras") >= k)["multi"].to_numpy(), rng
                ),
            }
            for k in (2, 3, 5, 10, 20)
        ],
        "marcas_por_banco": [
            {
                "bank_id": k[0],
                "actualizacion_u": prop_ci(g["actualizacion"].to_numpy(), rng),
                "seguridad_s": prop_ci(g["seguridad"].to_numpy(), rng),
                "sin_familia_ot": prop_ci(
                    np.array(["OT" in codes_list(c) for c in g["codes"]]), rng
                ),
            }
            for k, g in d.sort("bank_id").group_by(
                "bank_id", maintain_order=True
            )
        ],
    }


def validation(queue: str) -> tuple[dict, list, list] | None:
    """Acuerdo autor–Gemini de una cola, en total y en la mitad aleatoria."""
    labeled, prompt, _, codes = queue_version(queue)
    a, g = author(queue), gemini(labeled, prompt)
    if a is None or g is None:
        return None
    origen = pl.read_csv(queue_path(queue)).select(
        pl.col("text_id").cast(pl.UInt32), "origen"
    )
    v = a.join(g, on="text_id", suffix="_gemini").join(origen, on="text_id")
    hum = [codes_list(s) for s in v["codigos"]]
    gem = [codes_list(s) for s in v["codes"]]
    rand = (v["origen"] == "aleatoria").to_list()

    def sub(xs, mask=None):
        return [
            x
            for x, keep in zip(xs, mask or [True] * len(xs), strict=True)
            if keep
        ]

    def block(mask=None) -> dict:
        h, x = sub(hum, mask), sub(gem, mask)
        return {
            "items": len(h),
            "kappa_por_codigo": agreement(h, x, codes),
            "kappa_u": kappa(
                sub(v["u"].to_list(), mask),
                sub(v["actualizacion"].to_list(), mask),
            ),
            "kappa_s": kappa(
                sub(v["s"].to_list(), mask), sub(v["seguridad"].to_list(), mask)
            ),
            "multi_autor": round(float(np.mean([len(s) >= 2 for s in h])), 4),
            "multi_gemini": round(float(np.mean([len(s) >= 2 for s in x])), 4),
            "acuerdo_conjunto_exacto": round(
                float(np.mean([p == q for p, q in zip(h, x, strict=True)])), 3
            ),
        }

    out = {
        "cola": queue,
        "prompt_gemini": prompt,
        "guias": dict(v.group_by("guia").len().sort("guia").iter_rows()),
        "muestra": block(),
        "mitad_aleatoria": block(rand),
    }
    return out, hum, gem


def intra_author() -> dict:
    """Consistencia del autor.

    Con `recode` (misma guía), en todos los códigos. Con `recode-v21`, solo
    en los códigos y marcas cuya definición no cambió (`STABLE_CODES`); los
    demás no se pueden separar del cambio de guía.
    """
    a = author("muestra")
    for queue, codes in (
        ("recodificacion", CODES),
        ("muestra_v21", STABLE_CODES),
    ):
        r = author(queue)
        if r is None or a is None:
            continue
        w = r.join(a, on="text_id", suffix="_primera")
        first = [codes_list(s) for s in w["codigos_primera"]]
        second = [codes_list(s) for s in w["codigos"]]
        days = (
            w["fin"].str.to_datetime(time_zone="UTC")
            - w["fin_primera"].str.to_datetime(time_zone="UTC")
        ).dt.total_hours() / 24
        return {
            "fuente": queue,
            "nota": (
                "misma guía v2"
                if queue == "recodificacion"
                else "recodificación con la guía v2.1 y casillas agrupadas; "
                "solo códigos cuya definición no cambió"
            ),
            "items": w.height,
            "dias_entre_codificaciones_min": round(float(days.min()), 2),
            "kappa_por_codigo": agreement(first, second, codes),
            "kappa_u": kappa(w["u_primera"].to_list(), w["u"].to_list()),
            "kappa_s": kappa(w["s_primera"].to_list(), w["s"].to_list()),
        }
    return pending("recode-v21 y codificar la cola muestra_v21")


def decide(m: dict, hum, gem, prevalence: dict) -> dict:
    """Regla de decisión de la guía `v2`, sección 6, tal como se fijó."""
    intra = m["intra_autor"].get("kappa_por_codigo", {})
    m["validacion_autor"]["confusion"] = {
        c: confusion(hum, gem, c, s["contra"]) for c, s in SPLITS.items()
    }
    m["validacion_autor"]["kappa_fusion"] = {
        "+".join(ms): agreement(
            fused(hum, into, ms), fused(gem, into, ms), [into]
        )[into]
        for into, ms in {s["fusion"] for s in SPLITS.values()}
    }
    decision = {}
    for c, s in SPLITS.items():
        checks = {
            "kappa_intra_autor": intra.get(c),
            "kappa_autor_gemini": m["validacion_autor"]["muestra"][
                "kappa_por_codigo"
            ][c],
            "confusion": m["validacion_autor"]["confusion"][c]["proporcion"],
            "prevalencia": round(prevalence[c], 4),
        }
        ok = {
            "kappa_intra_autor": None
            if checks["kappa_intra_autor"] is None
            else checks["kappa_intra_autor"] >= RULE["kappa_intra_autor_min"],
            "kappa_autor_gemini": (checks["kappa_autor_gemini"] or 0)
            >= RULE["kappa_autor_gemini_min"],
            "confusion": checks["confusion"] < RULE["confusion_max"],
            "prevalencia": checks["prevalencia"] >= RULE["prevalencia_min"],
        }
        into, ms = s["fusion"]
        k_fusion = m["validacion_autor"]["kappa_fusion"]["+".join(ms)]
        failed = [k for k, passed in ok.items() if passed is False]
        decision[c] = {
            "valores": checks,
            "cumple": ok,
            "no_medible": [k for k, passed in ok.items() if passed is None],
            "separado": not failed,
            "fusion": None
            if not failed
            else {
                "codigo": into,
                "con": "+".join(ms),
                "fallan": failed,
                "kappa_autor_gemini": k_fusion,
                "valida": (k_fusion or 0) >= RULE["kappa_fusion_min"],
            },
        }
    decision["resumen"] = {
        "DV_UX_separados": decision["DV"]["separado"]
        and decision["UX"]["separado"],
        "FQ_separado": decision["FQ"]["separado"],
    }
    return decision


def analyze() -> None:
    rng = np.random.default_rng(SEED)
    intra = intra_author()

    # Guía `v2`: la regla de decisión tal como se fijó.
    m: dict = {
        "prompt": PROMPT,
        "guia": GUIDELINE,
        "model": MODEL,
        "codes": CODES,
        "regla_decision": RULE,
        "esquema_salida": {
            "archivo": f"data/eda/aspects_v2/labels_{PROMPT}_<set>.parquet",
            "columnas": OUTPUT_SCHEMA,
        },
        "intra_autor": intra,
    }
    g_ext = gemini("extracciones")
    prevalence: dict[str, float] = {}
    if g_ext is None:
        m["poblacion_filas_neg"] = pending("label --set extracciones")
    else:
        m["poblacion_filas_neg"] = population(g_ext, CODES, rng)
        sets = [
            codes_list(c)
            for c in pl.read_parquet(OUT_V1 / "draws.parquet").join(
                g_ext, on="text_id"
            )["codes"]
        ]
        prevalence = {c: float(np.mean([c in x for x in sets])) for c in CODES}
    val = validation("muestra")
    if val is None:
        m["validacion_autor"] = pending("codificar la muestra y label")
        m["decision"] = pending("falta la muestra")
    else:
        m["validacion_autor"], hum, gem = val
        m["decision"] = (
            decide(m, hum, gem, prevalence)
            if prevalence
            else pending("label --set extracciones")
        )
    write_metrics(m, PROMPT)

    # Guía `v2.1`: taxonomía final, decidida por el autor.
    f: dict = {
        "prompt": PROMPT_V21,
        "guia": GUIDELINE_V21,
        "model": MODEL,
        "codes": CODES_V21,
        "decision_autor": {
            "fecha": "2026-10-21",
            "taxonomia": (
                "DV separado; FQ dentro de UX; instalación y actualización en "
                "CO; token, códigos, NIP y biometría en AC"
            ),
            "desviacion_de_la_regla_v2": (
                "La regla v2 fusiona DV y UX en DU porque UX no llega a κ "
                "0.60. DV se mantiene separado por ahora, como excepción por "
                "baja prevalencia: la confusión DV↔UX es baja y DV tiene κ "
                "alto, así que el κ de UX viene de su frontera con otras "
                "familias. FQ se fusiona con UX por prevalencia."
            ),
            "criterio_fijado_antes_de_recodificar": (
                "1) Se mide el efecto aislado de v2.1 sobre UX con su κ sin "
                "fusionar DV (resuelto si κ ≥ 0.60). 2) Después se decide si "
                "DV se une a UX, por definición y prevalencia; el κ de DV+UX "
                "es solo sensibilidad."
            ),
            "kappa_marca_min": RULE["kappa_marca_min"],
            "decision_final_dv": (
                "2026-10-21: DV se mantiene separado como excepción a la "
                "prevalencia mínima (1.8 % con Gemini y v2.1). UX llegó a κ "
                "≥ 0.60 sin fusionarse y la confusión DV↔UX es baja; unirlos "
                "sería una decisión de definición que perdería esa distinción."
            ),
        },
        "esquema_salida": {
            "archivo": f"data/eda/aspects_v2/labels_{PROMPT_V21}_<set>.parquet",
            "columnas": OUTPUT_SCHEMA,
        },
        "intra_autor": intra,
    }
    g21 = gemini("extracciones", PROMPT_V21)
    f["poblacion_filas_neg"] = (
        pending("label --set extracciones --prompt aspects_v2_1")
        if g21 is None
        else population(g21, CODES_V21, rng)
    )
    val21 = validation("muestra_v21")
    if val21 is None:
        f["validacion_autor"] = pending(
            "recode-v21, codificar y label --set muestra --prompt aspects_v2_1"
        )
    else:
        f["validacion_autor"], hum21, gem21 = val21
        ux = f["validacion_autor"]["muestra"]["kappa_por_codigo"]["UX"]
        f["efecto_v21_en_ux"] = {
            "kappa_ux_v2": m.get("validacion_autor", {})
            .get("muestra", {})
            .get("kappa_por_codigo", {})
            .get("UX"),
            "kappa_ux_v21": ux,
            "resuelto": (ux or 0) >= RULE["kappa_autor_gemini_min"],
            "confusion_dv_ux": confusion(hum21, gem21, "DV", ["UX"]),
            "sensibilidad_kappa_dv_mas_ux": agreement(
                fused(hum21, "DU", ("DV", "UX")),
                fused(gem21, "DU", ("DV", "UX")),
                ["DU"],
            )["DU"],
        }
    write_metrics(f, PROMPT_V21)


def write_metrics(m: dict, prompt: str) -> None:
    path = DOCS / "eda" / f"{prompt}_metrics.json"
    path.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
    print(f"{path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("calibration")
    rnd = sub.add_parser("calibration-round")
    rnd.add_argument(
        "--ronda", type=int, choices=list(CALIB_ROUNDS), required=True
    )
    sub.add_parser("sample")
    lab = sub.add_parser("label")
    lab.add_argument("--set", choices=SETS, required=True)
    lab.add_argument("--max-cost", type=float, default=1.0)
    lab.add_argument("--prompt", choices=PROMPT_VERSIONS, default=PROMPT)
    lab.add_argument(
        "--solo-faltantes",
        action="store_true",
        help="etiqueta solo los textos sin etiqueta y los agrega",
    )
    dis = sub.add_parser("disagreements")
    dis.add_argument(
        "--set",
        choices=[*CALIB_QUEUES, "muestra", "muestra_v21"],
        required=True,
    )
    rec = sub.add_parser("recode")
    rec.add_argument("--min-dias", type=float, default=RECODE_MIN_DAYS)
    r21 = sub.add_parser("recode-v21")
    r21.add_argument("--min-dias", type=float, default=RECODE_V21_MIN_DAYS)
    sub.add_parser("analyze")
    args = parser.parse_args()
    if args.cmd == "label":
        label(args.set, args.max_cost, args.solo_faltantes, args.prompt)
    elif args.cmd == "disagreements":
        disagreements(args.set)
    elif args.cmd == "recode":
        recode(args.min_dias)
    elif args.cmd == "recode-v21":
        recode_v21(args.min_dias)
    elif args.cmd == "calibration-round":
        calibration_round(args.ronda)
    else:
        {
            "calibration": calibration,
            "sample": sample,
            "analyze": analyze,
        }[args.cmd]()


if __name__ == "__main__":
    main()
