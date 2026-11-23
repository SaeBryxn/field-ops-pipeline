"""Sugerencias automáticas de NODO e ITEM.

Orden de prioridad:
    1. Nombre del archivo (regex): ``AY-0901-A01_ITEM-3_001.jpg`` -> nodo 0901, item 3.
    2. OCR con Tesseract sobre el recorte inferior-derecho (donde está el rótulo).

Siempre es una *sugerencia*: el operador la ve prellenada y confirma con Enter o
la corrige. Si Tesseract no está instalado, el OCR se desactiva sin romper nada.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import Image, ImageFilter, ImageOps

from .rutas import normalize_item_input

#: Nodo en texto libre. Tolera confusiones típicas de OCR (O/0, I/1, S/5, espacios).
_NODO_OCR_RE = re.compile(r"A\s*Y\s*[-_—.\s]?\s*([0-9OIlSB]{4})\s*[-_—.\s]?\s*A\s*[0O]\s*[1Il]", re.IGNORECASE)
_NODO_NOMBRE_RE = re.compile(r"AY[-_ ]?(\d{3,4})(?:[-_ ]?A01)?", re.IGNORECASE)
_ITEM_RE = re.compile(r"ITEM\s*[-_:#.]?\s*([0-9A-Z]+(?:[_-][0-9A-Z]+)*)", re.IGNORECASE)

_OCR_DIGITOS = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"})


@dataclass(frozen=True)
class Sugerencia:
    """Resultado de la detección. ``fuente`` es ``"nombre"``, ``"ocr"`` o ``""``."""

    nodo_num: Optional[str] = None
    item: Optional[str] = None
    fuente: str = ""
    texto: str = ""

    @property
    def vacia(self) -> bool:
        return not (self.nodo_num or self.item)


def sugerir_desde_nombre(nombre: str) -> Sugerencia:
    """Busca nodo e ITEM en el nombre del archivo."""
    base = Path(nombre).stem
    num = None
    m = _NODO_NOMBRE_RE.search(base)
    if m:
        num = m.group(1).zfill(4)
    item = None
    mi = _ITEM_RE.search(base.replace(" ", "_"))
    if mi:
        # en nombres de archivo el ITEM termina antes del siguiente separador "_NNN"
        item = normalize_item_input(re.split(r"_(?=\d{3,}$)", mi.group(1))[0])
    if not (num or item):
        return Sugerencia()
    return Sugerencia(num, item, "nombre", base)


def parsear_texto_rotulo(texto: str) -> Sugerencia:
    """Extrae nodo e ITEM del texto que devolvió el OCR."""
    if not texto:
        return Sugerencia()
    num = None
    m = _NODO_OCR_RE.search(texto)
    if m:
        dig = m.group(1).translate(_OCR_DIGITOS)
        if dig.isdigit():
            num = dig.zfill(4)
    item = None
    mi = _ITEM_RE.search(texto)
    if mi:
        item = normalize_item_input(mi.group(1))
    if not (num or item):
        return Sugerencia(texto=texto)
    return Sugerencia(num, item, "ocr", texto.strip())


@lru_cache(maxsize=1)
def ocr_disponible() -> bool:
    """``True`` si pytesseract y el binario de Tesseract están disponibles."""
    try:
        import pytesseract
    except ImportError:
        return False
    cmd = os.environ.get("TESSERACT_CMD")
    if not cmd:
        default_win = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        cmd = str(default_win) if default_win.exists() else shutil.which("tesseract")
    if not cmd:
        return False
    pytesseract.pytesseract.tesseract_cmd = cmd
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def preprocesar(im: Image.Image) -> Image.Image:
    """Escala de grises, contraste, ampliación y binarizado para mejorar el OCR."""
    g = ImageOps.grayscale(im)
    if g.width < 900:
        f = 900 / max(1, g.width)
        g = g.resize((int(g.width * f), int(g.height * f)), Image.LANCZOS)
    g = ImageOps.autocontrast(g, cutoff=2)
    g = g.filter(ImageFilter.SHARPEN)
    return g.point(lambda p: 255 if p > 140 else 0)


def leer_rotulo(recorte: Image.Image) -> str:
    """Texto del rótulo vía Tesseract (``""`` si el OCR no está disponible)."""
    if not ocr_disponible():
        return ""
    import pytesseract

    proc = preprocesar(recorte)
    textos = []
    for variante in (proc, ImageOps.invert(proc)):  # rótulo claro u oscuro
        try:
            textos.append(pytesseract.image_to_string(variante, config="--psm 6"))
        except Exception:
            continue
        if parsear_texto_rotulo(textos[-1]).nodo_num:
            break
    return "\n".join(textos)


def sugerir(path: Path, recorte: Optional[Image.Image] = None, usar_ocr: bool = True) -> Sugerencia:
    """Combina nombre de archivo y OCR. El nombre gana; el OCR completa lo que falte."""
    s_nombre = sugerir_desde_nombre(path.name)
    if (s_nombre.nodo_num and s_nombre.item) or not usar_ocr or recorte is None:
        return s_nombre
    s_ocr = parsear_texto_rotulo(leer_rotulo(recorte))
    if s_ocr.vacia:
        return s_nombre
    if s_nombre.vacia:
        return s_ocr
    return Sugerencia(
        s_nombre.nodo_num or s_ocr.nodo_num,
        s_nombre.item or s_ocr.item,
        "nombre+ocr",
        s_ocr.texto,
    )
