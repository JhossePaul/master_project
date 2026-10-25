"""Ajuste de RoBERTuito: receta, partición por texto, mejor época y kernel."""

import json
import random
import runpy
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")

from voc_nlp import training  # noqa: E402
from voc_nlp.training import (  # noqa: E402
    TrainParams,
    batches,
    kernel_source,
    lr_factor,
    predict,
    train,
    val_split,
)

# Ids del tokenizador de prueba: <s>=0, </s>=2; una palabra por clase.
WORDS = {0: 8, 1: 5, 2: 10}  # mala → NEG, app → NEU, excelente → POS


def _data(n: int = 240) -> tuple[list[list[int]], np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0)
    labels = rng.integers(0, 3, n)
    ids = [[0, WORDS[int(y)], 4, 2] for y in labels]
    is_val = val_split([f"texto {i}" for i in range(n)], 0.2, 7)
    return ids, labels.astype(np.int64), is_val


def _model(path: Path):
    return transformers.AutoModelForSequenceClassification.from_pretrained(
        path, dtype=torch.float32, local_files_only=True
    )


def _loss(model, ids: list[list[int]], labels: np.ndarray) -> float:
    proba = predict(model, ids)
    return float(-np.log(proba[np.arange(len(labels)), labels]).mean())


FAST = TrainParams(epochs=1, lr=5e-3, batch=16, seed=3)


def test_val_split_groups_by_text_and_is_reproducible() -> None:
    groups = [f"t{i % 4000}" for i in range(8000)]
    mask = val_split(groups, 0.05, 20261019)
    assert (mask[:4000] == mask[4000:]).all()  # un texto, un solo lado
    assert 0.04 < mask.mean() < 0.06
    assert (mask == val_split(groups, 0.05, 20261019)).all()
    assert (mask != val_split(groups, 0.05, 1)).any()


def test_lr_warms_up_and_decays_to_zero() -> None:
    factor = lr_factor(100, 0.06)
    assert factor(0) == pytest.approx(1 / 6)
    assert factor(5) == pytest.approx(1.0)
    assert factor(53) == pytest.approx(0.5)
    assert factor(100) == 0.0


def test_batches_cover_every_text_once() -> None:
    lengths = [random.Random(1).randint(1, 50) for _ in range(500)]  # noqa: S311
    rng = random.Random(2)  # noqa: S311
    shuffled = batches(lengths, 32, True, rng)
    assert sorted(np.concatenate(shuffled).tolist()) == list(range(500))
    ordered = np.concatenate(batches(lengths, 32, False, rng))
    assert [lengths[i] for i in ordered] == sorted(lengths)


def test_one_epoch_lowers_the_loss(tiny_weights: Path) -> None:
    ids, labels, is_val = _data()
    model = _model(tiny_weights)
    before = _loss(model, ids, labels)
    result = train(model, ids, labels, is_val, FAST, device="cpu", log=str)
    assert _loss(model, ids, labels) < before
    assert result.train_texts + result.val_texts == len(ids)
    assert result.val_texts == int(is_val.sum())
    assert result.device == "cpu" and result.best_epoch == 1


def test_same_seed_same_weights(tiny_weights: Path) -> None:
    ids, labels, is_val = _data(96)
    states = []
    for _ in range(2):
        model = _model(tiny_weights)
        train(model, ids, labels, is_val, FAST, device="cpu", log=str)
        states.append(model.state_dict())
    assert all(torch.equal(states[0][k], states[1][k]) for k in states[0])


def test_keeps_the_epoch_with_the_best_validation_macro_f1(
    tiny_weights: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids, labels, is_val = _data(96)
    scores = iter([0.5, 0.9, 0.7])
    snapshots = []
    real_predict = training.predict

    def recording_predict(model, batch_ids, batch: int = 64):
        snapshots.append(
            {k: v.detach().clone() for k, v in model.state_dict().items()}
        )
        return real_predict(model, batch_ids, batch)

    monkeypatch.setattr(training, "macro_f1", lambda *_: next(scores))
    monkeypatch.setattr(training, "predict", recording_predict)
    model = _model(tiny_weights)
    params = TrainParams(epochs=3, lr=5e-3, batch=16)
    result = train(model, ids, labels, is_val, params, device="cpu", log=str)
    assert [h.val_macro_f1 for h in result.history] == [0.5, 0.9, 0.7]
    assert result.best_epoch == 2 and result.best.epoch == 2
    final = model.state_dict()
    assert all(torch.equal(final[k], snapshots[1][k]) for k in final)
    assert not all(torch.equal(final[k], snapshots[2][k]) for k in final)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"is_val": np.zeros(240, dtype=bool)}, "need texts"),
        ({"labels": np.zeros(3, dtype=np.int64)}, "align"),
        ({"ids": [[0] * 200] * 240}, "longer than 128"),
    ],
)
def test_rejects_invalid_inputs(
    tiny_weights: Path, change: dict, message: str
) -> None:
    ids, labels, is_val = _data()
    args = {"ids": ids, "labels": labels, "is_val": is_val, **change}
    with pytest.raises(ValueError, match=message):
        train(_model(tiny_weights), params=FAST, device="cpu", **args)


def test_kernel_runs_without_voc_nlp(
    tiny_weights: Path, tmp_path: Path
) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    ids, labels, is_val = _data(96)
    data = tmp_path / "input" / "voc-training-run1"
    (data / training.BASE_DIR).mkdir(parents=True)
    for item in tiny_weights.iterdir():
        (data / training.BASE_DIR / item.name).write_bytes(item.read_bytes())
    pq.write_table(
        pa.table(
            {"input_ids": ids, "label": labels, "is_val": is_val.tolist()}
        ),
        data / training.TRAIN_FILE,
    )
    pq.write_table(
        pa.table({"key": ["d1", "d2"], "input_ids": ids[:2]}),
        data / training.DEV_FILE,
    )
    work = tmp_path / "working"
    work.mkdir()
    source = kernel_source("run1", FAST, str(tmp_path / "input"), str(work))
    imports = [
        line for line in source.splitlines() if "import" in line.split("#")[0]
    ]
    assert not [line for line in imports if "voc_nlp" in line.split()[:2]]
    script = tmp_path / "kernel.py"
    script.write_text(source)
    runpy.run_path(str(script), run_name="__main__")

    log = json.loads((work / training.LOG_FILE).read_text())
    assert log["run"] == "run1" and log["params"]["seed"] == 3
    assert log["best_epoch"] == 1 and len(log["history"]) == 1
    preds = pq.read_table(work / training.DEV_PREDS_FILE).to_pydict()
    assert preds["key"] == ["d1", "d2"]
    assert np.allclose(
        np.array([preds[f"p_{c}"] for c in training.CLASSES]).sum(axis=0), 1
    )
    safetensors = pytest.importorskip("safetensors")
    weights = work / training.MODEL_DIR / "model.safetensors"
    with safetensors.safe_open(str(weights), framework="pt") as f:
        assert f.get_tensor(next(iter(f.keys()))).dtype == torch.float16
    assert (work / training.MODEL_DIR / "tokenizer.json").exists()
