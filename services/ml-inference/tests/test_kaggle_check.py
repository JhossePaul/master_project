from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from ml_inference.kaggle_check import run_check
from ml_inference.rescore import (
    KaggleApiClient,
    KernelFailed,
    RescoreError,
    raise_on_error,
)


class FakeKaggle:
    user = "autor"

    def __init__(self, statuses: list[str], create_error: str | None = None):
        self.statuses = statuses
        self.create_error = create_error
        self.created: list[Path] = []
        self.deleted: list[str] = []

    def create_dataset(self, folder: Path) -> None:
        if self.create_error:
            raise RescoreError(self.create_error)
        self.created.append(folder)

    def dataset_status(self, ref: str) -> str:
        return self.statuses.pop(0)

    def delete_dataset(self, ref: str) -> None:
        self.deleted.append(ref)


def test_error_in_the_response_is_raised_with_its_reason() -> None:
    with pytest.raises(RescoreError, match="dataset creation failed: sin cupo"):
        raise_on_error(SimpleNamespace(error="sin cupo"), "dataset creation")


def test_response_without_error_passes() -> None:
    raise_on_error(SimpleNamespace(error=None), "dataset creation")
    raise_on_error(SimpleNamespace(), "dataset creation")


def test_check_creates_waits_and_deletes(tmp_path: Path) -> None:
    kaggle = FakeKaggle(["pending", "ready"])
    ref = run_check(
        kaggle,  # type: ignore[arg-type]
        tmp_path,
        "20261025",
        sleep=lambda _: None,
        clock=lambda: 0.0,
    )
    assert ref == "autor/voc-kaggle-check-20261025"
    assert kaggle.created == [tmp_path] and kaggle.deleted == [ref]
    assert (tmp_path / "dataset-metadata.json").exists()


def test_check_deletes_the_dataset_even_if_the_status_fails(
    tmp_path: Path,
) -> None:
    kaggle = FakeKaggle(["error"])
    with pytest.raises(KernelFailed):
        run_check(
            kaggle,  # type: ignore[arg-type]
            tmp_path,
            "20261025",
            sleep=lambda _: None,
            clock=lambda: 0.0,
        )
    assert kaggle.deleted == ["autor/voc-kaggle-check-20261025"]


def test_check_stops_with_the_creation_error(tmp_path: Path) -> None:
    kaggle = FakeKaggle([], create_error="Kaggle dataset creation failed: x")
    with pytest.raises(RescoreError, match="creation failed"):
        run_check(kaggle, tmp_path, "20261025")  # type: ignore[arg-type]
    assert kaggle.deleted == []


def _http_error(code: int) -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = code
    return requests.exceptions.HTTPError(response=response)


def _client(api: Any) -> KaggleApiClient:
    client = KaggleApiClient.__new__(KaggleApiClient)
    client.api = api
    return client


@pytest.mark.parametrize("code", [403, 404])
def test_a_just_created_dataset_is_pending_not_failed(code: int) -> None:
    class Api:
        def dataset_status(self, ref: str) -> str:
            raise _http_error(code)

    assert _client(Api()).dataset_status("autor/x") == "pending"


def test_other_http_errors_are_not_hidden() -> None:
    class Api:
        def dataset_status(self, ref: str) -> str:
            raise _http_error(500)

    with pytest.raises(requests.exceptions.HTTPError):
        _client(Api()).dataset_status("autor/x")


def test_the_dataset_keeps_its_subfolders(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    class Api:
        def dataset_create_new(self, folder: str, **kwargs: Any) -> Any:
            seen.update(kwargs)
            return SimpleNamespace(error="")

    _client(Api()).create_dataset(tmp_path)
    assert seen["dir_mode"] == "zip" and seen["public"] is False
