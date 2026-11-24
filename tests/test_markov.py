"""Pruebas del módulo de Markov con cadenas pequeñas cuyo resultado se conoce a mano."""

import numpy as np
import pandas as pd
import pytest

from reto_ma2004b import markov as M


def partidas(secuencias: dict[str, list], sospechosas: dict[str, list] | None = None) -> pd.DataFrame:
    """Tabla tipo `partidas` a partir de {SKU: [estado mes 1, estado mes 2, ...]} (None = no aparece)."""
    filas = []
    meses = pd.date_range("2026-01-01", periods=max(len(v) for v in secuencias.values()), freq="MS")
    for sku, estados in secuencias.items():
        for i, e in enumerate(estados):
            if e is None:
                continue
            filas.append({"CODIGO": sku, "MES": meses[i], "SEMAFORO_DIAS": e, "VALORIZACION": 100.0,
                          "FULCOM_SOSPECHOSA": int(bool(sospechosas and i in sospechosas.get(sku, [])))})
    return pd.DataFrame(filas)


def test_maxima_verosimilitud_cuenta_transiciones():
    # A: V→V→Á→R ; B: V→Á→R→R  =>  desde VERDE: 1 a VERDE, 2 a ÁMBAR ; desde ÁMBAR: 2 a ROJO ; ROJO: 1 a ROJO
    p = partidas({"A": ["VERDE", "VERDE", "ÁMBAR", "ROJO"], "B": ["VERDE", "ÁMBAR", "ROJO", "ROJO"]})
    r = M.estimar(p, "SEMAFORO_DIAS")
    assert r.n_transiciones == 6
    assert r.matriz.loc["VERDE", "VERDE"] == pytest.approx(1 / 3)
    assert r.matriz.loc["VERDE", "ÁMBAR"] == pytest.approx(2 / 3)
    assert r.matriz.loc["ÁMBAR", "ROJO"] == pytest.approx(1.0)
    assert np.allclose(r.matriz.sum(axis=1), 1.0)


def test_meses_faltantes_no_crean_transiciones():
    p = partidas({"A": ["VERDE", None, "ROJO"]})
    assert M.estimar(p, "SEMAFORO_DIAS").n_transiciones == 0   # enero→marzo no es un paso de un mes
    r = M.estimar(p, "SEMAFORO_DIAS", incluir_ausencia=True)
    assert r.matriz.loc["VERDE", M.SIN_INVENTARIO] == 1.0
    assert r.matriz.loc[M.SIN_INVENTARIO, "ROJO"] == 1.0


def test_fechas_sospechosas_se_excluyen():
    p = partidas({"A": ["VERDE", "ROJO", "VERDE"], "B": ["VERDE", "VERDE", "VERDE"]}, sospechosas={"A": [1]})
    r = M.estimar(p, "SEMAFORO_DIAS")
    assert "ROJO" not in r.matriz.columns or r.conteos.loc["VERDE", "ROJO"] == 0
    assert M.estimar(p, "SEMAFORO_DIAS", excluir_sospechosas=False).conteos.loc["VERDE", "ROJO"] == 1


def test_suavizado_hacia_la_previa():
    n = pd.DataFrame([[3, 0], [0, 0]], index=["X", "Y"], columns=["X", "Y"], dtype=float)
    q = pd.DataFrame([[0.5, 0.5], [0.2, 0.8]], index=["X", "Y"], columns=["X", "Y"])
    p = M.matriz_transicion(n, q, alfa=1.0)
    assert p.loc["X", "X"] == pytest.approx((3 + 0.5) / 4)
    assert p.loc["Y", "Y"] == pytest.approx(0.8)          # sin datos propios: queda la previa
    assert M.matriz_transicion(n).loc["Y"].isna().all()   # sin previa: no se puede estimar


def test_cadena_periodica_no_es_ergodica():
    p = pd.DataFrame([[0, 1], [1, 0]], index=["A", "B"], columns=["A", "B"], dtype=float)
    pr = M.propiedades(p)
    assert pr["irreducible"] and not pr["aperiodica"] and not pr["ergodica"]
    assert pr["clases"][0]["periodo"] == 2
    assert pr["estacionaria"].tolist() == pytest.approx([0.5, 0.5])


def test_cadena_regular_es_ergodica_y_su_estacionaria():
    p = pd.DataFrame([[0.9, 0.1], [0.5, 0.5]], index=["A", "B"], columns=["A", "B"])
    pr = M.propiedades(p)
    assert pr["ergodica"] and pr["regular"]
    assert pr["estacionaria"]["A"] == pytest.approx(5 / 6)
    assert pr["tiempo_retorno"]["B"] == pytest.approx(6.0)


def test_estado_absorbente_y_clases():
    p = pd.DataFrame([[0.5, 0.5], [0, 1]], index=["A", "B"], columns=["A", "B"], dtype=float)
    pr = M.propiedades(p)
    assert pr["absorbentes"] == ["B"] and not pr["irreducible"]
    tipos = {tuple(c["estados"]): c["tipo"] for c in pr["clases"]}
    assert tipos[("A",)] == "transitoria" and tipos[("B",)] == "recurrente"
    assert M.tiempos_primer_paso(p, "B")["A"] == pytest.approx(2.0)


def test_proyeccion_conserva_probabilidad():
    p = pd.DataFrame([[0.9, 0.1], [0.5, 0.5]], index=["A", "B"], columns=["A", "B"])
    proy = M.proyectar(p, pd.Series({"A": 1.0}), 5)
    assert np.allclose(proy.sum(axis=1), 1.0)
    assert proy.loc[1, "B"] == pytest.approx(0.1)
    assert proy.loc[2, "B"] == pytest.approx(0.9 * 0.1 + 0.1 * 0.5)
