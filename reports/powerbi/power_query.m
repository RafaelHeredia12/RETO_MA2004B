// =====================================================================
//  Power Query (lenguaje M) para cargar las tablas del pipeline
//  Reto MA2004B · Monitoreo de saldo de inventarios (FEMSA Salud, FCV)
//
//  Cómo usarlo (Power BI Desktop → Inicio → Transformar datos):
//   1. Inicio → Administrar parámetros → Nuevo parámetro
//        Nombre: RutaDatos   Tipo: Texto
//        Valor:  C:\RETO_MA2004B\data\processed\powerbi\      (con "\" al final)
//   2. Inicio → Nuevo origen → Consulta en blanco → Editor avanzado.
//      Pega el bloque "fnLeerCsv" y renombra la consulta a fnLeerCsv.
//   3. Repite (consulta en blanco → editor avanzado) con cada tabla de abajo,
//      pegando solo su bloque y dándole el nombre indicado.
//   4. Cerrar y aplicar.
//
//  Si cambias de computadora, solo cambia el valor de RutaDatos.
//  Los números vienen con punto decimal; la función los lee con cultura en-US
//  para que no importe la configuración regional de Windows.
// =====================================================================


// ---------- Consulta: fnLeerCsv ----------
(archivo as text, columnasTexto as list, columnasFecha as list) as table =>
let
    Origen = Csv.Document(
        File.Contents(RutaDatos & archivo),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Tabla = Table.PromoteHeaders(Origen, [PromoteAllScalars = true]),
    Numericas = List.Difference(Table.ColumnNames(Tabla), columnasTexto & columnasFecha),
    Tipos =
        List.Transform(columnasTexto, each {_, type text})
        & List.Transform(columnasFecha, each {_, type date})
        & List.Transform(Numericas, each {_, type number}),
    ConTipos = Table.TransformColumnTypes(Tabla, Tipos, "en-US")
in
    ConTipos


// ---------- Consulta: partidas ----------
let
    Fuente = fnLeerCsv(
        "partidas.csv",
        {"CODIGO", "DESCRIPTOR", "NOMBRE_LINEA", "POLITICA_CANJE", "RANGO_ANTIG",
         "SEMAFORO_MESES", "SEMAFORO_DIAS", "RIESGO_POLITICA", "ALERTA_STOCK", "ALERTA_COSTO",
         "ALERTA_CONVERSION", "ALERTA_DUPLICADO", "ESTADO_GENERAL"},
        {"MES", "FULCOM"}
    )
in
    Fuente


// ---------- Consulta: resumen_mensual ----------
let
    Fuente = fnLeerCsv(
        "resumen_mensual.csv",
        {"MES_ETIQUETA", "ESTADO_CONCILIACION", "SEMAFORO_CONCILIACION", "ALERTA_VARIACION"},
        {"MES"}
    )
in
    Fuente


// ---------- Consulta: alertas ----------
let
    Fuente = fnLeerCsv("alertas.csv", {"TIPO_ALERTA", "NIVEL", "CODIGO", "DETALLE"}, {"MES"})
in
    Fuente


// ---------- Consulta: transiciones ----------
let
    Fuente = fnLeerCsv(
        "transiciones.csv",
        {"CODIGO", "RANGO_ANTIG", "POLITICA_CANJE", "NOMBRE_LINEA", "RANGO_SIGUIENTE"},
        {"MES", "MES_SIGUIENTE"}
    )
in
    Fuente


// ---------- Consulta: dim_linea ----------
let
    Fuente = fnLeerCsv("dim_linea.csv", {"NOMBRE_LINEA"}, {})
in
    Fuente


// ---------- Consulta: dim_semaforo ----------
let
    Fuente = fnLeerCsv("dim_semaforo.csv", {"SEMAFORO", "COLOR_HEX"}, {})
in
    Fuente


// ---------- Consulta: dim_rango ----------
let
    Fuente = fnLeerCsv("dim_rango.csv", {"RANGO_ANTIG"}, {})
in
    Fuente


// ---------- Consulta: validacion (solo si corriste el pipeline con --validar) ----------
let
    Fuente = fnLeerCsv("validacion.csv", {"MES", "COLUMNA"}, {})
in
    Fuente
