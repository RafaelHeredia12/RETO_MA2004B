"""Pruebas de las reglas con casos pequeños escritos a mano. Correr con: uv run pytest"""

import pandas as pd
import pytest

from reto_ma2004b import indicadores, reglas


def kardex(**cols):
    base = {
        "PERIODO": pd.to_datetime(["2026-01-01"]),
        "CODIGO": ["SKU_1"], "DESCRIPTOR": ["X"], "STOCK": [10], "COSTO": [100.0],
        "FULCOM": pd.to_datetime(["2025-12-15"]), "UNID_CONV": [1.0],
        "LINEA": pd.array([400], dtype="Int64"), "NOMBRE_LINEA": ["FARMACIA"], "POLITICA_CANJE": ["P0"],
    }
    base.update(cols)
    n = max(len(v) for v in base.values())
    return pd.DataFrame({k: (list(v) * n if len(v) == 1 else list(v)) for k, v in base.items()})


@pytest.mark.parametrize("fulcom, esperado", [
    ("2026-01-10", 0),   # mismo mes
    ("2025-12-31", 1),
    ("2025-01-31", 12),
    ("2024-12-01", 13),
    ("2026-03-01", 0),   # fecha posterior al cierre: Excel la deja en 0
])
def test_meses_antiguedad_replica_excel(fulcom, esperado):
    periodo = pd.Series(pd.to_datetime(["2026-01-01"]))
    assert reglas.meses_antiguedad(periodo, pd.Series(pd.to_datetime([fulcom]))).iloc[0] == esperado


@pytest.mark.parametrize("meses, color", [(0, "VERDE"), (6, "VERDE"), (7, "ÁMBAR"), (12, "ÁMBAR"), (13, "ROJO")])
def test_semaforo_meses(meses, color):
    assert reglas.semaforo_meses(pd.Series([meses], dtype="Int64")).iloc[0] == color


@pytest.mark.parametrize("dias, color", [(0, "VERDE"), (90, "VERDE"), (91, "ÁMBAR"), (180, "ÁMBAR"), (181, "ROJO")])
def test_semaforo_dias(dias, color):
    assert reglas.semaforo_dias(pd.Series([dias], dtype="Int64")).iloc[0] == color


@pytest.mark.parametrize("color, politica, riesgo", [
    ("VERDE", "P0", "NORMAL"), ("ÁMBAR", "P1", "REVISIÓN"), ("ROJO", "P1", "REVISIÓN"), ("ROJO", "P0", "RIESGO ALTO"),
])
def test_riesgo_por_politica(color, politica, riesgo):
    assert reglas.riesgo_politica(pd.Series([color]), pd.Series([politica])).iloc[0] == riesgo


def test_conversion_na_no_se_pierde():
    r = reglas.construir_columnas(kardex(UNID_CONV=[float("nan")]))
    assert r["ALERTA_CONVERSION"].iloc[0] == "INVÁLIDA"
    assert r["ESTADO_GENERAL"].iloc[0] == "REVISAR"


def test_duplicado_marca_ambas_filas():
    r = reglas.construir_columnas(kardex(CODIGO=["SKU_1", "SKU_1", "SKU_2"]))
    assert r["ALERTA_DUPLICADO"].tolist() == ["DUPLICADO", "DUPLICADO", "OK"]


def test_conciliacion_semaforo():
    det = reglas.construir_columnas(kardex(STOCK=[1], COSTO=[1_000_000.0]))  # total Kardex = 1,000,000
    verde = indicadores.conciliacion(det, saldo_gl=1_500_000.4, recetario=500_000)
    assert verde["SEMAFORO_CONCILIACION"] == "VERDE" and verde["ESTADO_CONCILIACION"] == "CONCILIADO"
    ambar = indicadores.conciliacion(det, saldo_gl=1_501_000.0, recetario=500_000)  # 1,000 CLP < 0.1 %
    assert ambar["SEMAFORO_CONCILIACION"] in {"VERDE", "ÁMBAR"}
    rojo = indicadores.conciliacion(det, saldo_gl=2_000_000.0, recetario=500_000)
    assert rojo["ESTADO_CONCILIACION"] == "DIFERENCIA"
    sin = indicadores.conciliacion(det, saldo_gl=1_500_000.0, recetario=None)
    assert sin["ESTADO_CONCILIACION"] == "SIN RECETARIO"


def test_variacion_mensual_umbral():
    res = pd.DataFrame({"MES": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"]),
                        "SALDO_GL": [100.0, 104.0, 98.0], "TOTAL_KARDEX": [100.0, 104.0, 98.0]})
    v = indicadores.variacion_mensual(res)
    assert v["ALERTA_VARIACION"].tolist() == ["SIN MES PREVIO", "OK", "ALERTA"]
