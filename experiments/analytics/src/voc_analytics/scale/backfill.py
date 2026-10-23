"""Backfill de sentimiento con M4 en Kaggle, con pipeline desde GCP (P7-1).

Decisión del autor (2026-10-22): el backfill y el *re-scoring* (P7-4) corren
en la T4 de Kaggle por tiempo de ejecución; se asume el riesgo de subir el
corpus completo (FMEA F-14). El delta diario queda en Cloud Run.

Pasos (cada uno es un subcomando):

1. `export` (entorno de la raíz, tiene `google-cloud-bigquery`): `EXPORT
   DATA` de los textos únicos de `sanitized_reviews_tds` al bucket del
   proyecto (`gs://voc-datalake-<proyecto>/backfill/<corrida>/`) y descarga a
   `data/backfill/<corrida>/texts/`. Viaja solo `texto_sanitizado`, su clave
   (`text_key` = SHA-256 hexadecimal del texto, igual en BigQuery y en Python)
   y su número de filas.
2. `dataset`: arma el dataset privado de Kaggle `voc-backfill-corpus` con los
   textos y los pesos `M4_robertuito_s{1,2,3}_ppi`, y lo sube.
3. `kernel`: lanza el kernel privado con GPU `voc-backfill-m4`. Predice todos
   los textos con las tres semillas (la de producción se elige después) y
   escribe `preds_s<semilla>.parquet` con `text_key` y las probabilidades sin
   calibrar (la T de cada semilla se aplica al cargar).
4. `pull`: descarga la salida a `data/backfill/<corrida>/preds/`.
5. `check`: valida contra las predicciones de 5.6 sobre `ppi_v0` (mismos
   pesos, otra GPU) y escribe `docs/analytics/scale/backfill_v0_metrics.json`,
   solo agregados.

La carga a BigQuery (`review_predictions`, esquema v3) queda para EPIC-6
(6.2 y 6.3), con la aprobación del autor.

El dataset `voc-backfill-corpus` de la corrida `20261022` se borró de Kaggle
el 2026-10-23, al cerrar EPIC-5 (F-14). En EPIC-6 (6.3), cada *re-scoring*
sube su propio dataset (`voc-backfill-corpus-<corrida>`) y lo borra en cuanto
la carga en BigQuery queda verificada (decisión del autor, 2026-10-23).

    .venv/bin/python \\
        experiments/analytics/src/voc_analytics/scale/backfill.py \\
        export --run 20261022
    # desde experiments/analytics:
    uv run python -m voc_analytics.scale.backfill dataset --run 20261022 \\
        --user <usuario>
    uv run python -m voc_analytics.scale.backfill kernel --user <usuario>
    uv run python -m voc_analytics.scale.backfill pull --run 20261022 \\
        --user <usuario>
    uv run python -m voc_analytics.scale.backfill check --run 20261022
"""

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

PROJECT = "project-7bafd424-a385-4c05-b5b"
LOCATION = "us-central1"
TABLE = f"{PROJECT}.bbva_voc_tds.sanitized_reviews_tds"
BUCKET = f"voc-datalake-{PROJECT}"
ANALYTICS = Path(__file__).resolve().parents[3]
DATA = ANALYTICS / "data"
BACKFILL = DATA / "backfill"
WEIGHTS = DATA / "models" / "weights"
DOCS = ANALYTICS.parents[1] / "docs" / "analytics" / "scale"
SEEDS = (1, 2, 3)
DATASET = "voc-backfill-corpus"
KERNEL_SLUG = "voc-backfill-m4"

EXPORT_SQL = f"""
EXPORT DATA OPTIONS (
  uri = 'gs://{BUCKET}/backfill/{{run}}/texts/*.parquet',
  format = 'PARQUET', overwrite = true) AS
SELECT
  TO_HEX(SHA256(texto_sanitizado)) AS text_key,
  texto_sanitizado,
  COUNT(*) AS filas
FROM `{TABLE}`
WHERE texto_sanitizado IS NOT NULL AND TRIM(texto_sanitizado) != ''
GROUP BY texto_sanitizado
"""  # noqa: S608 - tabla fija

KERNEL = '''"""Backfill de M4 en Kaggle (generado por scale/backfill.py)."""
import json, shutil, subprocess, sys, time
from pathlib import Path

subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                "pysentimiento>=0.7,<1"], check=True)
import numpy as np, pyarrow as pa, pyarrow.parquet as pq, torch
from pysentimiento.preprocessing import preprocess_tweet
from transformers import AutoModelForSequenceClassification, AutoTokenizer

src = next(Path("/kaggle/input").rglob("texts.parquet")).parent
work = Path("/kaggle/working")
for z in src.glob("*.zip"):  # Kaggle puede dejar las carpetas como .zip.
    shutil.unpack_archive(z, work / "weights" / z.stem)
for d in src.iterdir():
    if d.is_dir():
        shutil.copytree(d, work / "weights" / d.name, dirs_exist_ok=True)
CLASSES = ["NEG", "NEU", "POS"]
t0 = time.perf_counter()
table = pq.read_table(src / "texts.parquet",
                      columns=["text_key", "texto_sanitizado"])
if LIMIT:  # prueba de humo
    table = table.slice(0, LIMIT)
keys = table["text_key"]
texts = [preprocess_tweet(t) for t in table["texto_sanitizado"].to_pylist()]
first = sorted((work / "weights").iterdir())[0]
tok = AutoTokenizer.from_pretrained(first)
ids = tok(texts, truncation=True, max_length=128)["input_ids"]
order = np.argsort([len(x) for x in ids], kind="stable")
log = {"textos": len(ids), "preparacion_s": round(time.perf_counter() - t0, 1)}
print(log, flush=True)
for seed in SEEDS:
    path = work / "weights" / f"M4_robertuito_s{seed}_ppi"
    model = AutoModelForSequenceClassification.from_pretrained(
        path, torch_dtype=torch.float16).cuda().eval()
    assert [model.config.id2label[i] for i in range(3)] == CLASSES
    out = np.zeros((len(ids), 3), dtype=np.float32)
    start = time.perf_counter()
    with torch.inference_mode():
        for i in range(0, len(ids), BATCH):
            idx = order[i:i + BATCH]
            batch = [ids[j] for j in idx]
            width = max(map(len, batch))
            x = torch.full((len(batch), width), tok.pad_token_id)
            for r, b in enumerate(batch):
                x[r, :len(b)] = torch.tensor(b)
            x = x.cuda()
            mask = x != tok.pad_token_id
            logits = model(input_ids=x, attention_mask=mask).logits
            out[idx] = torch.softmax(logits.float(), dim=-1).cpu().numpy()
    secs = time.perf_counter() - start
    pq.write_table(pa.table({"text_key": keys, "p_NEG": out[:, 0],
                             "p_NEU": out[:, 1], "p_POS": out[:, 2]}),
                   work / f"preds_s{seed}.parquet", compression="zstd")
    log[f"s{seed}"] = {"segundos": round(secs, 1),
                       "textos_por_segundo": round(len(ids) / secs, 1)}
    print(log, flush=True)
    del model
    torch.cuda.empty_cache()
shutil.rmtree(work / "weights")
(work / "log.json").write_text(json.dumps(log, indent=2))
'''


def kaggle(*args: str) -> None:
    # CLI local con argumentos fijos de este script.
    subprocess.run(["uvx", "kaggle", *args], check=True)  # noqa: S603, S607


def export(run: str) -> None:
    from google.cloud import bigquery

    client = bigquery.Client(project=PROJECT, location=LOCATION)
    job = client.query(EXPORT_SQL.format(run=run), location=LOCATION)
    job.result()
    rows = client.query(
        f"SELECT COUNT(*) AS filas, COUNT(DISTINCT texto_sanitizado) AS textos,"  # noqa: S608
        f" MAX(fecha) AS fecha_max FROM `{TABLE}`",
        location=LOCATION,
    )
    stats = next(iter(rows.result()))
    out = BACKFILL / run / "texts"
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "gcloud",
            "storage",
            "cp",
            f"gs://{BUCKET}/backfill/{run}/texts/*.parquet",
            str(out),
        ],
        check=True,
    )
    manifest = {
        "corrida": run,
        "exportado": datetime.now(UTC).isoformat(timespec="seconds"),
        "fuente": TABLE,
        "uri": f"gs://{BUCKET}/backfill/{run}/texts/",
        "filas_tds": stats["filas"],
        "textos_unicos": stats["textos"],
        "fecha_max": str(stats["fecha_max"]),
        "gb_facturados": round(job.total_bytes_billed / 1e9, 3),
        "archivos": len(list(out.glob("*.parquet"))),
    }
    (BACKFILL / run / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def dataset(run: str, user: str, update: bool) -> None:
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq

    folder = BACKFILL / "kaggle_dataset"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    table = ds.dataset(BACKFILL / run / "texts", format="parquet").to_table()
    pq.write_table(table, folder / "texts.parquet", compression="zstd")
    for s in SEEDS:
        name = f"M4_robertuito_s{s}_ppi"
        shutil.copytree(WEIGHTS / name, folder / name)
    meta = {
        "title": "VOC backfill corpus",
        "id": f"{user}/{DATASET}",
        "licenses": [{"name": "other"}],
    }
    (folder / "dataset-metadata.json").write_text(json.dumps(meta, indent=2))
    print(f"{table.num_rows} textos en {folder}", flush=True)
    if update:
        kaggle(
            "datasets", "version", "-p", str(folder), "-m", run,
            "--dir-mode", "zip",
        )  # fmt: skip
    else:
        kaggle("datasets", "create", "-p", str(folder), "--dir-mode", "zip")


def kernel(user: str, batch: int, limit: int) -> None:
    folder = DATA / "kaggle_kernels" / "backfill_m4"
    folder.mkdir(parents=True, exist_ok=True)
    script = (
        f"SEEDS = {list(SEEDS)}\nBATCH = {batch}\nLIMIT = {limit}\n" + KERNEL
    )
    (folder / "run.py").write_text(script)
    meta = {
        "id": f"{user}/{KERNEL_SLUG}",
        "title": KERNEL_SLUG,
        "code_file": "run.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,
        "dataset_sources": [f"{user}/{DATASET}"],
    }
    (folder / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    kaggle("kernels", "push", "-p", str(folder))


def pull(run: str, user: str) -> None:
    out = BACKFILL / run / "preds"
    out.mkdir(parents=True, exist_ok=True)
    kaggle("kernels", "output", f"{user}/{KERNEL_SLUG}", "-p", str(out))


def check(run: str) -> None:
    import hashlib

    import numpy as np
    import polars as pl

    from voc_analytics.sentiment.data import PREDS, SILVER

    folder = BACKFILL / run
    manifest = json.loads((folder / "manifest.json").read_text())
    texts = pl.read_parquet(folder / "texts" / "*.parquet")
    ppi_texts = (
        pl.read_parquet(SILVER.parent / "ppi_v0" / "texts.parquet")
        .select("text_id", "texto_sanitizado")
        .with_columns(
            text_key=pl.col("texto_sanitizado").map_elements(
                lambda t: hashlib.sha256(t.encode()).hexdigest(),
                return_dtype=pl.String,
            )
        )
    )
    result: dict = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "corrida": run,
        "textos_exportados": texts.height,
        "filas_tds": manifest["filas_tds"],
        "filas_cubiertas": int(texts["filas"].sum()),
        "log_kaggle": json.loads((folder / "preds" / "log.json").read_text()),
        "semillas": {},
    }
    classes = np.array(["NEG", "NEU", "POS"])
    for s in SEEDS:
        preds = pl.read_parquet(folder / "preds" / f"preds_s{s}.parquet")
        old = pl.read_parquet(
            PREDS / f"M4_robertuito_s{s}_ppi__ppi.parquet"
        ).join(ppi_texts.select("text_id", "text_key"), on="text_id")
        j = old.join(preds, on="text_key", suffix="_bf")
        a = j.select("p_NEG", "p_NEU", "p_POS").to_numpy()
        b = j.select("p_NEG_bf", "p_NEU_bf", "p_POS_bf").to_numpy()
        new_cls = classes[b.argmax(axis=1)]
        share = preds.select(
            pl.concat_list("p_NEG", "p_NEU", "p_POS").list.arg_max().alias("c")
        )["c"].value_counts(normalize=True)
        result["semillas"][f"s{s}"] = {
            "textos_predichos": preds.height,
            "faltantes": texts.join(preds, on="text_key", how="anti").height,
            "control_ppi_v0": {
                "textos": j.height,
                "acuerdo_clase": round(
                    float(np.mean(new_cls == j["pred"].to_numpy())), 4
                ),
                "max_dif_prob": round(float(np.abs(a - b).max()), 4),
            },
            "proporcion_por_clase_textos": {
                classes[c]: round(p, 4) for c, p in share.iter_rows()
            },
        }
    out = DOCS / "backfill_v0_metrics.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "step", choices=["export", "dataset", "kernel", "pull", "check"]
    )
    ap.add_argument("--run", default=datetime.now(UTC).strftime("%Y%m%d"))
    ap.add_argument("--user")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--limit", type=int, default=0, help="prueba de humo")
    args = ap.parse_args()
    if args.step == "export":
        export(args.run)
    elif args.step == "dataset":
        dataset(args.run, args.user, args.update)
    elif args.step == "kernel":
        kernel(args.user, args.batch, args.limit)
    elif args.step == "pull":
        pull(args.run, args.user)
    else:
        check(args.run)


if __name__ == "__main__":
    main()
