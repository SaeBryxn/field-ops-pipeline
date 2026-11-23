"""Reporte Excel para el supervisor: resumen por nodo/ITEM + log de acciones."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from .nodos import CatalogoNodos
from .registro import RegistroAcciones
from .rutas import escanear_ordenado

ENCABEZADO = PatternFill("solid", fgColor="1F4E78")
ALERTA = PatternFill("solid", fgColor="FCE4D6")


def escribir_hoja(ws, cabeceras: Sequence[str], filas: Iterable[Sequence], tabla: Optional[str] = None) -> None:
    """Escribe cabecera + filas con formato, filtro, panel fijo y ancho automático."""
    ws.append(list(cabeceras))
    for c in range(1, len(cabeceras) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = ENCABEZADO
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    n = 1
    for f in filas:
        ws.append(list(f))
        n += 1
    ws.freeze_panes = "A2"
    ultima = get_column_letter(len(cabeceras))
    if tabla and n > 1:
        t = Table(displayName=tabla, ref=f"A1:{ultima}{n}")
        t.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
        ws.add_table(t)
    else:
        ws.auto_filter.ref = f"A1:{ultima}{max(n, 1)}"
    autoajustar(ws)


def autoajustar(ws, max_width: int = 60) -> None:
    for col in ws.columns:
        largo = max((len(str(c.value)) for c in col[:2000] if c.value is not None), default=0)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(10, largo + 2), max_width)


def generar_reporte(
    out_base: Path,
    destino: Optional[Path] = None,
    catalogo: Optional[CatalogoNodos] = None,
    minimo_fotos: int = 1,
) -> Path:
    """Crea ``REPORTE_ORDENAMIENTO_<fecha>.xlsx`` en ``out_base``.

    Hojas:
        * Resumen: una fila por NODO/ITEM con cantidad de fotos y observación.
        * Por nodo: totales por nodo.
        * Log: todas las acciones registradas (incluye Undo).
    """
    carpetas = escanear_ordenado(out_base)
    destino = destino or out_base / f"REPORTE_ORDENAMIENTO_{datetime.now():%Y%m%d_%H%M}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    filas = []
    for c in carpetas:
        obs = []
        if len(c.fotos) < minimo_fotos:
            obs.append(f"menos de {minimo_fotos} foto(s)")
        if catalogo is not None and len(catalogo) and c.codigo not in catalogo:
            obs.append("nodo no está en catálogo")
        filas.append([c.codigo, c.localidad, c.item, len(c.fotos), "; ".join(obs) or "OK"])
    escribir_hoja(ws, ["NODO", "LOCALIDAD", "ITEM", "FOTOS", "OBSERVACIÓN"], filas, tabla="Resumen")
    for r in range(2, len(filas) + 2):
        if ws.cell(row=r, column=5).value != "OK":
            for col in range(1, 6):
                ws.cell(row=r, column=col).fill = ALERTA

    ws2 = wb.create_sheet("Por nodo")
    totales: dict[tuple[str, str], list[int]] = {}
    for c in carpetas:
        t = totales.setdefault((c.codigo, c.localidad), [0, 0])
        t[0] += 1
        t[1] += len(c.fotos)
    escribir_hoja(
        ws2, ["NODO", "LOCALIDAD", "ITEMS", "FOTOS"],
        [[k[0], k[1], v[0], v[1]] for k, v in sorted(totales.items())], tabla="PorNodo",
    )

    ws3 = wb.create_sheet("Log")
    log = RegistroAcciones.en_salida(out_base).leer()
    cab = list(log[0].keys()) if log else ["fecha", "accion"]
    escribir_hoja(ws3, cab, ([fila.get(k, "") for k in cab] for fila in log))

    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino
