"""
Reglas por partida (una fila del Kardex).

La primera parte replica las fórmulas de la hoja DETALLE KARDEX de la propuesta de
FEMSA; cada función cita la fórmula que reemplaza. La segunda parte agrega lo que el
dashboard necesita: semáforo en días, riesgo por política de canje y rangos.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


# ---------------------------------------------------------------------------
# Réplica de las fórmulas de Excel
# ---------------------------------------------------------------------------

def valorizacion(stock: pd.Series, costo: pd.Series) -> pd.Series:
    """Excel F: =E*D"""
    return costo * stock


def meses_antiguedad(periodo: pd.Series, fulcom: pd.Series) -> pd.Series:
    """
    Excel I: =IF(G="","",MAX(0,(YEAR(EOMONTH(A,0))-YEAR(G))*12+MONTH(EOMONTH(A,0))-MONTH(G)))
    Meses de calendario entre el cierre del periodo y la fecha de compra; mínimo 0.
    """
    cierre = periodo + pd.offsets.MonthEnd(0)
    meses = (cierre.dt.year - fulcom.dt.year) * 12 + (cierre.dt.month - fulcom.dt.month)
    return meses.clip(lower=0).astype("Int64")


def semaforo_meses(meses: pd.Series,
                   limite_ambar: int = C.LIMITE_AMBAR_MESES,
                   limite_rojo: int = C.LIMITE_ROJO_MESES) -> pd.Series:
    """Excel J: =IF(G="","SIN FECHA",IF(I>12,"ROJO",IF(I>6,"ÁMBAR","VERDE")))"""
    m = meses.astype("float")
    return pd.Series(np.select([m.isna(), m > limite_rojo, m > limite_ambar],
                               ["SIN FECHA", "ROJO", "ÁMBAR"], default="VERDE"), index=meses.index)


def dif_valorizacion(valor: pd.Series, stock: pd.Series, costo: pd.Series) -> pd.Series:
    """Excel K: =F-(D*E). Por construcción es 0 (control circular, ver criterio fila 16)."""
    return valor - stock * costo


def alerta_stock(stock: pd.Series) -> pd.Series:
    """Excel L: =IF(D<0,"NEGATIVO",IF(D=0,"CERO","OK"))"""
    return pd.Series(np.select([stock < 0, stock == 0], ["NEGATIVO", "CERO"], default="OK"), index=stock.index)


def alerta_costo(costo: pd.Series) -> pd.Series:
    """Excel M: =IF(E<=0,"INVÁLIDO","OK")"""
    return pd.Series(np.where(costo <= 0, "INVÁLIDO", "OK"), index=costo.index)


def alerta_conversion(unid_conv: pd.Series) -> pd.Series:
    """
    Excel N: =IF(OR(H="",H<=0),"INVÁLIDA",IF(H<>1,"REVISAR","OK"))
    Con #N/A Excel propaga el error; aquí queda INVÁLIDA para que la partida no se pierda.
    """
    invalida = unid_conv.isna() | (unid_conv <= 0)
    return pd.Series(np.select([invalida, unid_conv != 1], ["INVÁLIDA", "REVISAR"], default="OK"),
                     index=unid_conv.index)


def alerta_duplicado(codigo: pd.Series) -> pd.Series:
    """Excel O es un "OK" fijo; se implementa COUNTIF(CODIGO)>1 como recomienda la propuesta."""
    return pd.Series(np.where(codigo.duplicated(keep=False), "DUPLICADO", "OK"), index=codigo.index)


def estado_general(df: pd.DataFrame, columna_semaforo: str = "SEMAFORO_MESES") -> pd.Series:
    """
    Excel P: =IF(OR(J="ROJO",L<>"OK",M<>"OK",ABS(K)>1,N<>"OK",O<>"OK"),"REVISAR",
                IF(J="ÁMBAR","MONITOREAR","OK"))
    """
    revisar = ((df[columna_semaforo] == "ROJO") | (df["ALERTA_STOCK"] != "OK")
               | (df["ALERTA_COSTO"] != "OK") | (df["DIF_VALORIZACION"].abs() > 1)
               | (df["ALERTA_CONVERSION"] != "OK") | (df["ALERTA_DUPLICADO"] != "OK"))
    monitorear = df[columna_semaforo] == "ÁMBAR"
    return pd.Series(np.select([revisar, monitorear], ["REVISAR", "MONITOREAR"], default="OK"), index=df.index)


# ---------------------------------------------------------------------------
# Política en días, riesgo y rangos (hoja "criterio de alertas")
# ---------------------------------------------------------------------------

def dias_antiguedad(periodo: pd.Series, fulcom: pd.Series) -> pd.Series:
    """Días entre la fecha de compra y el cierre del mes (negativo si la compra es posterior)."""
    return ((periodo + pd.offsets.MonthEnd(0)) - fulcom).dt.days.astype("Int64")


def semaforo_dias(dias: pd.Series,
                  limite_ambar: int = C.LIMITE_AMBAR_DIAS,
                  limite_rojo: int = C.LIMITE_ROJO_DIAS) -> pd.Series:
    """VERDE 0–90, ÁMBAR 91–180, ROJO > 180 días. Valida contra la tabla de impacto de la propuesta."""
    d = dias.astype("float").clip(lower=0)
    return pd.Series(np.select([d.isna(), d > limite_rojo, d > limite_ambar],
                               ["SIN FECHA", "ROJO", "ÁMBAR"], default="VERDE"), index=dias.index)


def riesgo_politica(semaforo: pd.Series, politica: pd.Series) -> pd.Series:
    """NORMAL / REVISIÓN / RIESGO ALTO según color y política de canje (P0 sin canje, P1 con canje)."""
    claves = zip(semaforo, politica.fillna("").astype(str).str.strip().str.upper())
    return pd.Series([C.RIESGO_POR_POLITICA.get(k, "SIN DATO") for k in claves], index=semaforo.index)


def rango_antiguedad(dias: pd.Series) -> pd.Series:
    """Rango de antigüedad en días para filtros y estados de Markov."""
    d = dias.astype("float")
    condiciones, etiquetas = [d.isna()], ["Sin fecha"]
    for minimo, maximo, etiqueta in C.RANGOS_DIAS:
        cond = d.clip(lower=0) >= minimo if maximo is None else d.clip(lower=0).between(minimo, maximo)
        condiciones.append(cond)
        etiquetas.append(etiqueta)
    return pd.Series(np.select(condiciones, etiquetas, default="Sin fecha"), index=dias.index)


def orden_rango(rango: pd.Series) -> pd.Series:
    orden = {etiqueta: i + 1 for i, (_, _, etiqueta) in enumerate(C.RANGOS_DIAS)}
    return rango.map(orden).fillna(len(orden) + 1).astype(int)


# ---------------------------------------------------------------------------
# Todo junto
# ---------------------------------------------------------------------------

def construir_columnas(kardex: pd.DataFrame, politica_estado: str = "meses") -> pd.DataFrame:
    """
    Agrega a un Kardex limpio todas las columnas de alerta.

    politica_estado: "meses" replica ESTADO GENERAL del Excel; "dias" lo calcula con el
    semáforo de la hoja de criterios. Ambos semáforos se calculan siempre.
    """
    df = kardex.copy()
    df["VALORIZACION"] = valorizacion(df["STOCK"], df["COSTO"])

    df["MESES_ANTIG"] = meses_antiguedad(df["PERIODO"], df["FULCOM"])
    df["SEMAFORO_MESES"] = semaforo_meses(df["MESES_ANTIG"])
    df["DIAS_ANTIG"] = dias_antiguedad(df["PERIODO"], df["FULCOM"])
    df["SEMAFORO_DIAS"] = semaforo_dias(df["DIAS_ANTIG"])
    df["RIESGO_POLITICA"] = riesgo_politica(df["SEMAFORO_DIAS"], df["POLITICA_CANJE"])
    df["RANGO_ANTIG"] = rango_antiguedad(df["DIAS_ANTIG"])
    df["RANGO_ORDEN"] = orden_rango(df["RANGO_ANTIG"])
    df["MAS_1_ANIO"] = (df["DIAS_ANTIG"].astype("float") > 365).astype(int)

    df["DIF_VALORIZACION"] = dif_valorizacion(df["VALORIZACION"], df["STOCK"], df["COSTO"])
    df["ALERTA_STOCK"] = alerta_stock(df["STOCK"])
    df["ALERTA_COSTO"] = alerta_costo(df["COSTO"])
    df["ALERTA_CONVERSION"] = alerta_conversion(df["UNID_CONV"])
    df["ALERTA_DUPLICADO"] = alerta_duplicado(df["CODIGO"])

    columna = "SEMAFORO_DIAS" if politica_estado == "dias" else "SEMAFORO_MESES"
    df["ESTADO_GENERAL"] = estado_general(df, columna)

    # Calidad de datos
    cierre = df["PERIODO"] + pd.offsets.MonthEnd(0)
    df["FULCOM_FUTURA"] = (df["FULCOM"] > cierre).astype(int)
    df["NATURALEZA_CONTRARIA"] = ((df["STOCK"] < 0) | (df["VALORIZACION"] < 0)).astype(int)
    return df
