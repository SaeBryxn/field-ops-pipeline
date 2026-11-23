"""Conversión WGS84 lat/lon -> UTM (sin dependencias externas).

Implementa las series de Krüger usadas por el estándar UTM; error < 1 mm dentro
de la zona. Suficiente para la cartera (las coordenadas se redondean a metros).
"""

from __future__ import annotations

import math
from typing import Tuple

_A = 6378137.0
_F = 1 / 298.257223563
_K0 = 0.9996
_E0 = 500000.0
_N0_SUR = 10000000.0


def zona_utm(lon: float) -> int:
    """Zona UTM (1-60) para una longitud."""
    return int((lon + 180) // 6) % 60 + 1


def latlon_a_utm(lat: float, lon: float, zona: int | None = None) -> Tuple[float, float, int, str]:
    """Devuelve ``(este, norte, zona, hemisferio)``. Hemisferio ``"N"`` o ``"S"``."""
    if not -80.0 <= lat <= 84.0:
        raise ValueError(f"Latitud fuera de rango UTM: {lat}")
    zona = zona or zona_utm(lon)
    lon0 = math.radians((zona - 1) * 6 - 180 + 3)

    n = _F / (2 - _F)
    a_rect = _A / (1 + n) * (1 + n**2 / 4 + n**4 / 64)
    alfa = (
        n / 2 - 2 * n**2 / 3 + 5 * n**3 / 16,
        13 * n**2 / 48 - 3 * n**3 / 5,
        61 * n**3 / 240,
    )

    phi = math.radians(lat)
    lam = math.radians(lon) - lon0
    e = math.sqrt(_F * (2 - _F))
    t = math.sinh(math.atanh(math.sin(phi)) - e * math.atanh(e * math.sin(phi)))
    xi_p = math.atan2(t, math.cos(lam))
    eta_p = math.atanh(math.sin(lam) / math.sqrt(1 + t * t))

    xi = xi_p + sum(alfa[j] * math.sin(2 * (j + 1) * xi_p) * math.cosh(2 * (j + 1) * eta_p) for j in range(3))
    eta = eta_p + sum(alfa[j] * math.cos(2 * (j + 1) * xi_p) * math.sinh(2 * (j + 1) * eta_p) for j in range(3))

    este = _E0 + _K0 * a_rect * eta
    norte = _K0 * a_rect * xi
    hemis = "N"
    if lat < 0:
        norte += _N0_SUR
        hemis = "S"
    return este, norte, zona, hemis
