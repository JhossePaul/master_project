"""Viabilidad de la búsqueda semántica con `VECTOR_SEARCH` de BigQuery (P8-6).

Experimento aprobado por el autor (2026-10-22). Mide latencia, bytes
escaneados y costo de una búsqueda de vecinos en BigQuery, sin índice (fuerza
bruta) y con índice IVF, a escala del corpus. No sube texto: solo vectores.

* **Datos:**
  * `emb_real`: los 40 382 embeddings MiniLM (384) de las negativas de la
    plata (5.5), con `text_id`; sirve para comprobar que la consulta devuelve
    vecinos con sentido (misma familia `aspects_v2_1` más seguido que al azar).
  * `emb_synth`: 1 383 138 vectores aleatorios de 384, generados en
    BigQuery, del tamaño del corpus de textos únicos; mide la escala.
* **Consultas:** 5 por configuración, `top_k` 20, distancia coseno; se
  reportan la mediana de latencia, los bytes procesados y facturados.
* **Limpieza:** el dataset temporal (`voc_bench_57`, con expiración de tablas
  de un día) se borra al final.

Se corre con el entorno de la raíz del repo, que tiene `google-cloud-bigquery`
(el proyecto `experiments/analytics` no lo tiene):

    A=experiments/analytics
    .venv/bin/python $A/src/voc_analytics/scale/vector_search.py \\
        --embeddings $A/data/topics/working_v0/emb_minilm.npy \\
        --texts $A/data/topics/working_v0/texts.parquet \\
        --families \\
        $A/data/topics/aspects_scale_v0/labels_aspects_v2_1.parquet \\
        --out docs/analytics/scale/vector_search_v0_metrics.json
"""

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from google.cloud import bigquery

PROJECT = "project-7bafd424-a385-4c05-b5b"
LOCATION = "us-central1"
DATASET = "voc_bench_57"
CORPUS_TEXTS = 1_383_138
DIM = 384
QUERIES = 5
TOP_K = 20
SEED = 20261022


def run(client: bigquery.Client, sql: str, params=None) -> tuple:
    config = bigquery.QueryJobConfig(
        query_parameters=params or [], use_query_cache=False
    )
    start = time.perf_counter()
    job = client.query(sql, job_config=config, location=LOCATION)
    rows = list(job.result())
    return rows, {
        "segundos": round(time.perf_counter() - start, 2),
        "bytes_procesados": job.total_bytes_processed,
        "bytes_facturados": job.total_bytes_billed,
        "slot_ms": job.slot_millis,
    }


def summarize(stats: list[dict]) -> dict:
    return {
        "consultas": len(stats),
        "latencia_mediana_s": statistics.median(s["segundos"] for s in stats),
        "bytes_procesados_mediana": statistics.median(
            s["bytes_procesados"] for s in stats
        ),
        "gb_facturados_mediana": round(
            statistics.median(s["bytes_facturados"] for s in stats) / 1e9, 3
        ),
    }


def search_sql(table: str, use_index: bool) -> str:
    options = (
        ", options => '{\"fraction_lists_to_search\": 0.05}'"
        if use_index
        else ""
    )
    return f"""
    SELECT base.id AS id, distance
    FROM VECTOR_SEARCH(
      TABLE `{PROJECT}.{DATASET}.{table}`, 'embedding',
      (SELECT embedding FROM `{PROJECT}.{DATASET}.{table}` WHERE id = @q),
      top_k => {TOP_K}, distance_type => 'COSINE'{options})
    """  # noqa: S608 - tablas fijas


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embeddings", type=Path, required=True)
    ap.add_argument("--texts", type=Path, required=True)
    ap.add_argument("--families", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--keep", action="store_true", help="no borrar el dataset")
    args = ap.parse_args()
    client = bigquery.Client(project=PROJECT, location=LOCATION)
    ds = bigquery.Dataset(f"{PROJECT}.{DATASET}")
    ds.location = LOCATION
    ds.default_table_expiration_ms = 24 * 3600 * 1000
    client.create_dataset(ds, exists_ok=True)
    result: dict = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "ubicacion": LOCATION,
    }
    try:
        # Tabla real: text_id + embedding.
        emb = np.load(args.embeddings).astype(np.float64)
        ids = pq.read_table(args.texts, columns=["text_id"])[
            "text_id"
        ].to_pylist()
        table = pa.table(
            {
                "id": pa.array(ids, pa.int64()),
                "embedding": pa.array(list(emb), pa.list_(pa.float64())),
            }
        )
        buf = pa.BufferOutputStream()
        pq.write_table(table, buf)
        job = client.load_table_from_file(
            pa.BufferReader(buf.getvalue()),
            f"{PROJECT}.{DATASET}.emb_real",
            job_config=bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.PARQUET,
                parquet_options=bigquery.ParquetOptions.from_api_repr(
                    {"enableListInference": True}
                ),
            ),
        )
        job.result()
        # Tabla sintética del tamaño del corpus.
        _, synth = run(
            client,
            f"""
            CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.emb_synth` AS
            SELECT id, ARRAY(SELECT RAND() - 0.5
                             FROM UNNEST(GENERATE_ARRAY(1, {DIM}))) AS embedding
            FROM (
              -- GENERATE_ARRAY admite hasta un millón de elementos.
              SELECT a * 1000 + b + 1 AS id
              FROM UNNEST(GENERATE_ARRAY(0, {CORPUS_TEXTS // 1000})) AS a,
                   UNNEST(GENERATE_ARRAY(0, 999)) AS b
            )
            WHERE id <= {CORPUS_TEXTS}
            """,  # noqa: S608 - tablas fijas
        )
        size = client.get_table(f"{PROJECT}.{DATASET}.emb_synth").num_bytes
        result["tabla_sintetica"] = {
            "filas": CORPUS_TEXTS,
            "gb": round(size / 1e9, 3),
        }
        rng = np.random.default_rng(SEED)

        def queries(table: str, n_ids: int, use_index: bool, pool=None) -> list:
            picks = (
                rng.choice(pool, QUERIES, replace=False)
                if pool is not None
                else rng.integers(1, n_ids, QUERIES)
            )
            out = []
            for q in picks:
                rows, st = run(
                    client,
                    search_sql(table, use_index),
                    [bigquery.ScalarQueryParameter("q", "INT64", int(q))],
                )
                st["vecinos"] = [r.id for r in rows]
                st["consulta"] = int(q)
                out.append(st)
            return out

        brute = queries("emb_synth", CORPUS_TEXTS, False)
        result["sintetica_sin_indice"] = summarize(brute)
        # Índice IVF y las mismas consultas.
        start = time.perf_counter()
        run(
            client,
            f"""
            CREATE VECTOR INDEX IF NOT EXISTS idx_synth
            ON `{PROJECT}.{DATASET}.emb_synth`(embedding)
            OPTIONS(index_type = 'IVF', distance_type = 'COSINE')
            """,
        )
        status = "PENDING"
        while time.perf_counter() - start < 1800:
            rows, _ = run(
                client,
                f"""
                SELECT coverage_percentage, index_status
                FROM `{PROJECT}.{DATASET}.INFORMATION_SCHEMA.VECTOR_INDEXES`
                WHERE index_name = 'idx_synth'
                """,  # noqa: S608 - tablas fijas
            )
            if rows and rows[0].coverage_percentage == 100:
                status = rows[0].index_status
                break
            time.sleep(30)
        result["indice"] = {
            "estado": status,
            "minutos_hasta_cobertura_total": round(
                (time.perf_counter() - start) / 60, 1
            ),
        }
        if status == "ACTIVE":
            indexed = queries("emb_synth", CORPUS_TEXTS, True)
            result["sintetica_con_indice"] = summarize(indexed)
        # Tabla real: latencia y sentido de los vecinos.
        fam = pq.read_table(
            args.families, columns=["text_id", "codes"]
        ).to_pydict()
        first = {
            t: (c.split(",")[0] if c else "")
            for t, c in zip(fam["text_id"], fam["codes"], strict=True)
        }
        real = queries("emb_real", len(ids), False, pool=np.array(ids))
        same = [
            np.mean(
                [
                    first.get(v) == first.get(r["consulta"])
                    for v in r["vecinos"][1:]
                ]
            )
            for r in real
        ]
        base = np.mean(
            [
                first.get(a) == first.get(b)
                for a, b in rng.choice(ids, (2000, 2))
            ]
        )
        result["real_sin_indice"] = summarize(real) | {
            "vecinos_misma_familia": round(float(np.mean(same)), 3),
            "pares_al_azar_misma_familia": round(float(base), 3),
        }
    finally:
        if not args.keep:
            client.delete_dataset(
                f"{PROJECT}.{DATASET}", delete_contents=True, not_found_ok=True
            )
            result["dataset_borrado"] = True
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
