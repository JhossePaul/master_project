"""Controladores del full: decisiones, bucles y paradas de seguridad."""

import json
from typing import Any

import pytest

from tools import backfill_controller as bc


def report(**fields: Any) -> dict[str, Any]:
    base = {
        "stop_reason": "message_budget",
        "messages": 1000,
        "tds_committed": 900,
        "already_processed": 100,
        "elapsed_sec": 50.0,
        "events_retryable": 0,
        "transient_failure": False,
    }
    return base | fields


class FakeCloud:
    """Simula gcloud, Cloud Run, Logging y el servicio de ingesta."""

    def __init__(self, events: list[dict[str, Any]], *, completes: bool = True):
        self.events = list(events)
        self.completes = completes
        self.calls: list[list[str]] = []
        self.executions = 0
        self.posts: list[dict[str, Any]] = []
        self.post_statuses: list[int] = []
        self.clock = 0.0
        self.failing: set[str] = set()
        self.token = "id-token-for-tests"  # noqa: S105

    def gcloud(self, args):
        args = list(args)
        self.calls.append(args)
        if args[:3] == ["run", "jobs", "execute"]:
            self.executions += 1
            return f"projects/p/locations/r/executions/exec-{self.executions}\n"
        if args[:4] == ["run", "jobs", "executions", "describe"]:
            name = args[4]
            if not self.completes:
                return json.dumps({"status": {}})
            ok = name not in self.failing
            return json.dumps(
                {
                    "status": {
                        "completionTime": "2026-10-15T12:00:00Z",
                        "succeededCount": 1 if ok else 0,
                        "failedCount": 0 if ok else 1,
                    }
                }
            )
        if args[:2] == ["logging", "read"]:
            if not self.events:
                return "[]"
            return json.dumps([{"jsonPayload": self.events.pop(0)}])
        if args[:2] == ["auth", "print-identity-token"]:
            return f"{self.token}\n"
        if args[:3] == ["run", "services", "describe"]:
            return "https://worker.example\n"
        raise AssertionError(args)

    def post(self, url, body, token):
        assert url.endswith("/api/v1/ingest") and token == self.token
        self.posts.append(body)
        status = self.post_statuses.pop(0) if self.post_statuses else 202
        if status == 202:
            return 202, {
                "execution": f"projects/p/jobs/j/executions/h-{len(self.posts)}"
            }
        return status, {"detail": "x"}

    def sleep(self, seconds):
        self.clock += seconds

    def monotonic(self):
        return self.clock

    def controller(self, out):
        return bc.Controller(
            project="p",
            region="r",
            gcloud=self.gcloud,
            post=self.post,
            sleep=self.sleep,
            monotonic=self.monotonic,
            out=out,
        )


# ------------------------------------------------------------ decisiones
@pytest.mark.parametrize(
    ("fields", "stalled", "expected"),
    [
        ({"stop_reason": "drained"}, 0, "done"),
        (
            {"messages": 0, "tds_committed": 0, "already_processed": 0},
            0,
            "done",
        ),
        ({}, 0, "continue"),
        ({"tds_committed": 0, "already_processed": 5}, 1, "continue"),
        ({"tds_committed": 0, "already_processed": 0}, 1, "continue"),
        ({"tds_committed": 0, "already_processed": 0}, 2, "stop"),
        ({"transient_failure": True, "tds_committed": 10}, 0, "continue"),
    ],
)
def test_drain_action(fields, stalled, expected):
    parsed = bc.DrainReport.from_log(report(**fields))
    assert bc.drain_action(parsed, stalled) == expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("SOURCE_EXHAUSTED_OBSERVED", "done"),
        ("TARGET_REACHED", "done"),
        ("BUDGET_EXHAUSTED", "resume"),
        ("PAUSED_BACKLOG", "resume"),
        ("PARTIAL_RATE_LIMITED", "cooldown"),
        ("BLOCKED", "stop"),
        ("PROTOCOL_ERROR", "stop"),
        ("LEASE_CONFLICT", "stop"),
        ("", "stop"),
    ],
)
def test_ingest_action(status, expected):
    assert bc.ingest_action(status) == expected


# ----------------------------------------------------------------- drain
def test_drain_loops_until_the_queue_is_empty():
    cloud = FakeCloud(
        [report(), report(), report(stop_reason="drained", messages=300)]
    )
    lines: list[str] = []
    assert cloud.controller(lines.append).drain() == 0
    assert cloud.executions == 3
    assert "Cola vacía" in lines[-1]
    assert "18.0 msg/s" not in lines[0] and "20.0 msg/s" in lines[0]


def test_drain_passes_job_arguments_to_every_execution():
    cloud = FakeCloud([report(stop_reason="drained")])
    cloud.controller(lambda _: None).drain(job_args="--max-runtime-sec=1200")
    execute = next(
        c for c in cloud.calls if c[:3] == ["run", "jobs", "execute"]
    )
    assert "--args=--max-runtime-sec=1200" in execute
    assert "--async" in execute


def test_drain_stops_after_two_runs_without_progress():
    stuck = report(tds_committed=0, already_processed=0)
    cloud = FakeCloud([stuck, stuck, stuck])
    with pytest.raises(bc.ControllerError, match="sin avance"):
        cloud.controller(lambda _: None).drain()
    assert cloud.executions == 2


def test_drain_stops_when_an_execution_fails():
    cloud = FakeCloud([report()])
    cloud.failing = {"exec-1"}
    with pytest.raises(bc.ControllerError, match="falló"):
        cloud.controller(lambda _: None).drain()


def test_drain_respects_the_execution_limit():
    cloud = FakeCloud([report(), report()])
    lines: list[str] = []
    assert cloud.controller(lines.append).drain(max_executions=2) == 2
    assert "no se vació" in lines[-1]


def test_missing_final_event_and_hung_execution_are_reported():
    cloud = FakeCloud([])
    with pytest.raises(bc.ControllerError, match="sin evento"):
        cloud.controller(lambda _: None).final_event(
            "job", "e1", "msg", wait_sec=30
        )
    hung = FakeCloud([], completes=False)
    with pytest.raises(bc.ControllerError, match="no terminó"):
        hung.controller(lambda _: None).wait_execution("e1", timeout_sec=60)


# ---------------------------------------------------------------- ingest
def history(status: str, **fields: Any) -> dict[str, Any]:
    return {
        "status": status,
        "requests": 1000,
        "reviews_published": 199_000,
        "pages_committed": 1000,
        "elapsed_sec": 2500,
    } | fields


def test_ingest_resumes_on_budget_and_closes_the_plan():
    cloud = FakeCloud(
        [
            history("BUDGET_EXHAUSTED", reason="requests"),
            history("SOURCE_EXHAUSTED_OBSERVED", reviews_published=50_000),
        ]
    )
    lines: list[str] = []
    assert cloud.controller(lines.append).ingest("BBVA", stars=True) == 0
    assert [p["mode"] for p in cloud.posts] == ["FULL_BACKFILL"] * 2
    assert cloud.posts[0] == {
        "bank_id": "BBVA",
        "mode": "FULL_BACKFILL",
        "partition_by_stars": True,
    }
    assert "BUDGET_EXHAUSTED/requests" in lines[0]
    assert "249000 publicadas" in lines[-1]


@pytest.mark.parametrize(
    "status", ["BLOCKED", "PROTOCOL_ERROR", "LEASE_CONFLICT"]
)
def test_ingest_stops_on_anything_that_is_not_normal_progress(status):
    cloud = FakeCloud([history(status)])
    with pytest.raises(bc.ControllerError, match=status):
        cloud.controller(lambda _: None).ingest("BBVA")
    assert len(cloud.posts) == 1


def test_ingest_waits_out_rate_limits_and_respects_the_limit():
    cloud = FakeCloud(
        [history("PARTIAL_RATE_LIMITED"), history("BUDGET_EXHAUSTED")]
    )
    lines: list[str] = []
    result = cloud.controller(lines.append).ingest(
        "NUBANK", max_executions=2, cooldown_sec=600
    )
    assert result == 2 and cloud.clock >= 600
    assert "plan sigue abierto" in lines[-1]


def test_launch_retries_on_active_lease_and_explains_a_403():
    cloud = FakeCloud([history("SOURCE_EXHAUSTED_OBSERVED")])
    cloud.post_statuses = [409, 409, 202]
    assert cloud.controller(lambda _: None).ingest("BBVA") == 0
    assert len(cloud.posts) == 3 and cloud.clock >= 120
    denied = FakeCloud([])
    denied.post_statuses = [403]
    with pytest.raises(bc.ControllerError, match="run.invoker"):
        denied.controller(lambda _: None).ingest("BBVA")
    failing = FakeCloud([])
    failing.post_statuses = [500]
    with pytest.raises(bc.ControllerError, match="respondió 500"):
        failing.controller(lambda _: None).ingest("BBVA")


def test_persistent_conflict_gives_up_after_the_retries():
    cloud = FakeCloud([])
    cloud.post_statuses = [409] * 10
    with pytest.raises(bc.ControllerError, match="409"):
        cloud.controller(lambda _: None).ingest("BBVA", conflict_retries=2)
    assert len(cloud.posts) == 3


# ------------------------------------------------------------------- CLI
def test_cli_requires_explicit_confirmation_for_ingest(capsys):
    assert bc.main(["--project", "p", "ingest", "--bank", "bbva"]) == 64
    assert "--yes" in capsys.readouterr().out


def test_cli_parses_arguments_and_reports_errors(monkeypatch, capsys):
    args = bc.parse_args(["--project", "p", "drain", "--max-executions", "7"])
    assert (args.command, args.max_executions, args.region) == (
        "drain",
        7,
        "us-central1",
    )

    def boom(self, **kwargs):
        raise bc.ControllerError("sin avance")

    monkeypatch.setattr(bc.Controller, "drain", boom)
    assert bc.main(["--project", "p", "drain"]) == 1
    assert "DETENIDO: sin avance" in capsys.readouterr().err

    seen: dict[str, Any] = {}

    def fake_ingest(self, bank, **kwargs):
        seen.update(bank=bank, **kwargs)
        return 0

    monkeypatch.setattr(bc.Controller, "ingest", fake_ingest)
    code = bc.main(
        ["--project", "p", "ingest", "--bank", "bbva", "--yes", "--stars"]
    )
    assert code == 0 and seen["bank"] == "BBVA" and seen["stars"] is True


def test_common_options_work_before_and_after_the_subcommand():
    before = bc.parse_args(["--project", "p", "--region", "r", "drain"])
    after = bc.parse_args(["drain", "--project", "p", "--region", "r"])
    assert (before.project, before.region) == (after.project, after.region)
    assert (after.project, after.region) == ("p", "r")
    default = bc.parse_args(["ingest", "--bank", "BBVA", "--project", "p"])
    assert default.region == "us-central1"


def test_project_falls_back_to_gcloud_config(monkeypatch):
    monkeypatch.setattr(bc, "run_gcloud", lambda args: "from-config\n")
    assert bc._project(bc.parse_args(["drain"])) == "from-config"
    monkeypatch.setattr(bc, "run_gcloud", lambda args: "\n")
    with pytest.raises(bc.ControllerError, match="--project"):
        bc._project(bc.parse_args(["drain"]))
