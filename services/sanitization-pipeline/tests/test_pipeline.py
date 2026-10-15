"""Features 4.1 y 4.4: entrypoint, preflight, despacho y orquestación.

La página se captura y publica con el publisher real de EPIC-3 sobre GCS
simulado con generaciones; esos mismos mensajes alimentan al suscriptor.
"""

import copy
import itertools
import json
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from google.api_core import exceptions as gexc
from ingestion_worker import (
    PROTOCOL_VERSION,
    RawReviewBatchPublisher,
    WatermarkRepository,
    parse_batchexecute_response,
)
from sanitization_pipeline import orchestrator as orch
from sanitization_pipeline import pipeline
from sanitization_pipeline.bq_writer import (
    BigQueryTdsUpsertManager,
)
from sanitization_pipeline.config import (
    SanitizationExecutionConfig,
)
from sanitization_pipeline.dlp_transforms import (
    BatchCloudDlpDeidentifyDoFn,
)
from sanitization_pipeline.processing_ledger import (
    ProcessingLedgerRepository,
)
from voc_common import (
    PLAYSTORE_BANK_APPS,
    BankKey,
    IngestionMode,
    SanitizationStatus,
    ScanContext,
    ScanStreamState,
    Settings,
)


def last_log(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_invalid_configuration_exits_before_any_work(capsys, settings):
    code = pipeline.main(["--max-messages", "0"], {}, settings_factory=settings)
    assert code == pipeline.EX_USAGE
    log = last_log(capsys)
    assert log["severity"] == "ERROR"
    assert log["message"] == "Invalid sanitization configuration"


def test_disabled_v2_and_missing_templates_fail_closed(capsys, settings):
    disabled = pipeline.main(
        [],
        {},
        settings_factory=lambda: Settings(_env_file=None),
    )
    assert disabled == pipeline.EX_USAGE
    assert "not enabled" in last_log(capsys)["error"]
    missing = pipeline.main(
        [],
        {"SANITIZATION_USE_CLOUD_DLP_API": "true"},
        settings_factory=lambda: settings(dlp_deidentify_template_id=None),
    )
    assert missing == pipeline.EX_USAGE


def test_unregistered_modes_do_not_pretend_success(
    monkeypatch, capsys, settings
):
    assert set(pipeline.RUNNERS) == {
        pipeline.ExecutionMode.BATCH_PULL_SERVERLESS,
        pipeline.ExecutionMode.GCS_BACKFILL_MANIFESTS,
        pipeline.ExecutionMode.GCS_FAST_REPLAY,
    }
    monkeypatch.delitem(
        pipeline.RUNNERS, pipeline.ExecutionMode.BATCH_PULL_SERVERLESS
    )
    assert pipeline.main([], {}, settings_factory=settings) == (
        pipeline.EX_SOFTWARE
    )
    assert last_log(capsys)["execution_mode"] == "BATCH_PULL_SERVERLESS"


def test_registered_runner_receives_validated_inputs(
    monkeypatch, settings, dlp_names
):
    calls = []

    def runner(config, loaded, parent):
        calls.append((config, loaded, parent))
        return pipeline.EX_OK

    monkeypatch.setitem(
        pipeline.RUNNERS, pipeline.ExecutionMode.GCS_BACKFILL_MANIFESTS, runner
    )
    code = pipeline.main(
        ["--execution-mode", "GCS_BACKFILL_MANIFESTS"],
        {},
        settings_factory=settings,
    )
    assert code == pipeline.EX_OK
    config, loaded, parent = calls[0]
    assert parent == dlp_names["parent"]
    assert loaded.dlp_inspect_template_id == dlp_names["inspect"]
    assert loaded.dlp_deidentify_template_id == dlp_names["deidentify"]
    assert config.execution_mode == "GCS_BACKFILL_MANIFESTS"


def test_unknown_flag_is_a_usage_error(settings):
    with pytest.raises(SystemExit) as exc:
        pipeline.main(["--nope"], {}, settings_factory=settings)
    assert exc.value.code == 2


# ===================================================================
# Feature 4.4: orquestador con publisher real de EPIC-3 y fakes de GCP.
# ===================================================================
BANK = BankKey.BBVA
APP = PLAYSTORE_BANK_APPS[BANK]
T0 = datetime(2026, 10, 15, 8, tzinfo=UTC)
SALT = "salt-for-sanitization-tests"
PARENT = "projects/test-project/locations/us-central1"
INSPECT = f"{PARENT}/inspectTemplates/voc-dlp-inspect-template"
DEIDENTIFY = f"{PARENT}/deidentifyTemplates/voc-dlp-deidentify-template"
SUBSCRIPTION = "projects/test-project/subscriptions/voc-raw-reviews-sub"
NEXT = "next-page-cursor"
TEXTS = (
    "Juan Pérez no puede transferir a la cuenta 0123456789",
    "ok",
    "la app se cierra al pagar servicios",
)


class FakeBlob:
    def __init__(self, bucket: "FakeBucket", name: str) -> None:
        self.bucket, self.name = bucket, name
        self.metadata: dict[str, str] | None = None
        self.generation: int | None = None

    def _get(self, expected: int | None = None) -> dict[str, Any]:
        if self.name not in self.bucket.objects:
            raise gexc.NotFound("missing")
        record = self.bucket.objects[self.name]
        if expected is not None and record["generation"] != expected:
            raise gexc.PreconditionFailed("changed")
        return record

    def reload(self, *, if_generation_match=None, timeout=None) -> None:
        record = self._get(if_generation_match)
        self.generation = record["generation"]
        self.metadata = copy.deepcopy(record["metadata"])

    def download_as_bytes(self, *, if_generation_match=None, timeout=None):
        return self._get(if_generation_match)["data"]

    def upload_from_string(
        self, data, *, content_type, if_generation_match, timeout
    ) -> None:
        if self.bucket.fail_prefix and self.name.startswith(
            self.bucket.fail_prefix
        ):
            raise gexc.ServiceUnavailable("gcs down")
        record = self.bucket.objects.get(self.name)
        if (record["generation"] if record else 0) != if_generation_match:
            raise gexc.PreconditionFailed("changed")
        self.bucket.counter += 1
        self.generation = self.bucket.counter
        self.bucket.objects[self.name] = {
            "generation": self.generation,
            "data": bytes(data),
            "metadata": copy.deepcopy(self.metadata),
        }


class FakeBucket:
    name = "test-bucket"

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.counter = 0
        self.fail_prefix: str | None = None

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)


class FakeStorage:
    def __init__(self) -> None:
        self.value = FakeBucket()

    def bucket(self, _: str) -> FakeBucket:
        return self.value


class FakeBigQuery:
    def __init__(self) -> None:
        self.merges = 0
        self.rows: list[dict[str, Any]] = []
        self.sqls: list[str] = []
        self.fail = False

    def create_table(self, table, timeout=None):
        return table

    def load_table_from_json(self, rows, destination, **kwargs):
        self.rows.extend(rows)
        return Mock(job_id="load-1", errors=None)

    def query(self, sql, **kwargs):
        self.sqls.append(sql)
        job = Mock(job_id="merge-1", errors=None)
        if self.fail:
            job.result.side_effect = gexc.BadRequest("merge failed")
        else:
            self.merges += 1
        return job

    def delete_table(self, table, not_found_ok=False, timeout=None):
        return None


DLP_CALLS: list[int] = []
DLP_ERRORS: list[Exception] = []


class FakeDlpClient:
    def deidentify_content(self, *, request, retry, timeout):
        DLP_CALLS.append(len(request["item"]["table"]["rows"]))
        if DLP_ERRORS:
            raise DLP_ERRORS.pop(0)
        rows = [
            SimpleNamespace(
                values=[
                    SimpleNamespace(
                        string_value=v["string_value"].replace(
                            "Juan Pérez", "[PERSON_NAME]"
                        )
                    )
                    for v in row["values"]
                ]
            )
            for row in request["item"]["table"]["rows"]
        ]
        return SimpleNamespace(
            item=SimpleNamespace(table=SimpleNamespace(rows=rows))
        )


class FakeDlpFactory:
    def __call__(self) -> FakeDlpClient:
        return FakeDlpClient()


class FakeSubscriber:
    def __init__(self, pulls: list[list[Any]]) -> None:
        self.pulls = list(pulls)
        self.requests: list[int] = []
        self.acked: list[str] = []
        self.nacked: list[str] = []
        self.renewed: list[list[str]] = []

    def pull(self, *, request, timeout):
        assert request["subscription"] == SUBSCRIPTION
        self.requests.append(request["max_messages"])
        return SimpleNamespace(
            received_messages=self.pulls.pop(0) if self.pulls else []
        )

    def acknowledge(self, *, request):
        self.acked.extend(request["ack_ids"])

    def modify_ack_deadline(self, *, request):
        if request["ack_deadline_seconds"] == 0:
            self.nacked.extend(request["ack_ids"])
        else:
            assert request["ack_deadline_seconds"] == 600
            self.renewed.append(list(request["ack_ids"]))


def row(rid: str, text: str, ts: int) -> list[Any]:
    return [rid, ["user"], 2, None, text, [ts], 0, None, None, None, "1.0"] + [
        None
    ] * 6


class Env:
    """Página real de EPIC-3 (captura + manifiesto + mensajes publicados)."""

    def __init__(self, texts: tuple[str, ...] = TEXTS) -> None:
        DLP_CALLS.clear()
        DLP_ERRORS.clear()
        self.storage = FakeStorage()
        self.bucket = self.storage.value
        self.ingestion = WatermarkRepository(
            self.storage, "test-bucket", clock=lambda: T0
        )
        self.published: list[tuple[bytes, dict[str, str]]] = []
        pubsub = Mock()
        pubsub.publish.side_effect = self._publish
        publisher = RawReviewBatchPublisher(
            self.ingestion, pubsub, "projects/test-project/topics/raw"
        )
        self.publisher = publisher
        self.last_token = NEXT
        handle = self.ingestion.acquire_lease(BANK, "run")
        stream = ScanStreamState(
            bank_id=BANK,
            app_id=APP,
            stream_id="stream",
            context=ScanContext(app_id=APP, protocol_version=PROTOCOL_VERSION),
        )
        self.ingestion.register(handle, [stream])
        self.ingestion.start_incremental(handle, "stream")
        base = int(T0.timestamp())
        inner = [
            [row(f"r{i}", text, base - i) for i, text in enumerate(texts)],
            [None, NEXT],
            None,
        ]
        body = json.dumps([["wrb.fr", "oCPfdb", json.dumps(inner)]]).encode()
        page = parse_batchexecute_response(body, bank_id=BANK, app_id=APP)
        manifest = publisher.prepare_page(
            handle,
            stream,
            page,
            mode=IngestionMode.INCREMENTAL,
            fetched_at=T0,
            fetch_attempt_id="fetch",
        )
        publisher.publish_page(handle, manifest)
        self.ingestion.release_lease(handle)
        self.page_id = manifest.page_id
        self.backup = manifest.backup_uri.removeprefix("gs://test-bucket/")
        self.ledger = ProcessingLedgerRepository(
            self.storage, "test-bucket", self.ingestion, clock=lambda: T0
        )
        self.bq = FakeBigQuery()
        self.upsert = BigQueryTdsUpsertManager(
            self.bq,  # type: ignore[arg-type]
            project="test-project",
            dataset="bbva_voc_tds",
            clock=lambda: T0,
        )

    def add_page(self, number: int, texts: tuple[str, ...]) -> str:
        """Otra página encadenada a la anterior, publicada como en prod."""
        handle = self.ingestion.acquire_lease(BANK, "run")
        stream = self.ingestion.get_stream(self.ingestion.load(BANK), "stream")
        base = int(T0.timestamp()) - 100_000 * number
        token = f"next-page-{number}"
        inner = [
            [row(f"p{number}r{i}", t, base - i) for i, t in enumerate(texts)],
            [None, token],
            None,
        ]
        body = json.dumps([["wrb.fr", "oCPfdb", json.dumps(inner)]]).encode()
        page = parse_batchexecute_response(body, bank_id=BANK, app_id=APP)
        manifest = self.publisher.prepare_page(
            handle,
            stream,
            page,
            mode=IngestionMode.INCREMENTAL,
            fetched_at=T0,
            fetch_attempt_id=f"fetch-{number}",
            input_token=self.last_token,
        )
        self.publisher.publish_page(handle, manifest)
        self.ingestion.release_lease(handle)
        self.last_token = token
        return manifest.page_id

    def _publish(self, topic, data, **attributes):
        self.published.append((data, attributes))
        future = Mock()
        future.result.return_value = "id"
        return future

    cloud_dlp = True

    def do_fn(self) -> BatchCloudDlpDeidentifyDoFn:
        return BatchCloudDlpDeidentifyDoFn(
            user_hash_salt=SALT,
            use_cloud_dlp_api=self.cloud_dlp,
            parent=PARENT,
            inspect_template=INSPECT,
            deidentify_template=DEIDENTIFY,
            client_factory=FakeDlpFactory(),
            retry_sleep=lambda _: None,
        )

    def services(self, subscriber: Any = None) -> orch.Services:
        return orch.Services(
            ingestion=self.ingestion,
            ledger=self.ledger,
            upsert=self.upsert,
            do_fn=self.do_fn,
            subscriber=subscriber,
            subscription=SUBSCRIPTION,
        )

    def messages(self, prefix: str = "a") -> list[Any]:
        return [
            SimpleNamespace(
                ack_id=f"{prefix}{i}",
                message=SimpleNamespace(
                    data=data, attributes=attrs, message_id=f"m{i}"
                ),
            )
            for i, (data, attrs) in enumerate(self.published)
        ]

    def drain(self, pulls, **config: Any) -> tuple[orch.RunReport, Any]:
        subscriber = FakeSubscriber(pulls)
        drainer = orch.PubSubDrainer(
            subscriber,
            SUBSCRIPTION,
            self.services(subscriber).processor(),
            SanitizationExecutionConfig(**config),
        )
        return drainer.run(), subscriber


def test_drain_persists_before_ack_and_closes_the_page():
    env = Env()
    messages = env.messages()
    duplicate = env.messages(prefix="dup")[0]
    report, subscriber = env.drain([[*messages, duplicate]])
    assert report.exit_code() == orch.EX_OK
    assert sorted(subscriber.acked) == ["a0", "a1", "a2", "dup0"]
    assert not subscriber.nacked
    assert env.bq.merges == 1 and len(env.bq.rows) == 3
    assert DLP_CALLS == [3]
    assert report.tds_committed == 3
    assert report.pages == {"RESOLVED": 1}
    assert (report.messages, report.duplicate_messages) == (4, 1)
    assert report.elapsed_sec >= 0
    closure = env.ledger.page_closure(BANK, env.page_id)
    assert closure.status == SanitizationStatus.RESOLVED
    dumped = json.dumps(env.bq.rows, ensure_ascii=False)
    assert "Juan Pérez" not in dumped and "0123456789" not in dumped


def test_redelivery_after_commit_is_acked_without_dlp_or_bigquery():
    env = Env()
    env.drain([env.messages()])
    calls, merges = list(DLP_CALLS), env.bq.merges
    report, subscriber = env.drain([env.messages(prefix="again")])
    assert sorted(subscriber.acked) == ["again0", "again1", "again2"]
    assert DLP_CALLS == calls and env.bq.merges == merges
    assert report.already_processed == 3


def test_same_event_from_another_page_gets_its_own_receipt():
    env = Env()
    env.drain([env.messages()])
    data, attrs = env.published[0]
    moved = json.loads(data)
    moved["page_id"] = "other-page"
    message = SimpleNamespace(
        ack_id="x",
        message=SimpleNamespace(
            data=json.dumps(moved).encode(),
            attributes=attrs | {"page_id": "other-page"},
        ),
    )
    report, subscriber = env.drain([[message]])
    assert subscriber.acked == ["x"]
    receipt = env.ledger.page_receipt(BANK, "other-page", attrs["event_id"])
    assert receipt.status.value == "TDS_COMMITTED"
    assert report.pages == {"PENDING": 1}


def test_poison_messages_are_acknowledged_without_processing():
    env = Env()
    data, attrs = env.published[0]
    poison = [
        SimpleNamespace(
            ack_id="bad-json", message=SimpleNamespace(data=b"{", attributes={})
        ),
        SimpleNamespace(
            ack_id="bad-attrs",
            message=SimpleNamespace(
                data=data, attributes=attrs | {"page_id": "x"}
            ),
        ),
    ]
    report, subscriber = env.drain([poison])
    assert sorted(subscriber.acked) == ["bad-attrs", "bad-json"]
    assert report.poison == 2 and not DLP_CALLS and env.bq.merges == 0


def test_bigquery_failure_nacks_valid_events_only():
    env = Env()
    env.bq.fail = True
    report, subscriber = env.drain([env.messages()])
    # Sin filtro de longitud, todo evento depende del MERGE para confirmarse.
    assert not subscriber.acked
    assert sorted(subscriber.nacked) == ["a0", "a1", "a2"]
    assert report.exit_code() == orch.EX_TEMPFAIL
    assert env.ledger.page_closure(BANK, env.page_id) is None


def test_local_regex_default_drains_without_calling_dlp():
    env = Env()
    env.cloud_dlp = False
    report, subscriber = env.drain([env.messages()])
    assert report.exit_code() == orch.EX_OK
    assert sorted(subscriber.acked) == ["a0", "a1", "a2"]
    assert not subscriber.nacked and not DLP_CALLS
    assert env.bq.merges == 1 and report.tds_committed == 3
    assert all(
        row["texto_respuesta_sanitizado"] is None and row["titulo"] is None
        for row in env.bq.rows
    )


def test_dlp_outage_nacks_and_configuration_error_stops(capsys):
    env = Env()
    DLP_ERRORS.extend([gexc.ServiceUnavailable("down")] * 4)
    report, subscriber = env.drain([env.messages()])
    assert sorted(subscriber.nacked) == ["a0", "a1", "a2"]
    assert report.events_retryable == 3 and not subscriber.acked
    DLP_ERRORS.append(gexc.PermissionDenied("iam"))
    subscriber = FakeSubscriber([env.messages(prefix="c")])
    code = orch.run_batch_pull(
        SanitizationExecutionConfig(),
        Mock(),
        PARENT,
        services_factory=lambda *_: env.services(subscriber),
    )
    assert code == orch.EX_USAGE
    assert sorted(subscriber.nacked) == ["c0", "c1", "c2"]
    assert "configuration" in capsys.readouterr().out


def test_receipt_write_failure_nacks_everything_and_stops():
    env = Env()
    env.bucket.fail_prefix = "state/ingestion/receipts/"
    report, subscriber = env.drain([env.messages(), env.messages(prefix="b")])
    assert sorted(subscriber.nacked) == ["a0", "a1", "a2"]
    assert not subscriber.acked
    assert report.stop_reason == "transient_failure"
    assert report.exit_code() == orch.EX_TEMPFAIL
    assert len(subscriber.requests) == 1


def test_budgets_bound_pulls_and_stop_cleanly():
    env = Env()
    report, subscriber = env.drain(
        [env.messages()[:2], env.messages()[2:]],
        max_messages=3,
        microbatch_size=2,
        dlp_max_rows=2,
    )
    assert subscriber.requests == [2, 1]
    assert report.stop_reason == "message_budget"
    empty, _ = env.drain([])
    assert empty.stop_reason == "drained" and empty.messages == 0
    clock = itertools.chain([0.0, 2000.0], itertools.repeat(2000.0))
    drainer = orch.PubSubDrainer(
        FakeSubscriber([env.messages()]),
        SUBSCRIPTION,
        env.services().processor(),
        SanitizationExecutionConfig(),
        monotonic=lambda: next(clock),
    )
    late = drainer.run()
    assert late.stop_reason == "runtime_budget"
    assert late.elapsed_sec == 2000.0


def test_ack_deadline_is_renewed_while_the_microbatch_runs():
    renewed = threading.Event()
    subscriber = FakeSubscriber([])
    original = subscriber.modify_ack_deadline

    def renew(*, request):
        original(request=request)
        if len(subscriber.renewed) >= 2:
            renewed.set()

    subscriber.modify_ack_deadline = renew  # type: ignore[method-assign]
    with orch.AckDeadlineRenewer(
        subscriber,
        SUBSCRIPTION,
        ["a", "b"],
        interval_sec=0.01,
        deadline_sec=600,
    ) as renewer:
        assert renewed.wait(5)
    count = renewer.renewals
    assert count >= 2 and subscriber.renewed[0] == ["a", "b"]
    renewed.clear()
    assert not renewed.wait(0.05) and renewer.renewals == count
    failing = Mock()
    failing.modify_ack_deadline.side_effect = gexc.ServiceUnavailable("x")
    with orch.AckDeadlineRenewer(
        failing, SUBSCRIPTION, ["a"], interval_sec=0.01, deadline_sec=600
    ):
        threading.Event().wait(0.05)
    assert failing.modify_ack_deadline.call_count >= 1
    with orch.AckDeadlineRenewer(
        failing, SUBSCRIPTION, [], interval_sec=0.01, deadline_sec=600
    ) as idle:
        pass
    assert idle.renewals == 0


def test_unexpected_errors_nack_and_propagate():
    env = Env()
    subscriber = FakeSubscriber([env.messages()])

    class Broken(orch.MicrobatchProcessor):
        def process(self, envelopes):
            raise RuntimeError("bug")

    drainer = orch.PubSubDrainer(
        subscriber,
        SUBSCRIPTION,
        Broken(env.ledger, env.upsert, lambda batch: None),  # type: ignore[arg-type]
        SanitizationExecutionConfig(),
    )
    with pytest.raises(RuntimeError):
        drainer.run()
    assert sorted(subscriber.nacked) == ["a0", "a1", "a2"]


# ------------------------------------------------------- manifest replay
def test_manifest_backfill_replays_committed_capture_once():
    env = Env()
    backfill = orch.ManifestBackfill(
        env.ingestion,
        env.services().processor(),
        SanitizationExecutionConfig(),
        banks=(BANK,),
    )
    report = backfill.run()
    assert report.pages == {"RESOLVED": 1} and report.messages == 3
    assert env.bq.merges == 1
    again = backfill.run()
    assert again.messages == 0 and env.bq.merges == 1
    assert orch._latest_manifests(env.ingestion, BankKey.NUBANK) == []


def test_manifest_backfill_marks_expired_capture_as_gap():
    env = Env()
    del env.bucket.objects[env.backup]
    report = orch.ManifestBackfill(
        env.ingestion,
        env.services().processor(),
        SanitizationExecutionConfig(),
        banks=(BANK,),
    ).run()
    assert report.expired_captures == 1
    closure = env.ledger.page_closure(BANK, env.page_id)
    assert closure.status == SanitizationStatus.GAPS_DETECTED
    assert closure.reason == "STAGING_EXPIRED" and closure.missing == 3


def test_manifest_backfill_budgets_and_transient_stop():
    env = Env()
    config = SanitizationExecutionConfig(max_messages=1, microbatch_size=1)
    processor = env.services().processor()
    stopped = orch.ManifestBackfill(
        env.ingestion, processor, config, banks=(BANK, BANK)
    ).run()
    assert stopped.stop_reason == "message_budget"
    clock = itertools.chain([0.0, 5000.0], itertools.repeat(5000.0))
    late = orch.ManifestBackfill(
        Env().ingestion,
        processor,
        SanitizationExecutionConfig(),
        banks=(BANK,),
        monotonic=lambda: next(clock),
    ).run()
    assert late.stop_reason == "runtime_budget"
    assert late.elapsed_sec == 5000.0
    failing = Env()
    failing.bucket.fail_prefix = "state/ingestion/receipts/"
    report = orch.ManifestBackfill(
        failing.ingestion,
        failing.services().processor(),
        SanitizationExecutionConfig(),
        banks=(BANK,),
    ).run()
    assert report.transient_failure and report.exit_code() == orch.EX_TEMPFAIL


def test_reconcile_errors_do_not_block_acks(monkeypatch):
    env = Env()

    def broken(*args, **kwargs):
        raise gexc.ServiceUnavailable("gcs")

    monkeypatch.setattr(env.ledger, "reconcile_page", broken)
    report, subscriber = env.drain([env.messages()])
    assert sorted(subscriber.acked) == ["a0", "a1", "a2"]
    assert report.pages == {"ERROR": 1}


# ------------------------------------------------------------ wiring
def test_main_runs_registered_modes_end_to_end(monkeypatch, capsys, settings):
    env = Env()
    subscriber = FakeSubscriber([env.messages()])
    monkeypatch.setattr(
        orch, "build_services", lambda *_: env.services(subscriber)
    )
    monkeypatch.setitem(
        pipeline.RUNNERS,
        pipeline.ExecutionMode.BATCH_PULL_SERVERLESS,
        lambda c, s, p: orch.run_batch_pull(
            c, s, p, services_factory=lambda *_: env.services(subscriber)
        ),
    )
    assert pipeline.main([], {}, settings_factory=settings) == orch.EX_OK
    log = last_log(capsys)
    assert log["message"] == "Sanitization run finished"
    assert log["tds_committed"] == 3 and "Juan" not in json.dumps(log)
    assert {"duplicate_messages", "elapsed_sec", "stop_reason"} <= set(log)
    code = orch.run_manifest_backfill(
        SanitizationExecutionConfig(),
        Mock(),
        PARENT,
        services_factory=lambda *_: env.services(),
    )
    assert code == orch.EX_OK


def anonymous_gcs(monkeypatch):
    """Cliente de GCS falso sin credenciales reales; captura su sesión HTTP."""
    import google.auth
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import storage

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        google.auth, "default", lambda **_: (AnonymousCredentials(), "p")
    )

    class FakeClient:
        SCOPE = storage.Client.SCOPE

        def __new__(cls, **kwargs):
            captured.update(kwargs)
            return FakeStorage()

    monkeypatch.setattr(storage, "Client", FakeClient)
    return captured


def test_build_services_uses_settings(monkeypatch, settings):
    from google.cloud import bigquery, pubsub_v1

    anonymous_gcs(monkeypatch)
    monkeypatch.setattr(bigquery, "Client", lambda **_: Mock())
    monkeypatch.setattr(pubsub_v1, "SubscriberClient", Mock)
    loaded = settings(bq_sanitized_tds_table="custom_tds")
    services = orch.build_services(
        loaded, SanitizationExecutionConfig(), PARENT
    )
    assert services.ledger.io_workers == 16
    assert services.subscription == (
        "projects/test-project/subscriptions/voc-raw-reviews-sub"
    )
    assert services.upsert.table == "test-project.bbva_voc_tds.custom_tds"
    do_fn = services.do_fn()
    assert do_fn.inspect_template == loaded.dlp_inspect_template_id
    assert do_fn.max_rows == 250
    full = settings(pubsub_raw_subscription="projects/x/subscriptions/y")
    assert orch.subscription_path(full) == "projects/x/subscriptions/y"


def test_run_do_fn_cleans_its_sink():
    env = Env()
    result = orch.run_do_fn(env.do_fn(), [])
    assert not result.valid and not orch._SINK


# -------------------------------------------- cronómetros y presupuesto
def test_report_breaks_down_time_by_phase():
    env = Env()
    ticks = itertools.count(step=0.5)
    processor = orch.MicrobatchProcessor(
        env.ledger,
        env.upsert,
        lambda batch: orch.run_do_fn(env.do_fn(), batch),
        timer=lambda: next(ticks),
    )
    subscriber = FakeSubscriber([env.messages()])
    report = orch.PubSubDrainer(
        subscriber,
        SUBSCRIPTION,
        processor,
        SanitizationExecutionConfig(),
        monotonic=lambda: next(ticks),
    ).run()
    assert set(report.phase_seconds) == {
        "pull_s",
        "ledger_lookup_s",
        "sanitize_s",
        "bigquery_s",
        "receipts_s",
        "ack_s",
        "reconcile_s",
    }
    assert all(seconds > 0 for seconds in report.phase_seconds.values())
    assert vars(report)["phase_seconds"] == report.phase_seconds


def test_next_microbatch_is_skipped_when_it_would_not_fit():
    env = Env()
    now = [0.0]

    def slow_sanitize(batch):
        now[0] += 900.0  # el microbatch consume 900 s del presupuesto
        return orch.run_do_fn(env.do_fn(), batch)

    processor = orch.MicrobatchProcessor(env.ledger, env.upsert, slow_sanitize)
    subscriber = FakeSubscriber([env.messages(), env.messages(prefix="b")])
    report = orch.PubSubDrainer(
        subscriber,
        SUBSCRIPTION,
        processor,
        SanitizationExecutionConfig(),
        monotonic=lambda: now[0],
    ).run()
    # 900 s ya gastados + 900 s x 1.25 proyectados superan los 1500 s.
    assert report.stop_reason == "runtime_budget"
    assert len(subscriber.requests) == 1
    assert report.messages == 3


# ------------------------------------------------ logs estructurados
def _events(capsys) -> list[dict[str, Any]]:
    lines = capsys.readouterr().out.splitlines()
    return [json.loads(line) for line in lines if line.startswith("{")]


def test_run_emits_structured_events_without_review_text(capsys):
    env = Env()
    report, _ = env.drain([env.messages()])
    events = _events(capsys)
    by_message = {e["message"]: e for e in events}
    started = by_message["Sanitization run started"]
    assert started["run_id"] == report.run_id
    assert started["max_messages"] == 20_000 and started["io_workers"] == 8
    batch = by_message["Microbatch finished"]
    assert batch["run_id"] == report.run_id and batch["batch_index"] == 1
    assert batch["messages"] == 3 and batch["tds_committed"] == 3
    assert batch["batch_seconds"] >= 0
    assert set(batch["phase_seconds"]) == {
        "pull_s",
        "ledger_lookup_s",
        "sanitize_s",
        "bigquery_s",
        "receipts_s",
        "ack_s",
        "reconcile_s",
    }
    closed = by_message["Page closed"]
    assert closed["status"] == "RESOLVED" and closed["page_id"] == env.page_id
    # Un evento por microbatch y por página, nunca por reseña.
    assert len(events) <= 4
    dumped = json.dumps(events, ensure_ascii=False)
    for data, _attrs in env.published:
        text = json.loads(data)["raw"]["texto"]
        if len(text) > 5:  # los textos de 2 letras coincidirían por azar
            assert text not in dumped


def test_each_microbatch_gets_its_own_event(capsys):
    env = Env()
    messages = env.messages()
    env.drain([messages[:2], messages[2:]], microbatch_size=2)
    batches = [
        e for e in _events(capsys) if e["message"] == "Microbatch finished"
    ]
    assert [b["batch_index"] for b in batches] == [1, 2]
    assert [b["messages"] for b in batches] == [2, 1]


def test_pending_pages_are_counted_but_not_logged_as_closed(capsys):
    env = Env()
    env.bq.fail = True
    env.drain([env.messages()])
    events = _events(capsys)
    assert not [e for e in events if e["message"] == "Page closed"]
    batch = next(e for e in events if e["message"] == "Microbatch finished")
    assert batch["pages"] == {"PENDING": 1} and batch["retryable"] == 3


def test_replay_skips_a_bank_with_unreadable_state_and_flags_the_run(
    monkeypatch, capsys
):
    env = Env()
    original = env.ingestion.load

    def load(bank):
        if bank.value == "AZTECA":
            raise ValueError("app_id does not match bank_id")
        return original(bank)

    monkeypatch.setattr(env.ingestion, "load", load)
    backfill = orch.ManifestBackfill(
        env.ingestion,
        env.services().processor(),
        SanitizationExecutionConfig(),
        banks=(BankKey.AZTECA, BANK),
    )
    report = backfill.run()
    # El banco sano se procesa completo aunque el anterior estaba roto.
    assert report.bank_errors == {"AZTECA": "ValueError"}
    assert report.pages == {"RESOLVED": 1} and report.messages == 3
    assert report.exit_code() == orch.EX_TEMPFAIL
    errors = [
        e for e in _events(capsys) if e["message"].startswith("Bank state")
    ]
    assert errors[0]["bank_id"] == "AZTECA" and errors[0]["severity"] == "ERROR"


def test_gcs_pool_follows_the_io_workers(monkeypatch, settings):
    from google.cloud import bigquery, pubsub_v1

    captured = anonymous_gcs(monkeypatch)
    monkeypatch.setattr(bigquery, "Client", lambda **_: Mock())
    monkeypatch.setattr(pubsub_v1, "SubscriberClient", Mock)
    services = orch.build_services(
        settings(), SanitizationExecutionConfig(io_workers=32), PARENT
    )
    assert services.ledger.io_workers == 32
    adapter = captured["_http"].get_adapter("https://storage.googleapis.com")
    # Los hilos más un margen; el defecto de la biblioteca serían 10.
    assert adapter._pool_maxsize == adapter._pool_connections == 36
    assert captured["project"] == "test-project"


@pytest.mark.parametrize(
    ("workers", "pool"), [(1, 10), (6, 10), (8, 12), (16, 20), (64, 68)]
)
def test_pool_never_drops_below_the_library_default(workers, pool):
    from sanitization_pipeline.config import gcs_pool_size

    assert gcs_pool_size(workers) == pool


# ----------------------------------------------- replay rápido (por página)
def make_replay(env: "Env", *, io_workers: int = 8, sanitizer=None, **config):
    from sanitization_pipeline.dlp_transforms import BatchSanitizer
    from sanitization_pipeline.fast_replay import FastReplay

    ledger = ProcessingLedgerRepository(
        env.storage,
        "test-bucket",
        env.ingestion,
        clock=lambda: T0,
        io_workers=io_workers,
    )
    sanitizer = sanitizer or BatchSanitizer(
        user_hash_salt=SALT, clock=lambda: T0
    )
    replay = FastReplay(
        env.ingestion,
        ledger,
        env.upsert,
        sanitizer,
        SanitizationExecutionConfig(**config),
        banks=(BANK,),
    )
    return replay, ledger


def test_fast_replay_loads_a_page_and_closes_it_without_event_receipts():
    env = Env()
    replay, ledger = make_replay(env)
    report = replay.run()
    assert report.mode == "GCS_FAST_REPLAY"
    assert report.exit_code() == orch.EX_OK
    assert report.messages == 3 and report.tds_committed == 3
    assert report.pages == {"RESOLVED": 1} and report.stop_reason == "drained"
    # Sin filtro de longitud y con la regex local aplicada.
    assert len(env.bq.rows) == 3 and env.bq.merges == 1
    assert any(
        "[BBVA_ACCOUNT_NUMBER]" in r["texto_sanitizado"] for r in env.bq.rows
    )
    closure = ledger.page_closure(BANK, env.page_id)
    assert closure is not None and closure.tds_committed == 3
    assert closure.status.value == "RESOLVED" and not closure.missing
    # La diferencia con el modo normal: ningún recibo por reseña.
    assert [n for n in env.bucket.objects if "/_events/" in n] == []
    assert set(report.phase_seconds) >= {
        "capture_read_s",
        "sanitize_s",
        "bigquery_s",
        "closure_s",
    }


def test_fast_replay_is_idempotent_and_skips_closed_pages():
    env = Env()
    replay, _ = make_replay(env)
    replay.run()
    merges, rows = env.bq.merges, len(env.bq.rows)
    report = make_replay(env)[0].run()
    assert report.messages == 0 and report.pages == {}
    assert env.bq.merges == merges and len(env.bq.rows) == rows


def test_fast_replay_batches_pages_by_rows_and_merges_with_bank_filter():
    env = Env()
    for number in (1, 2):
        env.add_page(number, TEXTS)
    # Con 1 hilo la ventana es de 2 páginas; umbral de 4 filas => 2 cargas.
    replay, ledger = make_replay(env, io_workers=1, upsert_batch_rows=4)
    report = replay.run()
    assert report.pages == {"RESOLVED": 3} and report.tds_committed == 9
    assert env.bq.merges == 2
    assert all("T.bank_id IN ('BBVA')" in sql for sql in env.bq.sqls)
    manifests = orch._latest_manifests(env.ingestion, BANK)
    assert ledger.pending_pages(BANK, manifests) == []


def test_latest_manifests_can_be_listed_in_parallel():
    env = Env()
    for number in (1, 2, 3):
        env.add_page(number, TEXTS)
    sequential = orch._latest_manifests(env.ingestion, BANK)
    parallel = orch._latest_manifests(env.ingestion, BANK, workers=4)
    assert len(sequential) == 4
    assert [m.page_id for m in parallel] == [m.page_id for m in sequential]


def test_fast_replay_flags_an_expired_capture_as_a_gap():
    env = Env()
    env.bucket.objects.pop(env.backup)
    replay, ledger = make_replay(env)
    report = replay.run()
    assert report.expired_captures == 1 and report.tds_committed == 0
    closure = ledger.page_closure(BANK, env.page_id)
    assert closure.status.value == "GAPS_DETECTED"
    assert closure.reason == "STAGING_EXPIRED" and closure.missing == 3
    assert env.bq.merges == 0


def test_fast_replay_detects_a_capture_missing_events(monkeypatch):
    from sanitization_pipeline import fast_replay as module

    env = Env()
    original = module.read_committed_capture
    monkeypatch.setattr(
        module,
        "read_committed_capture",
        lambda repo, manifest: original(repo, manifest)[:2],
    )
    replay, ledger = make_replay(env)
    report = replay.run()
    closure = ledger.page_closure(BANK, env.page_id)
    assert report.tds_committed == 2
    assert closure.status.value == "GAPS_DETECTED"
    assert closure.reason == "INCOMPLETE_CAPTURE" and closure.missing == 1


def test_fast_replay_quarantines_without_losing_the_page(monkeypatch):
    env = Env()

    def broken(*args, **kwargs):
        raise ValueError("contract")

    monkeypatch.setattr(
        "sanitization_pipeline.dlp_transforms.SanitizedReviewRecord."
        "from_raw_and_dlp",
        broken,
    )
    replay, ledger = make_replay(env)
    report = replay.run()
    closure = ledger.page_closure(BANK, env.page_id)
    assert report.quarantined == 3 and report.tds_committed == 0
    assert closure.reason == "QUARANTINED" and closure.quarantined == 3
    assert len(closure.quarantined_event_ids) == 3


def test_fast_replay_keeps_pages_open_when_bigquery_fails():
    env = Env()
    env.bq.fail = True
    replay, ledger = make_replay(env)
    report = replay.run()
    assert report.transient_failure
    assert report.stop_reason == "transient_failure"
    assert report.exit_code() == orch.EX_TEMPFAIL
    assert ledger.page_closure(BANK, env.page_id) is None
    env.bq.fail = False
    assert make_replay(env)[0].run().pages == {"RESOLVED": 1}


def test_fast_replay_stops_between_windows_when_a_load_fails():
    env = Env()
    for number in (1, 2):
        env.add_page(number, TEXTS)
    env.bq.fail = True
    # Ventana de 2 páginas con umbral de 1 fila: la primera carga ya falla.
    replay, ledger = make_replay(env, io_workers=1, upsert_batch_rows=1)
    report = replay.run()
    assert report.transient_failure and report.pages == {}
    assert ledger.page_closure(BANK, env.page_id) is None


def test_fast_replay_does_not_close_a_page_with_retryable_events():
    from sanitization_pipeline.dlp_transforms import SanitizedBatch

    env = Env()

    class Retrying:
        def sanitize(self, envelopes):
            return SanitizedBatch(retryable=[Mock()] * len(envelopes))

    replay, ledger = make_replay(env, sanitizer=Retrying())
    report = replay.run()
    assert report.pages == {} and report.events_retryable == 3
    assert ledger.page_closure(BANK, env.page_id) is None


def test_fast_replay_stops_on_the_time_budget_after_loading_what_it_read():
    from sanitization_pipeline.dlp_transforms import BatchSanitizer
    from sanitization_pipeline.fast_replay import FastReplay

    env = Env()
    for number in (1, 2):
        env.add_page(number, TEXTS)
    now = [0.0]
    inner = BatchSanitizer(user_hash_salt=SALT, clock=lambda: T0)

    class Slow:
        def sanitize(self, envelopes):
            now[0] += 2000.0  # cada ventana consume más que el presupuesto
            return inner.sanitize(envelopes)

    ledger = ProcessingLedgerRepository(
        env.storage,
        "test-bucket",
        env.ingestion,
        clock=lambda: T0,
        io_workers=1,
    )
    replay = FastReplay(
        env.ingestion,
        ledger,
        env.upsert,
        Slow(),  # type: ignore[arg-type]
        SanitizationExecutionConfig(upsert_batch_rows=100_000),
        banks=(BANK,),
        monotonic=lambda: now[0],
    )
    report = replay.run()
    # La primera ventana (2 páginas) se carga y se cierra antes de parar.
    assert report.stop_reason == "runtime_budget"
    assert report.pages == {"RESOLVED": 2}


def test_fast_replay_skips_a_bank_with_unreadable_state(monkeypatch):
    from sanitization_pipeline.dlp_transforms import BatchSanitizer
    from sanitization_pipeline.fast_replay import FastReplay

    env = Env()
    original = env.ingestion.load

    def load(bank):
        if bank.value == "AZTECA":
            raise ValueError("app_id does not match bank_id")
        return original(bank)

    monkeypatch.setattr(env.ingestion, "load", load)
    ledger = ProcessingLedgerRepository(
        env.storage, "test-bucket", env.ingestion, clock=lambda: T0
    )
    replay = FastReplay(
        env.ingestion,
        ledger,
        env.upsert,
        BatchSanitizer(user_hash_salt=SALT),
        SanitizationExecutionConfig(),
        banks=(BankKey.AZTECA, BANK),
    )
    report = replay.run()
    assert report.bank_errors == {"AZTECA": "ValueError"}
    assert report.pages == {"RESOLVED": 1}
    assert report.exit_code() == orch.EX_TEMPFAIL


def test_fast_replay_runner_refuses_cloud_dlp_and_runs_end_to_end(capsys):
    from sanitization_pipeline import fast_replay as module
    from sanitization_pipeline.config import PreflightError

    env = Env()
    with pytest.raises(PreflightError):
        module.run_fast_replay(
            SanitizationExecutionConfig(use_cloud_dlp_api=True), Mock(), PARENT
        )
    services = env.services()
    code = module.run_fast_replay(
        SanitizationExecutionConfig(),
        Mock(user_hash_salt=SALT),
        PARENT,
        services_factory=lambda *_: services,
    )
    assert code == orch.EX_OK
    finished = [
        e
        for e in _events(capsys)
        if e["message"] == "Sanitization run finished"
    ]
    assert finished[-1]["mode"] == "GCS_FAST_REPLAY"
    assert finished[-1]["tds_committed"] == 3
