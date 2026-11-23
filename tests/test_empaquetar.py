from __future__ import annotations

import csv
import zipfile
from pathlib import Path

import openpyxl
import pytest

from field_ops.cli import main as cli_main
from field_ops.empaquetar import (
    RevisionPendiente, contar_pendientes, empaquetar_entrega, sha256, subir_con_rclone,
)
from field_ops.reporte import generar_reporte

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def salida(tmp_path) -> Path:
    """Salida ordenada mínima: 2 nodos, 3 ITEM, 4 fotos."""
    from generar_demo import crear_foto

    base = tmp_path / "salida"
    datos = [("AY-0901-A01", "VILLA EJEMPLO", "1", 2), ("AY-0901-A01", "VILLA EJEMPLO", "2", 1),
             ("AY-0902-A01", "SAN DEMO", "1", 1)]
    n = 0
    for codigo, loc, item, k in datos:
        for j in range(k):
            n += 1
            crear_foto(base / f"{codigo}-{loc}" / f"ITEM-{item}" / f"f{j}.jpg", codigo, item,
                       -13.16 + n * 1e-3, -74.22, 2750, semilla=n)
    return base


def _marcar_revisado(cartera: Path, todas: bool = True) -> None:
    wb = openpyxl.load_workbook(cartera)
    ws = wb["Revisión"]
    for r in range(2, ws.max_row + 1 if todas else 3):
        ws.cell(row=r, column=5, value="S")
    wb.save(cartera)


def test_empaquetar_bloquea_si_hay_revision_pendiente(salida):
    from field_ops.cartera.completar import completar_cartera

    res = completar_cartera(salida)  # sin plantilla: todo queda en REVISAR
    assert contar_pendientes(res.salida) == 3
    with pytest.raises(RevisionPendiente):
        empaquetar_entrega(salida)
    _marcar_revisado(res.salida, todas=False)
    assert contar_pendientes(res.salida) == 2
    _marcar_revisado(res.salida)
    assert contar_pendientes(res.salida) == 0

    ent = empaquetar_entrega(salida, zip_modo="por_nodo")
    assert (ent.nodos, ent.fotos, ent.pendientes) == (2, 4, 0)
    assert (ent.carpeta / "00_CARTERA.xlsx").exists() and (ent.carpeta / "00_REPORTE.xlsx").exists()
    assert "COMPLETA" in (ent.carpeta / "LEEME.txt").read_text(encoding="utf-8")
    assert len(ent.zips) == 2
    with zipfile.ZipFile(ent.zips[0]) as z:
        assert sorted(z.namelist()) == [
            "AY-0901-A01-VILLA EJEMPLO/ITEM-1/f0.jpg",
            "AY-0901-A01-VILLA EJEMPLO/ITEM-1/f1.jpg",
            "AY-0901-A01-VILLA EJEMPLO/ITEM-2/f0.jpg",
        ]
    # la salida original sigue intacta (se copia, no se mueve)
    assert len(list(salida.rglob("*.jpg"))) == 4


def test_manifiesto_integridad(salida):
    ent = empaquetar_entrega(salida, zip_modo="ninguno")
    with (ent.carpeta / "MANIFIESTO.csv").open(encoding="utf-8-sig") as f:
        filas = list(csv.DictReader(f))
    assert len(filas) == 4 and not ent.zips
    for fila in filas:
        assert sha256(ent.carpeta / fila["ruta"]) == fila["sha256"]
    assert "SIN CARTERA" in (ent.carpeta / "LEEME.txt").read_text(encoding="utf-8")


def test_empaquetar_forzado_y_zip_total(salida):
    from field_ops.cartera.completar import completar_cartera

    completar_cartera(salida)
    ent = empaquetar_entrega(salida, permitir_pendientes=True, zip_modo="total")
    assert ent.pendientes == 3 and ent.zips[0].name == f"{ent.carpeta.name}.zip"
    assert "Aviso" in ent.resumen()


def test_empaquetar_no_pisa_entrega_existente(salida, tmp_path):
    destino = tmp_path / "entrega"
    destino.mkdir()
    (destino / "algo.txt").write_text("x")
    with pytest.raises(FileExistsError):
        empaquetar_entrega(salida, destino=destino)


def test_reporte_excel(salida):
    p = generar_reporte(salida)
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["Resumen", "Por nodo", "Log"]
    assert wb["Resumen"].max_row == 4  # cabecera + 3 ITEM
    assert wb["Por nodo"]["D2"].value == 3  # fotos del primer nodo


def test_subir_sin_rclone(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(FileNotFoundError):
        subir_con_rclone(tmp_path, "drive:x")


def test_cli_de_punta_a_punta(salida, capsys):
    assert cli_main(["reporte", str(salida)]) == 0
    assert cli_main(["cartera", str(salida), "--nodos", str(RAIZ / "config" / "nodos.example.csv")]) == 0
    assert cli_main(["empaquetar", str(salida)]) == 2  # bloqueado por revisión
    assert cli_main(["empaquetar", str(salida), "--forzar", "--zip", "ninguno"]) == 0
    assert "Entrega:" in capsys.readouterr().out
