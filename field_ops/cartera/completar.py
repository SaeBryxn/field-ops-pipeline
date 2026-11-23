"""Paso 3 del flujo: completar la cartera Excel a partir de las fotos ordenadas.

Por cada carpeta ``NODO/ITEM-x``:
    * busca la fila (ID NODO + ITEM) en la cartera o crea una nueva;
    * llena datos del catálogo (nombre, departamento, provincia, distrito);
    * llena coordenadas desde el GPS de las fotos (lat/lon -> UTM, altitud), fecha y
      cantidad de fotos;
    * NUNCA pisa un dato que una persona ya escribió (solo completa celdas vacías);
    * recalcula las columnas con fórmulas (distancias, abscisas, cable, etc.);
    * marca cada fila como ``OK`` o ``REVISAR`` con el motivo.

El resultado es una copia versionada ``CARTERA_<fecha>__AUTO.xlsx`` lista para la
revisión humana, que es la que afina los detalles antes de entregar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Optional

import openpyxl
import pandas as pd

from ..imagen import leer_datos_foto
from ..nodos import CatalogoNodos
from ..reporte import ALERTA, escribir_hoja
from ..rutas import CarpetaItem, clave_item, escanear_ordenado
from ..utm import latlon_a_utm
from .esquema import SchemaManager
from .excel_io import crear_plantilla_vacia, escribir_tabla, leer_tabla
from .motor import recalcular_por_nodo
from .validador import Validator, vacio

COL_ESTADO = "ESTADO REVISIÓN"
COL_OBS = "OBSERVACIÓN AUTO"
TOLERANCIA_UTM_M = 50.0      # diferencia máxima entre UTM registrado y GPS de la foto
DISPERSION_ITEM_M = 30.0     # fotos de un mismo ITEM deberían estar juntas
SIEMPRE_ACTUALIZAR = {"n_fotos", "carpeta_fotos", "fecha_foto"}


@dataclass
class DatosItem:
    """Lo que se puede deducir de las fotos de un ITEM."""

    n_fotos: int
    lat: Optional[float] = None
    lon: Optional[float] = None
    alt: Optional[float] = None
    este: Optional[float] = None
    norte: Optional[float] = None
    fecha: Optional[datetime] = None
    dispersion_m: float = 0.0
    sin_gps: int = 0


def analizar_fotos(carpeta: CarpetaItem) -> DatosItem:
    """Promedia el GPS de las fotos del ITEM y mide qué tan dispersas están."""
    datos = [leer_datos_foto(p) for p in carpeta.fotos]
    con_gps = [d for d in datos if d.lat is not None and d.lon is not None]
    fechas = [d.fecha for d in datos if d.fecha]
    res = DatosItem(n_fotos=len(datos), fecha=min(fechas) if fechas else None, sin_gps=len(datos) - len(con_gps))
    if not con_gps:
        return res
    res.lat = mean(d.lat for d in con_gps)
    res.lon = mean(d.lon for d in con_gps)
    alts = [d.alt for d in con_gps if d.alt is not None]
    res.alt = mean(alts) if alts else None
    res.este, res.norte, zona, _ = latlon_a_utm(res.lat, res.lon)
    for d in con_gps:
        e, n, _, _ = latlon_a_utm(d.lat, d.lon, zona)
        res.dispersion_m = max(res.dispersion_m, math.hypot(e - res.este, n - res.norte))
    return res


@dataclass
class ResultadoCartera:
    salida: Path
    filas: int = 0
    nuevas: int = 0
    actualizadas: int = 0
    revisar: int = 0
    items_fotos: int = 0
    celdas_ref: list[str] = field(default_factory=list)

    def resumen(self) -> str:
        txt = (
            f"Cartera: {self.salida.name}\n"
            f"{self.items_fotos} carpetas ITEM procesadas · {self.filas} filas "
            f"({self.nuevas} nuevas, {self.actualizadas} completadas)\n"
            f"Filas para revisión humana: {self.revisar}"
        )
        if self.celdas_ref:
            txt += f"\nAviso: la plantilla tiene {len(self.celdas_ref)} celda(s) con #REF!"
        return txt


def _txt(v: Any) -> str:
    if vacio(v):
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip().upper()


def _num(v: Any) -> Optional[float]:
    try:
        return None if vacio(v) else float(str(v).replace(",", "."))
    except ValueError:
        return None


def completar_cartera(
    out_base: Path,
    plantilla: Optional[Path] = None,
    catalogo: Optional[CatalogoNodos] = None,
    schema: Optional[SchemaManager] = None,
    salida: Optional[Path] = None,
) -> ResultadoCartera:
    """Genera la cartera completada. Ver docstring del módulo."""
    schema = schema or SchemaManager.por_defecto()
    catalogo = catalogo or CatalogoNodos()
    salida = salida or out_base / f"CARTERA_{datetime.now():%Y%m%d_%H%M%S}__AUTO.xlsx"
    carpetas = escanear_ordenado(out_base)
    if not carpetas:
        raise ValueError(f"No hay carpetas NODO/ITEM ordenadas en {out_base}")

    if plantilla is None:
        cabeceras = list(dict.fromkeys(schema.columnas_modo("Completo") + schema.calculated_headers))
        plantilla = crear_plantilla_vacia(salida.with_name("_plantilla_tmp.xlsx"), cabeceras, schema)
        tmp = plantilla
    else:
        tmp = None
    tabla = leer_tabla(plantilla, schema)
    df = tabla.df.copy()

    # columnas que la automatización necesita y la plantilla no tiene
    col: dict[str, str] = {}
    for clave, prefijo in schema.columnas_auto.items():
        c = schema.resolve_column(df.columns, prefijo)
        if c is None and clave in ("id_nodo", "item", "n_fotos", "carpeta_fotos", "fecha_foto"):
            c = prefijo
            df[c] = None
        if c:
            col[clave] = c
    for extra in (COL_ESTADO, COL_OBS):
        if extra not in df.columns:
            df[extra] = None

    # índice de filas existentes por (nodo, item)
    indice = {
        (_txt(df.at[i, col["id_nodo"]]), _txt(df.at[i, col["item"]])): i
        for i in df.index
        if _txt(df.at[i, col["id_nodo"]]) and _txt(df.at[i, col["item"]])
    }
    obs: dict[int, list[str]] = {i: [] for i in df.index}
    res = ResultadoCartera(salida=salida, items_fotos=len(carpetas), celdas_ref=tabla.celdas_ref)
    nodos_lote = {c.codigo for c in carpetas}
    con_fotos: set[int] = set()

    for carpeta in carpetas:
        datos = analizar_fotos(carpeta)
        nodo = catalogo.get(carpeta.codigo)
        valores = {
            "id_nodo": carpeta.codigo,
            "item": int(carpeta.item) if carpeta.item.isdigit() else carpeta.item,
            "nombre_nodo": nodo.localidad if nodo else carpeta.localidad,
            "departamento": nodo.departamento if nodo else None,
            "provincia": nodo.provincia if nodo else None,
            "distrito": nodo.distrito if nodo else None,
            "x_utm": round(datos.este, 2) if datos.este is not None else None,
            "y_utm": round(datos.norte, 2) if datos.norte is not None else None,
            "altitud": round(datos.alt, 1) if datos.alt is not None else None,
            "latitud": round(datos.lat, 6) if datos.lat is not None else None,
            "longitud": round(datos.lon, 6) if datos.lon is not None else None,
            "n_fotos": datos.n_fotos,
            "carpeta_fotos": f"{carpeta.ruta.parent.name}/{carpeta.ruta.name}",
            "fecha_foto": datos.fecha.strftime("%Y-%m-%d %H:%M") if datos.fecha else None,
        }
        clave = (carpeta.codigo, carpeta.item)
        if clave in indice:
            i = indice[clave]
            res.actualizadas += 1
        else:
            i = (max(df.index) + 1) if len(df.index) else 0
            df.loc[i] = [None] * len(df.columns)
            obs[i] = ["fila nueva creada desde fotos"]
            indice[clave] = i
            res.nuevas += 1
        con_fotos.add(i)

        # alertas antes de llenar: comparar GPS con lo que ya estaba escrito
        if datos.este is not None and "x_utm" in col and "y_utm" in col:
            x0, y0 = _num(df.at[i, col["x_utm"]]), _num(df.at[i, col["y_utm"]])
            if x0 is not None and y0 is not None:
                dif = math.hypot(x0 - datos.este, y0 - datos.norte)
                if dif > TOLERANCIA_UTM_M:
                    obs[i].append(f"GPS de fotos a {dif:.0f} m del UTM registrado")
        if datos.este is None:
            obs[i].append("fotos sin GPS: completar coordenadas")
        elif datos.sin_gps:
            obs[i].append(f"{datos.sin_gps} foto(s) sin GPS")
        if datos.dispersion_m > DISPERSION_ITEM_M:
            obs[i].append(f"fotos separadas {datos.dispersion_m:.0f} m: ¿ITEM mal asignado?")
        if not nodo and len(catalogo):
            obs[i].append("nodo no está en el catálogo")

        for k, v in valores.items():
            c = col.get(k)
            if c is None or v is None:
                continue
            if k in SIEMPRE_ACTUALIZAR or vacio(df.at[i, c]):
                df.at[i, c] = v

    for i in df.index:  # filas del lote que ya no tienen fotos
        if i not in con_fotos and _txt(df.at[i, col["id_nodo"]]) in nodos_lote:
            obs[i].append("sin carpeta de fotos")

    # orden natural por nodo e ITEM (las fórmulas encadenan fila a fila)
    orden = sorted(
        df.index,
        key=lambda i: (
            _txt(df.at[i, col["id_nodo"]]) == "",
            _txt(df.at[i, col["id_nodo"]]),
            clave_item(_txt(df.at[i, col["item"]]) or "~"),
        ),
    )
    obs_ordenadas = [obs[i] for i in orden]
    df = df.loc[orden].reset_index(drop=True)
    df = recalcular_por_nodo(df, schema, col["id_nodo"]).reset_index(drop=True)
    df = df.astype(object).where(pd.notna(df), None)

    errores = Validator.validate(df, schema)
    for pos in range(len(df)):
        motivos = list(obs_ordenadas[pos])
        motivos += [m for m in errores.get(pos, {}).values() if m not in motivos]
        revisar = [m for m in motivos if m != "fila nueva creada desde fotos"]
        df.at[pos, COL_ESTADO] = "REVISAR" if revisar else "OK"
        df.at[pos, COL_OBS] = "; ".join(motivos) or None
        if revisar:
            res.revisar += 1
    res.filas = len(df)

    escribir_tabla(plantilla, salida, df, schema, errores=errores, col_estado=COL_ESTADO)
    _hojas_resumen(salida, df, col)
    if tmp is not None:
        tmp.unlink(missing_ok=True)
    return res


def _hojas_resumen(salida: Path, df: pd.DataFrame, col: dict[str, str]) -> None:
    """Agrega hojas "Revisión" (pendientes) y "Resumen por nodo"."""
    wb = openpyxl.load_workbook(salida)
    for nombre in ("Revisión", "Resumen por nodo"):
        if nombre in wb.sheetnames:
            del wb[nombre]

    ws = wb.create_sheet("Revisión")
    pendientes = df[df[COL_ESTADO] == "REVISAR"]
    escribir_hoja(
        ws, ["ID NODO", "ITEM", "MOTIVO", "REVISADO POR", "OK (S/N)"],
        ([r[col["id_nodo"]], r[col["item"]], r[COL_OBS], None, None] for _, r in pendientes.iterrows()),
    )
    for r in range(2, len(pendientes) + 2):
        for c in range(1, 6):
            ws.cell(row=r, column=c).fill = ALERTA

    ws2 = wb.create_sheet("Resumen por nodo")
    filas = []
    for nodo, g in df.groupby(col["id_nodo"], sort=True):
        fotos = sum(int(v) for v in g.get(col.get("n_fotos", ""), pd.Series(dtype=object)) if _num(v) is not None)
        filas.append([nodo, len(g), fotos, int((g[COL_ESTADO] == "REVISAR").sum())])
    escribir_hoja(ws2, ["ID NODO", "FILAS", "FOTOS", "POR REVISAR"], filas)
    wb.save(salida)
