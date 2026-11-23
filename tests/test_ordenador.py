from __future__ import annotations

from pathlib import Path

import pytest

from field_ops import undo
from field_ops.config import Preferencias
from field_ops.nodos import CatalogoNodos, buscar_codigo, normalize_node_input
from field_ops.registro import RegistroAcciones
from field_ops.rutas import (
    build_dest_folder, clave_item, escanear_ordenado, normalize_item_input,
    safe_folder_name, unique_path,
)

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def catalogo() -> CatalogoNodos:
    return CatalogoNodos.desde_csv(RAIZ / "config" / "nodos.example.csv")


# ------------------------------------------------------------------ nodos
@pytest.mark.parametrize("entrada, esperado", [
    ("901", ("0901", "AY-0901-A01")),
    ("0901", ("0901", "AY-0901-A01")),
    ("ay-0901-a01", ("0901", "AY-0901-A01")),
    ("AY0901A01", ("0901", "AY-0901-A01")),
    ("nodo 7", ("0007", "AY-0007-A01")),
])
def test_normalize_node_input(entrada, esperado, catalogo):
    num, code, _ = normalize_node_input(entrada, catalogo)
    assert (num, code) == esperado


def test_normalize_node_input_localidad(catalogo):
    assert normalize_node_input("901", catalogo)[2] == "VILLA EJEMPLO"
    assert normalize_node_input("7", catalogo)[2] is None  # no está en catálogo
    assert normalize_node_input("", catalogo) == (None, None, None)
    assert normalize_node_input("sin numero", catalogo) == (None, None, None)


def test_catalogo_csv_punto_y_coma(tmp_path):
    p = tmp_path / "n.csv"
    p.write_text("CODIGO;Localidad\nay-0001-a01;UNO\n", encoding="utf-8")
    cat = CatalogoNodos.desde_csv(p)
    assert cat.localidad("AY-0001-A01") == "UNO"


def test_buscar_codigo():
    assert buscar_codigo("foto_ay_0904_a01_x.jpg") == "AY-0904-A01"
    assert buscar_codigo("IMG_0001.jpg") is None


# ------------------------------------------------------------------ rutas
@pytest.mark.parametrize("entrada, esperado", [
    ("7_8", "7_8"),
    (" item: 01-a ", "01-A"),
    ("ITEM 3", "3"),
    ("__7__8__", "7_8"),
    ("7 / 8", "78"),
    ("", None),
    ("ITEM", None),
    ("$$", None),
])
def test_normalize_item_input(entrada, esperado):
    assert normalize_item_input(entrada) == esperado


@pytest.mark.parametrize("entrada, esperado", [
    ("VILLA EJEMPLO (@VILLA)", "VILLA EJEMPLO"),
    ("  SAN   DEMO  ", "SAN DEMO"),
    ('A/B:C*D?"E"', "A-B-C-D--E-"),
    ("...", "SIN_NOMBRE"),
    ("", "SIN_NOMBRE"),
])
def test_safe_folder_name(entrada, esperado):
    assert safe_folder_name(entrada) == esperado


def test_unique_path(tmp_path):
    p = tmp_path / "a.jpg"
    assert unique_path(p) == p
    p.write_bytes(b"x")
    assert unique_path(p) == tmp_path / "a_1.jpg"
    (tmp_path / "a_1.jpg").write_bytes(b"x")
    assert unique_path(p) == tmp_path / "a_2.jpg"


def test_build_dest_y_escanear(tmp_path):
    d = build_dest_folder(tmp_path, "AY-0901-A01", "VILLA EJEMPLO (@X)", "10")
    assert d == tmp_path / "AY-0901-A01-VILLA EJEMPLO" / "ITEM-10"
    d.mkdir(parents=True)
    (d / "f.jpg").write_bytes(b"x")
    d2 = build_dest_folder(tmp_path, "AY-0901-A01", "VILLA EJEMPLO", "2")
    d2.mkdir(parents=True)
    (tmp_path / "otra_cosa").mkdir()
    res = escanear_ordenado(tmp_path)
    assert [(c.codigo, c.item, len(c.fotos)) for c in res] == [
        ("AY-0901-A01", "2", 0), ("AY-0901-A01", "10", 1),
    ]


def test_clave_item_orden_natural():
    assert sorted(["10", "2", "10_A", "1"], key=clave_item) == ["1", "2", "10", "10_A"]


# ------------------------------------------------------------------- undo
def _foto(carpeta: Path, nombre: str = "f.jpg") -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    p = carpeta / nombre
    p.write_bytes(b"datos")
    return p


def test_undo_move(tmp_path):
    src = _foto(tmp_path / "fuente")
    dest = tmp_path / "salida" / "AY-0901-A01-X" / "ITEM-1"
    rec = undo.aplicar("move", src, dest, idx=3)
    assert not src.exists() and rec.dst.exists() and rec.idx == 3
    back = undo.revertir(rec)
    assert back == src and src.read_bytes() == b"datos"
    assert not dest.exists()  # carpetas vacías se limpian


def test_undo_move_no_pisa(tmp_path):
    src = _foto(tmp_path / "fuente")
    rec = undo.aplicar("move", src, tmp_path / "d")
    _foto(tmp_path / "fuente")  # alguien puso otro archivo con el mismo nombre
    back = undo.revertir(rec)
    assert back == tmp_path / "fuente" / "f_1.jpg"


def test_undo_copy(tmp_path):
    src = _foto(tmp_path / "fuente")
    dest = tmp_path / "d"
    _foto(dest)  # ya existe f.jpg en destino
    rec = undo.aplicar("copy", src, dest)
    assert rec.dst.name == "f_1.jpg" and src.exists()
    assert undo.revertir(rec) is None
    assert not rec.dst.exists() and (dest / "f.jpg").exists() and src.exists()


def test_undo_destino_borrado(tmp_path):
    rec = undo.aplicar("copy", _foto(tmp_path / "a"), tmp_path / "b")
    rec.dst.unlink()
    with pytest.raises(FileNotFoundError):
        undo.revertir(rec)


def test_undo_stack_multinivel(tmp_path):
    pila = undo.UndoStack()
    fotos = [_foto(tmp_path / "fuente", f"{i}.jpg") for i in range(3)]
    for i, f in enumerate(fotos):
        pila.push(undo.aplicar("move", f, tmp_path / "out", idx=i))
    while (rec := pila.pop()) is not None:
        undo.revertir(rec)
    assert all(f.exists() for f in fotos) and len(pila) == 0


def test_modo_invalido(tmp_path):
    with pytest.raises(ValueError):
        undo.aplicar("borrar", _foto(tmp_path), tmp_path / "x")


# ------------------------------------------------------- registro/config
def test_registro_csv(tmp_path):
    reg = RegistroAcciones.en_salida(tmp_path)
    reg.anotar("GUARDAR", "move", Path("a.jpg"), tmp_path / "x", nodo="AY-0901-A01", item="1", operador="op")
    reg.anotar("UNDO", "move", Path("a.jpg"), tmp_path / "x")
    filas = reg.leer()
    assert [f["accion"] for f in filas] == ["GUARDAR", "UNDO"]
    assert filas[0]["operador"] == "op"


def test_preferencias_roundtrip(tmp_path):
    p = tmp_path / "cfg.json"
    Preferencias(src_dir="C:/x", crop_pct=33).guardar(p)
    assert Preferencias.cargar(p).crop_pct == 33
    p.write_text("{no json", encoding="utf-8")
    assert Preferencias.cargar(p).crop_pct == 50  # config corrupta -> valores por defecto
