"""Utilidades de imagen: abrir con orientación EXIF, recortes y lectura de GPS/fecha."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

GPS_IFD = 0x8825
EXIF_IFD = 0x8769
TAG_DATETIME_ORIGINAL = 36867
TAG_DATETIME = 306


def open_image(path: Path) -> Image.Image:
    """Abre la imagen respetando la orientación EXIF y en modo RGB/RGBA."""
    with Image.open(path) as raw:
        im = ImageOps.exif_transpose(raw)
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        im.load()
    return im


def resize_to_fit(im: Image.Image, max_w: int, max_h: int) -> Image.Image:
    """Reduce (nunca agranda) manteniendo proporción."""
    w, h = im.size
    if w <= 0 or h <= 0:
        return im
    scale = min(max_w / w, max_h / h)
    if scale >= 1:
        return im
    return im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


def crop_bottom_right(im: Image.Image, pct: int) -> Image.Image:
    """Recorte de la esquina inferior derecha (donde va el rótulo). ``pct`` entre 10 y 90."""
    pct = max(10, min(90, int(pct)))
    w, h = im.size
    cw = max(1, int(w * pct / 100.0))
    ch = max(1, int(h * pct / 100.0))
    return im.crop((w - cw, h - ch, w, h))


@dataclass(frozen=True)
class DatosFoto:
    """Metadatos útiles para la cartera."""

    lat: Optional[float] = None
    lon: Optional[float] = None
    alt: Optional[float] = None
    fecha: Optional[datetime] = None


def _racional(v) -> float:
    try:
        return float(v)
    except TypeError:
        num, den = v
        return float(num) / float(den) if den else 0.0


def _dms_a_grados(dms, ref: str) -> float:
    d, m, s = (_racional(x) for x in dms)
    val = d + m / 60.0 + s / 3600.0
    return -val if ref in ("S", "W") else val


def leer_datos_foto(path: Path) -> DatosFoto:
    """Lee GPS (lat, lon, altitud) y fecha de toma del EXIF. Campos ausentes = ``None``."""
    try:
        with Image.open(path) as im:
            exif = im.getexif()
    except Exception:
        return DatosFoto()

    lat = lon = alt = None
    try:
        gps = exif.get_ifd(GPS_IFD)
        if gps.get(2) and gps.get(4):
            lat = _dms_a_grados(gps[2], str(gps.get(1, "N")))
            lon = _dms_a_grados(gps[4], str(gps.get(3, "E")))
        if gps.get(6) is not None:
            alt = _racional(gps[6])
            if gps.get(5) in (1, b"\x01"):
                alt = -alt
    except Exception:
        pass

    fecha = None
    try:
        raw = exif.get_ifd(EXIF_IFD).get(TAG_DATETIME_ORIGINAL) or exif.get(TAG_DATETIME)
        if raw:
            fecha = datetime.strptime(str(raw).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return DatosFoto(lat, lon, alt, fecha)
