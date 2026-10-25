"""Lanzador de Jobs de Cloud Run: URL, argumentos y ejecuciones en curso."""

from typing import Any

import pytest
from ml_inference.jobs import CloudRunJobs


class _Response:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self.body


class _Session:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append(("POST", url, kwargs))
        return _Response(self.body)

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append(("GET", url, kwargs))
        return _Response(self.body)


BASE = (
    "https://run.googleapis.com/v2/projects/test-project/locations/"
    "us-central1/jobs/voc-ml-topics-backfill"
)


def test_execute_overrides_the_args() -> None:
    session = _Session({"name": "operations/abc"})
    jobs = CloudRunJobs("test-project", "us-central1", session)
    assert jobs.execute("voc-ml-topics-backfill", ["topics-backfill"]) == (
        "operations/abc"
    )
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("POST", f"{BASE}:run")
    assert kwargs["json"] == {
        "overrides": {"containerOverrides": [{"args": ["topics-backfill"]}]}
    }


@pytest.mark.parametrize(
    ("executions", "expected"),
    [
        ([], False),
        ([{"completionTime": "2026-11-04T10:00:00Z"}], False),
        ([{"completionTime": "x"}, {"name": "sin terminar"}], True),
    ],
)
def test_running_looks_for_unfinished_executions(
    executions: list[dict], expected: bool
) -> None:
    session = _Session({"executions": executions} if executions else {})
    jobs = CloudRunJobs("test-project", "us-central1", session)
    assert jobs.running("voc-ml-topics-backfill") is expected
    method, url, _ = session.calls[0]
    assert (method, url) == ("GET", f"{BASE}/executions")


@pytest.mark.parametrize(
    ("project", "region", "job"),
    [
        ("Proyecto", "us-central1", "voc-ml-promote"),
        ("test-project", "us central1", "voc-ml-promote"),
        ("test-project", "us-central1", "../otro"),
    ],
)
def test_rejects_invalid_names(project: str, region: str, job: str) -> None:
    with pytest.raises(ValueError, match="invalid"):
        CloudRunJobs(project, region, _Session({})).execute(job, [])
