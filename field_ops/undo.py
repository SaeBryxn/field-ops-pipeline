"""Operaciones de archivo reversibles (mover / copiar) con pila de Undo ilimitada."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .rutas import unique_path


@dataclass
class UndoRecord:
    """Una acción deshacible.

    Attributes:
        mode: ``"move"`` o ``"copy"``.
        src: ruta original en la carpeta fuente (adonde vuelve si fue MOVE).
        dst: ruta final en la carpeta de salida.
        idx: posición que tenía el archivo en la lista (solo MOVE), para reinsertarlo.
    """

    mode: str
    src: Path
    dst: Path
    idx: int = -1
    nodo: str = ""
    localidad: str = ""
    item: str = ""


def aplicar(mode: str, src: Path, dest_dir: Path, idx: int = -1) -> UndoRecord:
    """Mueve o copia ``src`` dentro de ``dest_dir`` (sin pisar archivos) y devuelve el registro."""
    if mode not in ("move", "copy"):
        raise ValueError(f"Modo inválido: {mode}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = unique_path(dest_dir / src.name)
    if mode == "copy":
        shutil.copy2(src, dst)
    else:
        shutil.move(str(src), str(dst))
    return UndoRecord(mode=mode, src=src, dst=dst, idx=idx)


def revertir(rec: UndoRecord) -> Optional[Path]:
    """Deshace ``rec``.

    * COPY: borra la copia (no toca la fuente). Devuelve ``None``.
    * MOVE: devuelve el archivo a la fuente (sin pisar) y retorna la ruta final.

    Lanza ``FileNotFoundError`` si el destino ya no existe.
    """
    if not rec.dst.exists():
        raise FileNotFoundError(f"No existe el destino: {rec.dst}")
    if rec.mode == "copy":
        rec.dst.unlink()
        _borrar_si_vacia(rec.dst.parent)
        return None
    rec.src.parent.mkdir(parents=True, exist_ok=True)
    back = unique_path(rec.src)
    shutil.move(str(rec.dst), str(back))
    _borrar_si_vacia(rec.dst.parent)
    return back


def _borrar_si_vacia(carpeta: Path) -> None:
    """Quita la carpeta ITEM (y la del nodo) si quedaron vacías tras un Undo."""
    for d in (carpeta, carpeta.parent):
        try:
            d.rmdir()
        except OSError:
            break


class UndoStack:
    """Pila LIFO de :class:`UndoRecord`."""

    def __init__(self) -> None:
        self._items: List[UndoRecord] = []

    def __len__(self) -> int:
        return len(self._items)

    def push(self, rec: UndoRecord) -> None:
        self._items.append(rec)

    def pop(self) -> Optional[UndoRecord]:
        return self._items.pop() if self._items else None

    def clear(self) -> None:
        self._items.clear()
