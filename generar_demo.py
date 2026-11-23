"""Genera un set de datos 100 % ficticio para probar el flujo y tomar capturas.

Crea en ``demo/``:
    fuente/                  ~40 fotos de "postes" con rótulo en la esquina inferior derecha
                             y GPS en el EXIF (la mitad con el código en el nombre del archivo,
                             la otra mitad solo legible por OCR, y 2 sin GPS para forzar REVISAR)
    salida/                  carpeta vacía donde se ordenan las fotos
    plantilla_cartera.xlsx   cartera Excel con tabla "Tareas" y 2 filas ya llenadas a mano

Uso:
    python generar_demo.py            # crea demo/
    python generar_demo.py --limpiar  # borra demo/ y lo vuelve a crear
"""

from __future__ import annotations

import argparse
import math
import random
import shutil
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo
from PIL import Image, ImageDraw, ImageFont, TiffImagePlugin

RAIZ = Path(__file__).resolve().parent

# Nodos ficticios (los mismos de config/nodos.example.csv) con un punto de partida inventado.
NODOS_DEMO = [
    ("AY-0901-A01", -13.1600, -74.2240, 2750),
    ("AY-0902-A01", -13.4100, -74.0300, 3120),
    ("AY-0903-A01", -13.6500, -73.9800, 2890),
    ("AY-0904-A01", -14.0200, -74.1500, 3360),
    ("AY-0905-A01", -14.3100, -74.4400, 3010),
]
ITEMS_POR_NODO = 4
FOTOS_POR_ITEM = 2

CABECERAS_PLANTILLA = [
    "RED", "REGION", "ID NODO", "NOMBRE DE NODO", "DEPARTAMENTO", "PROVINCIA", "DISTRITO",
    "ITEM", "CÓDIGO DE ESTRUCTURA", "TIPO DE CABLE",
    "TIPO DE ELEMENTO\nND: Nodo Distrital\nPE: Poste existente",
    "TIPO DE RED ELECTRICA\nAT / MT / BT / PN / PP",
    "X UTM", "Y UTM ", "ALTITUD (msnm)", "LATITUD", "LONGITUD",
    "DISTANCIA ENTRE ELEMENTOS (m.)", "FLECHA", "ABSCISA INICIAL", "ABSCISA FINAL",
    "VANO DE FIBRA OPTICA ENTRE ELEMENTOS \n(DIFERENCIA DE ABSCISAS) (m)", "CABLE",
    "SPAN CONSTRUIDO", "ETIQUETAS", "RESERVA  IN (m)", "RESERVA OUT (m)", "Tipo de Reserva",
    "Longitud Reserva\n(m.)", "TIPO FIJACIÓN", "BRAZOS EXTENSORES", "Caja Terminal Óptica",
    "TIPO DE EMPALME", "CINTA ACERADA (CANTIDAD UND)", "HEBILLAS", "CABLE MENSAJERO",
    "VANO FLOJO", "RED ELECTRICA\nRED VIAL", "N° FOTOS", "CARPETA FOTOS", "FECHA FOTO",
]


# ----------------------------------------------------------------- fuentes
def _fuente(tam: int, negrita: bool = True) -> ImageFont.ImageFont:
    nombres = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if negrita else ["arial.ttf", "DejaVuSans.ttf"]
    for n in nombres + ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        try:
            return ImageFont.truetype(n, tam)
        except OSError:
            continue
    return ImageFont.load_default(size=tam)


# -------------------------------------------------------------------- EXIF
def _rac(x: float, den: int = 10000) -> TiffImagePlugin.IFDRational:
    f = Fraction(x).limit_denominator(den)
    return TiffImagePlugin.IFDRational(f.numerator, f.denominator)


def _dms(grados: float) -> tuple:
    g = abs(grados)
    d = int(g)
    m = int((g - d) * 60)
    s = (g - d - m / 60) * 3600
    return (_rac(d, 1), _rac(m, 1), _rac(s, 100000))


def guardar_con_exif(
    im: Image.Image, path: Path, lat: Optional[float], lon: Optional[float],
    alt: Optional[float], fecha: datetime, calidad: int = 85,
) -> Path:
    """Guarda JPG con fecha de toma y (opcional) GPS en el EXIF."""
    exif = Image.Exif()
    exif[0x0110] = "Camara Demo"  # Model
    exif[306] = fecha.strftime("%Y:%m:%d %H:%M:%S")
    exif.get_ifd(0x8769)[36867] = fecha.strftime("%Y:%m:%d %H:%M:%S")
    if lat is not None and lon is not None:
        gps = exif.get_ifd(0x8825)
        gps[1] = "S" if lat < 0 else "N"
        gps[2] = _dms(lat)
        gps[3] = "W" if lon < 0 else "E"
        gps[4] = _dms(lon)
        if alt is not None:
            gps[5] = b"\x00"
            gps[6] = _rac(alt, 100)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "JPEG", quality=calidad, exif=exif)
    return path


# ------------------------------------------------------------------ dibujo
def crear_foto(
    path: Path, codigo: str, item: str, lat: Optional[float], lon: Optional[float],
    alt: Optional[float], fecha: Optional[datetime] = None, semilla: int = 0,
) -> Path:
    """Dibuja una foto de campo ficticia: cielo, cerros, poste y rótulo abajo a la derecha."""
    rnd = random.Random(semilla)
    w, h = 1600, 1200
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)

    for y in range(h * 3 // 5):  # cielo degradado
        t = y / (h * 0.6)
        d.line([(0, y), (w, y)], fill=(int(90 + 80 * t), int(150 + 60 * t), int(220 - 20 * t)))
    for capa, color in enumerate([(96, 110, 92), (70, 92, 64)]):  # cerros
        base = int(h * (0.45 + 0.08 * capa))
        pts = [(0, h)] + [
            (x, base - int(90 * math.sin(x / (230 + 60 * capa) + rnd.random() * 3) + rnd.randint(0, 25)))
            for x in range(0, w + 80, 80)
        ] + [(w, h)]
        d.polygon(pts, fill=color)
    d.rectangle([0, int(h * 0.72), w, h], fill=(122, 104, 80))  # suelo

    px = rnd.randint(int(w * 0.25), int(w * 0.5))  # poste
    d.rectangle([px - 18, int(h * 0.12), px + 18, int(h * 0.86)], fill=(165, 165, 160))
    d.rectangle([px - 90, int(h * 0.18), px + 90, int(h * 0.2)], fill=(120, 120, 115))
    for k in range(3):  # cables
        y0 = int(h * 0.19) + k * 14
        d.line([(0, y0 + 60), (px, y0), (w, y0 + 40)], fill=(30, 30, 30), width=4)
    d.ellipse([px - 40, int(h * 0.3), px + 40, int(h * 0.3) + 80], outline=(20, 20, 20), width=6)  # reserva

    fecha = fecha or datetime(2025, 6, 2, 9, 0)
    d.text((24, 20), fecha.strftime("%d/%m/%Y %H:%M"), font=_fuente(34, False), fill=(255, 210, 0))

    # rótulo blanco en la esquina inferior derecha (lo que el OCR debe leer)
    f_big = _fuente(54)
    lineas = [f"NODO {codigo}", f"ITEM {item}"]
    rw = int(max(d.textlength(t, font=f_big) for t in lineas)) + 60
    rh = 210
    x0, y0 = w - rw - 40, h - rh - 40
    d.rectangle([x0, y0, x0 + rw, y0 + rh], fill=(250, 250, 245), outline=(10, 10, 10), width=6)
    for i, txt in enumerate(lineas):
        d.text((x0 + 30, y0 + 22 + i * 90), txt, font=f_big, fill=(10, 10, 10))

    return guardar_con_exif(im, path, lat, lon, alt, fecha)


# ------------------------------------------------------------------- demo
def _desplazar(lat: float, lon: float, metros: float, rumbo_grados: float) -> tuple[float, float]:
    r = 6378137.0
    dlat = metros * math.cos(math.radians(rumbo_grados)) / r
    dlon = metros * math.sin(math.radians(rumbo_grados)) / (r * math.cos(math.radians(lat)))
    return lat + math.degrees(dlat), lon + math.degrees(dlon)


def _localidades() -> dict[str, str]:
    from field_ops.nodos import CatalogoNodos

    cat = CatalogoNodos.desde_csv(RAIZ / "config" / "nodos.example.csv")
    return {c: n.localidad for c, n in cat.nodos.items()}


def generar_fotos(destino: Path, ya_ordenado: bool = False) -> list[Path]:
    """Crea las fotos en ``destino``. Con ``ya_ordenado`` las deja en ``NODO/ITEM-x`` (como tras el paso 1)."""
    from field_ops.rutas import build_dest_folder

    locs = _localidades() if ya_ordenado else {}
    rnd = random.Random(42)
    fotos: list[Path] = []
    contador = 1
    fecha = datetime(2025, 6, 2, 8, 30)
    for n_nodo, (codigo, lat, lon, alt) in enumerate(NODOS_DEMO):
        rumbo = rnd.uniform(0, 360)
        for item in range(1, ITEMS_POR_NODO + 1):
            if item > 1:
                lat, lon = _desplazar(lat, lon, rnd.uniform(60, 140), rumbo + rnd.uniform(-25, 25))
                alt += rnd.uniform(-12, 12)
            for k in range(FOTOS_POR_ITEM):
                fecha += timedelta(minutes=rnd.randint(1, 6))
                # nodos pares: código en el nombre; impares: nombre de cámara (solo OCR)
                if n_nodo % 2 == 0:
                    nombre = f"{codigo}_ITEM-{item}_{k + 1:03d}.jpg"
                else:
                    nombre = f"IMG_{contador:04d}.jpg"
                sin_gps = codigo == "AY-0904-A01" and item == 3  # fuerza una fila "REVISAR"
                jlat = None if sin_gps else lat + rnd.uniform(-2e-5, 2e-5)
                jlon = None if sin_gps else lon + rnd.uniform(-2e-5, 2e-5)
                carpeta = build_dest_folder(destino, codigo, locs[codigo], str(item)) if ya_ordenado else destino
                fotos.append(crear_foto(
                    carpeta / nombre, codigo, str(item), jlat, jlon, round(alt, 1),
                    fecha=fecha, semilla=contador,
                ))
                contador += 1
    return fotos


def _filas_diseno(utm_desfasado: Optional[tuple[float, float]] = None) -> list[dict]:
    """Filas "de diseño" que ya existían antes de ir a campo (sin coordenadas).

    Nodos 0901-0903 vienen del diseño; 0904 y 0905 no, así que la automatización
    crea esas filas y las manda a revisión. Una fila trae un UTM mal digitado para
    mostrar la alerta de discrepancia con el GPS de las fotos.
    """
    tipos = ["PE", "PE", "CA", "PE"]
    redes = ["BT", "MT", "-", "BT"]
    reservas = [(0, 0, "-"), (15, 15, "RE"), (0, 0, "-"), (10, 10, "RT")]
    filas = []
    for n, codigo in enumerate(["AY-0901-A01", "AY-0902-A01", "AY-0903-A01"]):
        for k in range(ITEMS_POR_NODO):
            rin, rout, tipo_res = reservas[k]
            fila = {
                "ID NODO": codigo, "ITEM": str(k + 1), "CÓDIGO DE ESTRUCTURA": f"E-{n + 1}{k + 1:02d}",
                "TIPO DE CABLE": "ADSS", "TIPO DE ELEMENTO": tipos[k], "TIPO DE RED ELECTRICA": redes[k],
                "SPAN CONSTRUIDO": 100, "RESERVA  IN (m)": rin, "RESERVA OUT (m)": rout,
                "Tipo de Reserva": tipo_res, "TIPO FIJACIÓN": "CB" if k == 1 else "AB",
                "BRAZOS EXTENSORES": 1 if k == 1 else 0, "Caja Terminal Óptica": 0, "TIPO DE EMPALME": "-",
            }
            if utm_desfasado and codigo == "AY-0903-A01" and k == 1:
                fila["X UTM"], fila["Y UTM "] = utm_desfasado
            filas.append(fila)
    return filas


def crear_plantilla_cartera(path: Path, utm_desfasado: Optional[tuple[float, float]] = None) -> Path:
    """Cartera Excel de ejemplo: hoja "Cartera", tabla "Tareas", listas desplegables y filas de diseño."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Cartera"
    ws.append(CABECERAS_PLANTILLA)
    col = {h.split("\n")[0].strip(): i + 1 for i, h in enumerate(CABECERAS_PLANTILLA)}
    col["Y UTM "] = col["Y UTM"]

    filas_manuales = _filas_diseno(utm_desfasado)
    for r, datos in enumerate(filas_manuales, start=2):
        for k, v in datos.items():
            ws.cell(row=r, column=col[k], value=v)
        # columna calculada con fórmula real de Excel (debe conservarse y copiarse hacia abajo)
        a = get_column_letter(col["RESERVA  IN (m)"])
        b = get_column_letter(col["RESERVA OUT (m)"])
        ws.cell(row=r, column=col["Longitud Reserva"], value=f'=IF({a}{r}="-",0,ABS({a}{r}+{b}{r}))')

    ultima = get_column_letter(len(CABECERAS_PLANTILLA))
    t = Table(displayName="Tareas", ref=f"A1:{ultima}{1 + len(filas_manuales)}")
    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(t)

    listas = {
        "TIPO DE ELEMENTO": "ND,EC,PE,PN,PA,CA,IAO,HS,-",
        "TIPO DE RED ELECTRICA": "AT,MT,BT,PN,PP,-",
        "Tipo de Reserva": "RE,RD,RM,RT,RP,-",
    }
    for cab, valores in listas.items():
        dv = DataValidation(type="list", formula1=f'"{valores}"', allow_blank=True)
        letra = get_column_letter(col[cab])
        dv.add(f"{letra}2:{letra}{1 + len(filas_manuales)}")
        ws.add_data_validation(dv)

    for c in range(1, len(CABECERAS_PLANTILLA) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        ws.column_dimensions[get_column_letter(c)].width = 16
    ws.row_dimensions[1].height = 60
    ws.freeze_panes = "A2"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--destino", type=Path, default=RAIZ / "demo")
    ap.add_argument("--limpiar", action="store_true", help="borra la carpeta demo antes de generar")
    ap.add_argument("--ya-ordenado", action="store_true",
                    help="deja las fotos ya ordenadas en salida/ (para probar directo los pasos 3 y 4)")
    args = ap.parse_args()

    if args.limpiar and args.destino.exists():
        shutil.rmtree(args.destino)
    if args.ya_ordenado:
        fotos = generar_fotos(args.destino / "salida", ya_ordenado=True)
    else:
        fotos = generar_fotos(args.destino / "fuente")
        (args.destino / "salida").mkdir(parents=True, exist_ok=True)
    # UTM "mal digitado": 180 m al este del GPS real de AY-0903-A01 ITEM 2
    from field_ops.imagen import leer_datos_foto
    from field_ops.utm import latlon_a_utm

    ref = next(args.destino.rglob("AY-0903-A01_ITEM-2_001.jpg"))
    d = leer_datos_foto(ref)
    e, n, _, _ = latlon_a_utm(d.lat, d.lon)
    plantilla = crear_plantilla_cartera(args.destino / "plantilla_cartera.xlsx", (round(e + 180, 2), round(n, 2)))
    print(f"OK: {len(fotos)} fotos en {fotos[0].parent if not args.ya_ordenado else args.destino / 'salida'}")
    print(f"OK: plantilla {plantilla}")
    print(f"Siguiente: python main.py   (fuente={args.destino / 'fuente'}, salida={args.destino / 'salida'})")


if __name__ == "__main__":
    main()
