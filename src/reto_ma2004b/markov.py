"""
Cadenas de Markov de primer orden sobre las alertas de cada SKU.

Cada alerta por partida (semáforo de antigüedad, riesgo por política, estado general, rango
de antigüedad, unidad de conversión) es un estado que cambia mes a mes. Con la tabla
`partidas` de todos los meses se arma, para cada SKU, la secuencia de estados y se cuentan
las transiciones de un mes al siguiente.

- `pares`: transiciones observadas (SKU, mes, estado de origen, estado de destino).
- `estimar`: matriz de transición global, de un segmento o de un SKU (con suavizado).
- `estimar_sku`: las matrices de un SKU para todas las alertas.
- `propiedades`: clases, periodicidad, ergodicidad, distribución estacionaria.
- `tiempos_primer_paso`, `proyectar`, `riesgo_por_sku`: uso predictivo.
- `prueba_homogeneidad`, `backtest`: qué tan razonable es el supuesto de Markov homogéneo.

La estimación es la de máxima verosimilitud: p_ij = n_ij / n_i. Para un SKU solo hay
6 transiciones (7 meses), así que su matriz se suaviza hacia la global:
p_ij = (n_ij + alfa * q_ij) / (n_i + alfa), con q la matriz global (previa de Dirichlet).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import gcd

import numpy as np
import pandas as pd

from . import config as C

SIN_INVENTARIO = "SIN INVENTARIO"

ALERTAS: dict[str, dict] = {
    "SEMAFORO_DIAS": {
        "titulo": "Semáforo de antigüedad (días, hoja de criterios)",
        "estados": ["VERDE", "ÁMBAR", "ROJO", "SIN FECHA"],
    },
    "SEMAFORO_MESES": {
        "titulo": "Semáforo de antigüedad (meses, fórmulas del Kardex)",
        "estados": ["VERDE", "ÁMBAR", "ROJO", "SIN FECHA"],
    },
    "RIESGO_POLITICA": {
        "titulo": "Riesgo por política de canje",
        "estados": ["NORMAL", "REVISIÓN", "RIESGO ALTO"],
    },
    "ESTADO_GENERAL": {
        "titulo": "Estado general de la partida",
        "estados": ["OK", "MONITOREAR", "REVISAR"],
    },
    "RANGO_ANTIG": {
        "titulo": "Rango de antigüedad",
        "estados": [r[2] for r in C.RANGOS_DIAS],
    },
    "ALERTA_CONVERSION": {
        "titulo": "Unidad de conversión",
        "estados": ["OK", "REVISAR", "INVÁLIDA"],
    },
}

# Estado "malo" de cada alerta: el que interesa predecir
ESTADO_CRITICO = {
    "SEMAFORO_DIAS": "ROJO",
    "SEMAFORO_MESES": "ROJO",
    "RIESGO_POLITICA": "RIESGO ALTO",
    "ESTADO_GENERAL": "REVISAR",
    "RANGO_ANTIG": "Más de 365 días",
    "ALERTA_CONVERSION": "REVISAR",
}


@dataclass
class ResultadoMarkov:
    alerta: str
    estados: list[str]
    conteos: pd.DataFrame          # n_ij (o valor en CLP si se pondera)
    matriz: pd.DataFrame           # p_ij; renglones sin datos quedan en NaN
    n_transiciones: int
    n_skus: int
    opciones: dict = field(default_factory=dict)

    @property
    def renglones_sin_datos(self) -> list[str]:
        return [e for e in self.estados if self.matriz.loc[e].isna().any()]


# ----------------------------------------------------------------------------- datos

def estados_de(partidas: pd.DataFrame, alerta: str, incluir_ausencia: bool = False) -> list[str]:
    """Estados en orden lógico: los definidos que aparecen en los datos y luego cualquier otro."""
    definidos = ALERTAS.get(alerta, {}).get("estados", [])
    observados = set(partidas[alerta].dropna().unique())
    estados = [e for e in definidos if e in observados] + sorted(observados - set(definidos))
    if incluir_ausencia:
        estados.append(SIN_INVENTARIO)
    return estados


def _filtrar(partidas: pd.DataFrame, filtros: dict | None) -> pd.DataFrame:
    if not filtros:
        return partidas
    m = pd.Series(True, index=partidas.index)
    for col, valor in filtros.items():
        if valor is None:
            continue
        valores = valor if isinstance(valor, (list, tuple, set)) else [valor]
        m &= partidas[col].isin(valores)
    return partidas[m]


def secuencias(partidas: pd.DataFrame, alerta: str, codigos=None,
               incluir_ausencia: bool = False) -> pd.DataFrame:
    """Tabla SKU × mes con el estado de la alerta (como la tabla de ejemplo del entregable)."""
    p = partidas if codigos is None else partidas[partidas["CODIGO"].isin(np.atleast_1d(codigos))]
    tabla = p.pivot(index="CODIGO", columns="MES", values=alerta)
    tabla = tabla.reindex(columns=sorted(partidas["MES"].unique()))
    if incluir_ausencia:
        tabla = tabla.fillna(SIN_INVENTARIO)
    return tabla


def pares(partidas: pd.DataFrame, alerta: str, incluir_ausencia: bool = False,
          excluir_sospechosas: bool = True, meses=None) -> pd.DataFrame:
    """
    Una fila por transición observada de un mes al siguiente.

    incluir_ausencia: si un SKU no aparece en un mes, su estado es "SIN INVENTARIO"
        (permite ver altas y bajas de productos). Si es False, solo cuentan los meses
        consecutivos en los que el SKU sí aparece.
    excluir_sospechosas: descarta las transiciones donde origen o destino tienen una fecha de
        compra marcada como sospechosa (el error de junio 2026), que no son cambios reales.
    meses: meses a considerar (por defecto, los de `partidas`); sirve para un SKU solo.
    """
    meses = pd.to_datetime(pd.Series(partidas["MES"].unique() if meses is None else list(meses)))
    meses = list(pd.date_range(meses.min(), meses.max(), freq="MS"))  # un mes faltante corta la secuencia
    estado = partidas.pivot(index="CODIGO", columns="MES", values=alerta).reindex(columns=meses)
    valor = partidas.pivot(index="CODIGO", columns="MES", values="VALORIZACION").reindex(columns=meses)
    if excluir_sospechosas and "FULCOM_SOSPECHOSA" in partidas:
        sosp = partidas.pivot(index="CODIGO", columns="MES", values="FULCOM_SOSPECHOSA")
        sosp = sosp.reindex(columns=meses).fillna(0).astype(bool)
    else:
        sosp = pd.DataFrame(False, index=estado.index, columns=meses)

    bloques = []
    for m0, m1 in zip(meses[:-1], meses[1:]):
        b = pd.DataFrame({
            "CODIGO": estado.index,
            "MES": m0,
            "MES_SIGUIENTE": m1,
            "ORIGEN": estado[m0].to_numpy(),
            "DESTINO": estado[m1].to_numpy(),
            "VALOR_ORIGEN": valor[m0].to_numpy(),
            "VALOR_DESTINO": valor[m1].to_numpy(),
        })
        b = b[~(sosp[m0].to_numpy() | sosp[m1].to_numpy())]
        if incluir_ausencia:
            b[["ORIGEN", "DESTINO"]] = b[["ORIGEN", "DESTINO"]].fillna(SIN_INVENTARIO)
        else:
            b = b[b["ORIGEN"].notna() & b["DESTINO"].notna()]
        bloques.append(b)

    out = pd.concat(bloques, ignore_index=True)
    out["PESO_VALOR"] = out["VALOR_ORIGEN"].fillna(out["VALOR_DESTINO"]).clip(lower=0)
    return out


# ----------------------------------------------------------------------------- estimación

def conteos(transiciones: pd.DataFrame, estados: list[str], ponderar: bool = False) -> pd.DataFrame:
    """Matriz n_ij. Con ponderar=True suma el valor del inventario en lugar de contar SKU."""
    pesos = transiciones["PESO_VALOR"] if ponderar else pd.Series(1.0, index=transiciones.index)
    n = pd.crosstab(transiciones["ORIGEN"], transiciones["DESTINO"], values=pesos, aggfunc="sum")
    return n.reindex(index=estados, columns=estados).fillna(0.0)


def matriz_transicion(n: pd.DataFrame, previa: pd.DataFrame | None = None, alfa: float = 0.0) -> pd.DataFrame:
    """
    p_ij = (n_ij + alfa * q_ij) / (n_i + alfa).

    Sin previa (o alfa = 0) es la estimación de máxima verosimilitud. Un renglón sin
    observaciones y sin previa queda en NaN: no hay información para estimarlo.
    """
    n = n.astype(float)
    if previa is not None and alfa > 0:
        q = previa.reindex(index=n.index, columns=n.columns)
        q = q.apply(lambda r: r.fillna(0.0) if r.notna().any() else r, axis=1)
        num = n + alfa * q.fillna(0.0)
        den = n.sum(axis=1) + alfa * q.notna().any(axis=1)
    else:
        num, den = n, n.sum(axis=1)
    p = num.div(den.replace(0, np.nan), axis=0)
    return p


def estimar(partidas: pd.DataFrame, alerta: str, codigo: str | None = None, filtros: dict | None = None,
            incluir_ausencia: bool = False, excluir_sospechosas: bool = True, ponderar: bool = False,
            alfa: float = 0.0, previa: pd.DataFrame | None = None) -> ResultadoMarkov:
    """
    Matriz de transición de una alerta.

    - Global: estimar(partidas, "SEMAFORO_DIAS")
    - Segmento: estimar(partidas, "SEMAFORO_DIAS", filtros={"NOMBRE_LINEA": "FARMACIA"})
    - Un SKU: estimar(partidas, "SEMAFORO_DIAS", codigo="SKU_000123", alfa=2)
      (con alfa > 0 y sin previa, la previa es la matriz global con las mismas opciones)
    """
    estados = estados_de(partidas, alerta, incluir_ausencia)
    base = _filtrar(partidas, filtros)
    opciones = dict(incluir_ausencia=incluir_ausencia, excluir_sospechosas=excluir_sospechosas,
                    ponderar=ponderar)

    if codigo is not None:
        sub = base[base["CODIGO"] == codigo]
        if sub.empty:
            raise ValueError(f"No hay partidas para {codigo}")
        if alfa > 0 and previa is None:
            previa = estimar(base, alerta, **opciones).matriz
    else:
        sub = base
    if sub.empty:
        raise ValueError("No hay partidas con esos filtros")

    t = pares(sub, alerta, incluir_ausencia, excluir_sospechosas, meses=partidas["MES"].unique())
    n = conteos(t, estados, ponderar)
    p = matriz_transicion(n, previa, alfa)
    return ResultadoMarkov(alerta, estados, n, p, int(len(t)), int(t["CODIGO"].nunique()),
                           {**opciones, "codigo": codigo, "filtros": filtros, "alfa": alfa})


def estimar_sku(partidas: pd.DataFrame, codigo: str, alertas: list[str] | None = None,
                alfa: float = 1.0, **opciones) -> dict[str, ResultadoMarkov]:
    """Las matrices de un SKU para todas las alertas (suavizadas hacia la global)."""
    alertas = alertas or [a for a in ALERTAS if a in partidas]
    return {a: estimar(partidas, a, codigo=codigo, alfa=alfa, **opciones) for a in alertas}


# ----------------------------------------------------------------------------- propiedades

def _alcance(adj: np.ndarray) -> np.ndarray:
    """Cerradura transitiva (Warshall): r[i, j] = se puede llegar de i a j en ≥ 0 pasos."""
    r = adj.copy() | np.eye(len(adj), dtype=bool)
    for k in range(len(adj)):
        r |= r[:, [k]] & r[[k], :]
    return r


def _periodo(adj: np.ndarray, nodos: list[int]) -> int:
    """Periodo de una clase: mcd de (nivel(u) + 1 − nivel(v)) sobre las aristas internas."""
    nivel = {nodos[0]: 0}
    cola = [nodos[0]]
    while cola:
        u = cola.pop(0)
        for v in nodos:
            if adj[u, v] and v not in nivel:
                nivel[v] = nivel[u] + 1
                cola.append(v)
    d = 0
    for u in nodos:
        for v in nodos:
            if adj[u, v]:
                d = gcd(d, nivel[u] + 1 - nivel[v])
    return abs(d) if d else 0


def estacionaria(p: pd.DataFrame) -> pd.Series | None:
    """Resuelve pi P = pi, sum(pi) = 1. Devuelve None si la matriz tiene renglones sin datos."""
    if p.isna().any().any():
        return None
    a = p.to_numpy().T - np.eye(len(p))
    a = np.vstack([a, np.ones(len(p))])
    b = np.zeros(len(p) + 1)
    b[-1] = 1.0
    pi, *_ = np.linalg.lstsq(a, b, rcond=None)
    pi = np.clip(pi, 0, None)
    return pd.Series(pi / pi.sum(), index=p.index)


def propiedades(p: pd.DataFrame, tol: float = 1e-12) -> dict:
    """
    Estructura de la cadena.

    - clases comunicantes, cuáles son cerradas (recurrentes) y cuáles transitorias
    - periodo de cada clase; estados absorbentes
    - irreducible (una sola clase), aperiódica (periodo 1) y ergódica (ambas)
    - regular: alguna potencia P^k tiene todas sus entradas positivas
    - distribución estacionaria y tiempo medio de retorno (1 / pi_i), si es única
    """
    estados = list(p.index)
    con_datos = [e for e in estados if p.loc[e].notna().all()]
    adj = (p.fillna(0).to_numpy() > tol)
    r = _alcance(adj)
    mutuo = r & r.T

    clases, vistos = [], set()
    for i in range(len(estados)):
        if i in vistos:
            continue
        miembros = [j for j in range(len(estados)) if mutuo[i, j]]
        vistos.update(miembros)
        sale = any(adj[u, v] for u in miembros for v in range(len(estados)) if v not in miembros)
        sin_datos = any(estados[u] not in con_datos for u in miembros)
        clases.append({
            "estados": [estados[j] for j in miembros],
            "tipo": "sin datos" if sin_datos else ("transitoria" if sale else "recurrente"),
            "periodo": _periodo(adj, miembros),
        })

    completa = len(con_datos) == len(estados)
    recurrentes = [c for c in clases if c["tipo"] == "recurrente"]
    irreducible = completa and len(clases) == 1
    aperiodica = completa and all(c["periodo"] == 1 for c in recurrentes)
    absorbentes = [e for e in con_datos if p.loc[e, e] >= 1 - 1e-9]

    regular = False
    if completa:
        m = len(estados)
        pk = np.eye(m)
        for _ in range((m - 1) ** 2 + 1):
            pk = pk @ p.to_numpy()
            if (pk > tol).all():
                regular = True
                break

    pi = estacionaria(p) if completa and len(recurrentes) == 1 else None
    return {
        "completa": completa,
        "estados_sin_datos": [e for e in estados if e not in con_datos],
        "clases": clases,
        "irreducible": irreducible,
        "aperiodica": aperiodica,
        "ergodica": irreducible and aperiodica,
        "regular": regular,
        "absorbentes": absorbentes,
        "estacionaria": pi,
        "tiempo_retorno": (1 / pi.replace(0, np.nan)) if pi is not None else None,
    }


def resumen_propiedades(prop: dict) -> str:
    """Texto corto para reportes y la app."""
    if not prop["completa"]:
        return (f"Matriz incompleta: no hay transiciones que salgan de {prop['estados_sin_datos']}. "
                "Usa suavizado (alfa > 0) o un segmento con más SKU.")
    partes = ["irreducible" if prop["irreducible"] else f"reducible ({len(prop['clases'])} clases)",
              "aperiódica" if prop["aperiodica"] else "periódica",
              "ergódica" if prop["ergodica"] else "no ergódica"]
    if prop["absorbentes"]:
        partes.append(f"estados absorbentes: {', '.join(prop['absorbentes'])}")
    return "; ".join(partes)


# ----------------------------------------------------------------------------- predicción

def potencia(p: pd.DataFrame, k: int) -> pd.DataFrame:
    """P^k: probabilidad de pasar de i a j en exactamente k meses."""
    return pd.DataFrame(np.linalg.matrix_power(p.fillna(0).to_numpy(), k), index=p.index, columns=p.columns)


def proyectar(p: pd.DataFrame, inicial: pd.Series, pasos: int) -> pd.DataFrame:
    """Distribución esperada después de 0, 1, ..., pasos meses: x_{t+1} = x_t P."""
    x = inicial.reindex(p.index).fillna(0.0).to_numpy()
    x = x / x.sum()
    filas = [x]
    for _ in range(pasos):
        x = x @ p.fillna(0).to_numpy()
        filas.append(x)
    return pd.DataFrame(filas, columns=p.index).rename_axis("MESES")


def distribucion(partidas: pd.DataFrame, alerta: str, mes=None, ponderar: bool = False,
                 filtros: dict | None = None, excluir_sospechosas: bool = False) -> pd.Series:
    """Proporción de SKU (o del valor del inventario) en cada estado en un mes (por defecto el último)."""
    base = _filtrar(partidas, filtros)
    mes = pd.Timestamp(mes) if mes is not None else base["MES"].max()
    b = base[base["MES"] == mes]
    if excluir_sospechosas and "FULCOM_SOSPECHOSA" in b:
        b = b[b["FULCOM_SOSPECHOSA"] != 1]
    pesos = b["VALORIZACION"].clip(lower=0) if ponderar else pd.Series(1.0, index=b.index)
    d = pesos.groupby(b[alerta]).sum()
    return (d / d.sum()).reindex(estados_de(partidas, alerta)).fillna(0.0)


def tiempos_primer_paso(p: pd.DataFrame, destino: str) -> pd.Series:
    """
    Meses esperados para llegar por primera vez a `destino` desde cada estado.

    Resuelve m_i = 1 + sum_{j != destino} p_ij m_j. Si desde un estado no se puede llegar,
    el tiempo es infinito.
    """
    estados = list(p.index)
    pm = p.fillna(0).to_numpy()
    r = _alcance(pm > 0)
    d = estados.index(destino)
    otros = [i for i in range(len(estados)) if i != d and r[i, d]]
    m = pd.Series(np.inf, index=estados)
    m[destino] = 0.0
    if otros:
        q = pm[np.ix_(otros, otros)]
        sol = np.linalg.solve(np.eye(len(otros)) - q, np.ones(len(otros)))
        m.iloc[otros] = sol
    return m


def riesgo_por_sku(partidas: pd.DataFrame, alerta: str = "SEMAFORO_DIAS", destino: str | None = None,
                   pasos: int = 3, alfa: float = 2.0, mes=None, excluir_sospechosas: bool = True,
                   solo_fuera_de_destino: bool = True) -> pd.DataFrame:
    """
    Para cada SKU del mes elegido: probabilidad de estar en `destino` dentro de `pasos` meses,
    con su propia matriz suavizada hacia la global, y valor esperado en ese estado.

    Con solo_fuera_de_destino=True deja fuera a los que ya están en el destino: es la lista
    de trabajo para actuar antes de que el producto llegue a rojo.
    """
    destino = destino or ESTADO_CRITICO[alerta]
    estados = estados_de(partidas, alerta)
    t = pares(partidas, alerta, excluir_sospechosas=excluir_sospechosas)
    q = matriz_transicion(conteos(t, estados))
    q_np = q.fillna(0).to_numpy()
    idx = {e: i for i, e in enumerate(estados)}
    j = idx[destino]

    # conteos por SKU en un arreglo (n_sku, k, k)
    skus = t["CODIGO"].astype("category")
    k = len(estados)
    cnt = np.zeros((len(skus.cat.categories), k, k))
    np.add.at(cnt, (skus.cat.codes.to_numpy(), t["ORIGEN"].map(idx).to_numpy(), t["DESTINO"].map(idx).to_numpy()), 1)
    tiene_q = ~np.isnan(q.to_numpy()).any(axis=1)
    p_sku = (cnt + alfa * q_np) / (cnt.sum(axis=2, keepdims=True) + alfa * tiene_q[None, :, None])
    pk = np.linalg.matrix_power(p_sku, pasos)
    prob = pd.DataFrame(pk[:, :, j], index=skus.cat.categories, columns=estados)

    mes = pd.Timestamp(mes) if mes is not None else partidas["MES"].max()
    columnas = ["CODIGO", "DESCRIPTOR", "NOMBRE_LINEA", "POLITICA_CANJE", alerta, "DIAS_ANTIG", "VALORIZACION"]
    columnas += [c for c in ["FULCOM_SOSPECHOSA"] if c in partidas and c not in columnas]
    hoy = partidas[partidas["MES"] == mes][list(dict.fromkeys(columnas))].copy()
    sin_historia = ~hoy["CODIGO"].isin(prob.index)
    p_global = np.linalg.matrix_power(q_np, pasos)[:, j]
    hoy["PROB_DESTINO"] = [
        p_global[idx[e]] if s else prob.at[c, e]
        for c, e, s in zip(hoy["CODIGO"], hoy[alerta], sin_historia)
    ]
    hoy["VALOR_ESPERADO_DESTINO"] = hoy["PROB_DESTINO"] * hoy["VALORIZACION"].clip(lower=0)
    hoy["SIN_HISTORIA"] = sin_historia.to_numpy()
    hoy = hoy.rename(columns={alerta: "ESTADO_ACTUAL"})
    if solo_fuera_de_destino:
        hoy = hoy[hoy["ESTADO_ACTUAL"] != destino]
    return hoy.sort_values("VALOR_ESPERADO_DESTINO", ascending=False).reset_index(drop=True)


# ----------------------------------------------------------------------------- validación del modelo

def matrices_por_mes(partidas: pd.DataFrame, alerta: str, **opciones) -> dict:
    """Una matriz por cada par de meses consecutivos (para revisar si la cadena es homogénea)."""
    estados = estados_de(partidas, alerta, opciones.get("incluir_ausencia", False))
    t = pares(partidas, alerta, opciones.get("incluir_ausencia", False), opciones.get("excluir_sospechosas", True))
    return {m: matriz_transicion(conteos(g, estados)) for m, g in t.groupby("MES")}


def prueba_homogeneidad(partidas: pd.DataFrame, alerta: str, **opciones) -> dict:
    """
    Prueba de razón de verosimilitud (Anderson y Goodman) de H0: la matriz es la misma todos
    los meses. G = 2 * sum_t sum_ij n_ij(t) * ln(p_ij(t) / p_ij), aprox. chi-cuadrada.
    """
    from scipy.stats import chi2

    estados = estados_de(partidas, alerta, opciones.get("incluir_ausencia", False))
    t = pares(partidas, alerta, opciones.get("incluir_ausencia", False), opciones.get("excluir_sospechosas", True))
    p = matriz_transicion(conteos(t, estados)).fillna(0)
    g, gl = 0.0, 0
    for _, sub in t.groupby("MES"):
        n = conteos(sub, estados)
        pt = matriz_transicion(n).fillna(0)
        mask = n.to_numpy() > 0
        g += 2 * float((n.to_numpy()[mask] * np.log(pt.to_numpy()[mask] / p.to_numpy()[mask])).sum())
    for e in estados:
        meses_con_datos = t[t["ORIGEN"] == e]["MES"].nunique()
        destinos = int((p.loc[e] > 0).sum())
        gl += max(meses_con_datos - 1, 0) * max(destinos - 1, 0)
    return {"G": g, "gl": gl, "p_valor": float(chi2.sf(g, gl)) if gl else np.nan}


def backtest(partidas: pd.DataFrame, alerta: str, mes_corte, excluir_sospechosas: bool = True) -> pd.DataFrame:
    """
    Estima la matriz solo con las transiciones hasta `mes_corte`, toma a los SKU de ese mes y
    proyecta su distribución a los meses siguientes; la compara con lo que realmente pasó con
    esos mismos SKU. Devuelve una fila por mes y estado con lo proyectado y lo observado.
    """
    mes_corte = pd.Timestamp(mes_corte)
    estados = estados_de(partidas, alerta)
    t = pares(partidas, alerta, excluir_sospechosas=excluir_sospechosas)
    p = matriz_transicion(conteos(t[t["MES_SIGUIENTE"] <= mes_corte], estados))

    base = partidas
    if excluir_sospechosas and "FULCOM_SOSPECHOSA" in base:
        base = base[base["FULCOM_SOSPECHOSA"] != 1]
    cohorte = base[base["MES"] == mes_corte]["CODIGO"]
    futuros = sorted(m for m in base["MES"].unique() if m > mes_corte)
    inicial = distribucion(base[base["CODIGO"].isin(cohorte)], alerta, mes_corte)
    proy = proyectar(p, inicial, len(futuros))

    filas = []
    for h, mes in enumerate(futuros, start=1):
        obs = distribucion(base[base["CODIGO"].isin(cohorte)], alerta, mes)
        for e in estados:
            filas.append({"MES": mes, "HORIZONTE": h, "ESTADO": e,
                          "PROYECTADO": proy.loc[h, e], "OBSERVADO": obs.get(e, 0.0)})
    out = pd.DataFrame(filas)
    out["ERROR_PP"] = 100 * (out["PROYECTADO"] - out["OBSERVADO"])
    return out


def tabla_larga(res: ResultadoMarkov) -> pd.DataFrame:
    """Matriz en formato largo (ORIGEN, DESTINO, PROBABILIDAD, CONTEO) para Power BI o CSV."""
    p = res.matriz.stack(future_stack=True).rename("PROBABILIDAD")
    n = res.conteos.stack(future_stack=True).rename("CONTEO")
    out = pd.concat([p, n], axis=1).reset_index()
    out.columns = ["ORIGEN", "DESTINO", "PROBABILIDAD", "CONTEO"]
    out.insert(0, "ALERTA", res.alerta)
    return out
