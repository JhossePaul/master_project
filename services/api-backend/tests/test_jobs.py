"""Lanzador de Jobs: la misma petición que ``ml-inference`` y lista cerrada."""

from typing import Any

import pytest
from api_backend.jobs import ALLOWED_JOBS, CloudRunJobs


class _Response:
    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return {"name": "operations/abc"}


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append((url, kwargs))
        return _Response()


BASE = (
    "https://run.googleapis.com/v2/projects/test-project/locations/"
    "us-central1/jobs"
)


def test_execute_overrides_the_args_like_ml_inference() -> None:
    session = _Session()
    jobs = CloudRunJobs("test-project", "us-central1", session)
    args = ["promote", "--model-version=v2", "--actor-hash=h", "--reason=ok"]

    assert jobs.execute("voc-ml-promote", args) == "operations/abc"

    url, kwargs = session.calls[0]
    assert url == f"{BASE}/voc-ml-promote:run"
    assert kwargs["json"] == {
        "overrides": {"containerOverrides": [{"args": args}]}
    }
    assert kwargs["timeout"] == 60


def test_the_list_is_closed() -> None:
    assert set(ALLOWED_JOBS) == {
        "voc-ml-training",
        "voc-ml-rescoring",
        "voc-ml-promote",
        "voc-ml-topics-refit",
    }
    session = _Session()
    jobs = CloudRunJobs("test-project", "us-central1", session)
    with pytest.raises(ValueError, match="not allowed"):
        jobs.execute("voc-ml-inference-delta", ["delta"])
    with pytest.raises(ValueError, match="only runs"):
        jobs.execute("voc-ml-training", ["rescore"])
    with pytest.raises(ValueError, match="only runs"):
        jobs.execute("voc-ml-training", [])
    assert session.calls == []


@pytest.mark.parametrize(
    ("project", "region"), [("Bad Project", "us-central1"), ("ok", "nowhere")]
)
def test_rejects_malformed_project_or_region(project: str, region: str) -> None:
    with pytest.raises(ValueError, match="invalid"):
        CloudRunJobs(project, region)
