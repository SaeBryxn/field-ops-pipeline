"""Validación de la cartera: decide qué filas necesitan revisión humana."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .esquema import SchemaManager


def vacio(v: Any) -> bool:
    """``None``, ``""``, espacios o NaN."""
    if v is None:
        return True
    if isinstance(v, float) and v != v:
        return True
    return isinstance(v, str) and v.strip() == ""


def _no_numerico(v: Any) -> bool:
    if vacio(v) or str(v).strip() == "-":
        return False
    try:
        float(str(v).replace(",", "."))
        return False
    except ValueError:
        return True


class Validator:
    """Reglas del validador original + campos obligatorios."""

    @staticmethod
    def validate(df: pd.DataFrame, schema: SchemaManager) -> dict[int, dict[str, str]]:
        """Devuelve ``{fila: {columna: mensaje}}`` solo para filas con problemas.

        * UTM, altitud y reservas deben ser numéricas si están presentes.
        * Columnas con lista desplegable deben usar un valor permitido.
        * Columnas obligatorias (``obligatorias`` en el YAML) no pueden quedar vacías.
        """
        errors: dict[int, dict[str, str]] = {}
        numericas = [
            (schema.resolve_column(df.columns, p), p)
            for p in ("X UTM", "Y UTM", "ALTITUD", "RESERVA  IN", "RESERVA OUT")
        ]
        obligatorias = [(schema.resolve_column(df.columns, p), p) for p in schema.obligatorias]
        combos = [c for c in df.columns if schema.is_combo(c)]

        for pos, i in enumerate(df.index):
            row_err: dict[str, str] = {}
            for col, label in numericas:
                if col and _no_numerico(df.at[i, col]):
                    row_err[col] = f"{label.strip()} no numérico: {df.at[i, col]}"
            for col in combos:
                v = df.at[i, col]
                if vacio(v):
                    continue
                allowed = set(schema.combo_values(col))
                if allowed and str(v).strip() not in allowed:
                    row_err[col] = f"valor fuera de lista: {v}"
            for col, label in obligatorias:
                if col and vacio(df.at[i, col]):
                    row_err.setdefault(col, f"falta {label}")
            if row_err:
                errors[pos] = row_err
        return errors
