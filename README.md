# RETO_MA2004B · Monitoreo de saldo de inventarios (FEMSA Salud Chile, FCV)

Automatización de la auditoría mensual del inventario: conciliación del Kardex contra la cuenta de existencias (`CTA_000184`), variación mensual del saldo, antigüedad con semáforo y riesgo por política de canje, calidad de datos y tablas para Power BI. Cadenas de Markov sobre las alertas de cada SKU, con una app de Streamlit para consultarlas.

## Estructura

```
data/raw/            Excel originales (en Git solo los punteros .age.dvc)
data/processed/      tablas generadas (encriptadas con age, versionadas con DVC)
  powerbi/           salida del pipeline para el dashboard
notebooks/
  01_limpieza_datos.ipynb       exploración y calidad de los datos
  02_replica_propuesta.ipynb    un mes paso a paso, todos los meses y validación contra Excel
  03_cadenas_markov.ipynb       matrices de transición, propiedades, predicción y validación del modelo
src/reto_ma2004b/    paquete de Python (config, carga, reglas, indicadores, validacion, pipeline, markov)
app/                 app de Streamlit para las cadenas de Markov
tests/               pruebas de las reglas (uv run pytest)
reports/
  avance1/           primer reporte (LaTeX)
  avance3/           reporte de cadenas de Markov (LaTeX y PDF)
  powerbi/           guía, Power Query, medidas DAX y tema del dashboard
  figures/           gráficas
scripts/             encriptado y configuración de DVC
```

## Uso rápido

```bash
uv sync
dvc pull -r storage && ./scripts/dvc_decrypt.sh   # datos (requiere token de DagsHub y .age/key.txt)
uv run reto-ma2004b --validar                     # procesa todos los meses de data/raw
uv run reto-ma2004b --help                        # todas las opciones
uv run pytest                                     # pruebas
uv run streamlit run app/streamlit_app.py         # app de Markov (usa data/processed/powerbi/partidas.csv)
```

Opciones principales del pipeline:

| Opción | Qué hace |
|---|---|
| `--entrada CARPETA/ARCHIVOS` | Una o varias carpetas o archivos de Excel (por defecto `data/raw`) |
| `--meses 202601 202602` | Procesa solo esos meses |
| `--incremental` | Conserva lo ya procesado y agrega o reemplaza los meses indicados |
| `--politica dias` | Usa el semáforo en días (0–90 / 91–180 / >180) para `ESTADO_GENERAL` en lugar del de meses |
| `--validar` | Compara cada columna contra los valores que calculó Excel |
| `--excel` | Además exporta un `.xlsx` con todas las tablas |
| `--recetario archivo.csv` | Recetario manual (`MES,RECETARIO`) para meses cuyo Kardex no trae TD DETA |

Resultados de validación (enero a julio 2026): 965,706 de 965,718 celdas iguales a Excel; las 12 restantes son celdas que Excel deja en `#N/A`, que el código mantiene visibles a propósito.

## Cadenas de Markov

`src/reto_ma2004b/markov.py` estima una cadena de primer orden por alerta (semáforo en días y en meses, riesgo por política, estado general, rango de antigüedad, unidad de conversión) con las transiciones mes a mes de cada SKU.

```python
from reto_ma2004b import markov as M
r = M.estimar(partidas, "SEMAFORO_DIAS")                                  # todo el inventario
r = M.estimar(partidas, "SEMAFORO_DIAS", codigo="SKU_002583", alfa=2)     # un SKU, suavizado hacia la global
M.propiedades(r.matriz)                                                    # clases, periodo, ergodicidad, estacionaria
M.riesgo_por_sku(partidas, "SEMAFORO_DIAS", pasos=3)                       # SKU con más valor esperado en rojo
```

Por defecto se excluyen las transiciones con la fecha de compra sospechosa de junio 2026. La app (`app/streamlit_app.py`) permite elegir alerta, segmento o SKU, el suavizado y el horizonte de predicción.
