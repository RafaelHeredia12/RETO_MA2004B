"""
Construye las columnas de alertas de inventario para uno o varios meses.

Uso (desde la raíz del repo):
    uv run python src/construir_columnas.py                 # todos los meses en data/raw
    uv run python src/construir_columnas.py --mes 202601    # solo enero
    uv run python src/construir_columnas.py --mes 202601 --mes 202602

Salidas en data/processed/:
    kardex_alertas.csv   detalle por SKU y mes con todas las columnas calculadas
    resumen_mensual.csv  una fila por mes: conciliación, semáforo, variación, etc.
"""

import argparse
import re
from pathlib import Path

import pandas as pd

import alertas_inventario as ai

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"


def ubicar_archivos(raw: Path) -> dict[str, tuple[Path, Path]]:
    """Empareja Kardex y Balanza por periodo AAAAMM."""
    kardex = {ai.periodo_de_archivo(p): p for p in raw.glob("*Kardex_*.xlsx")}
    balanzas = {ai.periodo_de_archivo(p): p for p in raw.glob("*.xlsx")
                if re.search(r"B(a|la)lanza", p.name, re.I)}
    faltan = set(kardex) ^ set(balanzas)
    if faltan:
        raise FileNotFoundError(f"Periodos sin pareja Kardex/Balanza: {sorted(faltan)}")
    return {mes: (kardex[mes], balanzas[mes]) for mes in sorted(kardex)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mes", action="append", help="Periodo AAAAMM (se puede repetir)")
    args = parser.parse_args()

    archivos = ubicar_archivos(RAW)
    if not archivos:
        raise SystemExit("No hay archivos en data/raw. Correr dvc pull y ./scripts/dvc_decrypt.sh")
    meses = args.mes or list(archivos)

    detalles, resumenes = [], []
    for mes in meses:
        if mes not in archivos:
            raise SystemExit(f"No hay Kardex/Balanza para {mes}")
        detalle, resumen = ai.procesar_mes(*archivos[mes])
        detalles.append(detalle)
        resumenes.append(resumen)
        print(f"{mes}: {len(detalle):,} partidas | GL {resumen['SALDO_GL']:,.0f} | "
              f"diferencia {resumen['DIFERENCIA']:,.2f} | {resumen['ESTADO_CONCILIACION']} | "
              f"REVISAR {resumen['PARTIDAS_REVISAR']:,}")

    resumen = ai.variacion_mensual(pd.DataFrame(resumenes))

    PROCESSED.mkdir(parents=True, exist_ok=True)
    pd.concat(detalles, ignore_index=True).to_csv(PROCESSED / "kardex_alertas.csv", index=False, encoding="utf-8-sig")
    resumen.to_csv(PROCESSED / "resumen_mensual.csv", index=False, encoding="utf-8-sig")
    print(f"\nGuardado en {PROCESSED.relative_to(ROOT)}: kardex_alertas.csv, resumen_mensual.csv")


if __name__ == "__main__":
    main()
