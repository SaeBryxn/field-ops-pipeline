"""Paso 4 del flujo: armar la entrega lista para subir a Google Drive.

Genera ``ENTREGA_<fecha>/`` junto a la carpeta de salida con:

    00_CARTERA.xlsx        última cartera completada (con hojas de revisión)
    00_REPORTE.xlsx        reporte de ordenamiento (se crea si no existe)
    MANIFIESTO.csv         cada foto con nodo, item, tamaño y SHA-256 (control de integridad)
    LEEME.txt              resumen y estado de la revisión humana
    <NODO>/ITEM-x/...      fotos (copiadas: la salida original queda intacta)
    <NODO>.zip             opcional, un ZIP por nodo

La revisión humana es parte del proceso: si la hoja "Revisión" de la cartera tiene
filas sin "S" en la columna "OK (S/N)", no se empaqueta salvo que se fuerce.
La subida a Drive es opcional vía ``rclone`` (sin credenciales en el código).
"""

from __future__ import annotations

import csv
import hashlib
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import openpyxl

from .reporte import generar_reporte
from .rutas import escanear_ordenado

ModoZip = Literal["ninguno", "por_nodo", "total"]


class RevisionPendiente(Exception):
    """Hay filas de la cartera que nadie marcó como revisadas."""

    def __init__(self, pendientes: int, cartera: Path):
        self.pendientes = pendientes
        super().__init__(
            f"{pendientes} fila(s) de {cartera.name} siguen pendientes de revisión "
            "(hoja 'Revisión', columna 'OK (S/N)')."
        )


@dataclass
class ResultadoEntrega:
    carpeta: Path
    nodos: int = 0
    fotos: int = 0
    bytes: int = 0
    zips: list[Path] = field(default_factory=list)
    pendientes: int = 0
    cartera: Optional[Path] = None

    def resumen(self) -> str:
        mb = self.bytes / 1024 / 1024
        txt = f"Entrega: {self.carpeta.name}\n{self.nodos} nodos · {self.fotos} fotos · {mb:.1f} MB"
        if self.zips:
            txt += f" · {len(self.zips)} ZIP"
        if not self.cartera:
            txt += "\nAviso: no se encontró cartera completada (paso 3)."
        elif self.pendientes:
            txt += f"\nAviso: se empaquetó con {self.pendientes} fila(s) sin revisar."
        else:
            txt += "\nRevisión humana: completa."
        return txt


def ultimo(out_base: Path, patron: str) -> Optional[Path]:
    """Archivo más reciente que cumple ``patron`` (por nombre, que lleva la fecha)."""
    cands = sorted(out_base.glob(patron))
    return cands[-1] if cands else None


def contar_pendientes(cartera: Path) -> int:
    """Filas de la hoja "Revisión" sin "S" en "OK (S/N)"."""
    wb = openpyxl.load_workbook(cartera, read_only=True, data_only=True)
    try:
        if "Revisión" not in wb.sheetnames:
            return 0
        filas = list(wb["Revisión"].iter_rows(values_only=True))
    finally:
        wb.close()
    if not filas:
        return 0
    cab = [str(c or "").strip().upper() for c in filas[0]]
    i_ok = next((i for i, c in enumerate(cab) if c.startswith("OK")), None)
    pendientes = 0
    for f in filas[1:]:
        if not any(v not in (None, "") for v in f):
            continue
        marca = str(f[i_ok] or "").strip().upper() if i_ok is not None else ""
        if marca not in ("S", "SI", "SÍ", "X", "OK"):
            pendientes += 1
    return pendientes


def sha256(path: Path, bloque: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(bloque):
            h.update(chunk)
    return h.hexdigest()


def empaquetar_entrega(
    out_base: Path,
    destino: Optional[Path] = None,
    permitir_pendientes: bool = False,
    zip_modo: ModoZip = "por_nodo",
) -> ResultadoEntrega:
    """Arma la carpeta de entrega. Ver docstring del módulo."""
    carpetas = escanear_ordenado(out_base)
    if not carpetas:
        raise ValueError(f"No hay carpetas NODO/ITEM ordenadas en {out_base}")

    cartera = ultimo(out_base, "CARTERA_*__AUTO.xlsx")
    pendientes = contar_pendientes(cartera) if cartera else 0
    if pendientes and not permitir_pendientes:
        raise RevisionPendiente(pendientes, cartera)

    destino = destino or out_base.parent / f"ENTREGA_{datetime.now():%Y%m%d_%H%M%S}"
    if destino.exists() and any(destino.iterdir()):
        raise FileExistsError(f"La carpeta de entrega ya existe y no está vacía: {destino}")
    destino.mkdir(parents=True, exist_ok=True)
    res = ResultadoEntrega(carpeta=destino, pendientes=pendientes, cartera=cartera)

    if cartera:
        shutil.copy2(cartera, destino / "00_CARTERA.xlsx")
    reporte = ultimo(out_base, "REPORTE_ORDENAMIENTO_*.xlsx") or generar_reporte(out_base)
    shutil.copy2(reporte, destino / "00_REPORTE.xlsx")

    nodos: dict[str, Path] = {}
    with (destino / "MANIFIESTO.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["ruta", "nodo", "item", "bytes", "sha256"])
        for c in carpetas:
            dest_item = destino / c.ruta.parent.name / c.ruta.name
            dest_item.mkdir(parents=True, exist_ok=True)
            nodos[c.ruta.parent.name] = dest_item.parent
            for foto in c.fotos:
                copia = dest_item / foto.name
                shutil.copy2(foto, copia)
                digest = sha256(copia)
                if digest != sha256(foto):
                    raise IOError(f"La copia de {foto} no coincide con el original")
                tam = copia.stat().st_size
                w.writerow([copia.relative_to(destino).as_posix(), c.codigo, c.item, tam, digest])
                res.fotos += 1
                res.bytes += tam
    res.nodos = len(nodos)

    if zip_modo == "por_nodo":
        for nombre, carpeta in sorted(nodos.items()):
            res.zips.append(_zip(carpeta, destino / f"{nombre}.zip", destino))
    elif zip_modo == "total":
        res.zips.append(_zip(destino, destino.parent / f"{destino.name}.zip", destino.parent))

    _leeme(destino, res, len(carpetas))
    return res


def _zip(carpeta: Path, zip_path: Path, base: Path) -> Path:
    """ZIP sin compresión (las fotos JPG ya están comprimidas; así es más rápido)."""
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as z:
        for p in sorted(carpeta.rglob("*")):
            if p.is_file() and p != zip_path and p.suffix.lower() != ".zip":
                z.write(p, p.relative_to(base).as_posix())
    return zip_path


def _leeme(destino: Path, res: ResultadoEntrega, items: int) -> None:
    estado = (
        "COMPLETA" if res.cartera and not res.pendientes
        else f"PENDIENTE ({res.pendientes} filas sin revisar)" if res.pendientes
        else "SIN CARTERA"
    )
    (destino / "LEEME.txt").write_text(
        "ENTREGA DE FOTOS DE CAMPO\n"
        f"Generada: {datetime.now():%Y-%m-%d %H:%M}\n\n"
        f"Nodos: {res.nodos}\nCarpetas ITEM: {items}\nFotos: {res.fotos}\n"
        f"Tamaño: {res.bytes / 1024 / 1024:.1f} MB\n"
        f"Revisión humana: {estado}\n\n"
        "Contenido:\n"
        "  00_CARTERA.xlsx  cartera completada (hojas Revisión y Resumen por nodo)\n"
        "  00_REPORTE.xlsx  resumen de fotos por nodo/ITEM y log de acciones\n"
        "  MANIFIESTO.csv   control de integridad (SHA-256 de cada foto)\n\n"
        "Subir a Drive: arrastrar esta carpeta (o los ZIP) a la carpeta compartida,\n"
        "o usar: python main.py subir <esta carpeta> <remoto rclone>\n",
        encoding="utf-8",
    )


def subir_con_rclone(carpeta: Path, remoto: str) -> int:
    """Sube la entrega con ``rclone copy`` (p. ej. ``remoto="drive:Entregas"``).

    rclone guarda su propia autenticación con Google (``rclone config``), así que este
    proyecto nunca maneja credenciales. Devuelve el código de salida de rclone.
    """
    exe = shutil.which("rclone")
    if not exe:
        raise FileNotFoundError("rclone no está instalado: https://rclone.org/install/")
    if not remoto or ":" not in remoto:
        raise ValueError("El remoto debe tener forma 'nombre:carpeta', ej. drive:Entregas")
    destino = f"{remoto.rstrip('/')}/{carpeta.name}"
    return subprocess.call([exe, "copy", str(carpeta), destino, "--progress"])
