"""
Indicadores por mes y tablas para el dashboard.

- `resumen_mes`: una fila por mes con conciliación, KPIs y conteos (alerta 1 y KPIs).
- `variacion_mensual`: alerta 2 sobre el resumen de varios meses.
- `tabla_alertas`: todas las alertas en formato largo (una fila por alerta).
- `transiciones`: movimiento de cada SKU entre rangos de antigüedad (base para Markov).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def etiqueta_mes(periodo: pd.Timestamp) -> str:
    return f"{C.MESES_ES[periodo.month - 1]} {periodo.year}"


def conciliacion(detalle: pd.DataFrame, saldo_gl: float, recetario: float | None) -> dict:
    """
    Alerta 1 — Kardex + recetario vs. GL.

    Excel (dashboard): D5 = total Kardex + recetario; G5 = D5 − A5;
    J5 = IF(ABS(G5) <= ABS(A5)*0.001, "CONCILIADO", "DIFERENCIA").
    Además separa la diferencia que explica el recetario de la que no explica nada.
    """
    total_kardex = float(detalle["VALORIZACION"].sum())
    receta = float(recetario) if recetario is not None else np.nan
    conciliable = total_kardex + (0.0 if np.isnan(receta) else receta)
    dif_kardex_gl = total_kardex - saldo_gl                  # antes de sumar el recetario
    dif_no_explicada = conciliable - saldo_gl               # lo que queda después del recetario
    abs_dif = abs(dif_no_explicada)

    if np.isnan(receta):
        estado, semaforo = "SIN RECETARIO", "ROJO"
    elif abs_dif <= C.TOLERANCIA_REDONDEO_CLP:
        estado, semaforo = "CONCILIADO", "VERDE"
    elif abs_dif <= abs(saldo_gl) * C.TOLERANCIA_PCT_GL:
        estado, semaforo = "CONCILIADO", "ÁMBAR"
    else:
        estado, semaforo = "DIFERENCIA", "ROJO"

    return {
        "SALDO_GL": saldo_gl,
        "TOTAL_KARDEX": total_kardex,
        "RECETARIO": receta,
        "INVENTARIO_CONCILIABLE": conciliable,
        "DIF_KARDEX_GL": dif_kardex_gl,
        "DIF_NO_EXPLICADA": dif_no_explicada,
        "DIF_PCT": dif_no_explicada / saldo_gl if saldo_gl else np.nan,
        "ESTADO_CONCILIACION": estado,
        "SEMAFORO_CONCILIACION": semaforo,
    }


def resumen_mes(detalle: pd.DataFrame, saldo: dict, recetario: float | None, tc: float | None) -> dict:
    """Una fila de indicadores del mes (lo que alimenta las tarjetas del dashboard)."""
    periodo = detalle["PERIODO"].iloc[0]
    r = {
        "MES": periodo,
        "MES_ORDEN": int(periodo.strftime("%Y%m")),
        "MES_ETIQUETA": etiqueta_mes(periodo),
        "TC_MXN_POR_CLP": tc if tc is not None else np.nan,
    }
    r.update(conciliacion(detalle, saldo["SALDO_GL"], recetario))
    r["SALDO_GL_MXN"] = r["SALDO_GL"] * r["TC_MXN_POR_CLP"]
    r["GL_SALDO_ACREEDOR"] = int(saldo["GL_SALDO_ACREEDOR"])

    r["PARTIDAS"] = int(len(detalle))
    r["SKUS_UNICOS"] = int(detalle["CODIGO"].nunique())
    r["PARTIDAS_MAS_1_ANIO"] = int(detalle["MAS_1_ANIO"].sum())
    r["VALOR_MAS_1_ANIO"] = float(detalle.loc[detalle["MAS_1_ANIO"] == 1, "VALORIZACION"].sum())

    for politica, columna in [("MESES", "SEMAFORO_MESES"), ("DIAS", "SEMAFORO_DIAS")]:
        for color in ["VERDE", "ÁMBAR", "ROJO"]:
            mask = detalle[columna] == color
            clave = color.replace("Á", "A")
            r[f"PARTIDAS_{clave}_{politica}"] = int(mask.sum())
            r[f"VALOR_{clave}_{politica}"] = float(detalle.loc[mask, "VALORIZACION"].sum())

    r["PARTIDAS_RIESGO_ALTO"] = int((detalle["RIESGO_POLITICA"] == "RIESGO ALTO").sum())
    r["VALOR_RIESGO_ALTO"] = float(detalle.loc[detalle["RIESGO_POLITICA"] == "RIESGO ALTO", "VALORIZACION"].sum())
    r["PARTIDAS_REVISAR"] = int((detalle["ESTADO_GENERAL"] == "REVISAR").sum())
    r["PARTIDAS_MONITOREAR"] = int((detalle["ESTADO_GENERAL"] == "MONITOREAR").sum())
    r["PARTIDAS_CONVERSION"] = int((detalle["ALERTA_CONVERSION"] != "OK").sum())
    r["PARTIDAS_DUPLICADAS"] = int((detalle["ALERTA_DUPLICADO"] != "OK").sum())
    r["PARTIDAS_NATURALEZA_CONTRARIA"] = int(detalle["NATURALEZA_CONTRARIA"].sum())
    r["PARTIDAS_FULCOM_FUTURA"] = int(detalle["FULCOM_FUTURA"].sum())
    return r


def variacion_mensual(resumen: pd.DataFrame, umbral: float = C.UMBRAL_VARIACION) -> pd.DataFrame:
    """Alerta 2 — variación del saldo GL contra el cierre del mes anterior (|Δ| >= 5 %)."""
    r = resumen.sort_values("MES").reset_index(drop=True).copy()
    r["SALDO_GL_MES_ANTERIOR"] = r["SALDO_GL"].shift()
    r["VARIACION_PCT"] = r["SALDO_GL"] / r["SALDO_GL_MES_ANTERIOR"] - 1
    r["VARIACION_KARDEX_PCT"] = r["TOTAL_KARDEX"].pct_change()
    r["ALERTA_VARIACION"] = np.where(r["VARIACION_PCT"].abs() >= umbral, "ALERTA", "OK")
    r.loc[r["VARIACION_PCT"].isna(), "ALERTA_VARIACION"] = "SIN MES PREVIO"
    return r


def tabla_alertas(partidas: pd.DataFrame, resumen: pd.DataFrame) -> pd.DataFrame:
    """
    Todas las alertas en una sola tabla larga: MES, TIPO, NIVEL, CODIGO, DETALLE, VALOR_CLP.
    Pensada para una página de "Alertas" y para notificaciones en Power BI.
    """
    filas = []
    for _, r in resumen.iterrows():
        if r["ESTADO_CONCILIACION"] != "CONCILIADO" or r["SEMAFORO_CONCILIACION"] != "VERDE":
            filas.append((r["MES"], "1. Conciliación", "ALTO" if r["SEMAFORO_CONCILIACION"] == "ROJO" else "MEDIO",
                          None, f"Diferencia no explicada de {r['DIF_NO_EXPLICADA']:,.2f} CLP", r["DIF_NO_EXPLICADA"]))
        if r["ALERTA_VARIACION"] == "ALERTA":
            filas.append((r["MES"], "2. Variación mensual", "ALTO", None,
                          f"El saldo GL varió {r['VARIACION_PCT']:+.2%} contra el mes anterior",
                          r["SALDO_GL"] - r["SALDO_GL_MES_ANTERIOR"]))
        if r["GL_SALDO_ACREEDOR"]:
            filas.append((r["MES"], "4. Naturaleza contraria", "ALTO", None,
                          "Saldo acreedor en la cuenta de existencias", r["SALDO_GL"]))

    p = partidas
    reglas = [
        (p["RIESGO_POLITICA"] == "RIESGO ALTO", "3. Antigüedad", "ALTO", "Más de 180 días sin canje (P0)"),
        ((p["RIESGO_POLITICA"] == "REVISIÓN") & (p["SEMAFORO_DIAS"] == "ROJO"), "3. Antigüedad", "MEDIO",
         "Más de 180 días con canje (P1)"),
        (p["SEMAFORO_DIAS"] == "ÁMBAR", "3. Antigüedad", "BAJO", "Entre 91 y 180 días"),
        (p["NATURALEZA_CONTRARIA"] == 1, "4. Naturaleza contraria", "ALTO", "Stock o valorización negativa"),
        (p["ALERTA_CONVERSION"] != "OK", "5. Calidad de datos", "MEDIO", "Unidad de conversión distinta de 1 o inválida"),
        (p["ALERTA_DUPLICADO"] != "OK", "5. Calidad de datos", "ALTO", "Código duplicado en el mes"),
        (p["ALERTA_COSTO"] != "OK", "5. Calidad de datos", "ALTO", "Costo menor o igual a cero"),
        (p["FULCOM_FUTURA"] == 1, "5. Calidad de datos", "MEDIO", "Fecha de compra posterior al cierre"),
    ]
    if "FULCOM_RETROCEDE" in p:
        reglas.append((p["FULCOM_RETROCEDE"] == 1, "5. Calidad de datos", "ALTO",
                       "Fecha de compra anterior a la del mes previo (posible error de captura)"))
    if "FULCOM_SOSPECHOSA" in p:
        reglas.append(((p["FULCOM_SOSPECHOSA"] == 1) & (p.get("FULCOM_RETROCEDE", 0) == 0), "5. Calidad de datos",
                       "ALTO", "Conserva una fecha de compra que retrocedió en un mes anterior"))
    tablas = [pd.DataFrame(filas, columns=["MES", "TIPO_ALERTA", "NIVEL", "CODIGO", "DETALLE", "VALOR_CLP"])]
    for mask, tipo, nivel, detalle in reglas:
        sub = p.loc[mask, ["MES", "CODIGO", "VALORIZACION"]].rename(columns={"VALORIZACION": "VALOR_CLP"})
        if len(sub):
            tablas.append(sub.assign(TIPO_ALERTA=tipo, NIVEL=nivel, DETALLE=detalle))
    alertas = pd.concat([t for t in tablas if len(t)], ignore_index=True)
    alertas["NIVEL_ORDEN"] = alertas["NIVEL"].map({"ALTO": 1, "MEDIO": 2, "BAJO": 3})
    return alertas[["MES", "TIPO_ALERTA", "NIVEL", "NIVEL_ORDEN", "CODIGO", "DETALLE", "VALOR_CLP"]]


def marcar_fulcom_retrocede(partidas: pd.DataFrame) -> pd.Series:
    """
    1 si la fecha de compra de un SKU es ANTERIOR a la que tenía el mes previo.

    La última compra solo puede avanzar (o quedarse igual). Si retrocede, es un error de
    captura; en los datos de junio 2026 hay 591 SKU cuya FULCOM pasó de 01/05/2026 a
    01/05/2025 (un año exacto), lo que infla el inventario envejecido de ese mes.
    """
    p = partidas[["CODIGO", "MES", "FULCOM"]].sort_values(["CODIGO", "MES"])
    previo_mes = p.groupby("CODIGO")["MES"].shift()
    previo_fulcom = p.groupby("CODIGO")["FULCOM"].shift()
    consecutivo = (p["MES"] - pd.offsets.MonthBegin(1)) == previo_mes
    marca = (consecutivo & (p["FULCOM"] < previo_fulcom)).astype(int)
    return marca.reindex(partidas.index)


def marcar_fulcom_sospechosa(partidas: pd.DataFrame, retrocede: pd.Series) -> pd.Series:
    """
    1 si la partida tiene una fecha de compra que retrocedió (este mes o antes) y la
    conserva. En julio 2026, 308 de los 591 SKU de junio siguen con la fecha de 2025.
    """
    p = partidas[["CODIGO", "MES", "FULCOM"]].assign(RET=retrocede).sort_values(["CODIGO", "MES"])
    fecha_sospechosa = p["FULCOM"].where(p["RET"] == 1).groupby(p["CODIGO"]).ffill()
    return (p["FULCOM"] == fecha_sospechosa).astype(int).reindex(partidas.index)


def transiciones(partidas: pd.DataFrame) -> pd.DataFrame:
    """
    Para cada SKU y mes, el rango de antigüedad en t y en t+1 ("Sale" si desaparece del
    Kardex). Es la materia prima de las matrices de transición del modelo de Markov.
    """
    meses = sorted(partidas["MES"].unique())
    pares = []
    for actual, siguiente in zip(meses, meses[1:]):
        a = partidas.loc[partidas["MES"] == actual,
                         ["CODIGO", "RANGO_ANTIG", "RANGO_ORDEN", "VALORIZACION", "POLITICA_CANJE", "NOMBRE_LINEA"]]
        b = partidas.loc[partidas["MES"] == siguiente, ["CODIGO", "RANGO_ANTIG", "RANGO_ORDEN"]].rename(
            columns={"RANGO_ANTIG": "RANGO_SIGUIENTE", "RANGO_ORDEN": "RANGO_SIGUIENTE_ORDEN"})
        t = a.merge(b, on="CODIGO", how="left")
        t["RANGO_SIGUIENTE"] = t["RANGO_SIGUIENTE"].fillna("Sale")
        t["RANGO_SIGUIENTE_ORDEN"] = t["RANGO_SIGUIENTE_ORDEN"].fillna(len(C.RANGOS_DIAS) + 2).astype(int)
        t.insert(0, "MES", actual)
        t.insert(1, "MES_SIGUIENTE", siguiente)
        pares.append(t)
    return pd.concat(pares, ignore_index=True) if pares else pd.DataFrame()


def dimensiones(partidas: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Tablas pequeñas para relaciones, orden y colores en Power BI."""
    linea = (partidas[["LINEA", "NOMBRE_LINEA"]].drop_duplicates().sort_values("LINEA").reset_index(drop=True))
    semaforo = pd.DataFrame({"SEMAFORO": list(C.SEMAFORO_ORDEN),
                             "ORDEN": list(C.SEMAFORO_ORDEN.values()),
                             "COLOR_HEX": [C.SEMAFORO_COLOR[s] for s in C.SEMAFORO_ORDEN]})
    rango = pd.DataFrame({"RANGO_ANTIG": [e for _, _, e in C.RANGOS_DIAS] + ["Sin fecha"],
                          "RANGO_ORDEN": list(range(1, len(C.RANGOS_DIAS) + 2))})
    return {"dim_linea": linea, "dim_semaforo": semaforo, "dim_rango": rango}
