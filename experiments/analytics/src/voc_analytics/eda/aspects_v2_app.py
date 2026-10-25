"""App local para codificar aspectos con la guía `v2`/`v2.1` (EPIC-5, 5.2).

Uso (desde experiments/analytics):
    uv run streamlit run src/voc_analytics/eda/aspects_v2_app.py -- \\
        --cola muestra_v21
    (también --cola calibracion, calibracion2, calibracion3, muestra o
    recodificacion, que siguen la guía `v2`)

Lee la cola `data/eda/aspects_v2/<cola>.csv` (ver `eda_aspects_v2`) y agrega
cada codificación a `data/eda/aspects_v2/<cola>_annotations.csv`, fuera de
git. Corregir un texto agrega otra fila; al analizar gana la última por
`item`.

Sigue `docs/analytics/eda/eda_aspects_guideline.md`. Las familias se muestran
agrupadas en el orden de decisión de la guía `v2.1`, para bajar la carga
cognitiva. No muestra la salida de Gemini, ni estrellas, ni banco, ni el
origen del texto (enriquecido o aleatorio). En una recodificación no
muestra la respuesta anterior.
"""

import argparse
import csv
from datetime import UTC, datetime

import polars as pl
import streamlit as st

from voc_analytics.eda.eda_aspects import codes_list
from voc_analytics.eda.eda_aspects_v2 import (
    FIELDS,
    QUEUES,
    annotations_path,
    queue_path,
    queue_version,
)

NONE = "-"
# Etiqueta corta de cada casilla, con la guía `v2.1`; la tabla completa está
# en el pie. `FQ` solo aparece en las colas de la guía `v2`.
LABELS = {
    "AC": "Acceso y autenticación: sesión, contraseña, NIP, token, códigos, "
    "biometría, registro, bloqueo (en cualquier operación)",
    "TR": "Transferencias y pagos: SPEI, servicios, retiros, cajeros, "
    "contactos, comprobantes, restricciones",
    "DI": "Dinero y cargos: cargos no reconocidos, comisiones, dinero que "
    "falta, fraude",
    "PR": "Productos y cuentas: tarjetas, créditos, puntos, saldo, "
    "movimientos, trámites",
    "AT": "Atención: servicio al cliente, teléfono, chat, sucursal",
    "FA": "Falla general: no abre, se cierra, no carga, sin conexión",
    "LE": "Lentitud general de la app",
    "CO": "Compatibilidad, instalación y actualización: actualización "
    "forzosa o que falla, no se instala, teléfono, permisos, espacio",
    "DV": "Diseño visual: cómo se ve",
    "UX": "Usabilidad: cómo se hace algo, lo que interrumpe el uso "
    "(publicidad, notificaciones, idioma) y funciones que quitaron",
    "FQ": "Función quitada o cambiada, dicho explícitamente (guía v2)",
    "OT": "Sin familia: último recurso, solo si no cabe en ninguna",
}
# Orden de decisión de la guía `v2.1`.
GROUPS = [
    (
        "1 · ¿Es de una operación o de la autenticación?",
        ["AC", "TR", "DI", "PR", "AT"],
    ),
    (
        "2 · ¿Es de la app en general, su instalación o el teléfono?",
        ["FA", "LE", "CO"],
    ),
    ("3 · ¿Es de diseño?", ["DV", "UX", "FQ"]),
    ("4 · Último recurso", ["OT"]),
]
# Guía `v2.1` en tablas para el pie; resume
# docs/analytics/eda/eda_aspects_guideline.md.
FAMILIES = [
    (
        "AC",
        "Acceso y autenticación",
        "Sesión, contraseña, NIP, token, códigos de verificación, biometría, "
        "registro del dispositivo, verificación, bloqueo. Todo problema de "
        "token o código, sin importar qué operación bloquee",
        '"No abre", "no puedo entrar" sin autenticación, o se congela al '
        "iniciar sesión → FA",
    ),
    (
        "TR",
        "Transferencias y pagos",
        "SPEI, servicios, tarjeta, depósitos, retiros, cajeros, QR, CoDi, "
        "contactos y cuentas guardadas, comprobantes, horarios y restricciones",
        "Dinero que no llega o desaparece → DI; token para autorizar → AC",
    ),
    (
        "DI",
        "Dinero y cargos",
        "Cargos no reconocidos, comisiones, dinero que no aparece, fraude, "
        "reembolsos",
        "Consultar saldo o movimientos → PR",
    ),
    (
        "PR",
        "Productos y cuentas",
        "Tarjetas, créditos, inversiones, apartados, puntos, límites, "
        "solicitudes; saldo, movimientos, estados de cuenta; actualizar datos",
        "",
    ),
    (
        "AT",
        "Atención",
        "Servicio al cliente, teléfono, chat, sucursal, ejecutivos, sin "
        "respuesta",
        "",
    ),
    (
        "FA",
        "Falla general",
        "No abre, se cierra, no carga, se congela, sin conexión, errores que "
        "no son de una función; falla tras actualizar (+ u)",
        "El error de una función concreta → su familia",
    ),
    (
        "LE",
        "Lentitud general",
        "La app es lenta o pesada en general",
        '"Las transferencias tardan" → TR',
    ),
    (
        "CO",
        "Compatibilidad, instalación y actualización",
        "Todo el proceso de instalar o actualizar: forzosa, constante, que se "
        "atora, no se descarga. Modelo, sistema, root, permisos, espacio, "
        "batería, datos",
        "La app instalada que falla tras actualizar → FA + u",
    ),
    (
        "DV",
        "Diseño visual",
        "Cómo se ve: apariencia, colores, letra, íconos, modo oscuro, "
        "pantallas saturadas",
        '"Diseño poco amigable" → UX; "fea" sin más → sin familias',
    ),
    (
        "UX",
        "Usabilidad, recorrido y cambios",
        "Cómo se hace algo: confusa, poco intuitiva, difícil encontrar, muchos "
        "pasos, menús, idioma. Lo que interrumpe: publicidad, notificaciones, "
        "obligar a usar otra app. Funciones que dice que quitaron o cambiaron",
        'Frustración ("una pesadilla"); dificultad por una falla; fricción de '
        "una operación (guardar tarjetas, movimientos que tardan) → su "
        'dominio; "ya no me permite..." sin decir que lo quitaron → su dominio',
    ),
    (
        "OT",
        "Sin familia",
        "Problema concreto que no cabe en ninguna familia, tras descartarlas "
        "todas",
        "Lo difícil de decidir; cualquier tema que ya tenga familia",
    ),
]
MARKS = [
    (
        "Sin problema concreto",
        "Solo valora mal, sin decir qué falla",
        '"pésima", "no sirve", "fea"; "me gustaba la versión anterior" (+ u)',
    ),
    (
        "u · actualización",
        "Liga la queja a una actualización, versión nueva o cambio reciente. "
        "No es familia; puede ir sin familias",
        '"desde que actualizaron se cierra" → FA + u; "era buena, pero '
        'ahora..." → u',
    ),
    (
        "s · seguridad",
        "Se queja de hackeo, fraude con la app, desconfianza, biometría como "
        "seguridad o privacidad (objeta que le exijan biometría o datos). No "
        "es familia; puede ir sin familias",
        '"me hackearon y me sacaron dinero" → DI + s; "no funciona la '
        'huella" → AC sin s; "segura, aunque lenta" → sin s',
    ),
    (
        "Elogio concreto",
        "Además elogia un aspecto concreto",
        '"el diseño está bien, pero..."; "buena app, pero..." no cuenta',
    ),
]
RULES = [
    (
        "Un problema, una familia",
        "La más específica. Error al transferir → solo TR; saldo movido que "
        "no aparece → solo DI; token para transferir → solo AC",
    ),
    ("Problemas distintos", "Una familia por cada uno: AC + DI"),
    (
        "Consecuencias",
        'No se codifican: "no puedo descargar, así que no activo mi '
        'tarjeta" → solo CO',
    ),
    (
        "Función que no existe",
        "O con restricciones o fricción (guardar CLABEs, días inhábiles, "
        "movimientos que tardan) → solo su dominio, sin UX",
    ),
    ("Solo lo que dice el texto", "No se infiere la causa ni el problema"),
]


def table(header: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    """Tabla en markdown; escapa los `|` del contenido."""
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(" :--- " for _ in header) + "|",
    ]
    for r in rows:
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in r) + " |")
    return "\n".join(lines)


def guide_footer(guideline: str) -> None:
    st.divider()
    with st.expander("Guía de codificación v2.1 (tablas)", expanded=False):
        st.markdown("**Familias**, en el orden de decisión")
        st.markdown(
            table(
                ("Código", "Familia", "Incluye", "No incluye (va a)"), FAMILIES
            )
        )
        st.markdown("**Marcas**")
        st.markdown(table(("Marca", "Cuándo", "Ejemplos"), MARKS))
        st.markdown("**Reglas**")
        st.markdown(table(("Regla", "Cómo"), RULES))
        st.caption(
            "Guía completa: docs/analytics/eda/eda_aspects_guideline.md. Esta "
            f"cola se codifica con {guideline}."
        )


def load(path) -> dict[int, dict]:
    if not path.exists():
        return {}
    with path.open() as f:
        return {int(row["item"]): row for row in csv.DictReader(f)}


def save(path, row: dict) -> None:
    """Agrega una fila; respeta el encabezado de un archivo anterior a una
    columna nueva (`s` en la ronda 1, `comentario` hasta la muestra)."""
    new = not path.exists()
    fields = FIELDS
    if not new:
        with path.open() as f:
            fields = next(csv.reader(f))
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            writer.writeheader()
        writer.writerow(row)


parser = argparse.ArgumentParser()
parser.add_argument("--cola", choices=QUEUES, required=True)
queue_name = parser.parse_args().cola
annotations = annotations_path(queue_name)
_, _, guideline, codes = queue_version(queue_name)

st.set_page_config(page_title="Aspectos v2", layout="wide")
queue = pl.read_csv(queue_path(queue_name))
done = load(annotations)
items = queue["item"].to_list()

with st.sidebar:
    st.markdown(f"**Cola:** {queue_name} · guía `{guideline}`")
    st.metric("Codificados", f"{sum(i in done for i in items)} / {len(items)}")
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

item = items[st.session_state.pos]
row = queue.filter(pl.col("item") == item).row(0, named=True)
prev = done.get(item)
key = f"start_{item}"
if key not in st.session_state:
    st.session_state[key] = datetime.now(UTC)

st.caption(f"Ítem {item}{' · ya codificado' if prev else ''}")
st.markdown(
    "Esta reseña es **negativa**. ¿Sobre qué problemas concretos se queja?"
)
st.info(row["texto_sanitizado"])

prev_codes = set(codes_list((prev or {}).get("codigos")))
with st.form(f"form_{item}"):
    none = st.checkbox(
        "**Sin problema concreto** (solo valora mal, no dice qué falla)",
        value=bool(prev) and not prev_codes,
        key=f"{item}_none",
    )
    chosen = []
    for title, group in GROUPS:
        group = [c for c in group if c in codes]
        if not group:
            continue
        st.markdown(f"**{title}**")
        chosen += [
            c
            for c in group
            if st.checkbox(
                f"**{c}** · {LABELS[c]}",
                value=c in prev_codes,
                key=f"{item}_{c}",
            )
        ]
    st.markdown("**Marcas**")
    u = st.checkbox(
        "**u** · Liga la queja a una actualización o versión nueva",
        value=(prev or {}).get("u") == "1",
        key=f"{item}_u",
    )
    sec = st.checkbox(
        "**s** · Queja de seguridad: hackeo, fraude con la app, "
        "desconfianza, biometría como seguridad, privacidad",
        value=(prev or {}).get("s") == "1",
        key=f"{item}_s",
    )
    elogio = st.checkbox(
        "Además elogia un aspecto concreto",
        value=(prev or {}).get("elogio") == "1",
        key=f"{item}_elogio",
    )
    comment = st.text_area(
        "Comentario (opcional): dudas, ambigüedades o ideas para la guía",
        value=(prev or {}).get("comentario") or "",
        key=f"{item}_comentario",
        height=80,
    )
    submitted = st.form_submit_button("Guardar y seguir", type="primary")

if submitted and none == bool(chosen):
    st.error("Marca *Sin problema concreto* o al menos una familia, no ambas.")
elif submitted:
    end = datetime.now(UTC)
    start = st.session_state[key]
    save(
        annotations,
        {
            "item": item,
            "text_id": row["text_id"],
            "codigos": ",".join(chosen) if chosen else NONE,
            "u": int(u),
            "s": int(sec),
            "elogio": int(elogio),
            "guia": guideline,
            "inicio": start.isoformat(),
            "fin": end.isoformat(),
            "segundos": round((end - start).total_seconds(), 1),
            "comentario": comment.strip(),
        },
    )
    done = load(annotations)
    pending = [i for i in items if i not in done]
    st.session_state.pos = items.index(pending[0]) if pending else 0
    st.rerun()

guide_footer(guideline)
