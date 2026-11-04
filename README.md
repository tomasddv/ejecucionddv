# BEES Force · Control mensual, anomalías y planes de acción

Proyecto Streamlit para Distribuidora del Valle. Incluye seguimiento de tareas, revisión de tickets, proyección de cierre, fotos, clasificación manual de anomalías y planes de acción asociados a una meta mensual.

## Archivos guardados en Drive

Carpeta privada: https://drive.google.com/drive/folders/1j6SZlNNJJzvg8f5MO6mdm5wJ4NNOuCmR

- `BEES_FORCE_2026-09_CIERRE.xlsx`: cierre septiembre (10.181 registros, 7.405 validados, 74,50 % oficial).
- `BEES_FORCE_2026-10_CIERRE.xlsx`: cierre octubre (14.018 registros, 10.812 validados, 79,14 % oficial).
- `BEES_FORCE_REVISIONES_2026-10_ACTUAL.xlsx`: tickets y dictámenes de revisión del cierre de octubre.
- **`BEES_FORCE_ANOMALIAS_2026-10_2026-10-26.xlsx`**: reporte de anomalías de octubre (se conserva íntegro en Drive; **el dashboard filtra exclusivamente el distribuidor 70549 / Distribuidora del Valle S.A.**).
- **`BEES_FORCE_GESTION_Clasificaciones_y_Planes`**: Google Sheet privado que guarda un **historial** de los dictámenes de anomalías, los objetivos y planes de acción. [Abrir gestión](https://docs.google.com/spreadsheets/d/1eC3hioLGQLb1AmerMyIhUcJAgJNS7vjjUZ-1vrjKE_Y/edit?usp=drivesdk). La app escribe en `Eventos`; `Ayuda` describe el formato.

El reporte recibido de anomalías tiene 1.094 filas con fotos entre todos los distribuidores, y **solo una** de Distribuidora del Valle. La imagen de DDV corresponde al promotor Mariano Herrera, Supervisor 2, pilar Frío, y se concilia mediante el UUID contenido en el enlace a la foto; en la bajada figura inválida.

## Cargas a Drive: **no hace falta renombrar los archivos exportados**

La carpeta del proyecto sigue siendo [BEES Force - Tablero de tareas](https://drive.google.com/drive/folders/1j6SZlNNJJzvg8f5MO6mdm5wJ4NNOuCmR). El tablero lee los nombres que normalmente llegan en el trabajo, **no exige el prefijo BEES_FORCE**. Los nombres internos con `BEES_FORCE_YYYY-MM` son **solo respaldos y cierres generados por la aplicación**, que el usuario no necesita crear manualmente.

| Qué se carga | Ejemplo del nombre que podés usar | Cómo detecta el mes |
|---|---|---|
| **Bajada mensual de tareas** | **`planatareas.xlsx`** | De la columna `Fecha` de la hoja `Export`; debe contener un único mes. Podés reemplazarla con la nueva bajada manteniendo el nombre. |
| **Ticket de revisión** | **`Q4 2026 DEL VALLE - Ticket.xlsx`** (o una variante `Q4 2026 ... Ticket.xlsx`) | **Un solo archivo durante el trimestre.** Lee todas las hojas mensuales (`octubre`, `noviembre`, `diciembre`, `nov 2026`, `11-26`, etc.). Usa `Fecha` de cada fila o, si falta, el mes de la pestaña y el año del libro Q4. |
| **Anomalías semanales** | **`Anomalias nov 2026.xlsx`**, `Anomalias noviembre 2026.xlsx`, `Anomalias 11-26.xlsx`, `Anomalias 11/26.xlsx` | Reconoce mes abreviado/completo o numérico, con año de 2 o 4 cifras. Si no se identifica, usa `task_executed_datetime` de la hoja `base`. Acumula los reportes del mes y elimina duplicados por fotografía. |
| **Cierres históricos** | `BEES_FORCE_2026-10_CIERRE.xlsx` | El mes y el estado `CIERRE` se identifican por su nombre interno. **No se sobrescriben.** |

Se admiten `.xlsx`, `.xlsm` y `.csv` en las nuevas cargas. La bajada se reconoce como `planatareas`, incluyendo `planatareas (1)` si Windows agrega un número. Los tickets se reconocen por *ticket/revisión* junto con *Valle*, *Q1–Q4* o *BEES*, incluso con variaciones de mayúsculas, guiones o tildes. Las anomalías se reconocen por *anomalias/anomalías*. No hace falta convertir los reportes originales.

### Qué pasa al reemplazar `planatareas.xlsx`

- Cuando la app consulta la nueva `planatareas.xlsx`, **detecta el período desde sus fechas** y guarda/actualiza una copia privada del mes bajo `BEES_FORCE_YYYY-MM_ACTUAL.xlsx`. Se conserva el último respaldo disponible de cada período.
- Cuando el calendario avanza y la app vuelve a abrirse, transforma la última copia del mes vencido en `BEES_FORCE_YYYY-MM_CIERRE.xlsx` si aún no existe; los cierres anteriores siempre tienen prioridad y nunca se modifican.
- **Importante:** el respaldo se realiza al ejecutar la app con Drive conectado y permiso de edición. Si nunca se abre el tablero durante un mes y se reemplaza `planatareas` con el mes siguiente, no habrá forma de recuperar automáticamente los datos que no se respaldaron. Se recomienda abrir el tablero después de cada carga y antes de reemplazar el archivo al cambiar de mes.
- Si se suben varias versiones de `planatareas` para el mismo mes, se utiliza la más recientemente modificada. Los backups internos se mantienen separados.

### Tickets y reportes semanales

El archivo `Q4 2026 DEL VALLE - Ticket.xlsx` **mantiene su nombre hasta enero**. En noviembre tendrá `octubre` + `noviembre`, y en diciembre incluirá también `diciembre`. La app inspecciona todas las hojas con encabezados `ID Tarea` y `STATUS` y reconoce mes y año de cada fila (prioriza la columna `Fecha`, incluyendo el formato argentino `dd/mm/aaaa`; cuando falta una fecha utiliza el nombre de la hoja y el año del libro Q4). Las hojas auxiliares se ignoran. **Al elegir noviembre se usan exclusivamente los tickets de noviembre**, sin sumar octubre ni diciembre. En enero se admite un libro Q1 2027. Si hay varios archivos de ticket que cubren un mes, se usa el más recientemente modificado. Los cierres anteriores conservan prioridad.

Los reportes de anomalías pueden variar entre `nov 2026`, `noviembre 2026`, `11-26`, `11/26`, `nov-26` o `2026-11`; el nombre del reporte semanal no necesita respetar una plantilla fija. Si el archivo no expresa un mes/año reconocible, se inspecciona la columna `task_executed_datetime` de su hoja `base`. Para el mes elegido se cargan todos los reportes reconocidos de ese período. **Las fotos repetidas se contabilizan una sola vez**. La decisión manual sobre cada fotografía sigue guardándose en la hoja de gestión, independientemente del nombre del reporte donde aparezca.

Solo se consideran las anomalías de Distribuidora del Valle: `wholesaler_id = 70549` o la descripción correspondiente. Se lee la hoja `base` (no las hojas de resúmenes), y una foto con fecha de otro mes no contamina los indicadores del período elegido.

## Orden de las solapas

1. **Resumen general:** todas las cifras oficiales de la bajada, sin mezclar revisiones, anomalías ni estimaciones.
2. **Revisión de inválidas:** dictámenes de tickets y cierre proyectado. Solo suma fallas de algoritmo que **todavía figuran inválidas** en la bajada; reconoce la regla BONUS al cambiar también el denominador. Correcciones ya validadas no suman por segunda vez.
3. **Anomalías:** imágenes DDV con miniatura legible, clic para ampliar, filtros globales, ranking por promotor y clasificación manual `Pendiente / Falla de algoritmo / Inválida / Fraude`. Cada clasificación puede incluir observaciones; para Fraude la observación es obligatoria. **No cambia ni el KPI oficial ni el proyectado de tickets**: una alerta de anomalía no es por sí sola un dictamen aceptado por BEES.
4. **Plan de acción:** permite guardar **un porcentaje objetivo por cada mes**, alternar entre resultado oficial o proyectado (cuando hay tickets), listar promotores por debajo y **editar el plan directamente junto al resultado y la causa principal**. Al seleccionar un promotor se ve el desglose por pilar y las tareas más inválidas. Los planes persisten en Drive al presionar Guardar; Render no los guarda en su disco efímero.
5. Pilar · Supervisor.
6. Ranking promotores.
7. Tareas críticas.
8. Galería de fotos.
9. Detalle y exportación.

### Diagnóstico de la brecha

El sistema compara `Validadas / Enviadas computables` con el objetivo mensual indicado. Dentro de cada promotor calcula para cada pilar:

- Tasa de validación: `Validadas del pilar / Enviadas del pilar`.
- **Déficit neto frente al objetivo (tareas)**: `objetivo_decimal × enviadas_pilar - validadas_pilar`. Este valor indica cuál es el principal aporte al desvío, considerando el peso distinto de cada pilar.
- Tareas y variables con más **invalidaciones y justificaciones**, con detalle legible para planificar la mejora.

Se informa tanto el **pilar con menor porcentaje** como el **pilar que más afecta la meta por volumen**. Pueden ser distintos. No atribuye causalidad automática, ni inventa una causa cuando los datos solo muestran correlación. En modo proyectado, las recuperaciones de tickets pendientes se incluyen en los totales usados para el diagnóstico y no duplican tareas ya validadas.

**Importante:** los filtros globales también afectan los resultados del plan de acción. La app avisa si se seleccionaron filtros por estado, fechas parciales, variable o texto; un porcentaje de un subconjunto no es el porcentaje integral del mes. Para evaluar el objetivo global del mes, usar todos los estados, todas las fechas y todos los pilares.

## Publicación en GitHub y Render

No subir archivos `.xlsx`, `.csv`, `.env` ni claves a GitHub. El `.gitignore` ya excluye los datos y los secretos.

1. Reemplazar en GitHub los archivos del repositorio por los del ZIP (`app.py`, `bees_logic.py`, `review_logic.py`, `drive_source.py`, **`anomaly_logic.py`**, **`management_store.py`**, **`action_plan_logic.py`**, `requirements.txt`, `.streamlit/config.toml`, `.gitignore`, este README). Mantener el repositorio privado.
2. En Google Cloud habilitar **Drive API y Sheets API**. Crear una cuenta de servicio y compartir la carpeta del proyecto (incluida la planilla de gestión) con su dirección de correo como **Editor**.
3. Render Web Service, configuración:
   - Build: `pip install -r requirements.txt`
   - Start: `streamlit run app.py --server.address 0.0.0.0 --server.port $PORT --server.headless true`
4. Agregar a las **Environment Variables** de Render, no al código ni a GitHub:
   - `GOOGLE_SERVICE_ACCOUNT_JSON` = JSON completo de la cuenta de servicio.
   - `BEES_DRIVE_FOLDER_ID` = `1j6SZlNNJJzvg8f5MO6mdm5wJ4NNOuCmR`.
   - `BEES_GESTION_SHEET_ID` = `1eC3hioLGQLb1AmerMyIhUcJAgJNS7vjjUZ-1vrjKE_Y`.
   - `BEES_EDITOR_PASSWORD` = una clave larga, privada, exclusiva de los revisores. **No escribirla en GitHub**.
5. En el tablero, para guardar clasificaciones, objetivo o planes, introducir la clave de editor y **nombre o iniciales** en la barra lateral. El botón Guardar escribe inmediatamente una nueva fila en el Sheet `Eventos`, preservando el historial. Cuando se edita una anomalía, su dictamen y observación quedan registrados con su usuario y mes. **No basta con modificar la tabla sin pulsar Guardar**.

### Seguridad

Los Excel y los links contienen fotos y datos de personal y comercios. Las fotos usan URLs firmadas. **No compartas un servicio Render público con clientes externos.** El password de editor solamente controla el guardado: **no restringe la lectura del dashboard**. Para compartir el tablero, colocá una capa adicional de autenticación o controles de acceso y mantené Drive y la hoja de gestión privados. `Fraude` es únicamente una **clasificación manual interna**, no una conclusión automática del sistema.

El proyecto no incorpora un login completo de usuarios; para auditoría básica registra los datos de nombre/iniciales que se escriban al guardar. En cargas simultáneas, el Sheet escribe eventos por adición, y se aplica la última entrada de cada clave (tipo, mes, foto/promotor). Un cierre mensual existente tiene prioridad frente a ACTUAL y no se modifica desde el tablero.

## Ejecución local y alcance verificado

```bash
pip install -r requirements.txt
streamlit run app.py
```

Sin credenciales se puede previsualizar con archivos bajo `data/`, también con los nombres originales (`planatareas.xlsx`, `Q4 2026 DEL VALLE - Ticket.xlsx` y `Anomalias Octubre 2026 - 26.10.xlsx`). **Sin cuenta de servicio, la edición está deshabilitada y no se simula guardado local**. La aplicación no descarga ni almacena las fotos dentro de GitHub, sino que muestra los enlaces de origen; si el servidor BEES bloquea/vence el enlace, la imagen no podrá ampliarse.

Se comprobaron los módulos de cálculo y la detección de nombres con los Excel reales de octubre (14.018 registros, 10.812 validadas), deduplicación de la fotografía semanal y conciliación de la anomalía con la tarea. Se agregaron pruebas para `nov 2026`, `noviembre 2026`, `11-26`, `11/26`, y para un libro trimestral Q4 con pestañas de octubre, noviembre y diciembre y fechas en formato `dd/mm/aaaa`. Se revisó la sintaxis Python. **No se comprobó el render final de Streamlit en Render ni el acceso de una cuenta de servicio que aún no está configurada en el servidor**; deben verificarse al publicar.
