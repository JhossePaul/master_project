from pathlib import Path
from types import SimpleNamespace

import pytest
from ml_inference.kaggle_check import run_check
from ml_inference.rescore import KernelFailed, RescoreError, raise_on_error


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
