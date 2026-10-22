"""App local para validar los aspectos de las negativas (EPIC-5, feature 5.2).

Uso (desde experiments/analytics):
    uv run streamlit run src/voc_analytics/eda/aspects_app.py
    uv run streamlit run src/voc_analytics/eda/aspects_app.py -- --revisar-fa

Lee la cola a ciegas `data/eda/aspects_v0/validation.csv` (ver
`eda_aspects validation`) y agrega cada codificación a
`data/eda/aspects_v0/validation_annotations_v1.csv`, fuera de git. Corregir
un texto agrega otra fila; al analizar gana la última por `item`, y las de
este archivo ganan a las de la primera pasada (`validation_annotations.csv`,
guía `v0`).

Sigue `docs/analytics/eda_aspects_guideline_v1.md`. No muestra la salida de
Gemini, ni estrellas ni banco. `--revisar-fa` muestra solo los textos que la
primera pasada codificó con `FA` y precarga esa respuesta: en `v0` la opción
"sin problema concreto" no estaba explícita y esos casos quedaron como `FA`.
"""

import csv
import sys
from datetime import UTC, datetime

import polars as pl
import streamlit as st

from voc_analytics.eda.eda_aspects import (
    ANNOTATIONS,
    ANNOTATIONS_V1,
    CODES,
    GUIDELINE,
    OUT,
    codes_list,
)

QUEUE = OUT / "validation.csv"
FIELDS = [
    "item",
    "text_id",
    "codigos",
    "elogio",
    "guia",
    "inicio",
    "fin",
    "segundos",
]
NONE = "-"
LABELS = {
    "AC": "Acceso: sesión, contraseña, NIP, token, biometría, registro, "
    "verificación, bloqueo",
    "FA": "Falla general descrita: no abre, se cierra, no carga, se congela, "
    "errores no ligados a una función",
    "LE": "Lentitud general de la app",
    "TR": "Transferencias y pagos: SPEI, servicios, depósitos, retiros, QR, "
    "CoDi",
    "DI": "Dinero y cargos: cargos no reconocidos, comisiones, dinero que no "
    "aparece, fraude",
    "PR": "Productos: tarjetas, créditos, préstamos, inversiones, límites, "
    "solicitudes",
    "AT": "Atención: servicio al cliente, teléfono, chat, sucursal, "
    "ejecutivos, sin respuesta",
    "DS": "Diseño y actualizaciones: interfaz, usabilidad, funciones "
    "quitadas, problema atribuido a una actualización",
    "CO": "Compatibilidad: modelo de teléfono, sistema, root, versión, "
    "permisos",
    "OT": "Otro problema concreto: publicidad, notificaciones, idioma",
}
RULES = """
1. **Sin problema concreto:** "pésima", "no sirve", "no funciona", "la peor
   app" sin más detalle → marca solo *Sin problema concreto*. **FA** exige
   una falla descrita ("no abre", "se cierra", "marca error").
2. **Un problema, una familia, la más específica:** un error al transferir
   es solo **TR**; "las transferencias tardan" es **TR**. **FA** y **LE**
   son solo para la app en general.
3. **Problema atribuido a una actualización** ("desde que actualizaron se
   cierra") → el problema **y además DS**.
4. **Problemas distintos** → una familia por cada uno.
5. **Elogio concreto:** "el diseño está bien, pero...". "Buena app,
   pero..." no cuenta.

Guía completa: `docs/analytics/eda_aspects_guideline_v1.md`.
"""


def load(path) -> dict[int, dict]:
    if not path.exists():
        return {}
    with path.open() as f:
        return {int(row["item"]): row for row in csv.DictReader(f)}


def save(row: dict) -> None:
    new = not ANNOTATIONS_V1.exists()
    with ANNOTATIONS_V1.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)


review = "--revisar-fa" in sys.argv
st.set_page_config(page_title="Aspectos de negativas", layout="centered")
queue = pl.read_csv(QUEUE, schema_overrides={"codigos": pl.String})
first = load(ANNOTATIONS)
done = load(ANNOTATIONS_V1)
items = queue["item"].to_list()
if review:
    items = [
        i for i in items if "FA" in codes_list(first.get(i, {}).get("codigos"))
    ]
if not items:
    st.success("No hay textos que revisar.")
    st.stop()

with st.sidebar:
    st.markdown(
        f"**Modo:** {'revisión de FA' if review else 'codificación'} · "
        f"guía `{GUIDELINE}`"
    )
    st.metric(
        "Hechos con la guía v1",
        f"{sum(i in done for i in items)} / {len(items)}",
    )
    pending = [i for i in items if i not in done]
    if "pos" not in st.session_state:
        st.session_state.pos = items.index(pending[0]) if pending else 0
    st.session_state.pos = (
        st.number_input(
            f"Posición (1–{len(items)})",
            min_value=1,
            max_value=len(items),
            value=st.session_state.pos + 1,
            step=1,
        )
        - 1
    )
    st.markdown("**Reglas**")
    st.markdown(RULES)

item = items[st.session_state.pos]
row = queue.filter(pl.col("item") == item).row(0, named=True)
prev = done.get(item) or (first.get(item) if review else None)
key = f"start_{item}"
if key not in st.session_state:
    st.session_state[key] = datetime.now(UTC)

status = " · ya revisado con la guía v1" if item in done else ""
if review and item not in done:
    status = " · precargado con tu primera respuesta"
st.caption(f"Ítem {item}{status}")
st.markdown(
    "Esta reseña es **negativa**. ¿Sobre qué problemas concretos se queja?"
)
st.info(row["texto_sanitizado"])

prev_codes = set(codes_list((prev or {}).get("codigos")))
prev_none = bool(prev) and not prev_codes
with st.form(f"form_{item}"):
    none = st.checkbox(
        "**Sin problema concreto** (solo valora mal, no dice qué falla)",
        value=prev_none,
        key=f"{item}_none",
    )
    chosen = [
        c
        for c in CODES
        if st.checkbox(
            f"**{c}** · {LABELS[c]}", value=c in prev_codes, key=f"{item}_{c}"
        )
    ]
    elogio = st.checkbox(
        "Además elogia un aspecto concreto",
        value=(prev or {}).get("elogio") == "1",
        key=f"{item}_elogio",
    )
    submitted = st.form_submit_button("Guardar y seguir", type="primary")

if submitted:
    if none == bool(chosen):
        st.error(
            "Marca *Sin problema concreto* o al menos una familia, no ambas."
        )
        st.stop()
    end = datetime.now(UTC)
    start = st.session_state[key]
    save(
        {
            "item": item,
            "text_id": row["text_id"],
            "codigos": ",".join(chosen) if chosen else NONE,
            "elogio": int(elogio),
            "guia": GUIDELINE,
            "inicio": start.isoformat(),
            "fin": end.isoformat(),
            "segundos": round((end - start).total_seconds(), 1),
        }
    )
    done = load(ANNOTATIONS_V1)
    pending = [i for i in items if i not in done]
    st.session_state.pos = items.index(pending[0]) if pending else 0
    st.rerun()
