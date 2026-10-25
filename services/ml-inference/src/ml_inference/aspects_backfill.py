"""Familias del histórico con el prompt vigente, solo con el costo aprobado.

Corre en el Job ``voc-ml-aspects-backfill`` (comando ``aspects-backfill``).
El delta no re-etiqueta el histórico cuando cambia el prompt: las familias
quedan con el prompt con el que se etiquetaron. Este comando es para cuando
el autor decide pagar un prompt nuevo (en el backfill de los experimentos,
$60.61 por 659 316 textos).

* **Sin** ``--approve``: cuenta los textos únicos de las negativas de dos
  palabras o más sin fila para el ``prompt_version`` vigente y escribe en el
  log el costo estimado con ``gemini_usd_per_1000``. No llama a Gemini ni
  escribe nada.
* **Con** ``--approve --max-usd <tope>``: etiqueta como el delta (lotes de
  ``aspects_batch_size`` textos, reintento en lotes más chicos) y escribe
  después de cada página. Antes de cada lote compara el costo medido más el
  de un lote (el promedio medido, o el estimado antes del primero) con el
  tope, y se detiene si lo pasaría. Una corrida
  interrumpida o detenida se retoma sin repetir lo hecho: lo pendiente es lo
  que no tiene fila con el prompt vigente. Registra una fila en
  ``inference_runs`` (``kind = aspect_backfill``) con su costo.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from voc_common.analytics_codes import RunEnvironment, RunKind, RunStatus
from voc_common.operations_v3 import InferenceRun
from voc_common.predictions_v3 import ReviewAspects

from ml_inference.bq_io import StagingMergeWriter, query_rows, render
from ml_inference.config import InferenceSettings
from ml_inference.delta import peak_memory_mib
from ml_inference.runs import write_run

log = logging.getLogger(__name__)

PAGE_TEXTS: Final = 5_000

# Negativas de dos palabras o más sin fila para el prompt vigente.
_PENDING: Final = """
  SELECT p.id_resena, p.bank_id, p.text_key, p.fecha, p.model_version
  FROM `${ds}.review_predictions_current` AS p
  LEFT JOIN `${ds}.review_aspects` AS a
    ON a.id_resena = p.id_resena AND a.text_key = p.text_key
    AND a.prompt_version = @prompt
  WHERE p.sentiment = 'NEG' AND p.palabras >= 2 AND a.id_resena IS NULL
"""

# ``@@pending@@`` se reemplaza por ``_PENDING``, una constante: los valores
# van siempre como parámetros.
_COUNT_TEMPLATE: Final = """
-- Textos sin familias del prompt vigente
WITH pending AS (@@pending@@)
SELECT COUNT(DISTINCT text_key) AS texts FROM pending
"""
COUNT_SQL: Final = _COUNT_TEMPLATE.replace("@@pending@@", _PENDING)

# Una página de textos, en orden de ``text_key`` desde ``@after``, con todas
# sus reseñas pendientes.
_PAGE_TEMPLATE: Final = """
-- Página de textos sin familias del prompt vigente
WITH pending AS (@@pending@@),
keys AS (
  SELECT DISTINCT text_key FROM pending
  WHERE text_key > @after ORDER BY text_key LIMIT @limit
)
SELECT p.id_resena, p.bank_id, p.text_key, p.fecha, p.model_version,
  t.texto_sanitizado
FROM pending AS p
JOIN keys USING (text_key)
JOIN `${tds}` AS t
  ON t.id_resena = p.id_resena
  AND TO_HEX(SHA256(t.texto_sanitizado)) = p.text_key
ORDER BY p.text_key
"""
PAGE_SQL: Final = _PAGE_TEMPLATE.replace("@@pending@@", _PENDING)


@dataclass(frozen=True)
class Estimate:
    prompt_version: str
    texts: int
    usd: float


def estimate(settings: InferenceSettings, bigquery: Any) -> Estimate:
    """Textos pendientes y costo estimado; no llama a Gemini."""
    from voc_nlp.aspects import PROMPT_VERSION

    sql = render(COUNT_SQL, ds=settings.dataset)
    texts = int(
        query_rows(bigquery, sql, {"prompt": PROMPT_VERSION})[0]["texts"]
    )
    found = Estimate(
        PROMPT_VERSION, texts, texts / 1000 * settings.gemini_usd_per_1000
    )
    log.info(
        "aspects-backfill: %d textos sin familias de %s, costo estimado "
        "$%.2f; para etiquetarlos: --approve --max-usd <tope>",
        found.texts,
        found.prompt_version,
        found.usd,
    )
    return found


def run_aspects_backfill(
    settings: InferenceSettings,
    bigquery: Any,
    genai: Any,
    max_usd: float,
    now: datetime,
    *,
    run_id: str | None = None,
) -> InferenceRun:
    """Etiqueta lo pendiente hasta ``max_usd`` y registra la corrida."""
    from voc_nlp import aspects as gemini

    if max_usd <= 0:
        raise ValueError("max_usd must be positive")
    run_id = run_id or f"aspects-backfill-{now:%Y%m%dT%H%M%S}"
    writer = StagingMergeWriter(bigquery, settings.dataset)
    sql = render(PAGE_SQL, ds=settings.dataset, tds=settings.tds_table)
    usage = gemini.Usage()
    prompt = gemini.load_prompt()
    size = settings.aspects_batch_size
    batch_usd = size / 1000 * settings.gemini_usd_per_1000
    reviews = texts = batches = 0
    status = RunStatus.FAILED
    capped = False
    try:
        after = ""
        while not capped:
            page = query_rows(
                bigquery,
                sql,
                {
                    "prompt": gemini.PROMPT_VERSION,
                    "after": after,
                    "limit": PAGE_TEXTS,
                },
            )
            if not page:
                break
            after = page[-1]["text_key"]
            unique = {r["text_key"]: r["texto_sanitizado"] for r in page}
            items = sorted(unique.items())
            labels: dict[str, gemini.AspectLabel] = {}
            for start in range(0, len(items), size):
                per_batch = usage.cost_usd / batches if batches else batch_usd
                if usage.cost_usd + per_batch > max_usd:
                    capped = True
                    break
                batches += 1
                for label in gemini.label_batch(
                    genai,
                    items[start : start + size],
                    prompt,
                    settings.gemini_model,
                    usage=usage,
                ):
                    labels[label.key] = label
            rows = [
                ReviewAspects(
                    id_resena=r["id_resena"],
                    bank_id=r["bank_id"],
                    text_key=r["text_key"],
                    fecha=r["fecha"],
                    families=list(labels[r["text_key"]].families),
                    flag_update=labels[r["text_key"]].flag_update,
                    flag_security=labels[r["text_key"]].flag_security,
                    praise=labels[r["text_key"]].praise,
                    prompt_version=gemini.PROMPT_VERSION,
                    llm_model=settings.gemini_model,
                    guideline_version=gemini.GUIDELINE_VERSION,
                    sentiment_model_version=r["model_version"],
                    run_id=run_id,
                    labeled_at=now,
                )
                for r in page
                if r["text_key"] in labels
            ]
            reviews += writer.write(
                "review_aspects",
                rows,
                ["id_resena", "text_key", "prompt_version"],
                run_id,
            )
            texts += len(labels)
            log.info(
                "aspects-backfill: %d textos, $%.4f medidos",
                texts,
                usage.cost_usd,
            )
        if capped:
            log.warning(
                "aspects-backfill: detenido en $%.4f por el tope de $%.2f; "
                "otra corrida retoma lo pendiente",
                usage.cost_usd,
                max_usd,
            )
        status = RunStatus.SUCCEEDED
    finally:
        run = InferenceRun(
            run_id=run_id,
            kind=RunKind.ASPECT_BACKFILL,
            environment=RunEnvironment.CLOUDRUN,
            model_version=None,
            started_at=now,
            ended_at=max(datetime.now(UTC), now),
            reviews=reviews,
            texts=texts,
            status=status,
            cost_usd=round(usage.cost_usd, 6),
            peak_memory_mib=peak_memory_mib(),
        )
        write_run(writer, run)
    return run
