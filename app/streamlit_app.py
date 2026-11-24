"""
Cadenas de Markov sobre las alertas de inventario (FCV).

Correr desde la raíz del repo:
    uv run streamlit run app/streamlit_app.py

Lee la tabla `partidas.csv` que genera el pipeline (data/processed/powerbi/) o una que se
cargue desde la barra lateral, y construye la matriz de transición de la alerta elegida
para todo el inventario, un segmento o un SKU.
"""

from __future__ import annotations

import io

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from reto_ma2004b import markov as M
from reto_ma2004b.indicadores import etiqueta_mes
from reto_ma2004b.pipeline import raiz_del_repo

st.set_page_config(page_title="Markov · Alertas de inventario FCV", layout="wide")

RUTA_DEFECTO = raiz_del_repo() / "data" / "processed" / "powerbi" / "partidas.csv"
COLOR_ESTADO = {
    "VERDE": "#0CA30C", "OK": "#0CA30C", "NORMAL": "#0CA30C", "0-30 días": "#0CA30C",
    "ÁMBAR": "#FAB219", "MONITOREAR": "#FAB219", "REVISIÓN": "#FAB219", "31-90 días": "#C9D96B",
    "91-180 días": "#FAB219", "181-365 días": "#EB6834",
    "ROJO": "#D03B3B", "REVISAR": "#D03B3B", "RIESGO ALTO": "#D03B3B", "Más de 365 días": "#D03B3B",
    "INVÁLIDA": "#8A8A85", "SIN FECHA": "#8A8A85", M.SIN_INVENTARIO: "#C8C8C4",
}


# ----------------------------------------------------------------------------- datos

@st.cache_data(show_spinner="Leyendo partidas…")
def cargar(origen) -> pd.DataFrame:
    if isinstance(origen, bytes):
        origen = io.BytesIO(origen)
    p = pd.read_csv(origen, parse_dates=["MES", "FULCOM"])
    faltan = {"CODIGO", "MES", "VALORIZACION"} - set(p.columns)
    if faltan:
        raise ValueError(f"El archivo no tiene las columnas {sorted(faltan)}")
    return p


@st.cache_data(show_spinner="Estimando la matriz…")
def estimar(_p, clave, alerta, codigo, filtros, incluir_ausencia, excluir_sospechosas, ponderar, alfa):
    return M.estimar(_p, alerta, codigo=codigo, filtros=filtros, incluir_ausencia=incluir_ausencia,
                     excluir_sospechosas=excluir_sospechosas, ponderar=ponderar, alfa=alfa)


@st.cache_data(show_spinner="Calculando la lista de riesgo…")
def riesgo(_p, clave, alerta, pasos, alfa, excluir_sospechosas):
    return M.riesgo_por_sku(_p, alerta, pasos=pasos, alfa=alfa, excluir_sospechosas=excluir_sospechosas)


@st.cache_data(show_spinner="Revisando el modelo…")
def validacion(_p, clave, alerta, excluir_sospechosas):
    meses = sorted(_p["MES"].unique())
    corte = meses[max(len(meses) - 4, 1)]
    return (M.prueba_homogeneidad(_p, alerta, excluir_sospechosas=excluir_sospechosas),
            M.matrices_por_mes(_p, alerta, excluir_sospechosas=excluir_sospechosas),
            M.backtest(_p, alerta, corte, excluir_sospechosas), corte)


def heatmap(p: pd.DataFrame, titulo: str, formato: str = ".1%") -> alt.Chart:
    larga = p.reset_index().melt(id_vars=p.index.name or "index", var_name="DESTINO", value_name="P")
    larga.columns = ["ORIGEN", "DESTINO", "P"]
    orden = list(p.index)
    base = alt.Chart(larga).encode(
        x=alt.X("DESTINO:N", sort=orden, title="Mes siguiente", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("ORIGEN:N", sort=orden, title="Mes actual"),
    )
    celdas = base.mark_rect(stroke="white", strokeWidth=2).encode(
        color=alt.Color("P:Q", scale=alt.Scale(scheme="blues", domain=[0, 1]), title="Probabilidad"),
        tooltip=[alt.Tooltip("ORIGEN:N", title="De"), alt.Tooltip("DESTINO:N", title="A"),
                 alt.Tooltip("P:Q", title="Probabilidad", format=formato)],
    )
    texto = base.mark_text(fontSize=13).encode(
        text=alt.Text("P:Q", format=formato),
        color=alt.condition(alt.datum.P > 0.55, alt.value("white"), alt.value("#222")),
    )
    return (celdas + texto).properties(title=titulo, height=60 * len(orden) + 40)


def colorear(valor):
    c = COLOR_ESTADO.get(valor)
    return f"background-color: {c}; color: white; font-weight: 600" if c and valor != M.SIN_INVENTARIO else ""


def si_no(valor: bool) -> str:
    return "Sí" if valor else "No"


# ----------------------------------------------------------------------------- barra lateral

st.sidebar.title("Opciones")
archivo = st.sidebar.file_uploader("Tabla de partidas (CSV del pipeline)", type="csv")
if archivo is not None:
    p, clave = cargar(archivo.getvalue()), archivo.name
elif RUTA_DEFECTO.exists():
    p, clave = cargar(RUTA_DEFECTO), str(RUTA_DEFECTO)
else:
    st.info(f"No encontré `{RUTA_DEFECTO.relative_to(raiz_del_repo())}`. Corre `uv run reto-ma2004b` "
            "o carga el CSV desde la barra lateral.")
    st.stop()

alertas = [a for a in M.ALERTAS if a in p.columns]
alerta = st.sidebar.selectbox("Alerta", alertas, format_func=lambda a: M.ALERTAS[a]["titulo"])
critico = M.ESTADO_CRITICO.get(alerta)

nivel = st.sidebar.radio("Analizar", ["Todo el inventario", "Un segmento", "Un SKU"])
filtros, codigo, alfa = None, None, 0.0
if nivel == "Un segmento":
    lineas = st.sidebar.multiselect("Línea", sorted(p["NOMBRE_LINEA"].dropna().unique()))
    politicas = st.sidebar.multiselect("Política de canje", sorted(p["POLITICA_CANJE"].dropna().unique()))
    filtros = {"NOMBRE_LINEA": tuple(lineas) or None, "POLITICA_CANJE": tuple(politicas) or None}
elif nivel == "Un SKU":
    codigos = sorted(p["CODIGO"].unique())
    codigo = st.sidebar.selectbox("SKU", codigos, index=codigos.index("SKU_002583") if "SKU_002583" in codigos else 0)
    alfa = st.sidebar.slider("Suavizado hacia la matriz global (α)", 0.0, 10.0, 2.0, 0.5,
                             help="Peso de la matriz global, en número de transiciones equivalentes. "
                                  "Con α = 0 se usa solo la historia del SKU (6 transiciones como máximo).")

st.sidebar.divider()
excluir = st.sidebar.checkbox("Excluir fechas de compra sospechosas", True,
                              help="Quita las transiciones con la fecha que retrocede un año (junio 2026).")
ausencia = st.sidebar.checkbox("Incluir el estado «SIN INVENTARIO»", False,
                               help="Si el SKU no aparece en un mes, cuenta como un estado más.")
ponderar = st.sidebar.checkbox("Ponderar por valor del inventario", False,
                               help="Las probabilidades se calculan con pesos en CLP en lugar de contar SKU.")
pasos = st.sidebar.slider("Horizonte de predicción (meses)", 1, 12, 3)

filtros_clave = tuple(sorted((k, v) for k, v in (filtros or {}).items() if v))
try:
    res = estimar(p, clave, alerta, codigo, dict(filtros_clave) or None, ausencia, excluir, ponderar, alfa)
except ValueError as e:
    st.warning(str(e))
    st.stop()
prop = M.propiedades(res.matriz)

# ----------------------------------------------------------------------------- encabezado

st.title("Cadenas de Markov · Alertas de inventario")
st.caption(f"{M.ALERTAS[alerta]['titulo']} · {etiqueta_mes(p['MES'].min())} a {etiqueta_mes(p['MES'].max())} · "
           f"{p['CODIGO'].nunique():,} SKU en la tabla")

ambito = codigo if codigo else ("segmento: " + ", ".join(f"{k}={'/'.join(v)}" for k, v in filtros_clave)
                                if filtros_clave else "Global")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Ámbito", ambito)
c2.metric("Transiciones observadas", f"{res.n_transiciones:,}")
c3.metric("SKU con transiciones", f"{res.n_skus:,}")
c4.metric("Cadena", "Ergódica" if prop["ergodica"] else ("Incompleta" if not prop["completa"] else "No ergódica"))

tab_matriz, tab_prop, tab_pred, tab_riesgo, tab_valid = st.tabs(
    ["Matriz de transición", "Propiedades", "Predicción", "Lista de riesgo", "¿Funciona el modelo?"])

# ----------------------------------------------------------------------------- matriz

with tab_matriz:
    if codigo:
        st.subheader("Secuencia observada del SKU")
        sec = pd.concat({M.ALERTAS[a]["titulo"]: M.secuencias(p, a, codigo).iloc[0] for a in alertas}, axis=1)
        sec.index = [etiqueta_mes(m) for m in sec.index]
        if "FULCOM_SOSPECHOSA" in p:
            sosp = p[p["CODIGO"] == codigo].set_index("MES")["FULCOM_SOSPECHOSA"]
            sec["Fecha sospechosa"] = [("Sí" if sosp.get(m, 0) == 1 else "") for m in sorted(p["MES"].unique())]
        st.dataframe(sec.fillna("—").style.map(colorear), width="stretch")
        info = p[p["CODIGO"] == codigo].iloc[-1]
        st.caption(f"{info['DESCRIPTOR']} · {info['NOMBRE_LINEA']} · política {info['POLITICA_CANJE']}")

    izq, der = st.columns([3, 2])
    with izq:
        titulo = "Probabilidad de pasar de un estado (fila) a otro (columna) en un mes"
        if codigo and alfa > 0:
            titulo += f" · suavizada (α = {alfa:g})"
        st.altair_chart(heatmap(res.matriz.fillna(0), titulo), width="stretch")
        if res.renglones_sin_datos:
            st.warning(f"Sin transiciones que salgan de {', '.join(res.renglones_sin_datos)}: "
                       "esos renglones no se pueden estimar con estos datos (aparecen en 0). "
                       "Sube α o amplía el segmento.")
    with der:
        st.markdown("**Conteos de transiciones**" + (" (CLP)" if ponderar else ""))
        st.dataframe(res.conteos.style.format("{:,.0f}"), width="stretch")
        if codigo and alfa > 0:
            st.markdown("**Solo con la historia del SKU (α = 0)**")
            crudo = estimar(p, clave, alerta, codigo, None, ausencia, excluir, ponderar, 0.0)
            st.dataframe(crudo.matriz.map(lambda v: "sin datos" if pd.isna(v) else f"{v:.1%}"), width="stretch")
        st.download_button("Descargar matriz (CSV)", M.tabla_larga(res).to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"markov_{alerta.lower()}_{(codigo or 'global').lower()}.csv")

# ----------------------------------------------------------------------------- propiedades

with tab_prop:
    st.info(M.resumen_propiedades(prop))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Irreducible", si_no(prop["irreducible"]), help="Desde cualquier estado se puede llegar a cualquier otro.")
    c2.metric("Aperiódica", si_no(prop["aperiodica"]), help="No hay ciclos de longitud fija obligatoria.")
    c3.metric("Ergódica", si_no(prop["ergodica"]), help="Irreducible y aperiódica: tiene un equilibrio único al que converge.")
    c4.metric("Regular", si_no(prop["regular"]), help="Alguna potencia P^k tiene todas sus entradas positivas.")

    st.markdown("**Clases comunicantes**")
    st.dataframe(pd.DataFrame([{"Estados": ", ".join(c["estados"]), "Tipo": c["tipo"], "Periodo": c["periodo"]}
                               for c in prop["clases"]]), hide_index=True, width="stretch")
    if prop["absorbentes"]:
        st.write(f"Estados absorbentes (una vez ahí, no se sale): **{', '.join(prop['absorbentes'])}**")

    if prop["estacionaria"] is not None:
        izq, der = st.columns(2)
        with izq:
            est = pd.DataFrame({"Estado": prop["estacionaria"].index, "Largo plazo": prop["estacionaria"].values,
                                "Hoy": M.distribucion(p, alerta, ponderar=ponderar, filtros=dict(filtros_clave) or None)
                                .reindex(prop["estacionaria"].index).fillna(0).values})
            larga = est.melt("Estado", var_name="Momento", value_name="Proporción")
            st.altair_chart(alt.Chart(larga, title="Distribución hoy vs. equilibrio de largo plazo").mark_bar(
                cornerRadiusEnd=4).encode(
                y=alt.Y("Estado:N", sort=list(est["Estado"]), title=None),
                x=alt.X("Proporción:Q", axis=alt.Axis(format="%")),
                yOffset="Momento:N",
                color=alt.Color("Momento:N", scale=alt.Scale(range=["#8A8A85", "#2A78D6"]), sort=["Hoy", "Largo plazo"]),
                tooltip=["Estado", "Momento", alt.Tooltip("Proporción:Q", format=".1%")]),
                width="stretch")
        with der:
            tabla = pd.DataFrame({"Proporción de largo plazo": prop["estacionaria"],
                                  "Meses medios para volver": prop["tiempo_retorno"]})
            if critico in res.matriz.index:
                tabla[f"Meses medios hasta {critico}"] = M.tiempos_primer_paso(res.matriz, critico)
            st.dataframe(tabla.style.format({"Proporción de largo plazo": "{:.1%}"} |
                                            {c: "{:,.1f}" for c in tabla.columns[1:]}), width="stretch")
            st.caption("La distribución de largo plazo es a la que tiende el inventario si las probabilidades "
                       "actuales se mantienen. El tiempo medio de retorno es 1 / π.")
    elif prop["completa"]:
        st.write("La cadena tiene más de una clase cerrada, así que el equilibrio depende del estado inicial "
                 "(no hay una distribución estacionaria única).")

# ----------------------------------------------------------------------------- predicción

with tab_pred:
    pk = M.potencia(res.matriz, pasos)
    izq, der = st.columns([3, 2])
    with izq:
        if codigo:
            fila = p[(p["CODIGO"] == codigo) & (p["MES"] == p["MES"].max())]
            if fila.empty:
                st.write("Este SKU no aparece en el último mes; elige un estado inicial:")
                inicio = st.selectbox("Estado inicial", res.estados)
            else:
                inicio = fila[alerta].iloc[0]
            inicial = pd.Series({inicio: 1.0})
            st.markdown(f"Hoy el SKU está en **{inicio}**.")
        else:
            inicial = M.distribucion(p, alerta, ponderar=ponderar, filtros=dict(filtros_clave) or None,
                                     excluir_sospechosas=excluir)
            if ausencia:
                inicial = inicial.reindex(res.estados).fillna(0)
        proy = M.proyectar(res.matriz, inicial, pasos)
        larga = proy.reset_index().melt("MESES", var_name="Estado", value_name="Probabilidad")
        dominio = list(proy.columns)
        st.altair_chart(alt.Chart(larga, title=f"Distribución esperada en los próximos {pasos} meses").mark_line(
            point=alt.OverlayMarkDef(size=60), strokeWidth=2).encode(
            x=alt.X("MESES:O", title="Meses desde hoy", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Probabilidad:Q", axis=alt.Axis(format="%"), title="Proporción" if not codigo else "Probabilidad"),
            color=alt.Color("Estado:N", sort=dominio,
                            scale=alt.Scale(domain=dominio, range=[COLOR_ESTADO.get(e, "#8A8A85") for e in dominio])),
            tooltip=["MESES", "Estado", alt.Tooltip("Probabilidad:Q", format=".1%")]), width="stretch")
    with der:
        st.markdown(f"**Probabilidad de transición en {pasos} meses (P^{pasos})**")
        st.dataframe(pk.style.format("{:.1%}"), width="stretch")
        if not codigo and critico in proy.columns:
            total = p[p["MES"] == p["MES"].max()]
            if filtros_clave:
                total = M._filtrar(total, dict(filtros_clave))
            valor = total["VALORIZACION"].clip(lower=0).sum()
            hoy_c, fut_c = proy.loc[0, critico], proy.loc[pasos, critico]
            st.metric(f"En {critico} dentro de {pasos} meses", f"{fut_c:.1%}", f"{100 * (fut_c - hoy_c):+.1f} pp vs. hoy",
                      delta_color="inverse")
            if ponderar:
                st.caption(f"Equivale a unos {fut_c * valor / 1e6:,.0f} millones CLP del inventario actual "
                           f"({valor / 1e6:,.0f} millones).")

# ----------------------------------------------------------------------------- lista de riesgo

with tab_riesgo:
    if critico is None:
        st.write("Esta alerta no tiene un estado crítico definido.")
    else:
        st.markdown(f"SKU que hoy **no** están en **{critico}**, ordenados por el valor esperado que estará en "
                    f"{critico} dentro de {pasos} meses (probabilidad × valor actual). Cada SKU usa su propia "
                    "historia, suavizada hacia la matriz global.")
        alfa_r = alfa if codigo else 2.0
        r = riesgo(p, clave, alerta, pasos, alfa_r, excluir)
        if filtros_clave:
            r = M._filtrar(r, dict(filtros_clave))
        c1, c2 = st.columns(2)
        c1.metric("SKU evaluados", f"{len(r):,}")
        c2.metric(f"Valor esperado en {critico} (millones CLP)", f"{r['VALOR_ESPERADO_DESTINO'].sum() / 1e6:,.1f}")
        columnas = ["CODIGO", "NOMBRE_LINEA", "POLITICA_CANJE", "ESTADO_ACTUAL", "DIAS_ANTIG", "VALORIZACION",
                    "PROB_DESTINO", "VALOR_ESPERADO_DESTINO"]
        top = r.head(50)[columnas].rename(columns={"PROB_DESTINO": f"P({critico} en {pasos} m)",
                                         "VALOR_ESPERADO_DESTINO": "Valor esperado (CLP)"})
        st.dataframe(top.style.format({f"P({critico} en {pasos} m)": "{:.1%}", "Valor esperado (CLP)": "{:,.0f}",
                                       "VALORIZACION": "{:,.0f}"}), hide_index=True, width="stretch")
        st.download_button("Descargar lista completa (CSV)", r.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"riesgo_{alerta.lower()}_{pasos}m.csv")

# ----------------------------------------------------------------------------- validación

with tab_valid:
    homog, por_mes, bt, corte = validacion(p, clave, alerta, excluir)
    st.markdown("**¿La matriz es la misma todos los meses? (homogeneidad)**")
    st.write(f"Prueba de razón de verosimilitud: G = {homog['G']:,.1f}, gl = {homog['gl']}, "
             f"p-valor = {homog['p_valor']:.3g}. "
             + ("Se rechaza que la matriz sea constante: las probabilidades cambian de un mes a otro."
                if homog["p_valor"] < 0.05 else "No hay evidencia de que la matriz cambie entre meses."))
    diag = pd.DataFrame({f"{etiqueta_mes(m)[:3]}→{etiqueta_mes(m + pd.offsets.MonthBegin())[:3]}":
                         np.diag(q.fillna(0).to_numpy())
                         for m, q in por_mes.items()}, index=next(iter(por_mes.values())).index).T
    larga = diag.reset_index(names="Transición").melt("Transición", var_name="Estado", value_name="Permanece")
    st.altair_chart(alt.Chart(larga, title="Probabilidad de permanecer en el mismo estado, por mes").mark_line(
        point=True, strokeWidth=2).encode(
        x=alt.X("Transición:N", sort=list(diag.index), axis=alt.Axis(labelAngle=0)),
        y=alt.Y("Permanece:Q", axis=alt.Axis(format="%")),
        color=alt.Color("Estado:N", scale=alt.Scale(domain=list(diag.columns),
                                                    range=[COLOR_ESTADO.get(e, "#8A8A85") for e in diag.columns])),
        tooltip=["Transición", "Estado", alt.Tooltip("Permanece:Q", format=".1%")]), width="stretch")

    st.markdown(f"**Prueba fuera de muestra**: matriz estimada hasta {etiqueta_mes(corte)}; se proyecta la distribución de "
                "esos mismos SKU y se compara con lo observado.")
    tabla = bt.pivot_table(index="ESTADO", columns="HORIZONTE", values=["PROYECTADO", "OBSERVADO"])
    st.dataframe(tabla.style.format("{:.1%}"), width="stretch")
    st.caption(f"Error absoluto medio: {bt['ERROR_PP'].abs().mean():.2f} puntos porcentuales; "
               f"máximo: {bt['ERROR_PP'].abs().max():.2f} pp.")
