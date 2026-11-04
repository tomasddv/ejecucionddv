# BEES Force · Tablero simplificado + cierres mensuales

Aplicación Streamlit para Distribuidora del Valle, con **filtros arriba**, navegación por una sección a la vez, indicadores de pilares y promotores y archivo único de cierre por mes. No se publican datos operativos en GitHub.

## Publicación en GitHub y Render

Para actualizar un repositorio que ya funciona con el buscador de clientes, reemplazar `app.py` y agregar `pdv_search.py`. Si todavía no agregaste `monthly_snapshot.py` de la versión simplificada, incorporarlo también. Los otros módulos (`bees_logic.py`, `drive_source.py`, `review_logic.py`, `anomaly_logic.py`, `management_store.py`, `action_plan_logic.py`) deben mantenerse. Si se usa el ZIP completo, copiar los archivos Python, `requirements.txt` y `.streamlit/config.toml` a la raíz del proyecto; no copiar `data/`, credenciales ni archivos internos de prueba.

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `streamlit run app.py --server.address 0.0.0.0 --server.port $PORT --server.headless true`
- Variables existentes: `BEES_DRIVE_FOLDER_ID`, `BEES_GESTION_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `BEES_EDITOR_PASSWORD`.
- La cuenta de servicio debe tener permiso Editor sobre la carpeta y la planilla de gestión. No pegar el JSON en GitHub ni compartirlo por chat. Si la clave fue compartida, revocarla y generar otra.

## Qué cambia

1. **Sin filtros en barra lateral.** Los filtros de canal (opcional), pilar, supervisor y promotor están arriba.
2. **Secciones simplificadas:** Resumen, Promotores, Buscar cliente / PDV, Revisiones, Anomalías, Planes de acción, Fotografías, Cierre mensual. El contenido de las secciones que no están seleccionadas no se calcula ni renderiza automáticamente.
3. **Resumen por pilar** y **resultados por promotor**, sin cuadros independientes de AS, K+T y REF. Esos canales siguen disponibles como filtro.
4. **Fotografías** visibles solo al entrar a la sección. En meses con cierre consolidado, además se requiere activar `Habilitar fotografías del cierre`.
5. **Cierre mensual único:** conserva las tareas preparadas, sus referencias a fotos, revisiones de tickets conciliadas, anomalías y sus dictámenes, objetivo del mes, textos de los planes de acción e historial de cambios del mes. Nada de eso modifica las cifras oficiales.

## Cómo congelar un cierre mensual

1. Antes de cerrar el mes, guardar los planes y clasificaciones de anomalías en la aplicación. Verificar que la bajada `planatareas.xlsx` y los reportes de tickets/anomalías disponibles estén actualizados.
2. Abrir **Cierre mensual** y marcar la confirmación.
3. Elegir **Preparar archivo de cierre**. El programa toma **la bajada completa del mes**, independientemente de los filtros superiores, y congela los dictámenes y planes disponibles en Google Sheets.
4. Descargar el archivo `BEES_FORCE_CIERRE_AAAA-MM.json.gz` y subirlo **sin cambiar el nombre** a la carpeta privada de BEES Force en Google Drive.
5. Al volver a elegir ese mes, el tablero **prioriza este único archivo** y ya no descarga los Excel históricos de tareas, tickets ni anomalías.
6. Las fotos no están almacenadas físicamente en el cierre; solo sus enlaces. Si BEES revoca los enlaces, las imágenes podrán dejar de verse. Para conservarlas de forma permanente hace falta una política de almacenamiento autorizada.

**Importante:** con la cuenta de servicio actual no es posible crear automáticamente nuevos archivos en Mi unidad por la limitación de cuota de Google Drive (403 `storageQuotaExceeded`). Por eso hay una descarga y **subida manual** del único archivo consolidado. No prometemos un cierre automático mientras persista esta restricción. Si se cambia un dictamen o un plan después del cierre, deberá generarse y subirse una nueva versión del cierre de forma explícita.

## Qué no cambia

- **% oficial** = tareas validadas / enviadas computables; las BONUS no validadas no se incluyen en el denominador oficial.
- **Cierre proyectado** incorpora únicamente tickets con falla de algoritmo cuyo ID todavía figura inválido en la bajada y ajusta el denominador cuando se recupera una BONUS.
- Las **clasificaciones manuales** de anomalías no modifican el oficial ni se suman automáticamente como recuperaciones.
- Los planes y objetivos se guardan en el registro `Eventos` de Google Sheets mientras el mes esté abierto. El consolidado copia esos eventos para visualización histórica sin requerir consultas a Sheets.

## Actualización de los datos

Subir `planatareas.xlsx`, el libro trimestral de tickets y los Excel semanales de anomalías a la carpeta privada. El botón **Actualizar Drive** invalida la caché de lectura de archivos y eventos. El tablero detecta hojas mensuales del Q4 y archivos de anomalías con nombres de mes en texto o número.

**Seguridad:** el cierre contiene datos operativos, nombres, texto de planes y enlaces a evidencias; guardarlo solo en Drive privado. El almacenamiento temporal de Render no se usa como archivo histórico.

## Buscar cliente / PDV (nuevo)

- Seleccioná el mes arriba y entrá en **Buscar cliente / PDV**. Ingresá el código exacto del cliente en el campo `POC ID` y presioná **Buscar cliente**. Si el código está incompleto, se proponen coincidencias posibles para que elijas el PDV correcto, sin mezclar códigos distintos.
- Se muestran cantidad de tareas, validadas, inválidas, justificadas, evidencia fotográfica, desglose por pilar y lista completa de tareas asignadas. Las fotos se muestran en páginas de hasta 9 miniaturas ampliables.
- Los filtros superiores de pilar, supervisor, promotor, canal y día específico también afectan la búsqueda. Si el cliente existe en el mes, pero los filtros excluyen sus tareas, aparece un aviso.
- Los códigos originales de supervisores se mantienen para los cruces; en la interfaz se muestra **Bruno Ismael (Supervisor 1)** y **Hernán Casco (Supervisor 2)**.
- En un cierre consolidado las fotografías del cliente empiezan desactivadas y se habilitan a pedido, como el resto de las fotos históricas.

## Rankings incorporados

**Promotores → Rankings oficiales**

- Dos gráficos horizontales ordenados por cantidad: tareas **validadas** e **inválidas computables** por promotor.
- Se toman exclusivamente tareas `Enviada_oficial_bool=True`, de modo que **BONUS no validadas no entran** en los rankings oficiales. Los valores de validación no incluyen el cierre proyectado.
- Tabla expandible con ranking completo y otra vista por pilar. La selección superior de pilar, supervisor, promotor, canal y día se aplica a los rankings.

**Revisiones → Rankings de tickets**

- Dos gráficos separados: tickets con dictamen **Falla de algoritmo** y tickets con dictamen **Inválida confirmada**, ordenados por promotor.
- Tabla resumida de revisiones con **Recuperables** (todavía inválidas en la bajada) y **Ya validadas** (no suman al proyectado).
- Los tickets no conciliados siguen visibles en la revisión pero no corrigen el oficial.
- Si el mes elegido no tiene todavía archivo de tickets, se muestra un aviso y el resto del tablero sigue funcionando.

### Actualización mínima

Si ya instalaste el buscador de PDV y todas las dependencias, **reemplazá únicamente `app.py` en la raíz de GitHub**. No es necesario cambiar Drive, Render ni las variables de entorno. El paquete de actualización incluye `pdv_search.py` como respaldo para evitar el error de módulo faltante; `monthly_snapshot.py` debe mantenerse en la raíz.
