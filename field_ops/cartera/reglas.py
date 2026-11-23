"""Reglas de cálculo de la cartera (traducción 1:1 de las fórmulas Excel originales)."""

from __future__ import annotations

import math
from typing import Any


def _num(x: Any) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return None if isinstance(x, float) and math.isnan(x) else float(x)
    s = str(x).strip()
    if s == "" or s == "-":
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def distance_3d(x1, y1, z1, x2, y2, z2) -> float | None:
    a = _num(x1); b = _num(y1); c = _num(z1)
    d = _num(x2); e = _num(y2); f = _num(z2)
    if None in (a, b, c, d, e, f):
        return None
    return math.sqrt((d - a) ** 2 + (e - b) ** 2 + (f - c) ** 2)


def roundup(x: float, digits: int = 0) -> float:
    # tolerante a None / NaN / inf / strings vacíos
    if x is None:
        return 0.0
    try:
        xf = float(str(x).strip().replace(",", "."))
    except Exception:
        return 0.0

    if math.isnan(xf) or math.isinf(xf):
        return 0.0

    factor = 10 ** digits
    return math.ceil(xf * factor) / factor

def flecha_from_span(span: Any, ak: Any) -> Any:
    # según fórmula Excel observada: 100->1%, 200->1.15%, 300->1.25%, 600->2%, 1000->3%
    if span is None:
        return "-"

    s = str(span).strip()
    if s in ("-", ""):
        return "-"

    try:
        v = float(s.replace(",", "."))
    except Exception:
        return "-"

    if ak is None:
        return "-"

    ak_s = str(ak).strip()
    if ak_s in ("", "-"):
        return "-"

    try:
        akv = float(ak_s.replace(",", "."))
    except Exception:
        return "-"

    if v == 100:
        return akv * 0.01
    if v == 200:
        return akv * 0.0115
    if v == 300:
        return akv * 0.0125
    if v == 600:
        return akv * 0.02
    if v == 1000:
        return akv * 0.03
    return ""


def etiqueta_from_bc(bc: Any) -> str:
    s = "" if bc is None else str(bc).strip()
    if s in ("RT", "RM"):
        return "2"
    if s == "RE":
        return "3"
    return "1"


def long_reserva(ba: Any, bb: Any) -> float:
    # Excel: IF(BA="-","0",ABS(BB+BA))
    if ba is None:
        ba_val = 0.0
    else:
        if str(ba).strip() == "-":
            return 0.0
        ba_val = _num(ba) or 0.0
    bb_val = _num(bb) or 0.0
    return abs(ba_val + bb_val)


def cinta_acerada(bd: Any, bl: Any, bq: Any, ax: Any, av: Any) -> int:
    # Excel: 2*(OR(BD>0))+2*(BL="CB")+2*(BQ=1)+2*(AX=1)+2*(OR(AV="S",AV="D"))
    total = 0
    bdv = _num(bd) or 0.0
    if bdv > 0:
        total += 2
    if str(bl).strip() == "CB":
        total += 2
    if (_num(bq) or 0.0) == 1:
        total += 2
    if (_num(ax) or 0.0) == 1:
        total += 2
    if str(av).strip() in ("S", "D"):
        total += 2
    return int(total)


def red_from_wu(w: Any, u: Any, w_prev: Any) -> str:
    w_s = "" if w is None else str(w).strip()
    u_s = "" if u is None else str(u).strip()
    w_prev_s = "" if w_prev is None else str(w_prev).strip()

    if w_s in ("AT", "MT", "BT"):
        return "RED ELECTRICA"
    if w_s == "-" and u_s == "ND":
        return "RED VIAL"
    if w_s in ("PN", "PP"):
        return "RED VIAL"
    if w_s == "-" and u_s == "IAO":
        return "RED VIAL"
    if w_s == "-" and u_s == "CA" and w_prev_s in ("PN", "PP"):
        return "RED VIAL"
    return "RED ELECTRICA"
