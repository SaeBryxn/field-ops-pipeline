"""Esquema de la cartera: qué columnas son calculadas, numéricas, listas y obligatorias.

Las cabeceras reales del Excel traen saltos de línea y unidades
("ALTITUD (msnm)", "TIPO DE ELEMENTO\\nND: Nodo..."), por eso todo se resuelve
por *prefijo normalizado* (sin tildes, sin mayúsculas, espacios colapsados).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml


def norm(s: Any) -> str:
    """Normaliza una cabecera: minúsculas, sin tildes, sin saltos de línea."""
    s = "" if s is None else str(s)
    s = re.sub(r"\s+", " ", s.replace("\n", " ").replace("\r", " ")).strip().lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


@dataclass
class SchemaManager:
    """Configuración cargada desde ``config/cartera_schema.yml``."""

    path: Optional[Path] = None
    sheet_name: str = "Cartera"
    table_name: str = "Tareas"
    calculated_headers: list[str] = field(default_factory=list)
    numeric_headers: list[str] = field(default_factory=list)
    combos: dict[str, list[str]] = field(default_factory=dict)
    modes: dict[str, list[str]] = field(default_factory=dict)
    columnas_auto: dict[str, str] = field(default_factory=dict)
    obligatorias: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "SchemaManager":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        app = raw.get("app", {})
        return cls(
            path=path,
            sheet_name=app.get("sheet_name", "Cartera"),
            table_name=app.get("table_name", "Tareas"),
            calculated_headers=raw.get("calculated_headers", []),
            numeric_headers=raw.get("numeric_headers", []),
            combos={k: [str(v) for v in vals] for k, vals in raw.get("combos", {}).items()},
            modes=raw.get("modes", {}),
            columnas_auto=raw.get("columnas_auto", {}),
            obligatorias=raw.get("obligatorias", []),
        )

    @classmethod
    def por_defecto(cls) -> "SchemaManager":
        return cls.load(Path(__file__).resolve().parents[2] / "config" / "cartera_schema.yml")

    # --------------------------------------------------------- consultas
    @staticmethod
    def is_header_like(header: str, prefix: str) -> bool:
        return norm(header).startswith(norm(prefix))

    @staticmethod
    def _en(header: str, prefijos: Iterable[str]) -> Optional[str]:
        nh = norm(header)
        for p in prefijos:
            if nh.startswith(norm(p)):
                return p
        return None

    def is_calculated(self, header: str) -> bool:
        return self._en(header, self.calculated_headers) is not None

    def is_numeric(self, header: str) -> bool:
        return self._en(header, self.numeric_headers) is not None

    def is_combo(self, header: str) -> bool:
        return self._en(header, self.combos) is not None

    def combo_values(self, header: str) -> list[str]:
        k = self._en(header, self.combos)
        return self.combos[k] if k else []

    def resolve_column(self, columns: Iterable[str], prefix: str) -> Optional[str]:
        """Columna que corresponde a ``prefix``: primero coincidencia exacta, luego por prefijo.

        Ej.: con columnas ``CABLE MENSAJERO`` y ``CABLE`` el prefijo ``CABLE`` devuelve ``CABLE``
        (el motor original tomaba la primera que empezara igual).
        """
        cols = list(columns)
        np_ = norm(prefix)
        for c in cols:
            if norm(c) == np_:
                return c
        for c in cols:
            if norm(c).startswith(np_):
                return c
        return None

    def columnas_modo(self, modo: str = "Completo") -> list[str]:
        return list(self.modes.get(modo, []))
