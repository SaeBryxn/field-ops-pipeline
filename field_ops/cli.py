"""Línea de comandos.

    python main.py                         abre la interfaz (paso 1: ordenar fotos)
    python main.py reporte   SALIDA        paso 2: reporte Excel de lo ordenado
    python main.py cartera   SALIDA [--plantilla X.xlsx]
                                           paso 3: completar la cartera Excel
    python main.py empaquetar SALIDA [--zip por_nodo|total|ninguno] [--forzar] [--subir drive:Carpeta]
                                           paso 4: entrega lista para Drive
    python main.py subir CARPETA drive:Carpeta
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from .config import cargar_dotenv, raiz_proyecto
from .nodos import CatalogoNodos


def _catalogo(path: Optional[Path]) -> CatalogoNodos:
    return CatalogoNodos.desde_csv(path) if path else CatalogoNodos.por_defecto(raiz_proyecto())


def _dir(p: str) -> Path:
    path = Path(p)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"no existe la carpeta: {p}")
    return path


def construir_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="field-ops", description="Fotos de campo -> cartera Excel -> entrega.")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("gui", help="abrir la interfaz para ordenar fotos (por defecto)")

    p = sub.add_parser("reporte", help="reporte Excel de lo ordenado")
    p.add_argument("salida", type=_dir)
    p.add_argument("--nodos", type=Path, help="CSV del catálogo de nodos")

    p = sub.add_parser("cartera", help="completar la cartera Excel desde las fotos")
    p.add_argument("salida", type=_dir)
    p.add_argument("--plantilla", type=Path, help="cartera/plantilla .xlsx existente (opcional)")
    p.add_argument("--nodos", type=Path, help="CSV del catálogo de nodos")

    p = sub.add_parser("empaquetar", help="armar la entrega para Drive")
    p.add_argument("salida", type=_dir)
    p.add_argument("--zip", choices=["por_nodo", "total", "ninguno"], default="por_nodo")
    p.add_argument("--forzar", action="store_true", help="empaquetar aunque haya filas sin revisar")
    p.add_argument("--subir", metavar="REMOTO", default=os.environ.get("FIELD_OPS_RCLONE_DESTINO") or None,
                   help="subir con rclone al terminar, ej. drive:Entregas")

    p = sub.add_parser("subir", help="subir una entrega con rclone")
    p.add_argument("carpeta", type=_dir)
    p.add_argument("remoto")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    cargar_dotenv()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = construir_parser().parse_args(argv)

    if args.cmd in (None, "gui"):
        from .ui import run

        run()
        return 0

    if args.cmd == "reporte":
        from .reporte import generar_reporte

        print(f"Reporte: {generar_reporte(args.salida, catalogo=_catalogo(args.nodos))}")
        return 0

    if args.cmd == "cartera":
        from .cartera.completar import completar_cartera

        res = completar_cartera(args.salida, args.plantilla, catalogo=_catalogo(args.nodos))
        print(res.resumen())
        return 0

    if args.cmd == "empaquetar":
        from .empaquetar import RevisionPendiente, empaquetar_entrega, subir_con_rclone

        try:
            res = empaquetar_entrega(args.salida, permitir_pendientes=args.forzar, zip_modo=args.zip)
        except RevisionPendiente as e:
            print(f"Detenido: {e}\nMarca 'S' en la hoja Revisión o usa --forzar.", file=sys.stderr)
            return 2
        print(res.resumen())
        if args.subir:
            return subir_con_rclone(res.carpeta, args.subir)
        return 0

    if args.cmd == "subir":
        from .empaquetar import subir_con_rclone

        return subir_con_rclone(args.carpeta, args.remoto)
    return 1
