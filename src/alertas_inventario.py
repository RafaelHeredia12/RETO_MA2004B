"""
Alertas de inventario — FEMSA Salud Chile (FCV)

Traducción a Python de las fórmulas que usa el área de Auditoría Interna en el
archivo "Propuesta de alertas inventarios" (hojas DETALLE KARDEX y Dashboard).
Cada función indica, en su docstring, la fórmula de Excel que reemplaza.

Referencias de columnas en Excel (hoja DETALLE KARDEX):
    A PERIODO   B CODIGO   C DESCRIPTOR   D STOCK   E COSTO   F VALORIZACION
    G FULCOM    H UNID CONV   I MESES ANTIG.   J ALERTA ANTIG.
    K DIF. VALORIZACIÓN   L ALERTA STOCK   M ALERTA COSTO   N ALERTA CONVERSIÓN
    O ALERTA DUPLICADO*   P ESTADO GENERAL   Q LINEA   R NOMBRE LINEA
    S POLITICA CJE AL 30SEP
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

CUENTA_EXISTENCIAS = "CTA_000184"  # 111080001 en el planteamiento (anonimizada)
TOLERANCIA_CONCILIACION = 0.001    # 0.1% del saldo GL, como en el dashboard
UMBRAL_VARIACION = 0.05            # regla de negocio: variación mensual >= 5%

# Umbrales del semáforo que usa la propuesta (en meses).
# Se dejan como parámetro porque la política aún no está confirmada.
LIMITE_AMBAR = 6
LIMITE_ROJO = 12

COLUMNAS_BASE = {
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


# ---------------------------------------------------------------------------
# Lectura de fuentes
# ---------------------------------------------------------------------------

def periodo_de_archivo(path: Path) -> str | None:
    """Extrae 'AAAAMM' del nombre del archivo."""
    m = re.search(r"(20\d{2}(0[1-9]|1[0-2]))", Path(path).name)
    return m.group(1) if m else None


def leer_kardex(path: Path) -> pd.DataFrame:
    """
    Lee la hoja DETALLE KARDEX y conserva solo las columnas de entrada.

    Las columnas calculadas del Excel (MESES ANTIG., alertas, etc.) se ignoran
    porque se recalculan aquí. Se descartan las filas sin CODIGO: en julio el
    archivo trae debajo del detalle cuatro renglones de subtotales.
    """
    df = pd.read_excel(path, sheet_name="DETALLE KARDEX")
    df = df[df["CODIGO"].notna()]
    df = df[list(COLUMNAS_BASE)].rename(columns=COLUMNAS_BASE).reset_index(drop=True)
    df["PERIODO"] = pd.to_datetime(df["PERIODO"])
    df["FULCOM"] = pd.to_datetime(df["FULCOM"], errors="coerce")
    df["LINEA"] = df["LINEA"].astype("Int64")
    return df


def leer_recetario(path_kardex: Path, periodo: str) -> float:
    """
    Valor del recetario para el periodo, tomado de la tabla dinámica TD DETA.

    En el dashboard: 'TD DETA'!$F$11 (columna RECETARIO del mes). El recetario
    forma parte del inventario contable pero no viene en el detalle por SKU.
    """
    td = pd.read_excel(path_kardex, sheet_name="TD DETA", header=None)
    fila_encabezado, col_receta = next(
        (i, j) for i, fila in td.iterrows() for j, v in fila.items() if v == "RECETARIO"
    )
    col_periodo = td.iloc[fila_encabezado].tolist().index("PERIODO")
    fecha = pd.Timestamp(periodo + "01")
    for i in range(fila_encabezado + 1, len(td)):
        valor = td.iat[i, col_periodo]
        if isinstance(valor, (pd.Timestamp, np.datetime64)) or hasattr(valor, "year"):
            if pd.Timestamp(valor) == fecha:
                return float(td.iat[i, col_receta])
    raise ValueError(f"No se encontró el recetario de {periodo} en {Path(path_kardex).name}")


def leer_balanza(path: Path) -> pd.DataFrame:
    """Lee la hoja FCV de la balanza de comprobación (8 columnas + movimiento)."""
    hoja = next(h for h in pd.ExcelFile(path).sheet_names if h.strip().upper() == "FCV")
    bal = pd.read_excel(path, sheet_name=hoja, header=None, skiprows=7).iloc[:, :11]
    bal.columns = ["CUENTA", "DESCRIPCION",
                   "ALTAS_DEBITO", "ALTAS_CREDITO",
                   "BALANCE_DEBITO", "BALANCE_CREDITO",
                   "INV_DEBITO", "INV_CREDITO",
                   "PG_DEBITO", "PG_CREDITO", "MOVIMIENTO_MES"]
    return bal[bal["CUENTA"].astype(str).str.startswith("CTA_")].reset_index(drop=True)


def saldo_gl(balanza: pd.DataFrame, cuenta: str = CUENTA_EXISTENCIAS) -> float:
    """
    Saldo de la cuenta de existencias.

    Excel: =XLOOKUP("CTA_000184", balanza!A:A, balanza!K:K, 0)

    La propuesta toma la columna K ('Movimiento del mes'), pero en las balanzas
    de febrero a junio esa columna viene vacía. Se usa Balance Débito − Crédito,
    que coincide con K en los meses donde K sí está (enero y julio).
    """
    fila = balanza.loc[balanza["CUENTA"] == cuenta]
    if fila.empty:
        return 0.0
    fila = fila.iloc[0]
    return float(fila["BALANCE_DEBITO"] - fila["BALANCE_CREDITO"])


# ---------------------------------------------------------------------------
# Columnas por partida (hoja DETALLE KARDEX)
# ---------------------------------------------------------------------------

def valorizacion(stock: pd.Series, costo: pd.Series) -> pd.Series:
    """Excel F: =+E2*D2"""
    return costo * stock


def meses_antiguedad(periodo: pd.Series, fulcom: pd.Series) -> pd.Series:
    """
    Excel I:
    =IF(G2="","",MAX(0,(YEAR(EOMONTH(A2,0))-YEAR(G2))*12+MONTH(EOMONTH(A2,0))-MONTH(G2)))

    Diferencia en meses de calendario entre el cierre del periodo y la FULCOM.
    Si la FULCOM es posterior al cierre, el resultado se trunca a 0.
    """
    cierre = periodo + pd.offsets.MonthEnd(0)
    meses = (cierre.dt.year - fulcom.dt.year) * 12 + (cierre.dt.month - fulcom.dt.month)
    return meses.clip(lower=0).astype("Int64")  # FULCOM vacía queda como <NA>


def alerta_antiguedad(meses: pd.Series,
                      limite_ambar: int = LIMITE_AMBAR,
                      limite_rojo: int = LIMITE_ROJO) -> pd.Series:
    """
    Excel J:
    =IF(G2="","SIN FECHA",IF(I2>12,"ROJO",IF(I2>6,"ÁMBAR","VERDE")))
    """
    m = meses.astype("float")
    return pd.Series(
        np.select([m.isna(), m > limite_rojo, m > limite_ambar],
                  ["SIN FECHA", "ROJO", "ÁMBAR"], default="VERDE"),
        index=meses.index,
    )


def dif_valorizacion(valor: pd.Series, stock: pd.Series, costo: pd.Series) -> pd.Series:
    """
    Excel K: =F2-(D2*E2)

    Como F también es STOCK*COSTO, por construcción siempre da 0. Se mantiene
    para replicar el archivo; tendría sentido con un valor independiente del ERP.
    """
    return valor - stock * costo


def alerta_stock(stock: pd.Series) -> pd.Series:
    """Excel L: =IF(D2<0,"NEGATIVO",IF(D2=0,"CERO","OK"))"""
    return pd.Series(np.select([stock < 0, stock == 0], ["NEGATIVO", "CERO"], default="OK"),
                     index=stock.index)


def alerta_costo(costo: pd.Series) -> pd.Series:
    """Excel M: =IF(E2<=0,"INVÁLIDO","OK")"""
    return pd.Series(np.where(costo <= 0, "INVÁLIDO", "OK"), index=costo.index)


def alerta_conversion(unid_conv: pd.Series) -> pd.Series:
    """
    Excel N: =IF(OR(H2="",H2<=0),"INVÁLIDA",IF(H2<>1,"REVISAR","OK"))

    Diferencia con Excel: cuando H trae #N/A, Excel propaga el error y la fila
    queda sin estado. Aquí se clasifica como INVÁLIDA para que no se pierda.
    """
    invalida = unid_conv.isna() | (unid_conv <= 0)
    return pd.Series(np.select([invalida, unid_conv != 1], ["INVÁLIDA", "REVISAR"], default="OK"),
                     index=unid_conv.index)


def alerta_duplicado(codigo: pd.Series) -> pd.Series:
    """
    Excel O: valor fijo "OK" en el archivo.

    Se implementa la regla que la propia propuesta recomienda: COUNTIF(CODIGO)>1.
    """
    return pd.Series(np.where(codigo.duplicated(keep=False), "DUPLICADO", "OK"), index=codigo.index)


def estado_general(df: pd.DataFrame) -> pd.Series:
    """
    Excel P:
    =IF(OR(J2="ROJO",L2<>"OK",M2<>"OK",ABS(K2)>1,N2<>"OK",O2<>"OK"),"REVISAR",
        IF(J2="ÁMBAR","MONITOREAR","OK"))
    """
    revisar = (
        (df["ALERTA_ANTIG"] == "ROJO")
        | (df["ALERTA_STOCK"] != "OK")
        | (df["ALERTA_COSTO"] != "OK")
        | (df["DIF_VALORIZACION"].abs() > 1)
        | (df["ALERTA_CONVERSION"] != "OK")
        | (df["ALERTA_DUPLICADO"] != "OK")
    )
    monitorear = df["ALERTA_ANTIG"] == "ÁMBAR"
    return pd.Series(np.select([revisar, monitorear], ["REVISAR", "MONITOREAR"], default="OK"),
                     index=df.index)


def construir_columnas(kardex: pd.DataFrame) -> pd.DataFrame:
    """Agrega al Kardex de un mes todas las columnas calculadas de la propuesta."""
    df = kardex.copy()
    df["VALORIZACION"] = valorizacion(df["STOCK"], df["COSTO"])
    df["MESES_ANTIG"] = meses_antiguedad(df["PERIODO"], df["FULCOM"])
    df["ALERTA_ANTIG"] = alerta_antiguedad(df["MESES_ANTIG"])
    df["DIF_VALORIZACION"] = dif_valorizacion(df["VALORIZACION"], df["STOCK"], df["COSTO"])
    df["ALERTA_STOCK"] = alerta_stock(df["STOCK"])
    df["ALERTA_COSTO"] = alerta_costo(df["COSTO"])
    df["ALERTA_CONVERSION"] = alerta_conversion(df["UNID_CONV"])
    df["ALERTA_DUPLICADO"] = alerta_duplicado(df["CODIGO"])
    df["ESTADO_GENERAL"] = estado_general(df)
    # Indicador adicional (no está en el Excel): FULCOM posterior al cierre del mes,
    # que la fórmula de antigüedad convierte en 0 meses.
    df["FULCOM_FUTURA"] = df["FULCOM"].dt.normalize() > df["PERIODO"] + pd.offsets.MonthEnd(0)
    return df


# ---------------------------------------------------------------------------
# Indicadores del dashboard
# ---------------------------------------------------------------------------

def conciliacion(detalle: pd.DataFrame, gl: float, recetario: float,
                 tolerancia: float = TOLERANCIA_CONCILIACION) -> dict:
    """
    Alerta 1 — Conciliación Kardex vs GL.

    Excel (Dashboard):
        D5 = total detalle KARDEX + 'TD DETA'!F (recetario)
        G5 = D5 - A5
        J5 = IF(ABS(G5)<=ABS(A5)*0.001,"CONCILIADO","DIFERENCIA")
    """
    total_kardex = float(detalle["VALORIZACION"].sum())
    conciliable = total_kardex + recetario
    diferencia = conciliable - gl
    return {
        "SALDO_GL": gl,
        "TOTAL_KARDEX": total_kardex,
        "RECETARIO": recetario,
        "INVENTARIO_CONCILIABLE": conciliable,
        "DIFERENCIA": diferencia,
        "DIFERENCIA_PCT": diferencia / gl if gl else np.nan,
        "ESTADO_CONCILIACION": "CONCILIADO" if abs(diferencia) <= abs(gl) * tolerancia else "DIFERENCIA",
        "SKUS": int(detalle["CODIGO"].nunique()),
    }


def resumen_antiguedad(detalle: pd.DataFrame, inventario_conciliable: float) -> pd.DataFrame:
    """
    Tabla 'ANTIGÜEDAD DEL INVENTARIO' del dashboard.
    Excel: COUNTIF(J,"ROJO"), SUMIF(J,"ROJO",F) y SUMIF/D5 para cada color.
    """
    orden = ["ROJO", "ÁMBAR", "VERDE", "SIN FECHA"]
    t = (detalle.groupby("ALERTA_ANTIG")["VALORIZACION"]
         .agg(PARTIDAS="count", VALORIZACION="sum")
         .reindex(orden, fill_value=0))
    t["PCT"] = t["VALORIZACION"] / inventario_conciliable
    return t


def resumen_otras_alertas(detalle: pd.DataFrame) -> pd.DataFrame:
    """Tabla 'OTRAS ALERTAS DE INVENTARIO' del dashboard (COUNTIF / SUMIF)."""
    reglas = {
        "Stock negativo": detalle["ALERTA_STOCK"] == "NEGATIVO",
        "Stock cero": detalle["ALERTA_STOCK"] == "CERO",
        "Costo inválido": detalle["ALERTA_COSTO"] == "INVÁLIDO",
        "Valorización no cuadra (> CLP 1)": detalle["DIF_VALORIZACION"].abs() > 1,
        "Conversión distinta de 1 / inválida": detalle["ALERTA_CONVERSION"] != "OK",
        "Código duplicado": detalle["ALERTA_DUPLICADO"] != "OK",
        "Total para revisar": detalle["ESTADO_GENERAL"] == "REVISAR",
    }
    return pd.DataFrame({
        "PARTIDAS": {k: int(v.sum()) for k, v in reglas.items()},
        "VALORIZACION": {k: float(detalle.loc[v, "VALORIZACION"].sum()) for k, v in reglas.items()},
    })


def top_rojas(detalle: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Top N partidas en ROJO por valorización (Excel: LARGE + XLOOKUP)."""
    return (detalle.loc[detalle["ALERTA_ANTIG"] == "ROJO",
                        ["CODIGO", "DESCRIPTOR", "MESES_ANTIG", "VALORIZACION"]]
            .nlargest(n, "VALORIZACION")
            .reset_index(drop=True))


def detalle_alertas(detalle: pd.DataFrame) -> pd.DataFrame:
    """Hoja 'Alertas Inventario': partidas con estado REVISAR o MONITOREAR."""
    cols = ["CODIGO", "DESCRIPTOR", "STOCK", "COSTO", "VALORIZACION",
            "MESES_ANTIG", "ALERTA_ANTIG", "ESTADO_GENERAL"]
    return detalle.loc[detalle["ESTADO_GENERAL"].isin(["REVISAR", "MONITOREAR"]), cols]


def variacion_mensual(resumen: pd.DataFrame, columna: str = "SALDO_GL",
                      umbral: float = UMBRAL_VARIACION) -> pd.DataFrame:
    """
    Alerta 2 — variación del saldo respecto al cierre del mes anterior.
    Se activa cuando |variación| >= 5%.
    """
    r = resumen.sort_values("PERIODO").copy()
    r["VARIACION_PCT"] = r[columna].pct_change()
    r["ALERTA_VARIACION"] = np.where(r["VARIACION_PCT"].abs() >= umbral, "ALERTA", "OK")
    r.loc[r["VARIACION_PCT"].isna(), "ALERTA_VARIACION"] = "SIN MES PREVIO"
    return r


def naturaleza_contraria(detalle: pd.DataFrame, balanza: pd.DataFrame,
                         cuenta: str = CUENTA_EXISTENCIAS) -> dict:
    """
    Saldos de naturaleza contraria: partidas con stock o valorización negativa
    y saldo acreedor en la cuenta de existencias (que por naturaleza es deudora).
    """
    fila = balanza.loc[balanza["CUENTA"] == cuenta].iloc[0]
    return {
        "PARTIDAS_VALOR_NEGATIVO": int((detalle["VALORIZACION"] < 0).sum()),
        "GL_SALDO_ACREEDOR": bool(fila["BALANCE_CREDITO"] > fila["BALANCE_DEBITO"]),
    }


def procesar_mes(path_kardex: Path, path_balanza: Path) -> tuple[pd.DataFrame, dict]:
    """
    Cruce completo de un mes: Kardex + Balanza + recetario.

    Devuelve el detalle por SKU con todas las columnas calculadas y un
    diccionario con los indicadores del mes (una fila del resumen mensual).
    """
    periodo = periodo_de_archivo(path_kardex)
    detalle = construir_columnas(leer_kardex(path_kardex))
    balanza = leer_balanza(path_balanza)
    gl = saldo_gl(balanza)
    recetario = leer_recetario(path_kardex, periodo)

    resumen = {"PERIODO": pd.Timestamp(periodo + "01")}
    resumen.update(conciliacion(detalle, gl, recetario))

    antig = resumen_antiguedad(detalle, resumen["INVENTARIO_CONCILIABLE"])
    for color in antig.index:
        clave = color.replace("Á", "A").replace(" ", "_")
        resumen[f"PARTIDAS_{clave}"] = int(antig.loc[color, "PARTIDAS"])
        resumen[f"VALOR_{clave}"] = float(antig.loc[color, "VALORIZACION"])

    resumen["PARTIDAS_MAS_1_ANIO"] = int((detalle["MESES_ANTIG"] > 12).sum())
    resumen["VALOR_MAS_1_ANIO"] = float(detalle.loc[detalle["MESES_ANTIG"] > 12, "VALORIZACION"].sum())
    resumen["PARTIDAS_REVISAR"] = int((detalle["ESTADO_GENERAL"] == "REVISAR").sum())
    resumen["PARTIDAS_MONITOREAR"] = int((detalle["ESTADO_GENERAL"] == "MONITOREAR").sum())
    resumen["PARTIDAS_FULCOM_FUTURA"] = int(detalle["FULCOM_FUTURA"].sum())
    resumen.update(naturaleza_contraria(detalle, balanza))

    detalle.insert(0, "MES", periodo)
    return detalle, resumen
