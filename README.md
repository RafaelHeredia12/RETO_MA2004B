# RETO_MA2004B · Monitoreo de saldo de inventarios (FEMSA Salud Chile, FCV)

Automatización de la auditoría mensual del inventario: conciliación del Kardex contra la cuenta de existencias (`CTA_000184`), variación mensual del saldo, antigüedad con semáforo y riesgo por política de canje, calidad de datos y tablas para Power BI. Siguiente etapa: cadenas de Markov sobre los rangos de antigüedad.

## Estructura

```
data/raw/            Excel originales (en Git solo los punteros .age.dvc)
data/processed/      tablas generadas (encriptadas con age, versionadas con DVC)
  powerbi/           salida del pipeline para el dashboard
notebooks/
  01_limpieza_datos.ipynb       exploración y calidad de los datos
  02_replica_propuesta.ipynb    un mes paso a paso, todos los meses y validación contra Excel
src/reto_ma2004b/    paquete de Python (config, carga, reglas, indicadores, validacion, pipeline)
tests/               pruebas de las reglas (uv run pytest)
reports/
  avance1/           primer reporte (LaTeX)
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
