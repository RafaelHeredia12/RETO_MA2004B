"""
Comprobación de resultados contra los archivos de FEMSA.

Los Kardex traen las columnas de alerta calculadas por Excel. Comparar nuestras
columnas contra esos valores, partida por partida, demuestra que la automatización
reproduce el cálculo del área.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .carga import leer_valores_excel

# columna nuestra -> columna del Excel
COMPARABLES = {
    "VALORIZACION": "VALORIZACION",
    "MESES_ANTIG": "MESES_ANTIG",
    "SEMAFORO_MESES": "ALERTA_ANTIG",
    "DIF_VALORIZACION": "DIF_VALORIZACION",
    "ALERTA_STOCK": "ALERTA_STOCK",
    "ALERTA_COSTO": "ALERTA_COSTO",
    "ALERTA_CONVERSION": "ALERTA_CONVERSION",
    "ALERTA_DUPLICADO": "ALERTA_DUPLICADO",
    "ESTADO_GENERAL": "ESTADO_GENERAL",
}


def _iguales(a: pd.Series, b: pd.Series) -> np.ndarray:
    if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
        return np.isclose(a.astype(float), b.astype(float), atol=0.01, equal_nan=True)
    return (a.astype(str) == b.astype(str)).to_numpy()


def validar_contra_excel(detalle: pd.DataFrame, path_kardex: Path) -> pd.DataFrame:
    """
    % de coincidencia por columna entre el cálculo en Python y lo que guardó Excel.
    Las partidas con #N/A en Excel (sin estado) se reportan aparte, como diferencia esperada.
    """
    excel = leer_valores_excel(path_kardex)
    ours = detalle[["CODIGO", *COMPARABLES]].rename(columns={k: f"{k}__py" for k in COMPARABLES})
    suyas = [c for c in COMPARABLES.values() if c in excel.columns]
    theirs = excel[["CODIGO", *suyas]].rename(columns={c: f"{c}__xl" for c in suyas})
    comp = ours.merge(theirs, on="CODIGO", validate="one_to_one")
    filas = []
    for nuestra, suya in COMPARABLES.items():
        if f"{suya}__xl" not in comp:
            continue
        a, b = comp[f"{nuestra}__py"], comp[f"{suya}__xl"]
        ok = _iguales(a, b)
        error_excel = b.isna() & a.notna()  # celdas que en Excel quedaron en #N/A
        filas.append({
            "MES": detalle["PERIODO"].iloc[0].strftime("%Y%m"),
            "COLUMNA": nuestra,
            "PARTIDAS": len(comp),
            "COINCIDEN": int(ok.sum()),
            "DIFIEREN": int((~ok & ~error_excel).sum()),
            "NA_EN_EXCEL": int((~ok & error_excel).sum()),
        })
    t = pd.DataFrame(filas)
    t["PCT_COINCIDENCIA"] = t["COINCIDEN"] / t["PARTIDAS"]
    return t
