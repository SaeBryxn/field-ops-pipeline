from __future__ import annotations

import shutil
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from field_ops.cartera import reglas
from field_ops.cartera.completar import COL_ESTADO, COL_OBS, completar_cartera
from field_ops.cartera.esquema import SchemaManager
from field_ops.cartera.excel_io import leer_tabla
from field_ops.cartera.motor import CalcEngine, recalcular_por_nodo
from field_ops.cartera.validador import Validator
from field_ops.nodos import CatalogoNodos
from field_ops.rutas import build_dest_folder

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def schema() -> SchemaManager:
    return SchemaManager.por_defecto()


COLS = [
    "TIPO DE CABLE", "TIPO DE ELEMENTO\nND: Nodo Distrital", "TIPO DE RED ELECTRICA\nAT: Alta Tensión",
    "X UTM", "Y UTM ", "ALTITUD (msnm)", "SPAN CONSTRUIDO", "RESERVA  IN (m)", "RESERVA OUT (m)",
    "Tipo de Reserva", "DISTANCIA ENTRE ELEMENTOS (m.)", "FLECHA", "ABSCISA INICIAL", "ABSCISA FINAL",
    "VANO DE FIBRA OPTICA ENTRE ELEMENTOS \n(DIFERENCIA DE ABSCISAS) (m)", "CABLE", "ETIQUETAS",
    "Longitud Reserva\n(m.)", "CINTA ACERADA (CANTIDAD UND)", "HEBILLAS", "CABLE MENSAJERO",
    "VANO FLOJO", "RED ELECTRICA\nRED VIAL",
]


def _col(df: pd.DataFrame, prefijo: str) -> str:
    return next(c for c in df.columns if c.startswith(prefijo))


# ------------------------------------------------------------------ reglas
def test_reglas_basicas():
    assert reglas.distance_3d(0, 0, 0, 3, 4, 0) == 5.0
    assert reglas.distance_3d(0, 0, 0, "x", 4, 0) is None
    assert reglas.flecha_from_span(100, 200) == pytest.approx(2.0)
    assert reglas.flecha_from_span(600, 100) == pytest.approx(2.0)
    assert reglas.flecha_from_span("-", 100) == "-"
    assert reglas.roundup(10.01) == 11 and reglas.roundup(None) == 0.0
    assert reglas.etiqueta_from_bc("RE") == "3" and reglas.etiqueta_from_bc("RT") == "2"
    assert reglas.long_reserva(15, 15) == 30 and reglas.long_reserva("-", 5) == 0
    assert reglas.cinta_acerada(30, "CB", 1, 0, "S") == 8
    assert reglas.red_from_wu("-", "ND", None) == "RED VIAL"
    assert reglas.red_from_wu("BT", "PE", None) == "RED ELECTRICA"
    assert reglas._num(float("nan")) is None


# ------------------------------------------------------------------- motor
def test_calc_basic_distance_and_red(schema):
    """Test original del proyecto (corregido: buscaba la columna con `in` y tomaba
    "TIPO DE RED ELECTRICA" en lugar de "RED ELECTRICA")."""
    df = pd.DataFrame([
        ["ADSS", "PE", "BT", 0, 0, 0, 100, 0, 0, "-"] + [None, None, 10, 30] + [None] * 9,
        ["ADSS", "PE", "PN", 3, 4, 0, 100, 0, 0, "-"] + [None] * 13,
    ], columns=COLS, dtype=object)
    out = CalcEngine.recalculate(df, schema)
    assert float(out.loc[0, _col(out, "DISTANCIA ENTRE ELEMENTOS")]) == 5.0
    assert out.loc[0, _col(out, "RED ELECTRICA")] == "RED ELECTRICA"
    assert out.loc[1, _col(out, "RED ELECTRICA")] == "RED VIAL"
    # abscisas: AM0=10 (existente), AN0 = 30 (existente); fila 1 arranca en 30
    assert out.loc[1, _col(out, "ABSCISA INICIAL")] == 30


def test_resolve_column_prefiere_exacta(schema):
    cols = ["CABLE MENSAJERO", "CABLE", "TIPO DE CABLE"]
    assert schema.resolve_column(cols, "CABLE") == "CABLE"
    assert schema.resolve_column(["CABLE MENSAJERO"], "CABLE") == "CABLE MENSAJERO"
    assert schema.resolve_column(["Altitud (msnm)"], "ALTITUD") == "Altitud (msnm)"
    assert schema.resolve_column(["X"], "ALTITUD") is None


def test_recalculo_por_nodo_no_mezcla_nodos(schema):
    base = ["ADSS", "PE", "BT", None, None, 0, 100, 0, 0, "-"] + [None] * 13
    filas = []
    for x in (0, 100, 1_000_000, 1_000_050):  # dos nodos muy lejos entre sí
        f = list(base)
        f[3], f[4] = x, 0
        filas.append(f)
    df = pd.DataFrame(filas, columns=COLS, dtype=object)
    df["ID NODO"] = ["A", "A", "B", "B"]
    out = recalcular_por_nodo(df, schema, "ID NODO")
    dist = out[_col(out, "DISTANCIA ENTRE ELEMENTOS")].tolist()
    assert dist[0] == pytest.approx(100) and dist[2] == pytest.approx(50)
    assert dist[1] == ""  # último del nodo A: no se encadena con el nodo B
    assert out.loc[2, _col(out, "ABSCISA INICIAL")] == 0  # B arranca de cero


# --------------------------------------------------------------- validador
def test_validador(schema):
    df = pd.DataFrame(
        [["AY-0901-A01", "1", "PE", "abc", 1, 2], ["AY-0901-A01", "2", "ZZ", 1, 1, None]],
        columns=["ID NODO", "ITEM", "TIPO DE ELEMENTO", "X UTM", "Y UTM", "ALTITUD"], dtype=object,
    )
    err = Validator.validate(df, schema)
    assert "no numérico" in err[0]["X UTM"]
    assert "fuera de lista" in err[1]["TIPO DE ELEMENTO"]
    assert err[1]["ALTITUD"] == "falta ALTITUD"


# --------------------------------------------------------- de punta a punta
@pytest.fixture(scope="module")
def demo(tmp_path_factory) -> Path:
    """Demo ya ordenada (20 ITEM de 5 nodos) + plantilla con filas de diseño."""
    import generar_demo

    d = tmp_path_factory.mktemp("demo")
    generar_demo.generar_fotos(d / "salida", ya_ordenado=True)
    ref = next((d / "salida").rglob("AY-0903-A01_ITEM-2_001.jpg"))
    from field_ops.imagen import leer_datos_foto
    from field_ops.utm import latlon_a_utm

    g = leer_datos_foto(ref)
    e, n, _, _ = latlon_a_utm(g.lat, g.lon)
    generar_demo.crear_plantilla_cartera(d / "plantilla.xlsx", (e + 180, n))
    return d


def test_completar_cartera_con_plantilla(demo, schema, tmp_path):
    salida = shutil.copytree(demo / "salida", tmp_path / "salida")
    plantilla = demo / "plantilla.xlsx"
    antes = plantilla.read_bytes()
    cat = CatalogoNodos.desde_csv(RAIZ / "config" / "nodos.example.csv")

    res = completar_cartera(salida, plantilla, cat, schema)

    assert plantilla.read_bytes() == antes  # la plantilla original no se toca
    assert (res.filas, res.nuevas, res.actualizadas) == (20, 8, 12)
    df = leer_tabla(res.salida, schema).df
    fila = lambda nodo, item: df[(df["ID NODO"] == nodo) & (df["ITEM"].astype(str) == item)].iloc[0]  # noqa: E731

    ok = fila("AY-0901-A01", "1")
    assert ok[COL_ESTADO] == "OK"
    assert ok["NOMBRE DE NODO"] == "VILLA EJEMPLO"
    assert 500_000 < ok["X UTM"] < 700_000 and 8_000_000 < ok["Y UTM "] < 9_000_000
    assert ok["N° FOTOS"] == 2
    assert isinstance(ok[_col(df, "Longitud Reserva")], str)  # fórmula conservada

    desfasada = fila("AY-0903-A01", "2")
    assert desfasada[COL_ESTADO] == "REVISAR" and "del UTM registrado" in desfasada[COL_OBS]
    assert desfasada["X UTM"] > ok["X UTM"]  # el dato humano NO se pisó

    sin_gps = fila("AY-0904-A01", "3")
    assert sin_gps[COL_ESTADO] == "REVISAR" and "sin GPS" in sin_gps[COL_OBS]
    assert res.revisar == 9

    wb = openpyxl.load_workbook(res.salida)
    assert {"Revisión", "Resumen por nodo"} <= set(wb.sheetnames)
    ws = wb["Cartera"]
    assert ws.tables["Tareas"].ref.endswith("21")  # 20 filas + cabecera
    # la fórmula se copió (traducida) a la última fila nueva
    col_lr = next(c.column for c in ws[1] if str(c.value).startswith("Longitud Reserva"))
    assert ws.cell(row=21, column=col_lr).value.endswith("AA21))")


def test_completar_sin_plantilla(demo, schema, tmp_path):
    salida = shutil.copytree(demo / "salida", tmp_path / "salida")
    res = completar_cartera(salida, None, CatalogoNodos(), schema)
    assert res.nuevas == 20 and res.salida.exists()
    assert not list(salida.glob("_plantilla_tmp*"))
    df = leer_tabla(res.salida, schema).df
    assert set(df[COL_ESTADO]) == {"REVISAR"}  # sin diseño todo requiere revisión


def test_completar_sin_fotos(tmp_path, schema):
    with pytest.raises(ValueError):
        completar_cartera(tmp_path, None, schema=schema)


def test_fila_sin_carpeta_de_fotos(demo, schema, tmp_path):
    salida = shutil.copytree(demo / "salida", tmp_path / "salida")
    shutil.rmtree(build_dest_folder(salida, "AY-0901-A01", "VILLA EJEMPLO", "4"))
    res = completar_cartera(salida, demo / "plantilla.xlsx", schema=schema)
    df = leer_tabla(res.salida, schema).df
    f = df[(df["ID NODO"] == "AY-0901-A01") & (df["ITEM"].astype(str) == "4")].iloc[0]
    assert f[COL_ESTADO] == "REVISAR" and "sin carpeta de fotos" in f[COL_OBS]
