from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from field_ops.imagen import crop_bottom_right, leer_datos_foto, resize_to_fit
from field_ops.ocr import ocr_disponible, parsear_texto_rotulo, sugerir, sugerir_desde_nombre
from field_ops.utm import latlon_a_utm, zona_utm


# ------------------------------------------------------------ sugerencias
@pytest.mark.parametrize("nombre, nodo, item", [
    ("AY-0901-A01_ITEM-3_001.jpg", "0901", "3"),
    ("ay0902a01 item 7_8 002.JPG", "0902", "7_8"),
    ("AY_0903_ITEM_01-A.jpg", "0903", "01-A"),
    ("ITEM-12.jpg", None, "12"),
])
def test_sugerir_desde_nombre(nombre, nodo, item):
    s = sugerir_desde_nombre(nombre)
    assert (s.nodo_num, s.item, s.fuente) == (nodo, item, "nombre")


def test_sugerir_desde_nombre_vacio():
    assert sugerir_desde_nombre("IMG_20250101_1200.jpg").vacia


@pytest.mark.parametrize("texto, nodo, item", [
    ("NODO AY-0904-A01\nITEM 5", "0904", "5"),
    ("AY - O9O4 - AO1\nITEM: 7_8", "0904", "7_8"),  # confusiones típicas de OCR
    ("AY-09S1-A01", "0951", None),
    ("texto sin nada", None, None),
])
def test_parsear_texto_rotulo(texto, nodo, item):
    s = parsear_texto_rotulo(texto)
    assert (s.nodo_num, s.item) == (nodo, item)


def test_sugerir_sin_ocr_usa_nombre(tmp_path):
    s = sugerir(tmp_path / "AY-0901-A01_ITEM-2_001.jpg", None, usar_ocr=False)
    assert (s.nodo_num, s.item) == ("0901", "2")


@pytest.mark.skipif(not ocr_disponible(), reason="Tesseract no instalado")
def test_ocr_real_sobre_foto_demo(tmp_path):
    from generar_demo import crear_foto

    p = crear_foto(tmp_path / "IMG_0001.jpg", "AY-0903-A01", "4", lat=-13.1, lon=-74.2, alt=2750)
    from field_ops.imagen import open_image

    s = sugerir(p, crop_bottom_right(open_image(p), 40))
    assert s.fuente == "ocr"
    assert (s.nodo_num, s.item) == ("0903", "4")


# ----------------------------------------------------------------- imagen
def test_crop_y_resize():
    im = Image.new("RGB", (1000, 800))
    c = crop_bottom_right(im, 50)
    assert c.size == (500, 400)
    assert crop_bottom_right(im, 5).size == (100, 80)  # mínimo 10 %
    assert resize_to_fit(im, 500, 500).size == (500, 400)
    assert resize_to_fit(im, 2000, 2000) is im  # nunca agranda


def test_leer_gps_exif(tmp_path):
    from generar_demo import guardar_con_exif

    p = tmp_path / "gps.jpg"
    guardar_con_exif(Image.new("RGB", (64, 64)), p, -13.15875, -74.22390, 2761.5, datetime(2025, 6, 1, 9, 30))
    d = leer_datos_foto(p)
    assert d.lat == pytest.approx(-13.15875, abs=1e-5)
    assert d.lon == pytest.approx(-74.22390, abs=1e-5)
    assert d.alt == pytest.approx(2761.5, abs=0.1)
    assert d.fecha == datetime(2025, 6, 1, 9, 30)


def test_leer_sin_exif(tmp_path):
    p = tmp_path / "x.png"
    Image.new("RGB", (8, 8)).save(p)
    assert leer_datos_foto(p).lat is None


# -------------------------------------------------------------------- utm
def test_zona_utm():
    assert zona_utm(-74.2) == 18
    assert zona_utm(-77.0) == 18
    assert zona_utm(-81.0) == 17


@pytest.mark.parametrize("lat, lon, este, norte, zona", [
    # Valores de referencia calculados con PROJ (EPSG:4326 -> EPSG:32718 / 32617)
    (-13.15875, -74.22390, 584109.85, 8545178.92, 18),
    (-12.04640, -77.04280, 277617.45, 8667487.90, 18),
    (0.0, -81.0, 500000.0, 0.0, 17),
])
def test_latlon_a_utm(lat, lon, este, norte, zona):
    e, n, z, h = latlon_a_utm(lat, lon)
    assert z == zona
    assert e == pytest.approx(este, abs=0.05)
    assert n == pytest.approx(norte, abs=0.05)
    assert h == ("S" if lat < 0 else "N")
