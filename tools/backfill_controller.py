"""Controladores operativos del full histórico (solo biblioteca estándar).

Dos comandos que automatizan lo que a mano son decenas de ejecuciones:

* `drain`: lanza `voc-sanitization-job` en bucle hasta vaciar Pub/Sub.
* `ingest`: lanza el histórico de un banco (`FULL_BACKFILL`) y lo reanuda
  cuando una ejecución termina por presupuesto, hasta cerrar el plan.

Ambos usan `gcloud` con las credenciales de quien los ejecuta, leen el informe
de cada ejecución en Cloud Logging (eventos estructurados) y se detienen ante
cualquier señal que no sea un avance normal, en lugar de insistir.

    uv run python tools/backfill_controller.py drain --project P
    uv run python tools/backfill_controller.py ingest \
        --project P --bank BBVA --yes
"""

import argparse
import json
import subprocess  # noqa: S404  # nosec B404 - invoca gcloud
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

SANITIZATION_JOB = "voc-sanitization-job"
HISTORY_JOB = "voc-ingestion-history-job"
INGESTION_SERVICE = "voc-ingestion-worker"

# Estados de `ExtractionStatus` (runner de la ingesta).
DONE_STATUSES = frozenset({"SOURCE_EXHAUSTED_OBSERVED", "TARGET_REACHED"})
RESUME_STATUSES = frozenset(
    {"BUDGET_EXHAUSTED", "PAUSED_BACKLOG", "PUBLICATION_INCOMPLETE"}
)
COOLDOWN_STATUSES = frozenset({"PARTIAL_RATE_LIMITED"})
# Cualquier otro estado (BLOCKED, PROTOCOL_ERROR, TRANSPORT_ERROR,
# RECOVERY_REQUIRED, LEASE_CONFLICT) exige revisar a mano.

Gcloud = Callable[[Sequence[str]], str]
HttpPost = Callable[[str, dict[str, Any], str], tuple[int, dict[str, Any]]]


class ControllerError(RuntimeError):
    """Condición que obliga a detenerse y revisar."""


# ---------------------------------------------------------------- gcloud
def run_gcloud(args: Sequence[str]) -> str:
    # Argumentos construidos por este módulo, sin shell ni entrada externa.
    result = subprocess.run(  # noqa: S603  # nosec B603 B607
        ["gcloud", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ControllerError(
            f"gcloud {' '.join(args[:3])} falló: {result.stderr.strip()[:300]}"
        )
    return result.stdout


def http_post(
    url: str, body: dict[str, Any], token: str
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(  # noqa: S310
        url,
        data=json.dumps(body).encode(),
        headers={
            **({"Authorization": f"Bearer {token}"} if token else {}),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        # URL https del servicio propio, obtenida de `gcloud run services`.
        with urllib.request.urlopen(  # noqa: S310  # nosec B310
            request, timeout=120
        ) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read() or b"{}")
        except ValueError:
            payload = {}
        return error.code, payload


# ------------------------------------------------------------- decisiones
@dataclass(frozen=True)
class DrainReport:
    stop_reason: str
    messages: int
    tds_committed: int
    already_processed: int
    elapsed_sec: float
    retryable: int
    transient_failure: bool

    @classmethod
    def from_log(cls, payload: dict[str, Any]) -> "DrainReport":
        return cls(
            stop_reason=str(payload.get("stop_reason", "")),
            messages=int(payload.get("messages", 0)),
            tds_committed=int(payload.get("tds_committed", 0)),
            already_processed=int(payload.get("already_processed", 0)),
            elapsed_sec=float(payload.get("elapsed_sec", 0.0)),
            retryable=int(payload.get("events_retryable", 0)),
            transient_failure=bool(payload.get("transient_failure", False)),
        )

    @property
    def progressed(self) -> bool:
        return (self.tds_committed + self.already_processed) > 0


def drain_action(report: DrainReport, stalled_runs: int) -> str:
    """`done`, `continue` o `stop` tras una ejecución de sanitización.

    `stalled_runs` cuenta las ejecuciones seguidas sin avance, incluida esta.
    """
    if report.stop_reason == "drained" or report.messages == 0:
        return "done"
    if report.progressed:
        return "continue"
    # Había mensajes y ninguno avanzó: un tropiezo se tolera, dos no.
    return "stop" if stalled_runs >= 2 else "continue"


def ingest_action(status: str) -> str:
    """`done`, `resume`, `cooldown` o `stop` según el estado de la corrida."""
    if status in DONE_STATUSES:
        return "done"
    if status in RESUME_STATUSES:
        return "resume"
    if status in COOLDOWN_STATUSES:
        return "cooldown"
    return "stop"


# ------------------------------------------------------------ utilidades
class Controller:
    def __init__(
        self,
        *,
        project: str,
        region: str,
        gcloud: Gcloud = run_gcloud,
        post: HttpPost = http_post,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        out: Callable[[str], None] = print,
        service_url: str | None = None,
        impersonate: str | None = None,
    ) -> None:
        self.project = project
        self.region = region
        self.gcloud = gcloud
        self.post = post
        self.sleep = sleep
        self.monotonic = monotonic
        self.out = out
        # Con `gcloud run services proxy` el proxy local ya autentica.
        self.service_url_override = service_url
        # Cuenta de servicio con la que se firma el token (necesita
        # roles/iam.serviceAccountTokenCreator para quien ejecuta).
        self.impersonate = impersonate

    # --- Cloud Run
    def execute_job(self, job: str, args: str | None = None) -> str:
        command = [
            "run",
            "jobs",
            "execute",
            job,
            "--region",
            self.region,
            "--project",
            self.project,
            "--async",
            "--format=value(metadata.name)",
        ]
        if args:
            command.append(f"--args={args}")
        return self.gcloud(command).strip().rsplit("/", 1)[-1]

    def wait_execution(
        self,
        execution: str,
        *,
        timeout_sec: float = 2700.0,
        poll_sec: float = 15.0,
    ) -> bool:
        """Espera a que termine; devuelve True si tuvo éxito."""
        started = self.monotonic()
        while True:
            described = json.loads(
                self.gcloud(
                    [
                        "run",
                        "jobs",
                        "executions",
                        "describe",
                        execution,
                        "--region",
                        self.region,
                        "--project",
                        self.project,
                        "--format=json",
                    ]
                )
            )
            status = described.get("status", {})
            if status.get("completionTime"):
                return int(status.get("succeededCount", 0)) > 0
            if self.monotonic() - started > timeout_sec:
                raise ControllerError(
                    f"{execution} no terminó en {timeout_sec:.0f} s"
                )
            self.sleep(poll_sec)

    def final_event(
        self,
        job: str,
        execution: str,
        message: str,
        extra_filter: str = "",
        *,
        wait_sec: float = 120.0,
    ) -> dict[str, Any]:
        """Lee el evento final de una ejecución (los logs tardan en llegar)."""
        query = (
            'resource.type="cloud_run_job" '
            f'AND resource.labels.job_name="{job}" '
            f'AND labels."run.googleapis.com/execution_name"="{execution}" '
            f'AND jsonPayload.message="{message}"{extra_filter}'
        )
        started = self.monotonic()
        while True:
            rows = json.loads(
                self.gcloud(
                    [
                        "logging",
                        "read",
                        query,
                        "--project",
                        self.project,
                        "--limit=1",
                        "--format=json",
                    ]
                )
                or "[]"
            )
            if rows:
                return rows[0].get("jsonPayload", {})
            if self.monotonic() - started > wait_sec:
                raise ControllerError(f"sin evento «{message}» de {execution}")
            self.sleep(10.0)

    # --- drenado de sanitización
    def drain(
        self,
        *,
        max_executions: int = 100,
        job_args: str | None = None,
        pause_sec: float = 5.0,
    ) -> int:
        stalled = 0
        total = 0
        for number in range(1, max_executions + 1):
            execution = self.execute_job(SANITIZATION_JOB, job_args)
            ok = self.wait_execution(execution)
            if not ok:
                raise ControllerError(
                    f"{execution} falló: revisar sus logs antes de repetir"
                )
            report = DrainReport.from_log(
                self.final_event(
                    SANITIZATION_JOB, execution, "Sanitization run finished"
                )
            )
            rate = (
                report.messages / report.elapsed_sec
                if report.elapsed_sec
                else 0.0
            )
            total += report.tds_committed
            self.out(
                f"[{number}] {execution}: {report.messages} mensajes, "
                f"{report.tds_committed} nuevos, {report.already_processed} ya "
                f"procesados, {rate:.1f} msg/s, parada={report.stop_reason}"
            )
            stalled = 0 if report.progressed else stalled + 1
            action = drain_action(report, stalled)
            if action == "done":
                self.out(
                    f"Cola vacía. Nuevos en el TDS en esta sesión: {total}"
                )
                return 0
            if action == "stop":
                raise ControllerError(
                    "dos ejecuciones sin avance con mensajes pendientes; "
                    "revisar la DLQ y los logs"
                )
            self.sleep(pause_sec)
        self.out(
            f"Límite de {max_executions} ejecuciones; la cola no se vació."
        )
        return 2

    # --- histórico de un banco
    def service_url(self) -> str:
        if self.service_url_override:
            return self.service_url_override.rstrip("/")
        return self.gcloud(
            [
                "run",
                "services",
                "describe",
                INGESTION_SERVICE,
                "--region",
                self.region,
                "--project",
                self.project,
                "--format=value(status.url)",
            ]
        ).strip()

    def launch_history(self, bank: str, *, stars: bool) -> str:
        token = ""  # nosec B105 - sin token: el proxy local autentica
        if self.impersonate:
            token = self.gcloud(
                [
                    "auth",
                    "print-identity-token",
                    f"--impersonate-service-account={self.impersonate}",
                    f"--audiences={self.service_url()}",
                ]
            ).strip()
        elif not self.service_url_override:
            token = self.gcloud(["auth", "print-identity-token"]).strip()
        body = {
            "bank_id": bank,
            "mode": "FULL_BACKFILL",
            "partition_by_stars": stars,
        }
        status, payload = self.post(
            f"{self.service_url()}/api/v1/ingest", body, token
        )
        if status == 202 and payload.get("execution"):
            return str(payload["execution"]).rsplit("/", 1)[-1]
        if status == 403:
            raise ControllerError(
                "403: tu cuenta necesita roles/run.invoker sobre el servicio"
            )
        raise ControllerError(f"el lanzamiento respondió {status}: {payload}")

    def ingest(
        self,
        bank: str,
        *,
        stars: bool = False,
        max_executions: int = 3,
        cooldown_sec: float = 900.0,
        conflict_retries: int = 5,
    ) -> int:
        published_total = 0
        for number in range(1, max_executions + 1):
            execution = self._launch_with_retries(bank, stars, conflict_retries)
            self.wait_execution(execution, timeout_sec=4500.0)
            event = self.final_event(
                HISTORY_JOB,
                execution,
                "Ingestion run finished",
                f' AND jsonPayload.bank_id="{bank}"',
            )
            status = str(event.get("status", ""))
            published = int(event.get("reviews_published", 0))
            published_total += published
            self.out(
                f"[{number}] {execution}: {status}"
                f"{'/' + str(event['reason']) if event.get('reason') else ''}, "
                f"{event.get('requests', 0)} solicitudes, {published} reseñas "
                f"publicadas, {event.get('pages_committed', 0)} páginas, "
                f"{event.get('elapsed_sec', 0)} s"
            )
            action = ingest_action(status)
            if action == "done":
                self.out(
                    f"{bank}: histórico cerrado ({published_total} publicadas)."
                )
                return 0
            if action == "stop":
                raise ControllerError(
                    f"{bank} terminó con {status}: revisar antes de reanudar"
                )
            if action == "cooldown":
                self.out(f"Limitación de tasa: espera de {cooldown_sec:.0f} s")
                self.sleep(cooldown_sec)
        self.out(
            f"{bank}: límite de {max_executions} ejecuciones; "
            f"{published_total} publicadas y el plan sigue abierto."
        )
        return 2

    def _launch_with_retries(self, bank: str, stars: bool, retries: int) -> str:
        for attempt in range(retries + 1):
            try:
                return self.launch_history(bank, stars=stars)
            except ControllerError as error:
                if "respondió 409" not in str(error) or attempt == retries:
                    raise
                # Lease activo: la ejecución anterior aún cierra.
                self.sleep(60.0)
        raise ControllerError("sin lanzamiento")  # pragma: no cover


# ------------------------------------------------------------------- CLI
def _project(args: argparse.Namespace) -> str:
    if args.project:
        return str(args.project)
    value = run_gcloud(["config", "get-value", "project"]).strip()
    if not value:
        raise ControllerError("indica --project")
    return value


def job_arguments(job_args: str | None, fast_replay: bool) -> str | None:
    """Argumentos del Job: `--args` de gcloud separa por comas."""
    parts = ["--execution-mode=GCS_FAST_REPLAY"] if fast_replay else []
    if job_args:
        parts.append(job_args)
    return ",".join(parts) or None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project")
    parser.add_argument("--region", default="us-central1")
    # Las opciones comunes valen antes y después del subcomando.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", default=argparse.SUPPRESS)
    common.add_argument("--region", default=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    drain = sub.add_parser(
        "drain", parents=[common], help="vacía Pub/Sub con la sanitización"
    )
    drain.add_argument("--max-executions", type=int, default=100)
    drain.add_argument(
        "--job-args",
        help='separados por coma: "--max-runtime-sec=1200,--io-workers=32"',
    )
    drain.add_argument(
        "--fast-replay",
        action="store_true",
        help="replay rápido desde las capturas (recibo por página)",
    )
    ingest = sub.add_parser(
        "ingest", parents=[common], help="histórico completo de un banco"
    )
    ingest.add_argument("--bank", required=True)
    ingest.add_argument(
        "--stars", action="store_true", help="partición por estrellas"
    )
    ingest.add_argument("--max-executions", type=int, default=3)
    ingest.add_argument("--cooldown-sec", type=float, default=900.0)
    ingest.add_argument(
        "--impersonate",
        help="cuenta de servicio con la que se firma el token de invocación",
    )
    ingest.add_argument(
        "--service-url",
        help="URL del proxy local (gcloud run services proxy)",
    )
    ingest.add_argument(
        "--yes",
        action="store_true",
        help="confirma el lanzamiento contra Google Play",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "ingest" and not args.yes:
        print("`ingest` consulta Google Play a escala: repetir con --yes.")
        return 64
    try:
        controller = Controller(
            project=_project(args),
            region=args.region,
            service_url=getattr(args, "service_url", None),
            impersonate=getattr(args, "impersonate", None),
        )
        if args.command == "drain":
            return controller.drain(
                max_executions=args.max_executions,
                job_args=job_arguments(args.job_args, args.fast_replay),
            )
        return controller.ingest(
            args.bank.upper(),
            stars=args.stars,
            max_executions=args.max_executions,
            cooldown_sec=args.cooldown_sec,
        )
    except ControllerError as error:
        print(f"DETENIDO: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
