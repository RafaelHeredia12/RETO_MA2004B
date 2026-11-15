"""
Reto MA2004B — Monitoreo de saldo de inventarios (FEMSA Salud Chile, FCV).

Módulos:
    config       parámetros de negocio (cuenta, tolerancias, políticas de semáforo)
    carga        lectura y limpieza de Kardex, balanza, recetario y tipo de cambio
    reglas       alertas por partida (réplica de las fórmulas de Excel + política en días)
    indicadores  conciliación, variación, KPIs, tabla de alertas y transiciones
    validacion   comparación contra los valores calculados por Excel
    pipeline     script ejecutable: `uv run reto-ma2004b --help`
"""


def main() -> None:
    from .pipeline import main as _main
    _main()
