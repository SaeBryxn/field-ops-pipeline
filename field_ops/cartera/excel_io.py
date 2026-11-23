"""Lectura y escritura de la tabla de la cartera dentro de la plantilla Excel.

Escribe SIEMPRE en una copia versionada (nunca toca el archivo original) y conserva
lo que hace valiosa la plantilla: formato, tabla de Excel, listas desplegables y
fórmulas de las columnas calculadas (se copian hacia abajo en las filas nuevas).
"""

from __future__ import annotations

import copy
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import openpyxl
import pandas as pd
from openpyxl.formula.translate import Translator
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableColumn, TableStyleInfo

from .esquema import SchemaManager

ROJO = PatternFill("solid", fgColor="F8CBAD")
NARANJA = PatternFill("solid", fgColor="FFE699")
VERDE = PatternFill("solid", fgColor="C6EFCE")


@dataclass
class TablaCartera:
    """La tabla leída de la plantilla."""

    path: Path
    sheet_name: str
    table_name: str
    headers: list[str]
    df: pd.DataFrame
    celdas_ref: list[str] = field(default_factory=list)


def _cabeceras_unicas(raw: list[Any]) -> list[str]:
    vistos: dict[str, int] = {}
    out = []
    for h in raw:
        h = "" if h is None else str(h)
        if h in vistos:
            vistos[h] += 1
            h = f"{h} ({vistos[h]})"
        else:
            vistos[h] = 0
        out.append(h)
    return out


def _buscar_tabla(wb, schema: SchemaManager):
    """Hoja y tabla configuradas; si no existen, la primera tabla del libro."""
    if schema.sheet_name in wb.sheetnames and schema.table_name in wb[schema.sheet_name].tables:
        ws = wb[schema.sheet_name]
        return ws, ws.tables[schema.table_name]
    for ws in wb.worksheets:
        for t in ws.tables.values():
            return ws, t
    raise ValueError(
        f"No encontré la tabla '{schema.table_name}' en la hoja '{schema.sheet_name}' "
        "ni ninguna otra tabla de Excel (Insertar > Tabla)."
    )


def leer_tabla(path: Path, schema: SchemaManager) -> TablaCartera:
    """Lee la tabla como DataFrame (dtype object, celdas vacías = ``None``).

    Las columnas con fórmula se leen como texto ``"=..."``; el motor las recalcula.
    También informa celdas con ``#REF!`` (fórmulas rotas en la plantilla).
    """
    wb = openpyxl.load_workbook(path, data_only=False)
    ws, tbl = _buscar_tabla(wb, schema)
    min_col, min_row, max_col, max_row = range_boundaries(tbl.ref)
    headers = _cabeceras_unicas([ws.cell(row=min_row, column=c).value for c in range(min_col, max_col + 1)])
    filas, refs = [], []
    for r in range(min_row + 1, max_row + 1):
        fila = []
        for c in range(min_col, max_col + 1):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str) and "#REF!" in v:
                refs.append(f"{get_column_letter(c)}{r}")
            fila.append(v)
        if any(v not in (None, "") for v in fila):
            filas.append(fila)
    df = pd.DataFrame(filas, columns=headers, dtype=object)
    return TablaCartera(path, ws.title, tbl.displayName, headers, df, refs)


def crear_plantilla_vacia(path: Path, headers: list[str], schema: SchemaManager) -> Path:
    """Crea una cartera nueva con la tabla configurada (cuando no hay plantilla)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = schema.sheet_name
    ws.append(headers)
    ws.append([None] * len(headers))
    t = Table(displayName=schema.table_name, ref=f"A1:{get_column_letter(len(headers))}2")
    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(t)
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(c)].width = max(12, min(28, len(h) + 2))
        valores = schema.combo_values(h)
        if valores:
            dv = DataValidation(type="list", formula1='"' + ",".join(valores) + '"', allow_blank=True)
            dv.add(f"{get_column_letter(c)}2:{get_column_letter(c)}2")
            ws.add_data_validation(dv)
    ws.row_dimensions[1].height = 45
    ws.freeze_panes = "A2"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ------------------------------------------------------------- escritura
def _copiar_estilo(src, dst) -> None:
    if src.has_style:
        dst._style = copy.copy(src._style)


def _es_formula(v: Any) -> bool:
    return isinstance(v, str) and v.startswith("=")


def _valor_excel(v: Any) -> Any:
    if v is None or (isinstance(v, float) and v != v):
        return None
    if hasattr(v, "item"):  # numpy -> python
        return v.item()
    return v


def escribir_tabla(
    plantilla: Path,
    salida: Path,
    df: pd.DataFrame,
    schema: SchemaManager,
    errores: Optional[dict[int, dict[str, str]]] = None,
    col_estado: Optional[str] = None,
) -> Path:
    """Copia ``plantilla`` a ``salida`` y vuelca ``df`` en la tabla.

    * Agrega al final de la tabla las columnas de ``df`` que no existan.
    * Extiende la tabla, estilos, fórmulas y listas desplegables a las filas nuevas.
    * En columnas calculadas: si la celda tiene fórmula se respeta; si no, se escribe
      el valor calculado por el motor.
    * Pinta en rojo las celdas con error y la columna de estado (OK/REVISAR).
    """
    errores = errores or {}
    salida.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(plantilla, salida)
    wb = openpyxl.load_workbook(salida, data_only=False)
    ws, tbl = _buscar_tabla(wb, schema)
    min_col, min_row, max_col, max_row = range_boundaries(tbl.ref)

    # A) columnas nuevas
    existentes = _cabeceras_unicas([ws.cell(row=min_row, column=c).value for c in range(min_col, max_col + 1)])
    for h in [c for c in df.columns if c not in existentes]:
        max_col += 1
        ws.cell(row=min_row, column=max_col, value=h)
        _copiar_estilo(ws.cell(row=min_row, column=max_col - 1), ws.cell(row=min_row, column=max_col))
        ws.column_dimensions[get_column_letter(max_col)].width = max(14, min(40, len(h) + 2))
        tbl.tableColumns.append(TableColumn(id=len(tbl.tableColumns) + 1, name=h))
        existentes.append(h)
    col_de = {h: min_col + i for i, h in enumerate(existentes)}

    # B) filas: extender tabla y copiar estilo/fórmulas de la última fila original
    old_max_row = max_row
    new_max_row = max(old_max_row, min_row + max(len(df), 1))
    for r in range(old_max_row + 1, new_max_row + 1):
        for c in range(min_col, max_col + 1):
            src, dst = ws.cell(row=old_max_row, column=c), ws.cell(row=r, column=c)
            _copiar_estilo(src, dst)
            h = existentes[c - min_col]
            if schema.is_calculated(h) and _es_formula(src.value) and "#REF!" not in src.value:
                try:
                    dst.value = Translator(src.value, origin=src.coordinate).translate_formula(dst.coordinate)
                except Exception:  # noqa: BLE001 - fórmula no traducible: se escribe el valor calculado
                    dst.value = None
    tbl.ref = f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{new_max_row}"
    if tbl.autoFilter is not None:
        tbl.autoFilter.ref = tbl.ref

    # C) listas desplegables hacia filas nuevas
    if new_max_row > old_max_row:
        for dv in list(ws.data_validations.dataValidation):
            for cr in list(dv.sqref.ranges):
                if cr.min_col <= max_col and cr.max_col >= min_col:
                    dv.add(f"{get_column_letter(cr.min_col)}{old_max_row + 1}:{get_column_letter(cr.max_col)}{new_max_row}")
                    break

    # D) valores
    primera = min_row + 1
    for pos in range(len(df)):
        r = primera + pos
        fila = df.iloc[pos]
        for h, v in fila.items():
            c = col_de.get(h)
            if c is None:
                continue
            cell = ws.cell(row=r, column=c)
            if schema.is_calculated(h) and _es_formula(cell.value):
                continue  # la fórmula de la plantilla manda
            if _es_formula(v) and not schema.is_calculated(h):
                cell.value = v
                continue
            cell.value = _valor_excel(v)
        for h in errores.get(pos, {}):
            if h in col_de:
                ws.cell(row=r, column=col_de[h]).fill = ROJO
        if col_estado and col_estado in col_de:
            estado = ws.cell(row=r, column=col_de[col_estado])
            estado.fill = NARANJA if str(estado.value).startswith("REVISAR") else VERDE
    # filas sobrantes de la plantilla (si df tiene menos filas)
    for r in range(primera + len(df), new_max_row + 1):
        for c in range(min_col, max_col + 1):
            if not _es_formula(ws.cell(row=r, column=c).value):
                ws.cell(row=r, column=c).value = None

    wb.save(salida)
    return salida
