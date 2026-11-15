"""
Pipeline de monitoreo de saldo de inventarios.

Toma los Excel de Kardex y balanza (uno o varios meses), construye todas las alertas y
deja tablas listas para Power BI.

Uso (desde la raíz del repo):
    uv run reto-ma2004b                                   # todos los meses de data/raw
    uv run reto-ma2004b --meses 202601 202602             # solo esos meses
    uv run reto-ma2004b --entrada carpeta1 archivo.xlsx   # varias entradas
    uv run reto-ma2004b --incremental --meses 202608      # agrega un mes nuevo a lo ya procesado
    uv run reto-ma2004b --validar --excel                 # además valida contra Excel y exporta .xlsx

Salidas (data/processed/powerbi/ por defecto):
    partidas.csv         una fila por SKU y mes con todas las columnas de alerta
    resumen_mensual.csv  una fila por mes: conciliación, variación, KPIs, conteos
    alertas.csv          todas las alertas en formato largo (tipo, nivel, código, detalle)
    transiciones.csv     cambio de rango de antigüedad de cada SKU entre meses (Markov)
    dim_*.csv            líneas, semáforo y rangos (orden y colores)
    validacion.csv       coincidencia contra los valores de Excel (con --validar)
    ejecucion.json       qué archivos se procesaron, cuándo y con qué parámetros
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import carga, indicadores, reglas, validacion

COLUMNAS_PARTIDAS = [
    "MES", "MES_ORDEN", "CODIGO", "DESCRIPTOR", "LINEA", "NOMBRE_LINEA", "POLITICA_CANJE",
    "STOCK", "COSTO", "VALORIZACION", "VALORIZACION_MXN", "UNID_CONV",
    "FULCOM", "DIAS_ANTIG", "MESES_ANTIG", "RANGO_ANTIG", "RANGO_ORDEN", "MAS_1_ANIO",
    "SEMAFORO_MESES", "SEMAFORO_DIAS", "RIESGO_POLITICA",
    "DIF_VALORIZACION", "ALERTA_STOCK", "ALERTA_COSTO", "ALERTA_CONVERSION", "ALERTA_DUPLICADO",
    "ESTADO_GENERAL", "FULCOM_FUTURA", "NATURALEZA_CONTRARIA",
]  # FULCOM_RETROCEDE se agrega después, porque necesita comparar meses


def raiz_del_repo() -> Path:
    for carpeta in [Path.cwd(), *Path.cwd().parents]:
        if (carpeta / "pyproject.toml").exists():
            return carpeta
    return Path.cwd()


def _md5(path: Path) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()[:12]


def procesar_mes(path_kardex: Path, path_balanza: Path, recetario: float | None, tc: float | None,
                 politica_estado: str = "meses") -> tuple[pd.DataFrame, dict]:
    """Un mes completo: limpieza, reglas por partida e indicadores del mes."""
    detalle = reglas.construir_columnas(carga.leer_kardex(path_kardex), politica_estado)
    saldo = carga.saldo_cuenta(carga.leer_balanza(path_balanza))
    resumen = indicadores.resumen_mes(detalle, saldo, recetario, tc)
    detalle["MES"] = detalle["PERIODO"]
    detalle["MES_ORDEN"] = resumen["MES_ORDEN"]
    detalle["VALORIZACION_MXN"] = detalle["VALORIZACION"] * (tc if tc is not None else float("nan"))
    return detalle, resumen


def ejecutar(entradas: list[Path], salida: Path, meses: list[str] | None = None,
             politica_estado: str = "meses", incremental: bool = False,
             validar: bool = False, excel: bool = False, recetario_csv: Path | None = None) -> dict:
    inicio = time.time()
    archivos = carga.ubicar_archivos(entradas)
    disponibles = archivos["meses"]
    if not disponibles:
        raise SystemExit("No se encontraron Kardex ni balanzas en las entradas.")
    meses = meses or list(disponibles)
    faltan = [m for m in meses if m not in disponibles]
    if faltan:
        raise SystemExit(f"No hay Kardex/balanza para: {faltan}")

    todos = [d["kardex"] for d in disponibles.values()] + archivos["otros"]
    recetarios = carga.leer_recetarios(todos, recetario_csv)
    tipo_cambio = carga.leer_tipo_cambio(archivos["tipo_cambio"])

    partidas, resumenes, validaciones = [], [], []
    for mes in meses:
        rutas = disponibles[mes]
        detalle, resumen = procesar_mes(rutas["kardex"], rutas["balanza"],
                                        recetarios.get(mes), tipo_cambio.get(mes), politica_estado)
        partidas.append(detalle)
        resumenes.append(resumen)
        if validar:
            validaciones.append(validacion.validar_contra_excel(detalle, rutas["kardex"]))
        print(f"{mes}: {resumen['PARTIDAS']:>6,} partidas | GL {resumen['SALDO_GL']:>18,.0f} | "
              f"dif. no explicada {resumen['DIF_NO_EXPLICADA']:>8,.2f} | {resumen['ESTADO_CONCILIACION']:<10} | "
              f"rojo (días) {resumen['PARTIDAS_ROJO_DIAS']:>5,} | riesgo alto {resumen['PARTIDAS_RIESGO_ALTO']:>5,}")

    partidas = pd.concat(partidas, ignore_index=True)[COLUMNAS_PARTIDAS]
    resumen = pd.DataFrame(resumenes)

    salida.mkdir(parents=True, exist_ok=True)
    if incremental and (salida / "partidas.csv").exists():
        previas = pd.read_csv(salida / "partidas.csv", parse_dates=["MES", "FULCOM"])
        previo_res = pd.read_csv(salida / "resumen_mensual.csv", parse_dates=["MES"])
        procesados = set(partidas["MES_ORDEN"])
        previas = previas.drop(columns=["FULCOM_RETROCEDE", "FULCOM_SOSPECHOSA"], errors="ignore")
        partidas = pd.concat([previas[~previas["MES_ORDEN"].isin(procesados)], partidas], ignore_index=True)
        resumen = pd.concat([previo_res[~previo_res["MES_ORDEN"].isin(procesados)][list(resumen.columns)], resumen],
                            ignore_index=True)

    partidas = partidas.sort_values(["MES", "CODIGO"]).reset_index(drop=True)
    # Reglas que necesitan ver varios meses a la vez
    partidas["FULCOM_RETROCEDE"] = indicadores.marcar_fulcom_retrocede(partidas)
    partidas["FULCOM_SOSPECHOSA"] = indicadores.marcar_fulcom_sospechosa(partidas, partidas["FULCOM_RETROCEDE"])
    for col in ["FULCOM_RETROCEDE", "FULCOM_SOSPECHOSA"]:
        conteo = partidas.groupby("MES_ORDEN")[col].sum()
        resumen[f"PARTIDAS_{col}"] = resumen["MES_ORDEN"].map(conteo).fillna(0).astype(int)
    valor = partidas[partidas["FULCOM_SOSPECHOSA"] == 1].groupby("MES_ORDEN")["VALORIZACION"].sum()
    resumen["VALOR_FULCOM_SOSPECHOSA"] = resumen["MES_ORDEN"].map(valor).fillna(0.0)
    resumen = indicadores.variacion_mensual(resumen)
    alertas = indicadores.tabla_alertas(partidas, resumen)
    trans = indicadores.transiciones(partidas)
    dims = indicadores.dimensiones(partidas)

    tablas = {"partidas": partidas, "resumen_mensual": resumen, "alertas": alertas,
              "transiciones": trans, **dims}
    if validaciones:
        tablas["validacion"] = pd.concat(validaciones, ignore_index=True)

    for nombre, tabla in tablas.items():
        tabla.to_csv(salida / f"{nombre}.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    if excel:
        with pd.ExcelWriter(salida / "inventarios_powerbi.xlsx") as xw:
            for nombre, tabla in tablas.items():
                tabla.to_excel(xw, sheet_name=nombre[:31], index=False)

    registro = {
        "fecha_ejecucion": datetime.now().isoformat(timespec="seconds"),
        "meses_procesados": meses,
        "meses_en_salida": sorted(partidas["MES_ORDEN"].unique().tolist()),
        "politica_estado_general": politica_estado,
        "incremental": incremental,
        "entradas": {m: {"kardex": d["kardex"].name, "kardex_md5": _md5(d["kardex"]),
                         "balanza": d["balanza"].name, "balanza_md5": _md5(d["balanza"])}
                     for m, d in disponibles.items() if m in meses},
        "recetario": {m: recetarios.get(m) for m in meses},
        "tipo_cambio": {m: tipo_cambio.get(m) for m in meses},
        "filas": {n: int(len(t)) for n, t in tablas.items()},
        "segundos": round(time.time() - inicio, 1),
    }
    (salida / "ejecucion.json").write_text(json.dumps(registro, indent=2, ensure_ascii=False), encoding="utf-8")

    sin_receta = [m for m in meses if m not in recetarios]
    if sin_receta:
        print(f"AVISO: sin recetario para {sin_receta}; la conciliación de esos meses saldrá en ROJO.")
    if validaciones:
        v = tablas["validacion"]
        print(f"\nValidación contra Excel: {v['COINCIDEN'].sum():,} de {v['PARTIDAS'].sum():,} celdas coinciden "
              f"({v['COINCIDEN'].sum() / v['PARTIDAS'].sum():.4%}); {v['NA_EN_EXCEL'].sum()} con #N/A en Excel; "
              f"{v['DIFIEREN'].sum()} diferencias.")
    print(f"\nTablas en {salida}: " + ", ".join(f"{n} ({len(t):,})" for n, t in tablas.items()))
    print(f"Listo en {registro['segundos']} s.")
    return tablas


def main(argv: list[str] | None = None) -> None:
    raiz = raiz_del_repo()
    p = argparse.ArgumentParser(prog="reto-ma2004b", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--entrada", nargs="+", type=Path, default=[raiz / "data" / "raw"],
                   help="Carpetas y/o archivos .xlsx (Kardex, balanzas, Consulta_TC, propuesta)")
    p.add_argument("--salida", type=Path, default=raiz / "data" / "processed" / "powerbi")
    p.add_argument("--meses", nargs="+", help="Periodos AAAAMM a procesar (por defecto, todos)")
    p.add_argument("--politica", choices=["meses", "dias"], default="meses",
                   help="Semáforo que usa ESTADO GENERAL: 'meses' replica el Excel; 'dias' usa la hoja de criterios")
    p.add_argument("--incremental", action="store_true",
                   help="Conserva los meses ya procesados en --salida y agrega/reemplaza los indicados")
    p.add_argument("--validar", action="store_true", help="Compara contra los valores calculados por Excel")
    p.add_argument("--excel", action="store_true", help="Además guarda un .xlsx con todas las tablas")
    p.add_argument("--recetario", type=Path, help="CSV opcional MES,RECETARIO para meses sin TD DETA")
    a = p.parse_args(argv)
    ejecutar(a.entrada, a.salida, a.meses, a.politica, a.incremental, a.validar, a.excel, a.recetario)


if __name__ == "__main__":
    main()
