"""Los datos sintéticos incluyen el centinela donde un lector no debe verlo."""

from api_backend.fixtures import SENTINEL, load_sample


def test_el_centinela_esta_en_resenas_y_notas() -> None:
    reviews = load_sample("reviews")
    notes = load_sample("reviewer_notes")

    assert any(r["texto_sanitizado"] == SENTINEL for r in reviews)
    assert any(n["comment"] == SENTINEL for n in notes)


def test_los_demas_textos_son_cortos_e_inventados() -> None:
    for row in load_sample("reviews"):
        assert len(str(row["texto_sanitizado"])) < 80
        assert str(row["id_resena"]).startswith("syn-")
