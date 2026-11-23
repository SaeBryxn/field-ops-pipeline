"""Reglas de nombres de carpeta y archivos (funciones puras, sin interfaz)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

ITEM_RE = re.compile(r"^ITEM-(.+)$", re.IGNORECASE)
NODO_CARPETA_RE = re.compile(r"^([A-Z]{2}-\d{4}-[A-Z]\d{2})-(.*)$", re.IGNORECASE)


def safe_folder_name(name: str) -> str:
    """Limpia un texto para usarlo como nombre de carpeta en Windows.

    Quita paréntesis y su contenido, colapsa espacios y reemplaza caracteres
    prohibidos (``<>:"/\\|?*``) por guiones.
    """
    s = (name or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*\([^)]*\)\s*", "", s).strip()
    for ch in '<>:"/\\|?*':
        s = s.replace(ch, "-")
    s = s.strip().strip(".")
    return s if s else "SIN_NOMBRE"


def normalize_item_input(s: str) -> Optional[str]:
    """Normaliza el ITEM escrito por el operador: ``" item: 7_8 "`` -> ``"7_8"``.

    Devuelve ``None`` si no queda nada válido.
    """
    if not s:
        return None
    t = s.strip().upper()
    t = t.replace("ITEM", "").replace(":", "").replace(" ", "")
    t = re.sub(r"[^A-Z0-9_-]+", "", t)
    t = t.strip("_-")
    t = re.sub(r"__+", "_", t)
    t = re.sub(r"--+", "-", t)
    if not t:
        return None
    m = re.search(r"[A-Z0-9]+(?:[_-][A-Z0-9]+)*", t)
    return m.group(0) if m else None


def unique_path(path: Path) -> Path:
    """Devuelve ``path`` o ``stem_1.ext``, ``stem_2.ext``... si ya existe."""
    if not path.exists():
        return path
    i = 1
    while True:
        cand = path.parent / f"{path.stem}_{i}{path.suffix}"
        if not cand.exists():
            return cand
        i += 1


def list_images(folder: Path) -> List[Path]:
    """Lista imágenes (recursivo) ordenadas por nombre."""
    files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMG_EXTS]
    files.sort(key=lambda x: x.name.lower())
    return files


def nombre_carpeta_nodo(codigo: str, localidad: str) -> str:
    """``("AY-0901-A01", "VILLA EJEMPLO")`` -> ``"AY-0901-A01-VILLA EJEMPLO"``."""
    return f"{codigo}-{safe_folder_name(localidad)}"


def build_dest_folder(out_base: Path, codigo: str, localidad: str, item: str) -> Path:
    """Ruta destino ``<salida>/<CODIGO-LOCALIDAD>/ITEM-<item>`` (no la crea)."""
    return out_base / nombre_carpeta_nodo(codigo, localidad or "SIN_LOCALIDAD") / f"ITEM-{item}"


@dataclass(frozen=True)
class CarpetaItem:
    """Una carpeta ``NODO/ITEM-x`` ya ordenada."""

    codigo: str
    localidad: str
    item: str
    ruta: Path
    fotos: tuple[Path, ...]


def escanear_ordenado(out_base: Path) -> List[CarpetaItem]:
    """Recorre la salida ordenada y devuelve cada carpeta ITEM con sus fotos."""
    res: List[CarpetaItem] = []
    if not out_base.is_dir():
        return res
    for d_nodo in sorted(p for p in out_base.iterdir() if p.is_dir()):
        m = NODO_CARPETA_RE.match(d_nodo.name)
        if not m:
            continue
        codigo, localidad = m.group(1).upper(), m.group(2)
        for d_item in sorted(p for p in d_nodo.iterdir() if p.is_dir()):
            mi = ITEM_RE.match(d_item.name)
            if not mi:
                continue
            fotos = tuple(sorted(
                (p for p in d_item.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXTS),
                key=lambda x: x.name.lower(),
            ))
            res.append(CarpetaItem(codigo, localidad, mi.group(1).upper(), d_item, fotos))
    res.sort(key=lambda c: (c.codigo, clave_item(c.item)))
    return res


def clave_item(item: str) -> tuple:
    """Clave de orden natural: ``2`` < ``10`` < ``10_A``."""
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", item.upper()) if t)
