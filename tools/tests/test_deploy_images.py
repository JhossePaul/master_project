"""Pruebas de la herramienta de despliegue de imágenes (sin red ni Pulumi)."""

import json
from pathlib import Path

import pytest

from tools import deploy_images as di

REGISTRY = "us-central1-docker.pkg.dev/p/voc-containers-repo"
OLD, NEW = "a" * 40, "b" * 40
D = {"o": "sha256:" + "1" * 64, "n": "sha256:" + "2" * 64}


def listing(entries: list[tuple[str, list[str] | str]]) -> str:
    return json.dumps(
        [{"version": digest, "tags": tags} for digest, tags in entries]
    )


class Fake:
    """Sustituye gcloud y pulumi; registra los comandos ejecutados."""

    def __init__(
        self,
        ingestion,
        sanitization,
        current=None,
        preview=None,
        ml=None,
        api=None,
    ):
        self.images = {
            f"{REGISTRY}/ingestion-worker": ingestion,
            f"{REGISTRY}/sanitization-pipeline": sanitization,
            f"{REGISTRY}/ml-inference": ingestion if ml is None else ml,
            f"{REGISTRY}/api-backend": ingestion if api is None else api,
        }
        self.current = current or {}
        self.preview = (
            preview or "Resources:\n    ~ 2 to update\n    52 unchanged"
        )
        self.calls: list[list[str]] = []

    def __call__(self, args, cwd):
        args = list(args)
        self.calls.append(args)
        if args[0] == "gcloud":
            return self.images[args[5]]
        if args[:3] == ["pulumi", "config", "get"]:
            key = args[-1].split(":", 1)[1]
            if key not in self.current:
                raise di.DeployError("no existe")
            return self.current[key]
        if args[:2] == ["pulumi", "preview"]:
            return self.preview
        return "ok"

    def ran(self, *prefix):
        return [c for c in self.calls if c[: len(prefix)] == list(prefix)]


def both(new_first=True):
    entries = [(D["n"], [NEW]), (D["o"], [OLD, "latest"])]
    return listing(entries), listing(entries)


def run(fake, **kw):
    lines: list[str] = []
    code = di.deploy(
        project="p",
        region="us-central1",
        stack="dev",
        sha=kw.pop("sha", None),
        apply=kw.pop("apply", False),
        run=fake,
        out=lines.append,
        infra_dir=Path("."),
    )
    return code, "\n".join(lines)


def test_picks_the_latest_sha_present_in_every_image_and_sets_every_key():
    fake = Fake(*both())
    code, text = run(fake)
    assert code == 0 and f"Versión: {NEW}" in text
    sets = fake.ran("pulumi", "config", "set")
    assert {c[-2].split(":", 1)[1] for c in sets} == {
        "ingestion_worker_image",
        "sanitization_job_image",
        "ml_inference_image",
        "api_backend_image",
    }
    assert f"{REGISTRY}/ingestion-worker:{NEW}@{D['n']}" in {
        c[-1] for c in sets
    }
    assert not fake.ran("pulumi", "up") and "--apply" in text


def test_a_sha_built_in_only_one_image_is_never_chosen():
    ingestion = listing([(D["n"], [NEW]), (D["o"], [OLD])])
    sanitization = listing([(D["o"], [OLD])])
    code, text = run(Fake(ingestion, sanitization))
    assert f"Versión: {OLD}" in text


def test_ml_inference_must_share_the_sha():
    ingestion, sanitization = both()
    ml = listing([(D["o"], [OLD])])
    code, text = run(Fake(ingestion, sanitization, ml=ml))
    assert f"Versión: {OLD}" in text


def test_api_backend_must_share_the_sha():
    ingestion, sanitization = both()
    api = listing([(D["o"], [OLD])])
    code, text = run(Fake(ingestion, sanitization, api=api))
    assert f"Versión: {OLD}" in text


def test_refuses_when_no_sha_is_common():
    fake = Fake(listing([(D["n"], [NEW])]), listing([(D["o"], [OLD])]))
    with pytest.raises(di.DeployError, match="ninguna versión"):
        run(fake)


def test_explicit_sha_must_exist_in_every_image():
    fake = Fake(*both())
    with pytest.raises(di.DeployError, match="no existe"):
        run(fake, sha="c" * 40)
    with pytest.raises(di.DeployError, match="40 hex"):
        run(Fake(*both()), sha="latest")
    code, text = run(Fake(*both()), sha=OLD)
    assert f"Versión: {OLD}" in text


def test_ignores_mutable_tags_and_malformed_digests():
    entries = listing([("not-a-digest", [NEW]), (D["o"], "latest," + OLD)])
    code, text = run(Fake(entries, entries))
    assert f"Versión: {OLD}" in text


def test_no_changes_when_already_pinned():
    ref = lambda n, sha, d: f"{REGISTRY}/{n}:{sha}@{d}"  # noqa: E731
    fake = Fake(
        *both(),
        current={
            "ingestion_worker_image": ref("ingestion-worker", NEW, D["n"]),
            "sanitization_job_image": ref("sanitization-pipeline", NEW, D["n"]),
            "ml_inference_image": ref("ml-inference", NEW, D["n"]),
            "api_backend_image": ref("api-backend", NEW, D["n"]),
        },
        preview="Resources:\n    54 unchanged",
    )
    code, text = run(fake, apply=True)
    assert "Nada que desplegar" in text
    assert not fake.ran("pulumi", "config", "set") and not fake.ran(
        "pulumi", "up"
    )


def test_apply_runs_up_after_a_safe_preview():
    fake = Fake(*both())
    code, text = run(fake, apply=True)
    assert code == 0 and fake.ran("pulumi", "up") and "git commit" in text


@pytest.mark.parametrize(
    "summary",
    ["- 1 to delete", "+-1 to replace", "~ 1 to update\n    - 2 to delete"],
)
def test_apply_refuses_a_preview_that_deletes_or_replaces(summary):
    fake = Fake(*both(), preview=f"Resources:\n    {summary}\n    50 unchanged")
    with pytest.raises(di.DeployError, match="borra o reemplaza"):
        run(fake, apply=True)
    assert not fake.ran("pulumi", "up")


def test_main_reports_errors_and_resolves_the_project(monkeypatch, capsys):
    monkeypatch.setattr(di, "run_command", lambda args, cwd=None: " \n")
    assert di.main([]) == 1
    assert "indica --project" in capsys.readouterr().err
    monkeypatch.setattr(
        di,
        "deploy",
        lambda **kw: (print("proyecto", kw["project"], kw["stack"]), 0)[1],
    )
    monkeypatch.setattr(di, "run_command", lambda args, cwd=None: "proj\n")
    assert di.main(["--stack", "dev"]) == 0
    assert "proyecto proj dev" in capsys.readouterr().out


def test_run_command_wraps_failures(monkeypatch):
    class Result:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(di.subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(di.DeployError, match="boom"):
        di.run_command(["gcloud", "x"])
    Result.returncode, Result.stdout = 0, "fine"
    assert di.run_command(["gcloud", "x"]) == "fine"
