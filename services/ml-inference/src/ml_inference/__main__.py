"""CLI de ``ml-inference`` (``python -m ml_inference <comando>``).

* ``delta``: el delta diario (Job ``voc-ml-inference-delta``).
* ``seed``: versiones iniciales desde las métricas de los experimentos (autor).
* ``load-local``: carga única del backfill histórico desde el Mac (autor).
* ``register`` y ``promote``: ciclo de vida del modelo de sentimiento.
  ``promote`` evalúa la regla de promoción, recalcula la curva y propone la
  ``risk_policy`` del modelo nuevo; el candidato ya debe estar re-predicho.
* ``curve``: recalcula la curva de cobertura y riesgo de una versión.
* ``risk-policy``: nueva versión de la ``risk_policy`` con otra cobertura.
* ``topics-refit``: re-ajuste trimestral del modelo de tópicos (Job
  ``voc-ml-topics-refit``); la versión nueva asigna cuando se cura.
* ``topics-backfill``: re-asigna el histórico a la versión de tópicos
  vigente (Job ``voc-ml-topics-backfill``, lo lanza el delta).
* ``aspects-backfill``: familias del histórico con el prompt vigente (Job
  ``voc-ml-aspects-backfill``); sin ``--approve`` solo estima el costo.
* ``train``: reentrena el modelo de sentimiento en la GPU de Kaggle (Job
  ``voc-ml-training``) y registra un candidato; no lo promueve.
* ``upload-gold-ids``: sube una vez, desde la máquina del autor, los ids del
  oro que el entrenamiento excluye.
* ``drift-rates``: meses de alerta al año por serie y banco contra la línea
  base histórica (solo lee ``drift_metrics``).
* ``rescore``: predice todo el corpus con una versión candidata en la GPU
  de Kaggle (Job ``voc-ml-rescoring``), antes de promoverla.
* ``monitor``: el Job semanal (por ahora, deriva, cierre de subidas,
  muestras humanas, calidad y KPI).
* ``build-vocab``: sube una vez el vocabulario de entrenamiento.
"""

import argparse
import logging
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from ml_inference.config import InferenceSettings

log = logging.getLogger("ml_inference")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _actor(value: str) -> str:
    if not _SHA256.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "actor hash must be a SHA-256 hex digest"
        )
    return value


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ml_inference")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("delta", help="delta diario")
    sub.add_parser("monitor", help="monitor semanal")
    seed = sub.add_parser("seed", help="versiones iniciales")
    seed.add_argument("--actor-hash", type=_actor, required=True)
    seed.add_argument("--reason", required=True)
    seed.add_argument("--docs", type=Path, default=Path("docs/analytics"))
    load = sub.add_parser("load-local", help="carga única del backfill")
    load.add_argument("--actor-hash", type=_actor, required=True)
    load.add_argument(
        "--data", type=Path, default=Path("experiments/analytics/data")
    )
    load.add_argument("--work", type=Path, required=True)
    load.add_argument("--minilm", type=Path, default=None)
    reg = sub.add_parser("register", help="registra una versión candidata")
    reg.add_argument("--weights-uri", required=True)
    reg.add_argument("--model-version", required=True)
    reg.add_argument("--calibration-version", required=True)
    reg.add_argument("--calibration-t", type=float, required=True)
    reg.add_argument("--curve-json", type=Path, required=True)
    reg.add_argument("--serving-image", required=True)
    reg.add_argument("--base-checkpoint", required=True)
    reg.add_argument("--training-data", required=True)
    reg.add_argument("--license", required=True)
    reg.add_argument("--kappa-dev", type=float)
    reg.add_argument("--ece-dev", type=float)
    reg.add_argument("--aurc-dev", type=float)
    voc = sub.add_parser(
        "build-vocab", help="sube el vocabulario de entrenamiento"
    )
    voc.add_argument("--model-version", default=None)
    pro = sub.add_parser("promote", help="promueve una versión (o rollback)")
    pro.add_argument("--model-version", required=True)
    pro.add_argument("--actor-hash", type=_actor, required=True)
    pro.add_argument("--reason", required=True)
    pro.add_argument(
        "--force",
        action="store_true",
        help="promueve aunque el candidato sea significativamente peor",
    )
    sub.add_parser("drift-rates", help="tasas de alerta contra la línea base")
    top = sub.add_parser("topics-refit", help="re-ajuste de tópicos")
    top.add_argument(
        "--force", action="store_true", help="ajusta aunque no toque"
    )
    sub.add_parser("topics-backfill", help="re-asigna el histórico de tópicos")
    asp = sub.add_parser(
        "aspects-backfill", help="familias del histórico con costo aprobado"
    )
    asp.add_argument(
        "--approve", action="store_true", help="llama a Gemini (cuesta)"
    )
    asp.add_argument(
        "--max-usd", type=float, default=None, help="tope de costo en USD"
    )
    trn = sub.add_parser("train", help="reentrena y registra un candidato")
    trn.add_argument("--run", default=None, help="por defecto, la fecha y hora")
    trn.add_argument("--actor-hash", type=_actor, default=None)
    trn.add_argument("--reason", default=None)
    gold = sub.add_parser("upload-gold-ids", help="sube los ids del oro")
    gold.add_argument(
        "--labels",
        type=Path,
        default=Path("experiments/analytics/data/labels"),
    )
    res = sub.add_parser("rescore", help="re-predice con una candidata")
    res.add_argument("--model-version", required=True)
    res.add_argument("--run", default=None, help="por defecto, la fecha y hora")
    res.add_argument("--actor-hash", type=_actor, default=None)
    res.add_argument("--reason", default=None)
    cur = sub.add_parser("curve", help="recalcula la curva de una versión")
    cur.add_argument("--model-version", default=None)
    pol = sub.add_parser("risk-policy", help="cambia la cobertura objetivo")
    pol.add_argument("--coverage", type=float, required=True)
    pol.add_argument("--actor-hash", type=_actor, required=True)
    pol.add_argument("--reason", required=True)
    return p


def _clients(settings: InferenceSettings):  # pragma: no cover - red real
    from google.cloud import bigquery, storage

    return (
        bigquery.Client(project=settings.gcp_project_id),
        storage.Client(project=settings.gcp_project_id),
    )


def _publisher(
    settings: InferenceSettings, topic_name: str
):  # pragma: no cover - red real
    from google.cloud import pubsub_v1

    client = pubsub_v1.PublisherClient()
    topic = client.topic_path(settings.gcp_project_id, topic_name)

    def publish(message) -> None:
        data = message.model_dump_json().encode("utf-8")
        client.publish(topic, data).result(timeout=60)

    return publish


def _family_labeler(settings: InferenceSettings):  # pragma: no cover - red
    """Familias con Gemini (``aspects_v2_1``) para ``families_validation``."""
    from voc_nlp import aspects

    client = aspects.make_client(
        settings.gcp_project_id, settings.gemini_location
    )
    prompt = aspects.load_prompt()

    def label(items):
        return {
            got.key: frozenset(f.value for f in got.families)
            for got in aspects.label_batch(
                client, items, prompt, settings.gemini_model
            )
        }

    return label


def _sentiment_labeler(settings: InferenceSettings):  # pragma: no cover
    """Sentimiento con Gemini y el prompt de la plata (``gemini_agreement``)."""
    from voc_nlp import aspects, sentiment_gemini

    client = aspects.make_client(
        settings.gcp_project_id, settings.gemini_location
    )
    prompt = sentiment_gemini.load_prompt()

    def label(items):
        return {
            got.key: got.label
            for got in sentiment_gemini.label_texts(
                client, items, prompt, settings.gemini_model
            )
        }

    return label


def _monitor_state(settings: InferenceSettings, bigquery, storage):
    """Estado de servicio y vocabulario del modelo promovido.

    Sin modelo promovido no hay muestras ni vocabulario; sin vocabulario,
    la deriva omite ``out_of_vocabulary_share``.
    """
    from ml_inference.state import NoPromotedModel, load_state
    from ml_inference.vocab import load_vocab

    try:
        state = load_state(bigquery, settings.dataset)
    except NoPromotedModel as exc:
        log.warning("monitor: %s", exc)
        return None, None
    try:
        vocab = load_vocab(settings, storage, state.model.model_version)
    except FileNotFoundError as exc:
        log.warning("monitor: %s", exc)
        vocab = None
    return state, vocab


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    p = parser()
    args = p.parse_args(argv)
    if args.command == "aspects-backfill" and args.approve:
        if args.max_usd is None or args.max_usd <= 0:
            p.error("--approve needs --max-usd > 0")
    now = datetime.now(UTC)
    settings = InferenceSettings()  # type: ignore[call-arg]
    bigquery, storage = _clients(settings)
    from ml_inference.bq_io import StagingMergeWriter

    writer = StagingMergeWriter(bigquery, settings.dataset)
    if args.command == "monitor":
        from ml_inference.jobs import CloudRunJobs
        from ml_inference.monitor.drift_job import (
            BqDriftSource,
            MonitorClients,
            close_boosts,
            run_drift,
        )
        from ml_inference.monitor.kpis import KpiJob
        from ml_inference.monitor.quality import QualityJob
        from ml_inference.monitor.samples import SampleJob

        state, vocab = _monitor_state(settings, bigquery, storage)
        run_id = f"monitor_{now:%Y%m%dT%H%M%S}"
        clients = MonitorClients(
            BqDriftSource(
                bigquery, settings.dataset, settings.tds_table, vocab
            ),
            writer,
            _publisher(settings, settings.drift_topic),
            run_id,
        )
        close_boosts(clients, now)
        run_drift(settings, clients, now)
        if state is not None:
            SampleJob(bigquery, writer, settings.dataset, run_id).run(
                state.policy, state.model.model_version, now
            )
            QualityJob(
                bigquery,
                writer,
                settings.dataset,
                settings.tds_table,
                _publisher(settings, settings.quality_topic),
                run_id,
                family_labeler=_family_labeler(settings),
                sentiment_labeler=_sentiment_labeler(settings),
                llm_model=settings.gemini_model,
                jobs=CloudRunJobs(settings.gcp_project_id, settings.gcp_region),
                training_job=settings.training_job,
                gold_version=settings.gold_version,
            ).run(state.policy, state.model.model_version, now)
            KpiJob(bigquery, writer, settings.dataset, run_id).run(
                state.model.model_version, now
            )
        return 0
    if args.command == "build-vocab":
        from ml_inference.seed import MODEL_VERSION
        from ml_inference.vocab import build_vocab

        words, digest = build_vocab(
            settings, storage, args.model_version or MODEL_VERSION
        )
        log.info("build-vocab: %d palabras, sha256 %s", words, digest)
        return 0
    if args.command == "delta":
        from voc_nlp.aspects import make_client

        from ml_inference.delta import Clients, run_delta
        from ml_inference.jobs import CloudRunJobs

        genai = make_client(settings.gcp_project_id, settings.gemini_location)
        jobs = CloudRunJobs(settings.gcp_project_id, settings.gcp_region)
        run = run_delta(
            settings, Clients(bigquery, storage, genai, jobs=jobs), now
        )
        return 0 if run.status.value == "succeeded" else 1
    if args.command == "seed":
        from ml_inference.seed import seed

        log.info(
            "seed: %s",
            seed(
                settings, writer, args.docs, args.actor_hash, args.reason, now
            ),
        )
        return 0
    if args.command == "load-local":
        from ml_inference.load_local import LocalBackfill, load_backfill

        minilm = args.minilm or args.work / "minilm"
        if not minilm.exists():
            from voc_nlp.topics import EMBEDDING_MODEL, load_embedder

            load_embedder(EMBEDDING_MODEL).save(str(minilm))
        args.work.mkdir(parents=True, exist_ok=True)
        files = LocalBackfill.from_data_dir(args.data, minilm)
        load_backfill(
            settings, bigquery, storage, files, args.work, args.actor_hash, now
        )
        return 0
    if args.command == "register":
        from voc_common.policies import HitlCoverageCurve

        from ml_inference.registry import register

        curve = HitlCoverageCurve.model_validate_json(
            args.curve_json.read_text()
        )
        metrics = {
            k: v
            for k, v in {
                "kappa_dev": args.kappa_dev,
                "ece_dev": args.ece_dev,
                "aurc_dev": args.aurc_dev,
            }.items()
            if v is not None
        }
        register(
            settings,
            writer,
            weights_uri=args.weights_uri,
            model_version=args.model_version,
            calibration_version=args.calibration_version,
            calibration_t=args.calibration_t,
            curve=curve,
            metrics=metrics,
            serving_image=args.serving_image,
            base_checkpoint=args.base_checkpoint,
            training_data=args.training_data,
            license_name=args.license,
            now=now,
        )
        return 0
    if args.command == "drift-rates":
        from ml_inference.monitor.drift_rates import report

        found = report(bigquery, settings.dataset)
        for rate in found:
            log.info(
                "%-24s %-10s %5.2f meses/año (referencia %s, %d meses) %s",
                rate.series,
                rate.bank_id,
                rate.per_year,
                "—" if rate.reference is None else f"{rate.reference:.1f}",
                rate.months,
                "ok" if rate.ok else "FUERA",
            )
        return 0 if found and all(rate.ok for rate in found) else 1
    if args.command == "topics-refit":
        from ml_inference.state import load_state
        from ml_inference.topics_refit import TopicsRefit

        state = load_state(bigquery, settings.dataset)
        TopicsRefit(settings, bigquery, storage, writer).run(
            state.policy, state.topic_model_version, now, force=args.force
        )
        return 0
    if args.command == "topics-backfill":
        from ml_inference.state import load_state
        from ml_inference.topics_backfill import run_topics_backfill

        version = load_state(bigquery, settings.dataset).topic_model_version
        if version is None:
            log.warning("topics-backfill: no hay versión de tópicos vigente")
            return 0
        row = run_topics_backfill(settings, bigquery, storage, version, now)
        return 0 if row.status.value == "succeeded" else 1
    if args.command == "aspects-backfill":
        from ml_inference.aspects_backfill import (
            estimate,
            run_aspects_backfill,
        )

        estimate(settings, bigquery)
        if not args.approve:
            return 0
        from voc_nlp.aspects import make_client

        genai = make_client(settings.gcp_project_id, settings.gemini_location)
        row = run_aspects_backfill(settings, bigquery, genai, args.max_usd, now)
        return 0 if row.status.value == "succeeded" else 1
    if args.command == "train":
        from voc_nlp.aspects import make_client

        from ml_inference.jobs import CloudRunJobs
        from ml_inference.registry import latest_versions
        from ml_inference.rescore import KaggleApiClient
        from ml_inference.state import load_state
        from ml_inference.training import new_training, run_training

        job = new_training(
            settings,
            bigquery,
            storage,
            KaggleApiClient(),
            make_client(settings.gcp_project_id, settings.gemini_location),
            args.run or f"{now:%Y%m%d%H%M}",
            latest_versions(bigquery, settings.dataset),
            load_state(bigquery, settings.dataset).policy,
            CloudRunJobs(settings.gcp_project_id, settings.gcp_region),
        )
        job.actor_hash, job.reason = args.actor_hash, args.reason
        row = run_training(
            job,
            writer,
            settings.training_kernel_timeout_sec,
            lambda: datetime.now(UTC),
        )
        return 0 if row.status.value == "succeeded" else 1
    if args.command == "upload-gold-ids":
        from ml_inference.load_local import upload_gold_ids

        log.info(
            "upload-gold-ids: %d reseñas",
            upload_gold_ids(settings, storage, args.labels),
        )
        return 0
    if args.command == "rescore":
        from ml_inference.registry import latest_versions
        from ml_inference.rescore import (
            KaggleApiClient,
            new_rescoring,
            run_rescore,
        )

        job = new_rescoring(
            settings,
            bigquery,
            storage,
            KaggleApiClient(),
            args.model_version,
            args.run or f"{now:%Y%m%d%H%M}",
            latest_versions(bigquery, settings.dataset),
        )
        job.actor_hash, job.reason = args.actor_hash, args.reason
        row = run_rescore(
            job,
            writer,
            settings.rescore_kernel_timeout_sec,
            lambda: datetime.now(UTC),
        )
        return 0 if row.status.value == "succeeded" else 1
    from ml_inference.lifecycle import Lifecycle, promote_version
    from ml_inference.registry import latest_versions, resolve

    lifecycle = Lifecycle(
        bigquery, writer, settings.dataset, settings.gold_version
    )
    if args.command == "curve":
        model = (
            latest_versions(bigquery, settings.dataset)[args.model_version]
            if args.model_version
            else resolve(bigquery, settings)
        )
        lifecycle.recompute_curve(model, now)
        return 0
    if args.command == "risk-policy":
        policy = lifecycle.set_coverage(
            resolve(bigquery, settings),
            args.coverage,
            args.actor_hash,
            args.reason,
            now,
        )
        log.info(
            "risk-policy: %s, umbral %.4f",
            policy.policy_version,
            policy.hitl_threshold,
        )
        return 0
    promote_version(
        settings,
        lifecycle,
        model_version=args.model_version,
        actor_hash=args.actor_hash,
        reason=args.reason,
        now=now,
        force=args.force,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
