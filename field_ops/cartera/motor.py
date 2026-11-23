"""Motor de recálculo de columnas de la cartera (portado del proyecto original).

Reproduce las fórmulas de la plantilla Excel: distancia 3D entre elementos (UTM +
altitud), flecha según span, abscisas acumuladas, vano de fibra, cable, etiquetas,
longitud de reserva, cinta acerada/hebillas, cable mensajero, vano flojo y
clasificación red eléctrica / red vial.
"""

from __future__ import annotations

import logging
import pandas as pd

from .esquema import SchemaManager
from .reglas import (
    distance_3d, flecha_from_span, roundup, etiqueta_from_bc, long_reserva,
    cinta_acerada, red_from_wu
)

log = logging.getLogger(__name__)


class CalcEngine:
    @staticmethod
    def recalculate(df: pd.DataFrame, schema: SchemaManager) -> pd.DataFrame:
        df = df.copy()

        # resolver columnas por "starts with" (headers reales tienen saltos de línea)
        col_R = _find(df, schema, "TIPO DE CABLE")
        col_U = _find(df, schema, "TIPO DE ELEMENTO")
        col_W = _find(df, schema, "TIPO DE RED ELECTRICA")
        col_AF = _find(df, schema, "X UTM")
        col_AG = _find(df, schema, "Y UTM")
        col_AJ = _find(df, schema, "ALTITUD")
        col_AS = _find(df, schema, "SPAN CONSTRUIDO")
        col_BA = _find(df, schema, "RESERVA  IN")
        col_BB = _find(df, schema, "RESERVA OUT")
        col_BC = _find(df, schema, "Tipo de Reserva")
        col_BL = _find(df, schema, "TIPO FIJACIÓN")
        col_BQ = _find(df, schema, "BRAZOS EXTENSORES")
        col_AX = _find(df, schema, "Caja Terminal Óptica")
        col_AV = _find(df, schema, "TIPO DE EMPALME")

        # calculadas: buscar headers por prefijo
        c_AK = _find(df, schema, "DISTANCIA ENTRE ELEMENTOS")
        c_AL = _find(df, schema, "FLECHA")
        c_AM = _find(df, schema, "ABSCISA INICIAL")
        c_AN = _find(df, schema, "ABSCISA FINAL")
        c_AO = _find(df, schema, "VANO DE FIBRA OPTICA")
        c_AP = _find(df, schema, "CABLE")
        c_AU = _find(df, schema, "ETIQUETAS")
        c_BD = _find(df, schema, "Longitud Reserva")
        c_BO = _find(df, schema, "CINTA ACERADA")
        c_BP = _find(df, schema, "HEBILLAS")
        c_BV = _find(df, schema, "CABLE MENSAJERO")
        c_BW = _find(df, schema, "VANO FLOJO")
        c_BZ = _find(df, schema, "RED ELECTRICA")

        n = len(df)

        # BD primero (usa BA/BB)
        if c_BD and col_BA and col_BB:
            df[c_BD] = [long_reserva(df.at[i, col_BA], df.at[i, col_BB]) for i in range(n)]

        # AK distancia entre elementos (según fórmula Excel observada)
        if c_AK and col_R and col_U and col_AF and col_AG and col_AJ:
            ak_vals = []
            for i in range(n):
                r = str(df.at[i, col_R]).strip() if col_R else ""
                u = str(df.at[i, col_U]).strip() if col_U else ""
                u_next = str(df.at[i + 1, col_U]).strip() if i + 1 < n and col_U else ""
                if r == "DROP":
                    ak_vals.append("-")
                    continue
                if u in ("PA", "IAO") or u_next == "IAO":
                    ak_vals.append(0)
                    continue

                # si siguiente es PA, distancia a i+2; sino a i+1
                if u_next == "PA" and i + 2 < n:
                    d = distance_3d(
                        df.at[i, col_AF], df.at[i, col_AG], df.at[i, col_AJ],
                        df.at[i + 2, col_AF], df.at[i + 2, col_AG], df.at[i + 2, col_AJ],
                    )
                    ak_vals.append(d if d is not None else "")
                elif i + 1 < n:
                    d = distance_3d(
                        df.at[i, col_AF], df.at[i, col_AG], df.at[i, col_AJ],
                        df.at[i + 1, col_AF], df.at[i + 1, col_AG], df.at[i + 1, col_AJ],
                    )
                    ak_vals.append(d if d is not None else "")
                else:
                    ak_vals.append("")
            df[c_AK] = ak_vals

        # AL flecha
        if c_AL and c_AK and col_AS:
            df[c_AL] = [flecha_from_span(df.at[i, col_AS], df.at[i, c_AK]) for i in range(n)]

        # AM/AN abscisas (patrón observado)
        if c_AM and c_AN and col_R and c_AK and c_AL and col_BA and col_BB:
            am_vals = [None] * n
            an_vals = [None] * n

            # fila 0: usar valores existentes si numéricos, si no calcular
            try:
                am0 = float(df.at[0, c_AM]) if df.at[0, c_AM] not in (None, "", "-") else 0.0
            except Exception:
                am0 = 0.0
            try:
                an0 = float(df.at[0, c_AN]) if df.at[0, c_AN] not in (None, "", "-") else None
            except Exception:
                an0 = None

            # helper BA/BB como float
            def _res(i: int) -> float:
                try:
                    return float(df.at[i, col_BA] or 0) + float(df.at[i, col_BB] or 0)
                except Exception:
                    return 0.0

            def _ak(i: int) -> float:
                v = df.at[i, c_AK]
                try:
                    return float(v) if v not in (None, "", "-") else 0.0
                except Exception:
                    return 0.0

            def _al(i: int) -> float:
                v = df.at[i, c_AL]
                try:
                    return float(v) if v not in (None, "", "-") else 0.0
                except Exception:
                    return 0.0

            am_vals[0] = "-" if str(df.at[0, col_R]).strip() == "DROP" else am0
            if an0 is None:
                if am_vals[0] == "-":
                    an_vals[0] = "-"
                else:
                    an_vals[0] = roundup(float(am0) + _ak(0) + _al(0) + _res(0), 0)
            else:
                an_vals[0] = an0

            for i in range(1, n):
                if str(df.at[i, col_R]).strip() == "DROP":
                    am_vals[i] = "-"
                    an_vals[i] = "-"
                    continue
                am_vals[i] = an_vals[i - 1]
                an_vals[i] = roundup(float(am_vals[i]) + _ak(i) + _al(i) + _res(i), 0)

            df[c_AM] = am_vals
            df[c_AN] = an_vals

        # AO vano FO
        if c_AO and c_AM and c_AN and col_BA and col_BB:
            ao_vals = []
            for i in range(n):
                am = df.at[i, c_AM]
                an = df.at[i, c_AN]
                if am == "-" or am in (None, ""):
                    ao_vals.append("-")
                    continue
                try:
                    res_in = float(df.at[i, col_BA] or 0)
                except Exception:
                    res_in = 0.0
                try:
                    res_out = float(df.at[i, col_BB] or 0)
                except Exception:
                    res_out = 0.0
                try:
                    v = abs(float(am) - float(an)) - (res_in + res_out)
                except Exception:
                    v = ""
                ao_vals.append(v)
            df[c_AO] = ao_vals

        # AP cable = AO + BD
        if c_AP and c_AO and c_BD:
            ap_vals = []
            for i in range(n):
                ao = df.at[i, c_AO]
                if ao == "-" or ao in (None, ""):
                    ap_vals.append("-")
                    continue
                try:
                    ap_vals.append(float(ao) + float(df.at[i, c_BD] or 0))
                except Exception:
                    ap_vals.append("")
            df[c_AP] = ap_vals

        # AU etiquetas
        if c_AU and col_BC:
            df[c_AU] = [etiqueta_from_bc(df.at[i, col_BC]) for i in range(n)]

        # BO cinta acerada, BP hebillas
        if c_BO and c_BP and c_BD and col_BL and col_BQ and col_AX and col_AV:
            bo_vals = []
            for i in range(n):
                bo_vals.append(
                    cinta_acerada(
                        df.at[i, c_BD], df.at[i, col_BL], df.at[i, col_BQ],
                        df.at[i, col_AX], df.at[i, col_AV],
                    )
                )
            df[c_BO] = bo_vals
            df[c_BP] = bo_vals

        # BV cable mensajero
        if c_BV and col_U and col_AF and col_AG and col_AJ:
            bv_vals = []
            for i in range(n):
                u = str(df.at[i, col_U]).strip()
                if u != "PA":
                    bv_vals.append("-")
                    continue
                u_next = str(df.at[i + 1, col_U]).strip() if i + 1 < n else ""
                if u_next == "PA" and i + 2 < n:
                    d = distance_3d(
                        df.at[i, col_AF], df.at[i, col_AG], df.at[i, col_AJ],
                        df.at[i + 2, col_AF], df.at[i + 2, col_AG], df.at[i + 2, col_AJ],
                    )
                    bv_vals.append(d if d is not None else "")
                elif i + 1 < n:
                    d = distance_3d(
                        df.at[i, col_AF], df.at[i, col_AG], df.at[i, col_AJ],
                        df.at[i + 1, col_AF], df.at[i + 1, col_AG], df.at[i + 1, col_AJ],
                    )
                    bv_vals.append(d if d is not None else "")
                else:
                    bv_vals.append("")
            df[c_BV] = bv_vals

        # BW vano flojo: si U="CA" usa AK anterior; si no "-"
        if c_BW and col_U and c_AK:
            bw_vals = []
            for i in range(n):
                u = str(df.at[i, col_U]).strip()
                if u == "CA" and i > 0:
                    bw_vals.append(df.at[i - 1, c_AK])
                else:
                    bw_vals.append("-")
            df[c_BW] = bw_vals

        # BZ red electrica/vial
        if c_BZ and col_W and col_U:
            bz_vals = []
            for i in range(n):
                w_prev = df.at[i - 1, col_W] if i > 0 else None
                bz_vals.append(red_from_wu(df.at[i, col_W], df.at[i, col_U], w_prev))
            df[c_BZ] = bz_vals

        return df


def _find(df: pd.DataFrame, schema: SchemaManager, prefix: str) -> str | None:
    """Columna por nombre exacto y, si no hay, por prefijo (ver ``SchemaManager.resolve_column``)."""
    return schema.resolve_column(df.columns, prefix)


def recalcular_por_nodo(df: pd.DataFrame, schema: SchemaManager, col_nodo: str | None) -> pd.DataFrame:
    """Aplica :meth:`CalcEngine.recalculate` por separado a cada nodo.

    Las distancias y abscisas se encadenan fila a fila; si la cartera mezcla varios
    nodos, encadenar el último poste de un nodo con el primero del siguiente daría
    distancias de kilómetros. Con un solo nodo el resultado es idéntico al original.
    """
    if df.empty:
        return df.copy()
    if not col_nodo or col_nodo not in df.columns:
        return CalcEngine.recalculate(df.reset_index(drop=True), schema)
    df = df.reset_index(drop=True)
    partes = []
    claves = df[col_nodo].map(lambda v: "" if v is None or (isinstance(v, float) and v != v) else str(v).strip())
    for _, idx in df.groupby(claves, sort=False).groups.items():
        sub = CalcEngine.recalculate(df.loc[list(idx)].reset_index(drop=True), schema)
        sub.index = list(idx)
        partes.append(sub)
    return pd.concat(partes).sort_index()
