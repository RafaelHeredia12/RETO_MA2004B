"""
Lectura y limpieza de las fuentes: Kardex, balanza, recetario y tipo de cambio.

Las funciones toleran las variaciones que ya aparecieron en los archivos de FEMSA:
nombres de hoja con espacios ("DETALLE KARDEX ", "FCV "), renglones de subtotales
debajo del detalle, la balanza de julio nombrada "Blalanza" y Kardex sin la hoja TD DETA.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CUENTA_EXISTENCIAS

COLUMNAS_KARDEX = {
    "PERIODO": "PERIODO",
    "CODIGO": "CODIGO",
    "DESCRIPTOR": "DESCRIPTOR",
    "STOCK": "STOCK",
    "COSTO": "COSTO",
    "FULCOM": "FULCOM",
    "UNID CONV": "UNID_CONV",
    "LINEA": "LINEA",
    "NOMBRE LINEA": "NOMBRE_LINEA",
    "POLITICA CJE AL 30SEP": "POLITICA_CANJE",
}

COLUMNAS_BALANZA = ["CUENTA", "DESCRIPCION",
                    "ALTAS_DEBITO", "ALTAS_CREDITO",
                    "BALANCE_DEBITO", "BALANCE_CREDITO",
                    "INV_DEBITO", "INV_CREDITO",
                    "PG_DEBITO", "PG_CREDITO", "MOVIMIENTO_MES"]


# ---------------------------------------------------------------------------
# Ubicar archivos
# ---------------------------------------------------------------------------

def periodo_de_archivo(path: Path | str) -> str | None:
    """Extrae 'AAAAMM' del nombre del archivo (p. ej. INV_Kardex_202601.xlsx -> '202601')."""
    m = re.search(r"(20\d{2}(0[1-9]|1[0-2]))", Path(path).name)
    return m.group(1) if m else None


def _expandir(entradas: list[Path | str]) -> list[Path]:
    archivos = []
    for e in entradas:
        e = Path(e)
        archivos.extend(sorted(e.glob("*.xlsx")) if e.is_dir() else [e])
    return [a for a in archivos if not a.name.startswith("~$")]  # ignora temporales de Excel


def ubicar_archivos(entradas: list[Path | str]) -> dict:
    """
    Recibe carpetas y/o archivos y clasifica los Excel por tipo.

    Devuelve {"meses": {AAAAMM: {"kardex": Path, "balanza": Path}},
              "tipo_cambio": Path | None, "otros": [Path, ...]}.
    """
    meses: dict[str, dict] = {}
    tipo_cambio, otros = None, []
    for a in _expandir(entradas):
        nombre = a.name.lower()
        periodo = periodo_de_archivo(a)
        if "kardex" in nombre and periodo:
            meses.setdefault(periodo, {})["kardex"] = a
        elif re.search(r"b(a|la)lanza", nombre) and periodo:
            meses.setdefault(periodo, {})["balanza"] = a
        elif re.search(r"(^|[_\-\s])tc([_\-\s.]|$)", nombre) or ("tipo" in nombre and "cambio" in nombre):
            tipo_cambio = a
        else:
            otros.append(a)

    incompletos = {m: sorted(d) for m, d in meses.items() if set(d) != {"kardex", "balanza"}}
    if incompletos:
        raise FileNotFoundError(f"Periodos sin Kardex o sin balanza: {incompletos}")
    return {"meses": dict(sorted(meses.items())), "tipo_cambio": tipo_cambio, "otros": otros}


def _hoja(path: Path, nombre: str) -> str | None:
    """Nombre real de una hoja, ignorando mayúsculas y espacios sobrantes."""
    for h in pd.ExcelFile(path).sheet_names:
        if h.strip().upper() == nombre.upper():
            return h
    return None


# ---------------------------------------------------------------------------
# Kardex
# ---------------------------------------------------------------------------

def leer_kardex(path: Path) -> pd.DataFrame:
    """
    Detalle del Kardex con solo las columnas de entrada.

    - Descarta renglones sin CODIGO (subtotales que algunos meses traen al final).
    - Ignora las columnas calculadas del Excel: se recalculan en `reglas`.
    """
    hoja = _hoja(path, "DETALLE KARDEX")
    if hoja is None:
        raise ValueError(f"{Path(path).name} no tiene hoja DETALLE KARDEX")
    df = pd.read_excel(path, sheet_name=hoja)
    faltan = set(COLUMNAS_KARDEX) - set(df.columns)
    if faltan:
        raise ValueError(f"{Path(path).name}: faltan columnas {sorted(faltan)}")

    df = df[df["CODIGO"].notna()][list(COLUMNAS_KARDEX)].rename(columns=COLUMNAS_KARDEX)
    df["PERIODO"] = pd.to_datetime(df["PERIODO"]).dt.normalize()
    df["FULCOM"] = pd.to_datetime(df["FULCOM"], errors="coerce").dt.normalize()
    df["STOCK"] = pd.to_numeric(df["STOCK"], errors="coerce")
    df["COSTO"] = pd.to_numeric(df["COSTO"], errors="coerce")
    df["UNID_CONV"] = pd.to_numeric(df["UNID_CONV"], errors="coerce")  # '#N/A' -> NaN
    df["LINEA"] = df["LINEA"].astype("Int64")
    df["CODIGO"] = df["CODIGO"].astype(str).str.strip()
    return df.reset_index(drop=True)


def leer_valores_excel(path: Path) -> pd.DataFrame:
    """Columnas calculadas tal como Excel las guardó (para validar la réplica)."""
    hoja = _hoja(path, "DETALLE KARDEX")
    df = pd.read_excel(path, sheet_name=hoja)
    df = df[df["CODIGO"].notna()]
    return df.rename(columns={
        "MESES ANTIG.": "MESES_ANTIG", "ALERTA ANTIG.": "ALERTA_ANTIG",
        "DIF. VALORIZACIÓN": "DIF_VALORIZACION", "ALERTA STOCK": "ALERTA_STOCK",
        "ALERTA COSTO": "ALERTA_COSTO", "ALERTA CONVERSIÓN": "ALERTA_CONVERSION",
        "ALERTA DUPLICADO*": "ALERTA_DUPLICADO", "ESTADO GENERAL": "ESTADO_GENERAL",
    })


# ---------------------------------------------------------------------------
# Recetario
# ---------------------------------------------------------------------------

def leer_recetario_td_deta(path: Path) -> dict[str, float]:
    """
    Recetario por periodo desde la tabla TD DETA (columna RECETARIO).

    FEMSA confirmó que no hay integración: el recetario es un valor capturado que
    explica la diferencia entre el Kardex y la balanza.
    """
    hoja = _hoja(path, "TD DETA")
    if hoja is None:
        return {}
    td = pd.read_excel(path, sheet_name=hoja, header=None)
    pos = [(i, j) for i, fila in td.iterrows() for j, v in fila.items() if v == "RECETARIO"]
    if not pos:
        return {}
    fila_enc, col_rec = pos[0]
    col_per = td.iloc[fila_enc].tolist().index("PERIODO")
    valores = {}
    for i in range(fila_enc + 1, len(td)):
        fecha, valor = td.iat[i, col_per], td.iat[i, col_rec]
        if not hasattr(fecha, "year"):
            break  # fin del primer bloque ("Total general"); abajo hay otra tabla (P0) con porcentajes
        if pd.notna(valor):
            valores[pd.Timestamp(fecha).strftime("%Y%m")] = float(valor)
    return valores


def leer_recetarios(archivos: list[Path], csv_manual: Path | None = None) -> dict[str, float]:
    """
    Junta el recetario de todas las TD DETA disponibles.

    El Kardex de julio ya no trae TD DETA, pero los demás archivos sí y la tabla es
    la misma en todos; por eso se busca en cualquiera. Si se da un CSV con columnas
    MES,RECETARIO, sus valores tienen prioridad (para meses futuros).
    """
    recetario: dict[str, float] = {}
    for a in archivos:
        for mes, valor in leer_recetario_td_deta(a).items():
            recetario.setdefault(mes, valor)
    if csv_manual and Path(csv_manual).exists():
        manual = pd.read_csv(csv_manual, dtype={"MES": str})
        recetario.update(dict(zip(manual["MES"], manual["RECETARIO"].astype(float))))
    return recetario


# ---------------------------------------------------------------------------
# Balanza
# ---------------------------------------------------------------------------

def leer_balanza(path: Path) -> pd.DataFrame:
    """Balanza de 8 columnas (hoja FCV), una fila por cuenta."""
    hoja = _hoja(path, "FCV")
    if hoja is None:
        raise ValueError(f"{Path(path).name} no tiene hoja FCV")
    bal = pd.read_excel(path, sheet_name=hoja, header=None, skiprows=7).iloc[:, :11]
    bal.columns = COLUMNAS_BALANZA
    return bal[bal["CUENTA"].astype(str).str.startswith("CTA_")].reset_index(drop=True)


def saldo_cuenta(balanza: pd.DataFrame, cuenta: str = CUENTA_EXISTENCIAS) -> dict:
    """
    Saldo de la cuenta de existencias.

    La propuesta usa la columna 'Movimiento del mes' (K); como viene vacía de febrero
    a junio, se usa Balance Débito − Crédito, que coincide con K donde existe.
    """
    fila = balanza.loc[balanza["CUENTA"] == cuenta]
    if fila.empty:
        raise ValueError(f"La cuenta {cuenta} no está en la balanza")
    fila = fila.iloc[0]
    return {
        "SALDO_GL": float(fila["BALANCE_DEBITO"] - fila["BALANCE_CREDITO"]),
        "GL_SALDO_ACREEDOR": bool(fila["BALANCE_CREDITO"] > fila["BALANCE_DEBITO"]),
    }


# ---------------------------------------------------------------------------
# Tipo de cambio
# ---------------------------------------------------------------------------

def leer_tipo_cambio(path: Path | None) -> dict[str, float]:
    """Pesos mexicanos por peso chileno, por mes (archivo Consulta_TC de Banxico)."""
    if path is None:
        return {}
    hoja = _hoja(path, "Consulta") or pd.ExcelFile(path).sheet_names[-1]
    tc = pd.read_excel(path, sheet_name=hoja, header=None).iloc[:, :2]
    tc.columns = ["FECHA", "TC"]
    es_fecha = tc["FECHA"].map(lambda v: hasattr(v, "year"))
    tc = tc[es_fecha & pd.to_numeric(tc["TC"], errors="coerce").notna()]
    return {pd.Timestamp(f).strftime("%Y%m"): float(v) for f, v in zip(tc["FECHA"], tc["TC"])}
