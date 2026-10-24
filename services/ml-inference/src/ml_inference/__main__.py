"""CLI de ``ml-inference`` (``python -m ml_inference <comando>``).

* ``delta``: el delta diario (Job ``voc-ml-inference-delta``).
* ``seed``: versiones iniciales desde las métricas de EPIC-5 (autor).
* ``load-local``: carga única del backfill de EPIC-5 desde el Mac (autor).
* ``register`` y ``promote``: ciclo de vida del modelo de sentimiento.
* ``monitor``: el Job semanal de 6.4; hasta entonces no hace nada.
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
    sub.add_parser("monitor", help="monitor semanal (6.4)")
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
    pro = sub.add_parser("promote", help="promueve una versión (o rollback)")
    pro.add_argument("--model-version", required=True)
    pro.add_argument("--actor-hash", type=_actor, required=True)
    pro.add_argument("--reason", required=True)
    return p


def _clients(settings: InferenceSettings):  # pragma: no cover - red real
    from google.cloud import bigquery, storage

    return (
        bigquery.Client(project=settings.gcp_project_id),
        storage.Client(project=settings.gcp_project_id),
    )


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    args = parser().parse_args(argv)
    now = datetime.now(UTC)
    if args.command == "monitor":
        log.info("monitor: se implementa en 6.4; no hay nada que hacer")
        return 0
    settings = InferenceSettings()  # type: ignore[call-arg]
    bigquery, storage = _clients(settings)
    from ml_inference.bq_io import StagingMergeWriter

    writer = StagingMergeWriter(bigquery, settings.dataset)
    if args.command == "delta":
        from voc_nlp.aspects import make_client

        from ml_inference.delta import Clients, run_delta

        genai = make_client(settings.gcp_project_id, settings.gemini_location)
        run = run_delta(settings, Clients(bigquery, storage, genai), now)
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
    from ml_inference.registry import promote

    promote(
        settings,
        writer,
        bigquery,
        model_version=args.model_version,
        actor_hash=args.actor_hash,
        reason=args.reason,
        now=now,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
