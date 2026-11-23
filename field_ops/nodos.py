"""Catálogo de nodos (código -> localidad) cargado desde un CSV externo.

El catálogo real NO vive en el código ni en el repositorio: se lee de
``config/nodos.csv`` (ignorado por git). Para pruebas existe
``config/nodos.example.csv`` con nodos ficticios.
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

PREFIJO = "AY"
SUFIJO = "A01"

#: Código de nodo escrito de forma flexible: AY-0005-A01, AY0005A01, ay_0005_a01...
#: Sin ``\b`` porque ``_`` cuenta como letra y los nombres de archivo usan ``_`` de separador.
NODE_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{2})[-_ ]?(\d{4})[-_ ]?([A-Z]\d{2})(?![0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class Nodo:
    """Un nodo del catálogo."""

    codigo: str
    localidad: str
    departamento: str = ""
    provincia: str = ""
    distrito: str = ""


@dataclass
class CatalogoNodos:
    """Diccionario código -> :class:`Nodo` con utilidades de búsqueda."""

    nodos: Dict[str, Nodo] = field(default_factory=dict)
    origen: Optional[Path] = None

    def __len__(self) -> int:
        return len(self.nodos)

    def __contains__(self, codigo: str) -> bool:
        return codigo.upper() in self.nodos

    def get(self, codigo: Optional[str]) -> Optional[Nodo]:
        if not codigo:
            return None
        return self.nodos.get(codigo.upper())

    def localidad(self, codigo: Optional[str]) -> Optional[str]:
        n = self.get(codigo)
        return n.localidad if n else None

    @classmethod
    def desde_csv(cls, path: Path) -> "CatalogoNodos":
        """Carga un CSV con columnas ``codigo,localidad[,departamento,provincia,distrito]``.

        Acepta separador coma, punto y coma o tabulación y cabeceras en cualquier
        capitalización.
        """
        texto = path.read_text(encoding="utf-8-sig")
        try:
            dialecto = csv.Sniffer().sniff(texto.splitlines()[0], delimiters=",;\t")
        except (csv.Error, IndexError):
            dialecto = csv.excel
        nodos: Dict[str, Nodo] = {}
        for fila in csv.DictReader(texto.splitlines(), dialect=dialecto):
            f = {(k or "").strip().lower(): (v or "").strip() for k, v in fila.items()}
            codigo = f.get("codigo", "").upper()
            if not codigo:
                continue
            nodos[codigo] = Nodo(
                codigo=codigo,
                localidad=f.get("localidad", ""),
                departamento=f.get("departamento", ""),
                provincia=f.get("provincia", ""),
                distrito=f.get("distrito", ""),
            )
        return cls(nodos=nodos, origen=path)

    @classmethod
    def por_defecto(cls, raiz: Path) -> "CatalogoNodos":
        """Usa ``$FIELD_OPS_NODOS_CSV``, luego ``config/nodos.csv`` y por último el ejemplo."""
        candidatos = []
        env = os.environ.get("FIELD_OPS_NODOS_CSV")
        if env:
            p = Path(env)
            candidatos.append(p if p.is_absolute() else raiz / p)
        candidatos += [raiz / "config" / "nodos.csv", raiz / "config" / "nodos.example.csv"]
        for p in candidatos:
            if p.is_file():
                return cls.desde_csv(p)
        return cls()


def codigo_desde_numero(num: str) -> str:
    """``"5"`` -> ``"AY-0005-A01"``."""
    return f"{PREFIJO}-{num.zfill(4)}-{SUFIJO}"


def normalize_node_input(
    s: str, catalogo: Optional[CatalogoNodos] = None
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Interpreta lo que escribe el operador y devuelve ``(numero, codigo, localidad)``.

    Acepta ``"5"``, ``"0005"``, ``"AY-0005-A01"`` o texto con un número dentro.
    La localidad es ``None`` si el código no está en el catálogo.
    """
    if not s:
        return None, None, None
    t = s.strip().upper()

    m = re.search(rf"\b{PREFIJO}-?(\d{{1,4}})-?{SUFIJO}\b", t)
    if not m:
        m = re.fullmatch(r"(\d{1,4})", t) or re.search(r"(\d{1,4})", t)
    if not m:
        return None, None, None

    num = m.group(1).zfill(4)
    code = codigo_desde_numero(num)
    loc = catalogo.localidad(code) if catalogo else None
    return num, code, loc


def buscar_codigo(texto: str) -> Optional[str]:
    """Busca un código de nodo dentro de un texto libre (nombre de archivo, OCR...)."""
    m = NODE_RE.search((texto or "").upper())
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
