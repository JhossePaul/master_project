"""M8: Delora adaptado a un encoder (Yuan, Chen y Zhang, 2025; EPIC-5, 5.4).

Uso (desde experiments/analytics):
    uv run python -m voc_analytics.sentiment.models.delora robertuito \\
        [--limit N] [--h1 1 --h2 1]

**Etapa 1, detector de dos LoRA** sobre el encoder congelado, con las
**estrellas** (1–2 `NEG`, 3 `NEU`, 4–5 `POS`) como etiqueta ruidosa:

* LoRA limpia Δw_c y ruidosa Δw_n (rango r) en `query`, `value` y las capas
  lineales de la cabeza de clasificación. Pasadas: `c` (w0 + Δw_c), `n`
  (w0 + Δw_n) y `cn` (w0 + Δw_c + Δw_n).
* L_ce = CE de la pasada `cn` contra las estrellas.
* L_LoRA = λ · [τ1(t) ‖Δw_c − Δw_c(t−1)‖ + τ2(t) ‖Δw_n − Δw_n(t−1)‖], con
  τ1(t) = t^h1 y τ2(t) = t^−h2, donde t es la época y t−1 la instantánea al
  cierre de la época anterior (Eq. 4).
* Probabilidad de limpia: p_c(x, y) = σ(CE_n(x, y) − CE_c(x, y)). **Corrige
  la Eq. 5 del paper**, que tal como está escrita contradice la Eq. 3: limpia
  si CE_c < CE_n (`references.md`, 1.3).
* L_Detector (Eq. 6), después del *warm-up*: positivos = pares cuya
  pseudo-etiqueta coincide con las estrellas, −log p_c(x, y); negativos = la
  etiqueta volteada al azar a otra clase, −log(1 − p_c(x, y_volteada)). **La
  pseudo-etiqueta es la plata de Gemini** (en el paper, GPT-4o).
* **La Eq. 6 se implementa como una BCE estándar** (objetivo 1 para (x, y),
  0 para (x, y_volteada)), promediada sobre los N_p positivos. Tal como está
  escrita, ℓ_nll(p_c, y) + ℓ_nll(1 − p_c, y^n), tiene tres problemas:
  (1) arrastra el signo de la Eq. 5, así que minimizarla empujaría a la LoRA
  limpia a ajustar peor los pares limpios; (2) aplica una NLL multiclase a
  una probabilidad escalar con una etiqueta de clase; (3) no indica que el
  segundo p_c se evalúa en y^n, y leída literalmente (el mismo p_c(x, y) en
  ambos términos) la pérdida es degenerada.
* Selección (Eq. 3): D_c = {CE_c < CE_n} con la etiqueta de estrellas.

**Etapa 2, clasificador:** el mismo encoder, ajuste completo como M4.

* `M8_<encoder>`: CE en D_c con sus estrellas + *reversed cross-entropy* en
  el resto, re-etiquetado con la plata (Eq. 8; log q recortado en 1e−4, como
  en la RCE de Wang et al., 2019).
* `M8_<encoder>_solo_limpias`: solo D_c, sin re-etiquetado. Mide cuánto
  aporta el detector por sí mismo.

Memoria y dispositivo (`encoder.train_defaults`): en el Mac de 8 GB, lote 8
con acumulación ×4 y embeddings congelados en la etapa 2; en CUDA (Kaggle),
lote 32, fp16 y sin congelar. `--detector-sample 0` entrena el detector con
todos los pares. `--seed` y `--tag` permiten repetir con otras semillas.

Diferencias con el paper, declaradas: encoder de ~110 M en vez de
Llama-3.1-8B, menos épocas y un detector entrenado con una submuestra de
20 000 pares que después puntúa todos (presupuesto del Mac: ~9 pares/s en
MPS), y h1, h2 y λ sin valores publicados. Entrena sobre pares (texto
único, estrellas) sin ponderar.

Escribe predicciones en `data/models/preds/` y el diagnóstico del detector
(contra la plata y contra el oro *dev*) en su `.json`.
"""

import argparse
import copy
import json
import math
import random
import time

import numpy as np
import polars as pl
import torch
from torch import nn

from voc_analytics.sentiment.data import (
    CLASSES,
    PREDS,
    gold,
    holdout_rows,
    holdout_texts,
    save_predictions,
    silver_rows,
    training_star_pairs,
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
from voc_analytics.sentiment.models.finetune import frame


class DualLoRALinear(nn.Module):
    """Capa lineal congelada con dos adaptadores de bajo rango."""

    def __init__(self, base: nn.Linear, r: int, alpha: float):
        super().__init__()
        self.base = base
        for p in self.base.parameters():
            p.requires_grad = False
        self.scale = alpha / r
        self.mode = "cn"
        for tag in ("c", "n"):
            a = nn.Parameter(torch.empty(r, base.in_features))
            nn.init.kaiming_uniform_(a, a=math.sqrt(5))
            setattr(self, f"A_{tag}", a)
            setattr(
                self,
                f"B_{tag}",
                nn.Parameter(torch.zeros(base.out_features, r)),
            )

    def forward(self, x):
        out = self.base(x)
        for tag in ("c", "n"):
            if tag in self.mode:
                a, b = getattr(self, f"A_{tag}"), getattr(self, f"B_{tag}")
                out = out + (x @ a.T @ b.T) * self.scale
        return out


def wrap(model, r: int, alpha: float) -> list[DualLoRALinear]:
    for p in model.parameters():
        p.requires_grad = False
    layers = []
    for name, module in list(model.named_modules()):
        for child_name, child in list(module.named_children()):
            full = f"{name}.{child_name}" if name else child_name
            target = child_name in ("query", "value") or (
                full.startswith("classifier") and isinstance(child, nn.Linear)
            )
            if target and isinstance(child, nn.Linear):
                layer = DualLoRALinear(child, r, alpha)
                setattr(module, child_name, layer)
                layers.append(layer)
    return layers


def set_mode(layers, mode: str) -> None:
    for layer in layers:
        layer.mode = mode


def lora_params(layers, tag: str) -> list[nn.Parameter]:
    return [
        p
        for layer in layers
        for p in (getattr(layer, f"A_{tag}"), getattr(layer, f"B_{tag}"))
    ]


def per_sample_ce(logits, labels):
    return nn.functional.cross_entropy(logits, labels, reduction="none")


def detector(args, tok, model, ids, y_star, y_silver, dev_t, rng):
    layers = wrap(model, args.rank, 2 * args.rank)
    model.to(dev_t)
    params_c, params_n = lora_params(layers, "c"), lora_params(layers, "n")
    opt = torch.optim.AdamW(params_c + params_n, lr=args.lr_lora)
    amp = Amp(dev_t)
    positive = torch.from_numpy(y_star == y_silver)
    snap = None
    history = []
    for epoch in range(1, args.epochs_detector + 1):
        warm = epoch <= args.warmup
        tau1, tau2 = epoch**args.h1, epoch ** (-args.h2)
        start, seen, sums = time.perf_counter(), 0, np.zeros(3)
        model.train()
        for step, idx in enumerate(batches(ids, args.batch, True, rng)):
            input_ids, mask = collate(ids, idx, tok.pad_token_id, dev_t)
            ys = torch.from_numpy(y_star[idx]).to(dev_t)
            set_mode(layers, "cn")
            with amp.autocast():
                logits_cn = model(
                    input_ids=input_ids, attention_mask=mask
                ).logits
            loss_ce = nn.functional.cross_entropy(logits_cn.float(), ys)
            loss = loss_ce
            if snap is not None:
                dc = torch.sqrt(
                    sum(
                        ((p - s) ** 2).sum()
                        for p, s in zip(params_c, snap[0], strict=True)
                    )
                    + 1e-12
                )
                dn = torch.sqrt(
                    sum(
                        ((p - s) ** 2).sum()
                        for p, s in zip(params_n, snap[1], strict=True)
                    )
                    + 1e-12
                )
                loss = loss + args.lam * (tau1 * dc + tau2 * dn)
            loss_det = torch.zeros((), device=dev_t)
            if not warm:
                with amp.autocast():
                    set_mode(layers, "c")
                    lc = model(input_ids=input_ids, attention_mask=mask).logits
                    set_mode(layers, "n")
                    ln = model(input_ids=input_ids, attention_mask=mask).logits
                lc, ln = lc.float(), ln.float()
                flip = (ys + torch.randint(1, 3, ys.shape, device=dev_t)) % 3
                p_obs = torch.sigmoid(
                    per_sample_ce(ln, ys) - per_sample_ce(lc, ys)
                )
                p_flip = torch.sigmoid(
                    per_sample_ce(ln, flip) - per_sample_ce(lc, flip)
                )
                # Eq. 6 como BCE (ver docstring): ambos términos sobre los
                # positivos (D_p); el negativo es su misma muestra con la
                # etiqueta volteada.
                pos = positive[idx].to(dev_t)
                if pos.any():
                    loss_det = (
                        -torch.log(p_obs[pos] + 1e-8)
                        - torch.log(1 - p_flip[pos] + 1e-8)
                    ).mean()
                    loss = loss + loss_det
            amp.backward(loss / args.accum)
            if (step + 1) % args.accum == 0:
                amp.step(opt, params_c + params_n)
                opt.zero_grad()
            seen += len(idx)
            sums += len(idx) * np.array(
                [loss.item(), loss_ce.item(), loss_det.item()]
            )
            if step % 100 == 99:
                empty_cache(dev_t)
            if step % 200 == 0:
                print(
                    f"detector época {epoch} paso {step} "
                    f"pérdida {sums[0] / seen:.4f} "
                    f"{seen / (time.perf_counter() - start):.0f} pares/s",
                    flush=True,
                )
        snap = (
            [p.detach().clone() for p in params_c],
            [p.detach().clone() for p in params_n],
        )
        history.append(
            {
                "epoca": epoch,
                "warm_up": warm,
                "perdida": round(sums[0] / seen, 4),
                "perdida_ce": round(sums[1] / seen, 4),
                "perdida_detector": round(sums[2] / seen, 4),
                "pares_por_segundo": round(
                    seen / (time.perf_counter() - start)
                ),
            }
        )
        print(history[-1], flush=True)
    return layers, history


@torch.no_grad()
def clean_scores(model, layers, tok, ids, labels, dev_t) -> np.ndarray:
    """CE_n − CE_c por muestra (> 0: limpia según la Eq. 3)."""
    model.eval()
    out = np.zeros(len(ids), dtype=np.float32)
    for idx in batches(ids, 128, False, random.Random(0)):  # noqa: S311
        input_ids, mask = collate(ids, idx, tok.pad_token_id, dev_t)
        ys = torch.from_numpy(labels[idx]).to(dev_t)
        with Amp(dev_t).autocast():
            set_mode(layers, "c")
            lc = model(input_ids=input_ids, attention_mask=mask).logits
            set_mode(layers, "n")
            ln = model(input_ids=input_ids, attention_mask=mask).logits
        cc = per_sample_ce(lc.float(), ys)
        cn = per_sample_ce(ln.float(), ys)
        out[idx] = (cn - cc).float().cpu().numpy()
    return out


def detection_quality(clean: np.ndarray, truly_noisy: np.ndarray) -> dict:
    flagged = ~clean
    tp = int((flagged & truly_noisy).sum())
    prec = tp / max(int(flagged.sum()), 1)
    rec = tp / max(int(truly_noisy.sum()), 1)
    return {
        "n": int(len(clean)),
        "marcadas_ruidosas": int(flagged.sum()),
        "ruidosas_reales": int(truly_noisy.sum()),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1": round(2 * prec * rec / max(prec + rec, 1e-9), 4),
    }


def classifier(args, encoder, tok_ids, y_target, use_rce, va, dev_t, rng):
    """Etapa 2: ajuste completo; CE en limpias, RCE en re-etiquetadas."""
    tok, model = load(encoder)
    if train_defaults(dev_t)["freeze_embeddings"]:
        freeze_embeddings(model)
    model.to(dev_t)
    amp = Amp(dev_t)
    steps = args.epochs_classifier * -(
        -len(tok_ids) // (args.batch * args.accum)
    )
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
    best, best_state, history = -1.0, None, []
    log_q_floor = math.log(1e-4)
    for epoch in range(1, args.epochs_classifier + 1):
        model.train()
        start, seen = time.perf_counter(), 0
        for step, idx in enumerate(batches(tok_ids, args.batch, True, rng)):
            input_ids, mask = collate(tok_ids, idx, tok.pad_token_id, dev_t)
            ys = torch.from_numpy(y_target[idx]).to(dev_t)
            rce = torch.from_numpy(use_rce[idx]).to(dev_t)
            with amp.autocast():
                logits = model(input_ids=input_ids, attention_mask=mask).logits
            logits = logits.float()
            ce = per_sample_ce(logits, ys)
            p_true = torch.softmax(logits, -1).gather(1, ys[:, None])[:, 0]
            # RCE con q one-hot recortado: −Σ_k p_k log q_k = −A (1 − p_y).
            rce_loss = -log_q_floor * (1 - p_true)
            loss = torch.where(rce, rce_loss, ce).mean()
            amp.backward(loss / args.accum)
            if (step + 1) % args.accum == 0:
                amp.step(opt, model.parameters())
                sched.step()
                opt.zero_grad()
            seen += len(idx)
            if step % 100 == 99:
                empty_cache(dev_t)
        va_ids, va_y = va
        proba, _ = predict_proba(model, tok, va_ids)
        val = quality(
            np.asarray(CLASSES)[va_y], np.asarray(CLASSES)[proba.argmax(1)]
        )
        history.append(
            {
                "epoca": epoch,
                "val_plata_macro_f1": round(val["macro_f1"], 4),
                "val_plata_kappa": round(val["kappa"], 4),
                "textos_por_segundo": round(
                    seen / (time.perf_counter() - start)
                ),
            }
        )
        print("clasificador", history[-1], flush=True)
        if val["macro_f1"] > best:
            best = val["macro_f1"]
            best_state = copy.deepcopy(
                {k: v.detach().cpu() for k, v in model.state_dict().items()}
            )
    model.load_state_dict(best_state)
    return tok, model, history


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("encoder", choices=sorted(ENCODERS))
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--lr-lora", type=float, default=3e-4)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--batch", type=int, default=None)
    ap.add_argument(
        "--accum",
        type=int,
        default=None,
        help="pasos de acumulación (lote efectivo = batch × accum)",
    )
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--epochs-detector", type=int, default=3)
    ap.add_argument("--epochs-classifier", type=int, default=2)
    ap.add_argument("--h1", type=float, default=1.0)
    ap.add_argument("--h2", type=float, default=1.0)
    ap.add_argument("--lam", type=float, default=1.0)
    ap.add_argument(
        "--detector-sample",
        type=int,
        default=20_000,
        help="pares para entrenar el detector (0 = todos)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="prueba rápida con N pares; no guarda predicciones",
    )
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--tag", default="", help="sufijo del nombre del modelo")
    ap.add_argument(
        "--detector-only",
        action="store_true",
        help="solo etapa 1; guarda el diagnóstico para elegir h1, h2 y rango",
    )
    args = ap.parse_args()
    seed_all(args.seed)
    rng = random.Random(args.seed)  # noqa: S311 - muestreo, no criptografía
    dev_t = device()
    defaults = train_defaults(dev_t)
    args.batch = args.batch or defaults["batch"]
    args.accum = args.accum or defaults["accum"]

    rows = silver_rows()
    pairs = training_star_pairs(rows)
    if args.limit:
        pairs = pairs.sample(args.limit, seed=SEED)
    hold = holdout_texts(holdout_rows(rows))
    gdev = gold().filter(
        (pl.col("particion") == "dev") & (pl.col("oro") != "NA")
    )
    y_star = np.array([CLASSES.index(c) for c in pairs["estrellas_clase"]])
    y_silver = np.array([CLASSES.index(c) for c in pairs["plata"]])

    start = time.perf_counter()
    tok, base = load(args.encoder)
    ids = encode(tok, pairs["texto_sanitizado"].to_list())
    # Time-box: el detector se entrena con una submuestra (3 pasadas con
    # gradiente por lote, ~9 pares/s en MPS) y luego puntúa todos los pares.
    det_idx = np.arange(len(ids))
    if args.detector_sample and args.detector_sample < len(ids):
        det_idx = np.sort(
            np.random.default_rng(args.seed).choice(
                len(ids), args.detector_sample, replace=False
            )
        )
    layers, det_history = detector(
        args,
        tok,
        base,
        [ids[i] for i in det_idx],
        y_star[det_idx],
        y_silver[det_idx],
        dev_t,
        rng,
    )
    score = clean_scores(base, layers, tok, ids, y_star, dev_t)
    clean = score > 0
    det_secs = time.perf_counter() - start

    dev_ids = encode(tok, gdev["texto_sanitizado"].to_list())
    dev_star = np.array([CLASSES.index(c) for c in gdev["estrellas_clase"]])
    dev_clean = clean_scores(base, layers, tok, dev_ids, dev_star, dev_t) > 0
    diagnostics = {
        "contra_plata_entrenamiento": detection_quality(
            clean, y_star != y_silver
        ),
        "contra_oro_dev": detection_quality(
            dev_clean, (gdev["estrellas_clase"] != gdev["oro"]).to_numpy()
        ),
        "fraccion_limpia": round(float(clean.mean()), 4),
    }
    out_of_sample = np.ones(len(ids), bool)
    out_of_sample[det_idx] = False
    if out_of_sample.any():
        # Pares que el detector no vio: la medida honesta para elegir h1/h2.
        diagnostics["contra_plata_fuera_de_muestra"] = detection_quality(
            clean[out_of_sample], (y_star != y_silver)[out_of_sample]
        )
    print("detector", diagnostics, flush=True)
    if args.detector_only:
        name = f"delora_detector_{args.encoder}{args.tag}"
        # Fuera de `preds/`: no son predicciones y `evaluate.py` no las lee.
        out = PREDS.parent / "detectores"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{name}.json").write_text(
            json.dumps(
                {
                    "hiperparametros": vars(args),
                    "historial": det_history,
                    "diagnostico": diagnostics,
                    "segundos": round(det_secs),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        return
    del base, layers
    empty_cache(dev_t)

    is_val = val_split(pairs["clave"].to_numpy())
    variants = {
        f"M8_{args.encoder}{args.tag}": (
            np.where(clean, y_star, y_silver),
            ~clean,
            np.ones(len(ids), bool),
        ),
        f"M8_{args.encoder}_solo_limpias{args.tag}": (
            y_star,
            np.zeros(len(ids), bool),
            clean,
        ),
    }
    va = ([ids[i] for i in np.flatnonzero(is_val)], y_silver[is_val])
    for name, (target, use_rce, keep) in variants.items():
        sel = np.flatnonzero(keep & ~is_val)
        start = time.perf_counter()
        tok2, model, history = classifier(
            args,
            args.encoder,
            [ids[i] for i in sel],
            target[sel],
            use_rce[sel],
            va,
            dev_t,
            rng,
        )
        cls_secs = time.perf_counter() - start
        if args.limit:
            continue
        p_dev, _ = predict_proba(model, tok2, dev_ids)
        p_hold, speed = predict_proba(
            model, tok2, encode(tok2, hold["texto_sanitizado"].to_list())
        )
        save_predictions(
            name,
            frame(gdev.select("item_id"), p_dev),
            frame(hold.select("text_id"), p_hold),
            {
                "modelo": name,
                "checkpoint": ENCODERS[args.encoder],
                "metodo": "Delora (Yuan et al., 2025) adaptado a encoder",
                "hiperparametros": vars(args),
                "pares_entrenamiento": len(sel),
                "re_etiquetadas_con_plata": int(use_rce[sel].sum()),
                "detector": {
                    "historial": det_history,
                    "diagnostico": diagnostics,
                    "segundos": round(det_secs),
                },
                "clasificador": {
                    "historial": history,
                    "segundos": round(cls_secs),
                },
                "dispositivo": str(dev_t),
                "equipo": "Mac M2 8 GB",
                "inferencia": speed,
            },
        )
        print(name, "listo", flush=True)
        del model
        empty_cache(dev_t)


if __name__ == "__main__":
    main()
