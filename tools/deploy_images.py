"""Despliega las imágenes de los workers fijadas por digest (solo stdlib).

Sustituye el copiar a mano los comandos `pulumi config set` del resumen del CD:

1. Lista en Artifact Registry las imágenes de `ingestion-worker`,
   `sanitization-pipeline` y `ml-inference` (EPIC-6, 6.3).
2. Elige el SHA de commit más reciente que tengan **todas** (comparten código:
   desplegar una sola dejó páginas cerradas con hueco el 2026-10-16) o el que
   se pida con `--sha`.
3. Fija sus claves de Pulumi con `<registro>/<imagen>:<sha>@<digest>`.
4. Muestra `pulumi preview`; con `--apply` ejecuta `pulumi up` solo si el
   preview no borra ni reemplaza recursos.

No hace commit: al terminar recuerda versionar `infra/Pulumi.dev.yaml`.

    uv run python tools/deploy_images.py --project P            # preview
    uv run python tools/deploy_images.py --project P --apply    # preview + up
    uv run python tools/deploy_images.py --project P --sha <40 hex>
"""

import argparse
import json
import re
import subprocess  # noqa: S404  # nosec B404 - invoca gcloud y pulumi
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

REPOSITORY = "voc-containers-repo"
# (nombre de la imagen en el registro, clave de configuración de Pulumi)
WORKERS = (
    ("ingestion-worker", "ingestion_worker_image"),
    ("sanitization-pipeline", "sanitization_job_image"),
    ("ml-inference", "ml_inference_image"),
)
CONFIG_NAMESPACE = "bbva-voc-infra"
INFRA_DIR = Path(__file__).resolve().parent.parent / "infra"
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
# Resumen del preview de Pulumi: "- 1 to delete", "+-1 to replace".
DESTRUCTIVE = re.compile(r"\b\d+ to (?:delete|replace)\b")

Run = Callable[[Sequence[str], Path | None], str]


class DeployError(RuntimeError):
    """Condición que obliga a detenerse y revisar."""


def run_command(args: Sequence[str], cwd: Path | None = None) -> str:
    # Argumentos construidos por este módulo, sin shell ni entrada externa.
    result = subprocess.run(  # noqa: S603  # nosec B603
        list(args),
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-400:]
        raise DeployError(f"{' '.join(args[:3])} falló: {detail}")
    return result.stdout


def _tags(entry: dict[str, object]) -> list[str]:
    raw = entry.get("tags") or []
    if isinstance(raw, str):
        return [t for t in raw.split(",") if t]
    return [str(t) for t in raw] if isinstance(raw, list) else []


def images_by_sha(run: Run, registry: str, name: str) -> dict[str, str]:
    """`{sha de commit: digest}` de la imagen, más reciente primero."""
    out = run(
        [
            "gcloud",
            "artifacts",
            "docker",
            "images",
            "list",
            f"{registry}/{name}",
            "--include-tags",
            "--sort-by=~CREATE_TIME",
            "--format=json",
        ],
        None,
    )
    found: dict[str, str] = {}
    for entry in json.loads(out or "[]"):
        digest = str(entry.get("version", ""))
        if not DIGEST.match(digest):
            continue
        for tag in _tags(entry):
            if SHA.match(tag):
                found.setdefault(tag, digest)
    return found


def choose_sha(per_image: dict[str, dict[str, str]], wanted: str | None) -> str:
    """El SHA que existe en todas las imágenes (el más reciente o el pedido)."""
    names = list(per_image)
    if wanted is not None:
        if not SHA.match(wanted):
            raise DeployError("--sha debe ser un SHA de commit de 40 hex")
        missing = [n for n in names if wanted not in per_image[n]]
        if missing:
            raise DeployError(
                f"el SHA {wanted[:12]} no existe en: {', '.join(missing)}"
            )
        return wanted
    # Orden de la primera imagen (más reciente primero) filtrado por las demás.
    for sha in per_image[names[0]]:
        if all(sha in per_image[n] for n in names[1:]):
            return sha
    raise DeployError(
        "ninguna versión está construida en las dos imágenes; espera al CD"
    )


def deploy(
    *,
    project: str,
    region: str,
    stack: str,
    sha: str | None,
    apply: bool,
    run: Run = run_command,
    out: Callable[[str], None] = print,
    infra_dir: Path = INFRA_DIR,
) -> int:
    registry = f"{region}-docker.pkg.dev/{project}/{REPOSITORY}"
    per_image = {n: images_by_sha(run, registry, n) for n, _ in WORKERS}
    chosen = choose_sha(per_image, sha)
    refs = {
        key: f"{registry}/{name}:{chosen}@{per_image[name][chosen]}"
        for name, key in WORKERS
    }
    out(f"Versión: {chosen}")
    changed = False
    for key, ref in refs.items():
        current = _current(run, infra_dir, stack, key)
        state = "sin cambio" if current == ref else "actualiza"
        changed = changed or current != ref
        out(f"  {key}: {state}")
        if current != ref:
            run(
                [
                    "pulumi",
                    "config",
                    "set",
                    "--stack",
                    stack,
                    f"{CONFIG_NAMESPACE}:{key}",
                    ref,
                ],
                infra_dir,
            )
    preview = run(
        ["pulumi", "preview", "--stack", stack, "--non-interactive", "--diff"],
        infra_dir,
    )
    out(preview.strip())
    if (
        not changed
        and "to update" not in preview
        and "to create" not in preview
    ):
        out("Nada que desplegar: las imágenes ya están fijadas.")
        return 0
    if not apply:
        out("Preview terminado. Repite con --apply para ejecutar `pulumi up`.")
        _reminder(out, chosen)
        return 0
    if DESTRUCTIVE.search(preview):
        raise DeployError(
            "el preview borra o reemplaza recursos: revísalo y aplica a mano"
        )
    out(
        run(
            ["pulumi", "up", "--stack", stack, "--yes", "--non-interactive"],
            infra_dir,
        ).strip()
    )
    _reminder(out, chosen)
    return 0


def _current(run: Run, infra_dir: Path, stack: str, key: str) -> str:
    try:
        return run(
            [
                "pulumi",
                "config",
                "get",
                "--stack",
                stack,
                f"{CONFIG_NAMESPACE}:{key}",
            ],
            infra_dir,
        ).strip()
    except DeployError:
        return ""


def _reminder(out: Callable[[str], None], sha: str) -> None:
    out(
        "Falta versionar la configuración:\n"
        "  git add infra/Pulumi.dev.yaml && "
        f'git commit -m "Actualiza las imágenes desplegadas a {sha[:7]}"'
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project")
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--stack", default="dev")
    parser.add_argument("--sha", help="SHA de commit (por defecto, el último)")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="ejecuta `pulumi up` tras el preview",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        project = (
            args.project
            or run_command(
                ["gcloud", "config", "get-value", "project"], None
            ).strip()
        )
        if not project:
            raise DeployError("indica --project")
        return deploy(
            project=project,
            region=args.region,
            stack=args.stack,
            sha=args.sha,
            apply=args.apply,
        )
    except DeployError as error:
        print(f"DETENIDO: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
