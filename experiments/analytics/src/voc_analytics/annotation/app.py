"""App local de anotación del conjunto de oro (EPIC-5, feature 5.3).

Uso (desde experiments/analytics):
    uv run streamlit run src/voc_analytics/annotation/app.py
    GOLD_DIR=gold_v0_r2 uv run streamlit run src/voc_analytics/annotation/app.py

Lee la cola `data/labels/gold_v0/queue.parquet` (ver
`sampling/sample_gold_v0.py`) y agrega cada anotación a
`data/labels/gold_v0/annotations.csv`, ambos fuera de git. Corregir una
reseña agrega otra fila; al analizar gana la última por `item_id`.

Sigue `docs/analytics/labeling/annotation_guideline.md`: no muestra estrellas ni
banco; en modo `ciego` oculta la propuesta de Gemini y en `asistido` la
precarga para aceptarla o corregirla. En `calibracion` muestra lo que dijo
Gemini después de guardar. Solo muestra el bloque en la calibración, para
que en una cola mezclada (`gold_v1`) el anotador no sepa si una reseña es
aleatoria o dirigida.

`nombre_persona` marca si el texto contiene el nombre propio de una persona
(acción 1 de F-01 en `docs/governance/ethical_fmea_matrix.md`). Las colas
anteriores conservan su encabezado: si el CSV ya existe sin la columna, el
campo no se guarda.
"""

import csv
import os
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import streamlit as st

from voc_analytics.paths import LABELS

# `GOLD_DIR` elige la cola (por ejemplo, `gold_v0_r2` para la re-anotación).
GOLD = LABELS / os.environ.get("GOLD_DIR", "gold_v0")
QUEUE = GOLD / "queue.parquet"
ANNOTATIONS = Path(os.environ.get("ANNOTATIONS_CSV", GOLD / "annotations.csv"))
GUIDELINE_VERSION = "annotation_guideline_v2.2"
CLASSES = ["NEG", "NEU", "POS", "NO_EVALUABLE"]
FIELDS = [
    "item_id",
    "id_resena",
    "bloque",
    "modo",
    "sentimiento",
    "no_evaluable",
    "menciona_falla",
    "duda",
    "nombre_persona",
    "notas",
    "propuesta_mostrada",
    "guideline_version",
    "anotador",
    "inicio",
    "fin",
    "segundos",
]
RULES = """
1. **NO_EVALUABLE**: ininteligible, sin relación, solo emojis ambiguos u otro
   idioma. Emojis y palabras sueltas con valencia ("complicado") sí cuentan.
2. **Falla o queja concreta ⇒ NEG**, aunque haya elogios y aunque sea menor
   u ocasional ("a veces tarda", "el único problema es..."). También las
   decisiones del banco que no se explican y molestan (ubicación obligatoria,
   límites, rechazos sin motivo), aunque vengan de la regulación: llevan falla.
3. Sugerencia sin falla ⇒ por el tono general.
4. **POS**: valoración favorable sin queja concreta ("bien" incluido).
5. **NEU**: descripciones, preguntas, "ok", valoraciones intermedias sin
   queja.
6. Sarcasmo: el significado intencionado.
7. Quejas del banco (sucursal, ejecutivo) también cuentan.
8. Si dudas, elige la mejor y marca **duda**. No uses NEU como refugio.

**Menciona falla**: describe un problema concreto, aunque esté resuelto.

**Nombre propio**: el texto nombra a una persona (no tokens ni marcas).
"""


@st.cache_data
def load_queue() -> pl.DataFrame:
    return pl.read_parquet(QUEUE).sort("orden")


def load_annotations() -> dict[str, dict]:
    """Última anotación por `item_id`."""
    if not ANNOTATIONS.exists():
        return {}
    with ANNOTATIONS.open(newline="", encoding="utf-8") as handle:
        return {row["item_id"]: row for row in csv.DictReader(handle)}


def append_annotation(row: dict) -> None:
    ANNOTATIONS.parent.mkdir(parents=True, exist_ok=True)
    new = not ANNOTATIONS.exists()
    fields = FIELDS
    if not new:
        with ANNOTATIONS.open(newline="", encoding="utf-8") as handle:
            fields = next(csv.reader(handle))
    with ANNOTATIONS.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="ignore"
        )
        if new:
            writer.writeheader()
        writer.writerow(row)


def first_pending(queue: pl.DataFrame, done: dict) -> int:
    for pos, item_id in enumerate(queue["item_id"]):
        if item_id not in done:
            return pos
    return queue.height


def defaults(
    item: dict, saved: dict | None
) -> tuple[int | None, bool, bool, bool]:
    """Valores iniciales: lo ya guardado, o la propuesta si es asistido."""
    if saved:
        label = (
            "NO_EVALUABLE"
            if saved["no_evaluable"] == "1"
            else saved["sentimiento"]
        )
        return (
            CLASSES.index(label),
            saved["menciona_falla"] == "1",
            saved["duda"] == "1",
            saved.get("nombre_persona") == "1",
        )
    if item["modo"] == "asistido" and item.get("gemini_s"):
        label = "NO_EVALUABLE" if item["gemini_s"] == "NA" else item["gemini_s"]
        return CLASSES.index(label), bool(item["gemini_falla"]), False, False
    return None, False, False, False


def show_feedback(item: dict) -> None:
    st.info("Calibración: lo que dijo Gemini en el piloto")
    for key in ("retro_prompt_v0", "retro_prompt_v1"):
        if item.get(key):
            st.write(f"**{key.removeprefix('retro_')}**: {item[key]}")
    if st.button("Siguiente →", type="primary"):
        st.session_state.reveal = None
        st.session_state.pos += 1
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="Anotación de oro", layout="centered")
    queue = load_queue()
    done = load_annotations()
    state = st.session_state
    state.setdefault("pos", first_pending(queue, done))
    state.setdefault("started", {})
    state.setdefault("reveal", None)

    with st.sidebar:
        anotador = st.text_input("Anotador", value="autor")
        st.metric("Anotadas", f"{len(done)} / {queue.height}")
        progress = (
            queue.with_columns(hecho=pl.col("item_id").is_in(list(done.keys())))
            .group_by("bloque", "modo", maintain_order=True)
            .agg(pl.col("hecho").sum().alias("hechas"), pl.len().alias("total"))
        )
        st.dataframe(progress, hide_index=True)
        if st.button("Ir a la primera pendiente"):
            state.pos = first_pending(queue, done)
            state.reveal = None
            st.rerun()
        # Valor fijo: si dependiera de `pos`, Streamlit reiniciaría el widget.
        target = st.number_input("Ir a la posición", 1, queue.height, key="ir")
        if st.button("Ir"):
            state.pos = int(target) - 1
            state.reveal = None
            st.rerun()
        with st.expander("Reglas (guía v2.2)"):
            st.markdown(RULES)

    if state.pos >= queue.height:
        st.success("No quedan reseñas pendientes en la cola.")
        if st.button("← Anterior"):
            state.pos = queue.height - 1
            st.rerun()
        return

    item = queue.row(state.pos, named=True)
    item_id = item["item_id"]
    if state.reveal == item_id:
        st.subheader(f"{item_id} · guardada")
        st.markdown(f"> {item['texto_sanitizado']}")
        show_feedback(item)
        return

    state.started.setdefault(item_id, datetime.now(UTC))
    block = (
        f" · bloque **{item['bloque']}**"
        if item["bloque"] == "calibracion"
        else ""
    )
    st.caption(
        f"{state.pos + 1} de {queue.height}{block} · modo **{item['modo']}**"
        + (" · ya anotada (se corregirá)" if item_id in done else "")
    )
    st.markdown(
        f"<div style='font-size:1.25rem;line-height:1.5;padding:1rem;"
        f"border-radius:0.5rem;border:1px solid rgba(128,128,128,0.4)'>"
        f"{_escape(item['texto_sanitizado'])}</div>",
        unsafe_allow_html=True,
    )
    index, falla, duda, nombre = defaults(item, done.get(item_id))
    if item["modo"] == "asistido" and item.get("gemini_s"):
        st.caption(
            f"Propuesta de Gemini ({item['gemini_prompt']}): "
            f"{item['gemini_s']}, "
            f"falla {'sí' if item['gemini_falla'] else 'no'}"
        )

    with st.form(f"form_{item_id}", clear_on_submit=False):
        label = st.radio("Sentimiento", CLASSES, index=index, horizontal=True)
        menciona_falla = st.checkbox("Menciona falla", value=falla)
        marca_duda = st.checkbox("Duda", value=duda)
        nombre_persona = st.checkbox(
            "Contiene nombre propio de una persona",
            value=nombre,
            help="Nombre o apellido de una persona escrito en el texto, "
            "aunque no sea del autor. No cuentan los tokens como "
            "[PERSON_NAME] ni los nombres de bancos o apps.",
        )
        notas = st.text_input("Notas (opcional, sin copiar el texto)")
        saved = st.form_submit_button("Guardar", type="primary")

    left, _ = st.columns([1, 3])
    if left.button("← Anterior", disabled=state.pos == 0):
        state.pos -= 1
        st.rerun()

    if saved:
        if label is None:
            st.error("Elige una clase de sentimiento.")
            return
        end = datetime.now(UTC)
        start = state.started.pop(item_id, end)
        shown = item["modo"] == "asistido" and item.get("gemini_s")
        append_annotation(
            {
                "item_id": item_id,
                "id_resena": item["id_resena"],
                "bloque": item["bloque"],
                "modo": item["modo"],
                "sentimiento": "" if label == "NO_EVALUABLE" else label,
                "no_evaluable": int(label == "NO_EVALUABLE"),
                "menciona_falla": int(menciona_falla),
                "duda": int(marca_duda),
                "nombre_persona": int(nombre_persona),
                "notas": notas.strip(),
                "propuesta_mostrada": item["gemini_s"] if shown else "",
                "guideline_version": GUIDELINE_VERSION,
                "anotador": anotador.strip(),
                "inicio": start.isoformat(),
                "fin": end.isoformat(),
                "segundos": round((end - start).total_seconds(), 1),
            }
        )
        if item["bloque"] == "calibracion":
            state.reveal = item_id
        else:
            state.pos += 1
        st.rerun()


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )


main()
