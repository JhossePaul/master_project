"""¿Filtrar antes de `VECTOR_SEARCH` baja lo facturado? (5.7, P8-6).

Experimento aprobado por el autor (2026-10-22). El primero
(`vector_search.py`) mostró que cada búsqueda sobre todo el corpus factura la
columna de embeddings completa (4.26 GB), con o sin índice. Aquí se mide si
reducir las filas buscadas reduce los bytes facturados.

* **Tabla sintética** del tamaño del corpus (1 383 138 textos, 384
  dimensiones), con columnas de filtro de proporciones parecidas al corpus:
  `bank_id` (BBVA 30 %, SANTANDER 24 %, AZTECA 22 %, BANORTE 19 %, NUBANK
  5 %), `is_neg` (57 %) y `mes` (2018-01 a 2026-09).
* **Dos copias:** sin agrupar y **particionada por `mes` y agrupada por
  `bank_id` e `is_neg`**.
* **Variantes:** todo el corpus; solo un banco (BBVA); solo negativas; BBVA y
  negativas; los últimos 12 meses; y una tabla física aparte con solo las
  negativas. La tabla base de `VECTOR_SEARCH` va como subconsulta con
  `WHERE`.
* **Mide** bytes procesados y facturados y latencia, con 3 consultas por
  variante y el vector de consulta como parámetro. Sin índice (el primer
  experimento mostró que el índice no cambia lo facturado).
* El dataset temporal (`voc_bench_57f`) se borra al final.

Se corre con el entorno de la raíz (tiene `google-cloud-bigquery`):

    .venv/bin/python \\
        experiments/analytics/src/voc_analytics/scale/vector_filter.py \\
        --out docs/analytics/scale/vector_filter_v0_metrics.json
"""

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from google.cloud import bigquery

PROJECT = "project-7bafd424-a385-4c05-b5b"
LOCATION = "us-central1"
DATASET = "voc_bench_57f"
ROWS = 1_383_138
DIM = 384
QUERIES = 3
TOP_K = 20
SEED = 20261022
T = f"`{PROJECT}.{DATASET}"


def run(client: bigquery.Client, sql: str, params=None) -> dict:
    config = bigquery.QueryJobConfig(
        query_parameters=params or [], use_query_cache=False
    )
    start = time.perf_counter()
    job = client.query(sql, job_config=config, location=LOCATION)
    rows = list(job.result())
    return {
        "segundos": round(time.perf_counter() - start, 2),
        "gb_procesados": round(job.total_bytes_processed / 1e9, 3),
        "gb_facturados": round(job.total_bytes_billed / 1e9, 3),
        "filas": len(rows),
    }


def base_sql() -> str:
    return f"""
    SELECT a * 1000 + b + 1 AS id
    FROM UNNEST(GENERATE_ARRAY(0, {ROWS // 1000})) AS a,
         UNNEST(GENERATE_ARRAY(0, 999)) AS b
    """  # noqa: S608 - tablas fijas


def create_sql(name: str, clustered: bool) -> str:
    layout = "PARTITION BY mes CLUSTER BY bank_id, is_neg" if clustered else ""
    return f"""
    CREATE OR REPLACE TABLE {T}.{name}` {layout} AS
    SELECT
      id,
      CASE
        WHEN r < 0.30 THEN 'BBVA' WHEN r < 0.54 THEN 'SANTANDER'
        WHEN r < 0.76 THEN 'AZTECA' WHEN r < 0.95 THEN 'BANORTE'
        ELSE 'NUBANK' END AS bank_id,
      RAND() < 0.57 AS is_neg,
      DATE_ADD(DATE '2018-01-01',
               INTERVAL CAST(FLOOR(RAND() * 105) AS INT64) MONTH) AS mes,
      ARRAY(SELECT RAND() - 0.5
            FROM UNNEST(GENERATE_ARRAY(1, {DIM}))) AS embedding
    FROM (SELECT id, RAND() AS r FROM ({base_sql()}) WHERE id <= {ROWS})
    """  # noqa: S608 - tablas fijas


def search_sql(source: str) -> str:
    return f"""
    SELECT base.id, distance
    FROM VECTOR_SEARCH(
      ({source}), 'embedding',
      (SELECT @v AS embedding),
      top_k => {TOP_K}, distance_type => 'COSINE')
    """  # noqa: S608 - tablas fijas


VARIANTS = {
    "todo_el_corpus": "SELECT * FROM {t}",
    "solo_bbva": "SELECT * FROM {t} WHERE bank_id = 'BBVA'",
    "solo_negativas": "SELECT * FROM {t} WHERE is_neg",
    "bbva_negativas": "SELECT * FROM {t} WHERE bank_id = 'BBVA' AND is_neg",
    "ultimos_12_meses": "SELECT * FROM {t} WHERE mes >= DATE '2025-10-01'",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    client = bigquery.Client(project=PROJECT, location=LOCATION)
    ds = bigquery.Dataset(f"{PROJECT}.{DATASET}")
    ds.location = LOCATION
    ds.default_table_expiration_ms = 24 * 3600 * 1000
    client.create_dataset(ds, exists_ok=True)
    rng = np.random.default_rng(SEED)
    result: dict = {
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "filas": ROWS,
    }
    try:
        run(client, create_sql("plana", False))
        run(client, create_sql("agrupada", True))
        run(
            client,
            f"CREATE OR REPLACE TABLE {T}.solo_neg` AS "  # noqa: S608
            f"SELECT * FROM {T}.agrupada` WHERE is_neg",
        )
        sizes = {
            n: round(
                client.get_table(f"{PROJECT}.{DATASET}.{n}").num_bytes / 1e9, 3
            )
            for n in ("plana", "agrupada", "solo_neg")
        }
        result["tamano_gb"] = sizes
        out: dict = {}
        cases = [
            (f"{table}|{name}", sql.format(t=f"{T}.{table}`"))
            for table in ("plana", "agrupada")
            for name, sql in VARIANTS.items()
        ] + [("tabla_solo_neg|todo", f"SELECT * FROM {T}.solo_neg`")]  # noqa: S608
        for key, source in cases:
            stats = []
            for _ in range(QUERIES):
                vec = [float(x) for x in rng.random(DIM) - 0.5]
                stats.append(
                    run(
                        client,
                        search_sql(source),
                        [bigquery.ArrayQueryParameter("v", "FLOAT64", vec)],
                    )
                )
            out[key] = {
                "latencia_mediana_s": statistics.median(
                    s["segundos"] for s in stats
                ),
                "gb_facturados": statistics.median(
                    s["gb_facturados"] for s in stats
                ),
                "busquedas_por_tib": round(
                    1099.5
                    / max(
                        statistics.median(s["gb_facturados"] for s in stats),
                        0.01,
                    )
                ),
            }
            print(key, out[key], flush=True)
        result["variantes"] = out
    finally:
        client.delete_dataset(
            f"{PROJECT}.{DATASET}", delete_contents=True, not_found_ok=True
        )
        result["dataset_borrado"] = True
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
