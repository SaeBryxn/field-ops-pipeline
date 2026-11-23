"""Log CSV de cada acción del operador (trazabilidad para el supervisor)."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

CAMPOS = [
    "fecha", "accion", "modo", "archivo", "nodo", "localidad",
    "item", "destino", "operador", "sugerencia",
]

NOMBRE_LOG = "_registro_acciones.csv"


class RegistroAcciones:
    """Agrega filas a ``<salida>/_registro_acciones.csv`` (se crea con cabecera)."""

    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def en_salida(cls, out_base: Path) -> "RegistroAcciones":
        return cls(out_base / NOMBRE_LOG)

    def anotar(
        self,
        accion: str,
        modo: str,
        archivo: Path,
        destino: Optional[Path],
        nodo: str = "",
        localidad: str = "",
        item: str = "",
        operador: str = "",
        sugerencia: str = "",
        fecha: Optional[datetime] = None,
    ) -> None:
        nuevo = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS)
            if nuevo:
                w.writeheader()
            w.writerow({
                "fecha": (fecha or datetime.now()).isoformat(timespec="seconds"),
                "accion": accion,
                "modo": modo,
                "archivo": archivo.name,
                "nodo": nodo,
                "localidad": localidad,
                "item": item,
                "destino": str(destino or ""),
                "operador": operador,
                "sugerencia": sugerencia,
            })

    def leer(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        with self.path.open(newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
