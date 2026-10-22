"""Sube el paquete y lanza corridas de encoders en Kaggle (EPIC-5, 5.4).

Requisitos (una vez, los hace el autor):
* cuenta de Kaggle con el teléfono verificado (habilita GPU e internet);
* token de la API de Kaggle (CLI 2.x): Settings → API → Generate New Token,
  guardado en `~/.kaggle/access_token` (o en `KAGGLE_API_TOKEN`).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.sentiment.kaggle.export_bundle
    uv run python -m voc_analytics.sentiment.kaggle.kaggle_push \\
        dataset <usuario>  # 1.ª vez
    uv run python -m voc_analytics.sentiment.kaggle.kaggle_push \\
        dataset <usuario> --update
    uv run python -m voc_analytics.sentiment.kaggle.kaggle_push \\
        kernel <usuario> <lote>
    uvx kaggle kernels status <usuario>/voc-sentimiento-<lote>
    uvx kaggle kernels output <usuario>/voc-sentimiento-<lote> \\
        -p data/models/kaggle/<lote>

Cada lote es una lista de comandos de `LOTES`. El kernel instala
`pysentimiento`, corre los comandos sobre la GPU (T4) y deja en su salida
`preds/`, `detectores/`, `weights/` (si el lote los guarda) y un log por
comando. Las predicciones descargadas se
copian a `data/models/preds/` y se evalúan en el Mac con `evaluate.py`.
Dataset y kernel son privados.
"""

import json
import subprocess
import sys

from voc_analytics.paths import DATA

BUNDLE = DATA / "kaggle_bundle"
KERNELS = DATA / "kaggle_kernels"
DATASET = "voc-sentimiento-bundle"

# Comandos por lote: módulo de `code/` y sus argumentos.
FINETUNE = "-m voc_analytics.sentiment.models.finetune"
DELORA = "-m voc_analytics.sentiment.models.delora"
LOTES = {
    # Prueba de humo: verifica instalación, GPU y escritura de salidas.
    "humo": [
        f"{FINETUNE} robertuito --epochs 1 --limit 2000",
        f"{DELORA} robertuito --limit 2000 --epochs-detector 2 "
        "--epochs-classifier 1",
    ],
    # M4 con los dos encoders y tres semillas.
    "m4": [
        f"{FINETUNE} {enc} --seed {seed} --tag _s{seed}"
        for enc in ("robertuito", "beto")
        for seed in (1, 2, 3)
    ],
    # Búsqueda de h1, h2 y rango solo con el detector (fuera de muestra).
    "delora_grid": [
        f"{DELORA} robertuito --detector-only --detector-sample 20000 "
        f"--epochs-detector 4 --warmup 1 --h1 {h1} --h2 {h2} --rank {r} "
        f"--tag _h{h1}_{h2}_r{r}"
        for h1, h2 in ((0.5, 0.5), (1, 1), (2, 2), (1, 2), (2, 1))
        for r in (16,)
    ]
    + [
        f"{DELORA} robertuito --detector-only --detector-sample 20000 "
        f"--epochs-detector 4 --warmup 1 --rank {r} --tag _h1_1_r{r}"
        for r in (8, 32)
    ],
    # M5: M4 RoBERTuito con label smoothing, ε ∈ {0.1, 0.2} y tres semillas.
    # ε se elige por macro-F1 medio en la validación sobre la plata.
    "m5": [
        f"{FINETUNE} robertuito --label-smoothing {eps} --seed {seed} "
        f"--tag _s{seed}"
        for eps in (0.1, 0.2)
        for seed in (1, 2, 3)
    ],
    # 5.6, PPI opción B1: M4 RoBERTuito con tres semillas que además predice
    # la muestra sin etiqueta (`sample_ppi`) y guarda los pesos (fp16). El
    # sufijo `_ppi` evita pisar las predicciones de 5.4 con las que se
    # calibró; estos son los modelos con pesos para 5.7 y 5.8.
    "m4_ppi": [
        f"{FINETUNE} robertuito --seed {seed} --tag _s{seed}_ppi "
        "--ppi --save-weights"
        for seed in (1, 2, 3)
    ],
    # M8 completo con la configuración ganadora del grid (F1 del detector
    # contra la plata fuera de muestra): h1=1, h2=2, r=16; detector con todos
    # los pares, 8 épocas con 2 de warm-up y tres semillas.
    "delora": [
        f"{DELORA} robertuito --detector-sample 0 --epochs-detector 8 "
        f"--warmup 2 --h1 1 --h2 2 --rank 16 --seed {seed} --tag _s{seed}"
        for seed in (1, 2, 3)
    ],
}

KERNEL = '''"""Corridas de 5.4 en Kaggle (generado por kaggle_push.py)."""
import os, shutil, subprocess, sys
from pathlib import Path

subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                "pysentimiento>=0.7,<1"], check=True)
src = next(Path("/kaggle/input").rglob("silver_rows.parquet")).parent
work = Path("/kaggle/working")
if (src / "code").is_dir():
    shutil.copytree(src / "code", work / "code", dirs_exist_ok=True)
else:  # Kaggle puede dejar la carpeta como code.zip sin descomprimir.
    shutil.unpack_archive(src / "code.zip", work / "code")
print(sorted(str(p.relative_to(src)) for p in src.rglob("*"))[:40], flush=True)
env = dict(os.environ, VOC_BUNDLE=str(src), VOC_PREDS=str(work / "preds"),
           VOC_WEIGHTS=str(work / "weights"))
logs = work / "logs"
logs.mkdir(exist_ok=True)
for i, cmd in enumerate(COMMANDS):
    print(f"== {i} {cmd}", flush=True)
    with open(logs / f"{i:02d}.log", "w") as log:
        rc = subprocess.run([sys.executable, "-W", "ignore", *cmd.split()],
                            cwd=work / "code", env=env, stdout=log,
                            stderr=subprocess.STDOUT).returncode
    print(f"== {i} rc={rc}", flush=True)
    print(open(logs / f"{i:02d}.log").read()[-3000:], flush=True)
'''


def kaggle(*args: str) -> None:
    # CLI local con argumentos fijos de este script.
    subprocess.run(["uvx", "kaggle", *args], check=True)  # noqa: S603, S607


def dataset(user: str, update: bool) -> None:
    meta = {
        "title": "VOC sentimiento bundle",
        "id": f"{user}/{DATASET}",
        "licenses": [{"name": "other"}],
    }
    (BUNDLE / "dataset-metadata.json").write_text(json.dumps(meta, indent=2))
    if update:
        kaggle(
            "datasets",
            "version",
            "-p",
            str(BUNDLE),
            "-m",
            "update",
            "--dir-mode",
            "zip",
        )
    else:
        kaggle("datasets", "create", "-p", str(BUNDLE), "--dir-mode", "zip")


def kernel(user: str, lote: str) -> None:
    folder = KERNELS / lote
    folder.mkdir(parents=True, exist_ok=True)
    script = f"COMMANDS = {json.dumps(LOTES[lote], indent=4)}\n" + KERNEL
    (folder / "run.py").write_text(script)
    meta = {
        "id": f"{user}/voc-sentimiento-{lote.replace('_', '-')}",
        "title": f"voc-sentimiento-{lote.replace('_', '-')}",
        "code_file": "run.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,
        "dataset_sources": [f"{user}/{DATASET}"],
    }
    (folder / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    kaggle("kernels", "push", "-p", str(folder))


def main() -> None:
    action, user = sys.argv[1], sys.argv[2]
    if action == "dataset":
        dataset(user, "--update" in sys.argv)
    elif action == "kernel":
        kernel(user, sys.argv[3])
    else:
        raise SystemExit(f"acción desconocida: {action}")


if __name__ == "__main__":
    main()
