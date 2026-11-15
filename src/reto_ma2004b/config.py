"""
Parámetros del monitoreo de saldo de inventarios (FEMSA Salud Chile, FCV).

Todo lo que es una decisión de negocio vive aquí, para cambiarlo en un solo
lugar cuando FEMSA confirme una política distinta.
"""

# Cuenta contable de existencias (111080001 en el planteamiento, anonimizada en la balanza)
CUENTA_EXISTENCIAS = "CTA_000184"

# Conciliación Kardex + recetario vs. GL
TOLERANCIA_PCT_GL = 0.001       # 0.1 % del saldo GL: tolerancia del dashboard de la propuesta
TOLERANCIA_REDONDEO_CLP = 1_000  # por debajo de esto la diferencia se considera redondeo

# Variación mensual del saldo (regla de negocio del reto)
UMBRAL_VARIACION = 0.05

# Semáforo "meses": replica las fórmulas del Kardex (columna J)
#   VERDE <= 6 meses, ÁMBAR 7 a 12, ROJO > 12
LIMITE_AMBAR_MESES = 6
LIMITE_ROJO_MESES = 12

# Semáforo "días": hoja "criterio de alertas" de la propuesta (presentada como la regla)
#   VERDE 0 a 90 días, ÁMBAR 91 a 180, ROJO > 180
LIMITE_AMBAR_DIAS = 90
LIMITE_ROJO_DIAS = 180

# Riesgo según política de canje (hoja "criterio de alertas", filas 5 a 8)
RIESGO_POR_POLITICA = {
    ("VERDE", "P1"): "NORMAL",
    ("VERDE", "P0"): "NORMAL",
    ("ÁMBAR", "P1"): "REVISIÓN",
    ("ÁMBAR", "P0"): "REVISIÓN",
    ("ROJO", "P1"): "REVISIÓN",
    ("ROJO", "P0"): "RIESGO ALTO",
}

# Rangos de antigüedad para filtros del dashboard y estados del modelo de Markov
RANGOS_DIAS = [
    (0, 30, "0-30 días"),
    (31, 90, "31-90 días"),
    (91, 180, "91-180 días"),
    (181, 365, "181-365 días"),
    (366, None, "Más de 365 días"),
]

# Orden y colores (los usa Power BI para ordenar y dar formato condicional)
SEMAFORO_ORDEN = {"VERDE": 1, "ÁMBAR": 2, "ROJO": 3, "SIN FECHA": 4}
SEMAFORO_COLOR = {"VERDE": "#0CA30C", "ÁMBAR": "#FAB219", "ROJO": "#D03B3B", "SIN FECHA": "#8A8A85"}

MESES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
