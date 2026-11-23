"""Preferencias del usuario persistidas en JSON (últimas carpetas, % de recorte, etc.)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def ruta_config() -> Path:
    """``~/.field_ops/config.json`` (o ``$FIELD_OPS_CONFIG``)."""
    env = os.environ.get("FIELD_OPS_CONFIG")
    return Path(env) if env else Path.home() / ".field_ops" / "config.json"


def raiz_proyecto() -> Path:
    return Path(__file__).resolve().parents[1]


def cargar_dotenv(path: Path | None = None) -> None:
    """Carga ``.env`` simple (CLAVE=valor) sin pisar variables ya definidas."""
    path = path or raiz_proyecto() / ".env"
    if not path.is_file():
        return
    for linea in path.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Preferencias:
    src_dir: str = ""
    out_dir: str = ""
    modo: str = "move"
    crop_pct: int = 50
    operador: str = ""
    usar_ocr: bool = True
    plantilla_cartera: str = ""

    @classmethod
    def cargar(cls, path: Path | None = None) -> "Preferencias":
        path = path or ruta_config()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        validos = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in validos})

    def guardar(self, path: Path | None = None) -> None:
        path = path or ruta_config()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
