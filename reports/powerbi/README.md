# Dashboard en Power BI — Monitoreo de saldo de inventarios (FCV)

Guía para armar el dashboard a partir de las tablas que genera el pipeline. Archivos de esta carpeta:

| Archivo | Para qué |
|---|---|
| `power_query.m` | Código para cargar las tablas (parámetro de ruta + una función) |
| `medidas.dax` | Todas las medidas del dashboard, listas para pegar |
| `tema_inventarios.json` | Tema de colores y tipografía (Vista → Temas → Examinar temas) |
| `Dashboard_inventarios.pbit` | Plantilla del dashboard (se guarda aquí cuando esté lista; ver sección 9) |

---

## 1. Generar los datos

```bash
uv run reto-ma2004b --validar
```

Deja en `data/processed/powerbi/`:

| Tabla | Grano | Uso en el dashboard |
|---|---|---|
| `resumen_mensual` | 1 fila por mes | Conciliación, variación, KPIs del mes. **Es la tabla de meses** |
| `partidas` | SKU × mes | Semáforo, antigüedad, riesgo P0/P1, detalle por producto |
| `alertas` | 1 fila por alerta | Página de alertas (tipo, nivel, código, valor) |
| `transiciones` | SKU × mes → mes siguiente | Matriz de transición (vista previa de Markov) |
| `dim_linea`, `dim_semaforo`, `dim_rango` | catálogos | Segmentadores, orden y colores |
| `validacion` | mes × columna | Página de validación contra Excel |

## 2. Cargar los datos

Sigue las instrucciones al inicio de `power_query.m`. En resumen: crea el parámetro `RutaDatos` con la carpeta (terminando en `\`), pega la función `fnLeerCsv` y luego una consulta por tabla. Así, en otra computadora solo se cambia el parámetro.

## 3. Modelo

**Relaciones** (Vista de modelo; todas de uno a varios, dirección de filtro simple):

| Desde (1) | Hacia (varios) |
|---|---|
| `resumen_mensual[MES]` | `partidas[MES]` |
| `resumen_mensual[MES]` | `alertas[MES]` |
| `resumen_mensual[MES]` | `transiciones[MES]` |
| `dim_linea[LINEA]` | `partidas[LINEA]` |
| `dim_rango[RANGO_ANTIG]` | `partidas[RANGO_ANTIG]` |
| `dim_semaforo[SEMAFORO]` | `partidas[SEMAFORO_DIAS]` |

`Moneda` y `Politica Semaforo` (sección 4) quedan **sin relación**: solo las leen las medidas.

**Ordenar por columna** (seleccionar la columna → Herramientas de columnas → Ordenar por columna):

- `resumen_mensual[MES_ETIQUETA]` por `MES_ORDEN`
- `dim_semaforo[SEMAFORO]` por `ORDEN`
- `dim_rango[RANGO_ANTIG]` por `RANGO_ORDEN`
- `partidas[RANGO_ANTIG]` por `RANGO_ORDEN`
- `transiciones[RANGO_ANTIG]` por `RANGO_ORDEN` y `transiciones[RANGO_SIGUIENTE]` por `RANGO_SIGUIENTE_ORDEN`
- `alertas[NIVEL]` por `NIVEL_ORDEN`

**Ocultar** en la vista de informe las columnas técnicas (`*_ORDEN`, `COLOR_HEX`, `MES_ORDEN`) para que no estorben.

## 4. Medidas

1. Inicio → Especificar datos → tabla vacía llamada `Medidas` → Cargar.
2. Modelado → Nueva tabla → pega `Moneda` y luego `Politica Semaforo` (bloque 0 de `medidas.dax`).
3. Medidas, forma rápida: Vista de consultas DAX (4.º icono de la izquierda) → pega todo `medidas_consulta.dax` → **Actualizar el modelo con cambios** (crea las 44 de golpe) → Ejecutar para ver la tabla de prueba por mes. Forma manual: clic derecho en `Medidas` → Nueva medida → pega una de `medidas.dax`.
4. Formato sugerido: montos `#,0` con unidades en millones en las tarjetas; porcentajes `0.00%`.

**Por qué las tarjetas usan "el último mes"**: el inventario es un saldo. Si alguien selecciona enero a julio, sumar siete saldos no significa nada; las medidas toman el último mes de la selección. En gráficas por mes, cada punto usa su propio mes.

## 5. Tema

Vista → Temas → Examinar temas → `tema_inventarios.json`. Las series usan una paleta probada para daltonismo; verde, ámbar y rojo se reservan para el semáforo y siempre van con su etiqueta escrita (nunca solo color).

## 6. Páginas

Segmentadores en una sola fila arriba de cada página. Para que el mes elegido se mantenga al cambiar de página: Vista → Sincronizar segmentaciones.

### Página 1 · Resumen ejecutivo

```
┌ Mes ▾ ─ Moneda (CLP/MXN) ─────────────────── [Titulo Periodo] ┐
│ Saldo GL │ % Discrepancia │ Estado conciliación │ SKUs únicos  │
│ Partidas > 1 año (y valor) │ Riesgo alto (y valor) │ Alertas alto │
│ Línea: Saldo GL por mes          │ Barras: valor por semáforo    │
│ (marcador rojo si |var| ≥ 5 %)   │ (VERDE / ÁMBAR / ROJO)        │
└──────────────────────────────────────────────────────────────┘
```

- Tarjetas: `Saldo GL`, `% Discrepancia`, `Estado Conciliacion` (color de fondo con formato condicional → valor del campo → `Color Conciliacion`), `SKUs Unicos`, `Partidas Mas 1 Anio`, `Valor Mas 1 Anio`, `Partidas Riesgo Alto`, `Alertas Nivel Alto`.
- Línea: eje `resumen_mensual[MES_ETIQUETA]`, valor `Saldo GL`, información sobre herramientas `Variacion Mensual %`.
- Barras: eje `dim_semaforo[SEMAFORO]`, valor `Valor Inventario`; colores: formato condicional por valor de campo con `COLOR_HEX` (o asignando cada color a mano).

Estos son los **KPI que pidió FEMSA**: saldo total, % de discrepancia Kardex vs GL y artículos con más de un año.

### Página 2 · Conciliación y variación (alertas 1 y 2)

- Tabla por mes: `MES_ETIQUETA`, `Saldo GL`, `Total Kardex`, `Monto Recetario`, `Diferencia Kardex vs GL`, `Diferencia No Explicada`, `% Discrepancia`, `Estado Conciliacion`.
- Columnas: `Variacion Mensual %` por mes, con líneas de referencia en +5 % y −5 % (panel Análisis → Línea constante) y color de barra por `Color Variacion`.
- Texto fijo que explique la lectura: el recetario no tiene integración (FEMSA); lo que importa es la **diferencia no explicada**.

### Página 3 · Antigüedad y semáforo (alerta 3)

- Segmentadores: Mes, `dim_rango[RANGO_ANTIG]`, `dim_semaforo[SEMAFORO]`, `dim_linea[NOMBRE_LINEA]`, `partidas[POLITICA_CANJE]`, `Politica Semaforo[Politica]`.
- Barras apiladas: valor por `RANGO_ANTIG` y `POLITICA_CANJE`.
- Matriz: filas `NOMBRE_LINEA`, columnas `SEMAFORO_DIAS`, valores `Total Partidas` y `Valor Inventario`.
- Columnas agrupadas "Comparación de políticas": `Rojo Politica Dias` vs `Rojo Politica Meses` por mes (muestra que la política en días marca más partidas).
- Tabla Top 20 riesgo alto: `CODIGO`, `DESCRIPTOR`, `NOMBRE_LINEA`, `DIAS_ANTIG`, `Valor Inventario`, filtrada a `RIESGO_POLITICA = RIESGO ALTO` (filtro de nivel visual → N superior 20 por valor).

Filtros que pide el reto: **mes, rango de antigüedad y color de semáforo**.

### Página 4 · Alertas

- Segmentadores: Mes, `alertas[TIPO_ALERTA]`, `alertas[NIVEL]`.
- Tarjetas: `Alertas`, `Alertas Nivel Alto`, `Alertas Nivel Medio`.
- Barras: alertas por tipo y nivel.
- Tabla: `TIPO_ALERTA`, `NIVEL`, `CODIGO`, `DETALLE`, `VALOR_CLP`, con iconos por `NIVEL` (formato condicional → iconos).

### Página 5 · Calidad de datos y validación

- Tarjeta `% Coincidencia con Excel` y matriz `validacion` (filas `COLUMNA`, columnas `MES`, valor `PCT_COINCIDENCIA`).
- Tarjetas `Partidas Fecha Sospechosa` y `Valor Fecha Sospechosa`; tabla de partidas con `FULCOM_SOSPECHOSA = 1`, conversión distinta de 1 o fecha posterior al cierre.
- Texto: en junio 2026 hay 591 SKU cuya fecha de compra retrocede un año exacto (posible error de captura, ~1,000 millones CLP); en julio 308 la conservan (~482 millones).

### Página 6 · Transiciones (vista previa del modelo de Markov)

- Matriz: filas `transiciones[RANGO_ANTIG]`, columnas `transiciones[RANGO_SIGUIENTE]`, valor `Probabilidad Transicion` con escala de color (un solo tono, de claro a oscuro).
- Lectura: de los SKU que hoy están en un rango, qué % estará en cada rango el mes siguiente. Es la entrada del modelo de la siguiente entrega.

## 7. Alertas automáticas

El kickoff pide notificaciones. En Power BI Service (publicando el informe), sobre las tarjetas de `Diferencia No Explicada`, `Variacion Mensual %` y `Partidas Riesgo Alto`: menú `...` → Administrar alertas → umbral. Opcionalmente, un flujo de Power Automate puede enviar correo cuando se dispara la alerta.

## 8. Agregar un mes nuevo

```bash
# copiar el Kardex y la balanza del mes a data/raw/ y luego:
uv run reto-ma2004b --incremental --meses 202608
```

Después, en Power BI: Inicio → Actualizar. Si el Kardex nuevo no trae la tabla TD DETA, el recetario se toma de otro archivo; si ningún archivo lo tiene, se puede dar en un CSV (`--recetario recetario.csv` con columnas `MES,RECETARIO`).

## 9. Guardar el dashboard en el repo

El `.pbix` guarda los datos adentro, así que **no se sube a Git** (está en `.gitignore`). Se sube la **plantilla** sin datos: Archivo → Exportar → Plantilla de Power BI → `reports/powerbi/Dashboard_inventarios.pbit`. Quien la abra solo indica la ruta de `RutaDatos` y se cargan sus datos locales.
