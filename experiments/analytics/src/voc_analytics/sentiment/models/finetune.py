"""M4 y M5: encoder ajustado con la plata (EPIC-5, feature 5.4).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.sentiment.models.finetune robertuito \\
        [--epochs 2] [--label-smoothing 0.1] [--limit N]

* Parte de un checkpoint de sentimiento de `pysentimiento` (ver `encoder.py`)
  y ajusta **todos** los pesos con la plata (`prompt_v3`), un ejemplo por
  texto único: los mismos 63 720 textos que M1.
* El 5 % de los textos, agrupados por `clave`, queda como validación sobre la
  plata. Con ella se elige la mejor época; el oro *dev* no interviene.
* AdamW, *warm-up* lineal del 6 % y decaimiento lineal; recorte de gradiente
  en 1.0; semilla fija.
* **Memoria (Mac de 8 GB, límite MPS de 5.3 GB):** lote 8 con acumulación ×4
  (lote efectivo 32), embeddings congelados y caché de MPS vaciada cada 100
  pasos. Con lote 16 o 32 directo, MPS se queda sin memoria. En CUDA
  (Kaggle): lote 32, fp16 y sin congelar (`encoder.train_defaults`).
* `--seed` y `--tag` permiten repetir con otras semillas (`M4_<encoder><tag>`).
* **M5** (`--label-smoothing ε > 0`): la misma receta con *label smoothing*
  en la entropía cruzada (Szegedy et al., 2016; para etiquetas ruidosas,
  Gao et al., 2024). El objetivo reparte ε entre las tres clases, lo que
  limita la confianza en la plata cuando se equivoca. Se llama
  `M5_<encoder>_ls<ε><tag>`. ε se elige con la validación sobre la plata.
* Predice el oro *dev* y `holdout_nuevo`, y escribe en `data/models/preds/`
  (`M4_<encoder>`). Los pesos no se guardan (~0.5 GB por modelo).
"""

import argparse
import copy
import random
import time

import numpy as np
import polars as pl
import torch

from voc_analytics.sentiment.data import (
    CLASSES,
    gold,
    holdout_rows,
    holdout_texts,
    save_predictions,
    silver_rows,
    training_texts,
)
from voc_analytics.sentiment.encoder import (
    ENCODERS,
    SEED,
    Amp,
    batches,
    collate,
    device,
    empty_cache,
    encode,
    freeze_embeddings,
    load,
    predict_proba,
    seed_all,
    train_defaults,
    val_split,
)
from voc_analytics.sentiment.metrics import quality


def frame(keys: pl.DataFrame, proba: np.ndarray) -> pl.DataFrame:
    return keys.with_columns(
        pred=pl.Series(np.asarray(CLASSES)[proba.argmax(1)], dtype=pl.String),
        **{f"p_{c}": pl.Series(proba[:, i]) for i, c in enumerate(CLASSES)},
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("encoder", choices=sorted(ENCODERS))
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--batch", type=int, default=None)
    ap.add_argument(
        "--accum",
        type=int,
        default=None,
        help="pasos de acumulación (lote efectivo = batch × accum)",
    )
    ap.add_argument(
        "--label-smoothing",
        type=float,
        default=0.0,
        help="ε del label smoothing; > 0 convierte la corrida en M5",
    )
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--tag", default="", help="sufijo del nombre del modelo")
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="prueba rápida con N textos; no guarda predicciones",
    )
    args = ap.parse_args()
    seed_all(args.seed)
    dev_t = device()
    defaults = train_defaults(dev_t)
    args.batch = args.batch or defaults["batch"]
    args.accum = args.accum or defaults["accum"]
    amp = Amp(dev_t)

    rows = silver_rows()
    train = training_texts(rows)
    if args.limit:
        train = train.sample(args.limit, seed=SEED)
    hold = holdout_texts(holdout_rows(rows))
    gdev = gold().filter(
        (pl.col("particion") == "dev") & (pl.col("oro") != "NA")
    )

    tok, model = load(args.encoder)
    if defaults["freeze_embeddings"]:
        freeze_embeddings(model)
    model.to(dev_t)
    is_val = val_split(train["clave"].to_numpy())
    ids = encode(tok, train["texto_sanitizado"].to_list())
    y = np.array([CLASSES.index(c) for c in train["plata"]])
    tr_idx, va_idx = np.flatnonzero(~is_val), np.flatnonzero(is_val)
    tr_ids = [ids[i] for i in tr_idx]
    va_ids = [ids[i] for i in va_idx]

    rng = random.Random(args.seed)  # noqa: S311 - muestreo, no criptografía
    steps = args.epochs * -(-len(tr_ids) // (args.batch * args.accum))
    opt = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=args.lr,
        weight_decay=0.01,
    )
    warm = int(0.06 * steps)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt,
        lambda s: min(
            (s + 1) / max(warm, 1), max(0.0, (steps - s) / max(steps - warm, 1))
        ),
    )
    history, best, best_state = [], -1.0, None
    train_start = time.perf_counter()
    for epoch in range(1, args.epochs + 1):
        model.train()
        start, seen, total = time.perf_counter(), 0, 0.0
        for step, idx in enumerate(batches(tr_ids, args.batch, True, rng)):
            input_ids, mask = collate(tr_ids, idx, tok.pad_token_id, dev_t)
            labels = torch.from_numpy(y[tr_idx][idx]).to(dev_t)
            with amp.autocast():
                logits = model(input_ids=input_ids, attention_mask=mask).logits
            loss = torch.nn.functional.cross_entropy(
                logits.float(), labels, label_smoothing=args.label_smoothing
            )
            amp.backward(loss / args.accum)
            if (step + 1) % args.accum == 0:
                amp.step(opt, model.parameters())
                sched.step()
                opt.zero_grad()
            seen += len(idx)
            total += loss.item() * len(idx)
            if step % 100 == 99:
                empty_cache(dev_t)
            if step % 200 == 0:
                print(
                    f"época {epoch} paso {step} pérdida {total / seen:.4f}"
                    f" {seen / (time.perf_counter() - start):.0f} textos/s",
                    flush=True,
                )
        proba, _ = predict_proba(model, tok, va_ids)
        val = quality(
            np.asarray(CLASSES)[y[va_idx]], np.asarray(CLASSES)[proba.argmax(1)]
        )
        history.append(
            {
                "epoca": epoch,
                "perdida_entrenamiento": round(total / seen, 4),
                "textos_por_segundo": round(
                    seen / (time.perf_counter() - start)
                ),
                "val_macro_f1": round(val["macro_f1"], 4),
                "val_kappa": round(val["kappa"], 4),
            }
        )
        print(history[-1], flush=True)
        if val["macro_f1"] > best:
            best = val["macro_f1"]
            best_state = copy.deepcopy(
                {k: v.detach().cpu() for k, v in model.state_dict().items()}
            )
    train_secs = time.perf_counter() - train_start
    if args.limit:
        return
    model.load_state_dict(best_state)

    p_dev, _ = predict_proba(
        model, tok, encode(tok, gdev["texto_sanitizado"].to_list())
    )
    p_hold, speed = predict_proba(
        model, tok, encode(tok, hold["texto_sanitizado"].to_list())
    )
    name = (
        f"M5_{args.encoder}_ls{args.label_smoothing:g}{args.tag}"
        if args.label_smoothing
        else f"M4_{args.encoder}{args.tag}"
    )
    save_predictions(
        name,
        frame(gdev.select("item_id"), p_dev),
        frame(hold.select("text_id"), p_hold),
        {
            "modelo": name,
            "checkpoint": ENCODERS[args.encoder],
            "entrada": "texto_sanitizado",
            "etiqueta": "plata prompt_v3",
            "textos_entrenamiento": len(tr_ids),
            "textos_validacion_plata": len(va_ids),
            "epocas": args.epochs,
            "lr": args.lr,
            "batch": args.batch,
            "acumulacion": args.accum,
            "label_smoothing": args.label_smoothing,
            "semilla": args.seed,
            "embeddings_congelados": defaults["freeze_embeddings"],
            "epoca_elegida": max(history, key=lambda h: h["val_macro_f1"])[
                "epoca"
            ],
            "historial": history,
            "segundos_ajuste": round(train_secs),
            "dispositivo": str(dev_t),
            "equipo": (
                torch.cuda.get_device_name(0)
                if dev_t.type == "cuda"
                else "Mac M2 8 GB"
            ),
            "inferencia": speed,
        },
    )
    print(name, "listo", flush=True)


if __name__ == "__main__":
    main()
