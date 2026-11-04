"""BEES Force | Tablero de gestión de tareas y evidencias.
Ejecutar: streamlit run app.py
"""
from __future__ import annotations

import html
import os
import hmac
from pathlib import Path
from io import BytesIO

import pandas as pd
import plotly.express as px
import streamlit as st

from drive_source import service as drive_service, folder_id as drive_folder_id, list_monthly, choose, download, auto_close_old, sync_planatareas, current_month, local_monthly_files, list_reviews, local_review_files, auto_close_reviews, list_anomaly_reports, local_anomaly_reports

from review_logic import (load_review_source, prepare_reviews, reconcile_reviews,
                          filter_reviews, review_metrics, estimated_close, ranking_reviews, REVIEW_COLORS)

from anomaly_logic import (read_anomalies, prepare_anomalies, combine_anomalies, with_verdicts,
                           filter_anomalies, ANOMALY_CHOICES)
from management_store import read_events, append_events, last_value, configured as management_configured, spreadsheet_id as management_sheet_id
from action_plan_logic import promoter_summary, diagnostic

from bees_logic import (
    STATUS_COLORS, STATUS_ORDER, filter_data, group_summary,
    load_source, prepare, stats,
)

st.set_page_config(page_title='BEES Force · Control de tareas', page_icon='📋', layout='wide', initial_sidebar_state='expanded')

st.markdown('''
<style>
:root {color-scheme: light;}
.stApp, [data-testid="stSidebar"] { background: #f7f9fc; }
.stApp, .stApp p, .stApp label, .stApp span, .stApp div, .stApp h1, .stApp h2, .stApp h3 {color: #182334;}
h1, h2, h3 {letter-spacing: -.02em;}
h1 {font-size: 2rem !important;}
h3 {font-size: 1.1rem !important;}
[data-testid="stMetric"] {background: white; border: 1px solid #e2e8f0; border-radius: 13px; padding: 16px 12px; box-shadow: 0px 2px 10px #1e293b08;}
[data-testid="stMetricLabel"] * {color: #475569 !important; font-weight: 650;}
[data-testid="stMetricValue"] * {color: #162436 !important; font-weight: 800;}
[data-testid="stSidebar"] {border-right: 1px solid #dce5f1;}
[data-testid="stDataFrame"] {border-radius: 10px; overflow: hidden;}
.stTabs [data-baseweb="tab-list"] {gap: 8px;}
.stTabs [data-baseweb="tab"] {background: #fff; border: 1px solid #e2e8f0; border-radius: 9px;}
.mini-note {color:#475569; font-size:.88rem; margin-bottom: .9rem;}
.photo-card {background:#fff; border:1px solid #dde5ef; border-radius:13px; padding:10px; min-height:375px; box-shadow:0 1px 6px #12233a08;}
.photo-thumb {height:220px; width:100%; background:#edf2f8; border-radius:8px; display:flex; align-items:center; justify-content:center; overflow:hidden;}
.photo-thumb img {display:block; max-width:100%; max-height:100%; width:100%; height:100%; object-fit:contain;}
.photo-placeholder {display:flex; align-items:center; justify-content:center; height:220px; background:#f1f5f9; border-radius:8px; color:#64748b; font-size:.95rem;}
.photo-small {margin:.45rem 0 .2rem; font-size:.82rem; color:#475569;}
.photo-task {font-size:.87rem; line-height:1.34; min-height:58px; max-height:85px; overflow:hidden; color:#19283a;}
.status-pill {display:inline-block; font-size:.76rem; font-weight:700; padding:3px 9px; border-radius:100px; margin-right:6px;}
.photo-action {font-size:.82rem; font-weight:700; color:#0f5fa8; text-decoration:underline;}
</style>
''', unsafe_allow_html=True)

@st.cache_data(show_spinner=False, ttl=3600)
def _process_files(named_bytes):
    frames=[]
    for name, content in named_bytes:
        frames.append(load_source(BytesIO(content), filename=name))
    return prepare(pd.concat(frames, ignore_index=True))


@st.cache_data(ttl=240, show_spinner=False)
def _download_from_drive_cached(file_id: str, modified: str) -> bytes:
    connection = drive_service(st.secrets)
    return download(connection, file_id)


@st.cache_data(show_spinner=False, ttl=3600)
def _parse_review_cached(name: str, data: bytes, period: str = ''):
    raw = load_review_source(BytesIO(data), filename=name)
    # Una sola planilla Q4: octubre/noviembre/diciembre en pestañas diferentes.
    # Mes_revision usa la Fecha de fila cuando existe, o el mes de la hoja.
    if period and 'Mes_revision' in raw.columns:
        raw = raw.loc[raw['Mes_revision'].eq(period)].copy()
    return prepare_reviews(raw)



@st.cache_data(show_spinner=False, ttl=900)
def _parse_anomalies_cached(name: str, data: bytes, base: pd.DataFrame):
    raw=read_anomalies(BytesIO(data),name=name)
    return prepare_anomalies(raw,base,source=name)

@st.cache_data(show_spinner=False, ttl=45)
def _management_events_cached():
    return read_events(st.secrets)


def anomaly_image_card(row):
    esc=lambda x:html.escape(str(x),quote=True)
    url=esc(row['FotoURL']); task=esc(row['Detalle Tarea'])
    return f'''<div class="photo-card" style="min-height:320px">
      <a href="{url}" target="_blank" rel="noopener noreferrer" title="Abrir foto en tamaño completo">
        <div class="photo-thumb"><img src="{url}" alt="Foto señalada por el reporte BEES" loading="lazy" referrerpolicy="no-referrer"></div>
      </a><div class="photo-small"><b>{esc(row['Promotor'])}</b> · {esc(row['Supervisor'])}<br>
      {esc(row['Fecha_etiqueta'])} · {esc(row['Pilar de la Liga'])} · PDV {esc(row['POC ID'])}</div>
      <div class="photo-task" title="{task}">{task}</div>
      <a class="photo-action" href="{url}" target="_blank" rel="noopener noreferrer">Ampliar fotografía</a></div>'''


def editor_passphrase():
    val=os.getenv('BEES_EDITOR_PASSWORD','').strip()
    if not val:
        try:val=str(st.secrets.get('BEES_EDITOR_PASSWORD','')).strip()
        except Exception:pass
    return val

def number(n): return f'{int(n):,}'.replace(',', '.')
def percent(v): return f'{100 * v:.1f}%'.replace('.', ',')


def display_table(frame: pd.DataFrame, *, height=400):
    frame = frame.copy()
    for c in ['% Validación','% Invalidación','% Justificación','% fallas entre revisadas']:
        if c in frame.columns: frame[c] = frame[c].map(percent)
    st.dataframe(frame, use_container_width=True, height=height, hide_index=True)


def status_chart(grouped, key, heading, height=380, top=None):
    if grouped.empty:
        st.info('Sin datos para este segmento.'); return
    data=grouped.sort_values('Tareas', ascending=False)
    if top: data=data.head(top)
    long = data.melt(id_vars=[key], value_vars=['Validadas','Inválidas','Justificadas','Pendientes'], var_name='Estado', value_name='Tareas')
    long['Estado'] = long['Estado'].map({'Validadas':'Validada','Inválidas':'Inválida','Justificadas':'Justificada','Pendientes':'Pendiente'})
    fig=px.bar(long, x=key, y='Tareas', color='Estado', title=heading, barmode='stack',
               color_discrete_map=STATUS_COLORS,
               category_orders={'Estado':STATUS_ORDER},
               hover_data={'Tareas':True})
    fig.update_layout(height=height, margin=dict(l=12,r=10,t=55,b=20),
                     xaxis_title='',yaxis_title='Cantidad de tareas',
                     legend_title='', legend=dict(orientation='h',y=1.12,x=0),
                     paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
                     font=dict(color='#182334',size=12))
    fig.update_xaxes(tickangle=-30, showgrid=False)
    fig.update_yaxes(gridcolor='#e8eef5')
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar':False})


def rank_chart(frame:pd.DataFrame, name_col:str, metric:str, heading:str, *, ascending=False, limit=14):
    if frame.empty:
        st.info('Sin datos');return
    data=frame.sort_values([metric,'Completadas'],ascending=[ascending,False]).head(limit).copy()
    data=data.iloc[::-1]
    fig=px.bar(data,x=metric,y=name_col,orientation='h',title=heading,
               text=metric,color_discrete_sequence=[('#dc2626' if metric=='Inválidas' else '#15803d')])
    fig.update_traces(textposition='outside',cliponaxis=False)
    fig.update_layout(margin=dict(l=5,r=32,t=55,b=12),height=max(320,55+36*len(data)),
        paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
        xaxis_title='Cantidad',yaxis_title='',font=dict(color='#182334'))
    fig.update_xaxes(gridcolor='#e8eef5')
    st.plotly_chart(fig,use_container_width=True,config={'displayModeBar':False})


def photo_card(row):
    u=str(row['FotoURL']) if row['FotoURL'] else ''
    esc = lambda x: html.escape(str(x),quote=True)
    tag=str(row['Estado']); color=STATUS_COLORS.get(tag,'#64748b')
    p=esc(row['Promotor']); task=esc(row['Detalle Tarea']); dt=esc(row['Fecha_etiqueta']);
    pillar=esc(row['Pilar de la Liga']); sup=esc(row['Supervisor']); poc=esc(row['POC ID']);
    bono=' · BONUS fuera de KPI' if row['Bonus_excluida_bool'] else (' · BONUS validada' if row['Bonus_bool'] else '')
    if u:
        url=esc(u)
        pic=f'<a href="{url}" target="_blank" rel="noopener noreferrer" title="Clic para ampliar la fotografía en tamaño completo"><div class="photo-thumb"><img src="{url}" alt="Evidencia de tarea BEES Force" loading="lazy" referrerpolicy="no-referrer"></div></a>'
        action=f'<a class="photo-action" href="{url}" target="_blank" rel="noopener noreferrer">Ampliar fotografía</a>'
    else:
        pic='<div class="photo-placeholder">Sin fotografía de ejecución</div>'
        action='<span style="font-size:.82rem;color:#64748b">El origen indica “No aplica”</span>'
    return f'''<div class="photo-card">{pic}
      <div class="photo-small"><span class="status-pill" style="background:{color}19;color:{color}">{esc(tag)}</span> {dt} · {pillar}{bono}</div>
      <div class="photo-small"><b>{p}</b> · {sup} · PDV {poc}</div>
      <div class="photo-task" title="{task}">{task}</div>{action}</div>'''

st.title('BEES Force · Tablero de tareas')
st.caption('Control de ejecución, validación, justificaciones y evidencias fotográficas · Distribuidora del Valle')

with st.sidebar:
    st.header('Origen de datos')
    st.caption('Leemos planatareas.xlsx y los tickets/anomalías con sus nombres habituales. Los CIERRE se conservan por mes.')

    try:
        drive = drive_service(st.secrets)
    except Exception as exc:
        drive = None
        st.error('No se pudo conectar a Google Drive: ' + str(exc))

    availability = {}
    auto_closed = []
    if drive is not None:
        try:
            folder = drive_folder_id(st.secrets)
            availability = list_monthly(drive, folder, read_bytes=_download_from_drive_cached)
            try:
                backups = sync_planatareas(drive, availability, folder, read_bytes=_download_from_drive_cached)
                if backups:
                    st.caption('Copias mensuales actualizadas en Drive: ' + ', '.join(backups))
                    availability = list_monthly(drive, folder, read_bytes=_download_from_drive_cached)
            except Exception as exc:
                st.warning('No se pudo actualizar el respaldo automático de planatareas. El mes sigue disponible, pero revisá los permisos de Drive: '+str(exc))
            if any(m < current_month() and 'ACTUAL' in d and 'CIERRE' not in d for m,d in availability.items()):
                auto_closed = auto_close_old(drive, availability, folder)
                if auto_closed:
                    availability = list_monthly(drive,folder,read_bytes=_download_from_drive_cached)
                    st.success('Cierres automáticos: ' + ', '.join(auto_closed))
        except Exception as exc:
            st.error('Problema con la carpeta Drive: ' + str(exc))
            availability = {}
    else:
        local_months = local_monthly_files(Path(__file__).parent / 'data')
        availability = {month:{state:[{'id':str(path),'name':path.name}] for state,path in items.items()} for month,items in local_months.items()}
        st.caption('Sin credenciales Drive: modo local /data. Para Render configurá la cuenta de servicio.')

    months = sorted(availability, reverse=True)
    current = current_month()
    if months:
        # En noviembre mostrará noviembre si está; en otro caso el último cierre y aviso explícito.
        default_idx = months.index(current) if current in months else 0
        month = st.selectbox('Mes para analizar',months,index=default_idx,format_func=lambda m: pd.Timestamp(m+'-01').strftime('%m/%Y'))
        item = choose(availability,month)
        is_closed = bool(availability[month].get('CIERRE'))
        st.caption(('🔒 Cierre congelado' if is_closed else '🔄 Mes en curso / fuente ACTUAL') + f' · {item["name"]}')
        if month != current and not is_closed:
            st.warning('Este mes aún no tiene archivo CIERRE. Su contenido podría cambiar.')
        if month != current and current not in availability:
            st.caption('Todavía no hay archivo para ' + current + '. Se muestra el último mes disponible.')
        try:
            if drive is not None:
                # Caché por ID + modificación, para refrescar al cambiar el archivo ACTUAL en Drive.
                data = _download_from_drive_cached(item['id'], item.get('modifiedTime',''))
            else:
                data = Path(item['id']).read_bytes()
            files = ((item['name'],data),)
        except Exception as exc:
            st.error('No se pudo descargar el período seleccionado: ' + str(exc))
            files = None
    else:
        files = None

    st.divider()
    st.caption('Cargar una bajada manualmente permite previsualizar sin modificar Drive ni cierres.')
    manual = st.file_uploader('Previsualizar archivo Excel (opcional)',type=['xlsx','xlsm','csv'],accept_multiple_files=False)
    if manual is not None:
        files = ((manual.name,manual.getvalue()),)
        st.warning('Vista previa manual. Esta carga no se guarda ni sobrescribe el cierre en Google Drive.')
    st.divider()

if files is None:
    st.info('No hay bajadas disponibles. Subí **planatareas.xlsx** a la carpeta de Drive, o cargá una vista previa manual. Los cierres anteriores se reconocen automáticamente.')
    st.stop()

try:
    df,quality=_process_files(files)
except Exception as exc:
    st.error(f'No fue posible leer los datos: {exc}')
    st.stop()

if manual is None and months:
    actual_months=df['Fecha_dt'].dropna().dt.strftime('%Y-%m').unique().tolist()
    if actual_months != [month]:
        st.error(f'El archivo {item["name"]} no contiene exclusivamente tareas de {month}. Períodos detectados: {actual_months}. Revisá la bajada antes de analizarla.')
        st.stop()

st.caption(f'Período analizado: {month if manual is None and months else "Vista previa manual"}')

# Las revisiones del período se leen por separado; nunca alteran df ni el KPI oficial.
review_rows = None
review_quality = None
review_file_name = None
review_is_closed = False
with st.sidebar:
    st.divider()
    st.header('Tickets revisados')
    st.caption('Se cargan por el mismo mes seleccionado. Su dictamen modifica solo el cierre proyectado.')
    r_manual = st.file_uploader('Previsualizar archivo de tickets (opcional)',type=['xlsx','xlsm','csv'],key='review_manual')
    try:
        if r_manual is not None:
            rb = r_manual.getvalue()
            review_file_name = r_manual.name
            st.caption('Vista previa: no modifica el archivo de Drive.')
        elif months and manual is None:
            if drive is not None:
                r_availability = list_reviews(drive, folder, read_bytes=_download_from_drive_cached)
                if any(m < current_month() and 'ACTUAL' in d and 'CIERRE' not in d for m,d in r_availability.items()):
                    auto_close_reviews(drive, r_availability, folder)
                    r_availability = list_reviews(drive, folder, read_bytes=_download_from_drive_cached)
            else:
                r_availability = local_review_files(Path(__file__).parent / 'data')
            if month in r_availability:
                ri = choose(r_availability, month)
                review_is_closed = bool(r_availability[month].get('CIERRE'))
                review_file_name = ri['name']
                rb = (_download_from_drive_cached(ri['id'],ri.get('modifiedTime',''))
                      if drive is not None else Path(ri['id']).read_bytes())
                st.caption(('🔒 Revisión cerrada' if review_is_closed else '🔄 Revisión en seguimiento') + ' · '+review_file_name)
            else:
                rb = None
                st.caption('Sin tickets cargados para el mes elegido.')
        else:
            rb = None
        if rb is not None:
            review_rows, review_quality = _parse_review_cached(review_file_name,rb,month if months and manual is None else '')
    except Exception as exc:
        review_rows = None
        st.error('No se pudieron leer los tickets: '+str(exc))



# Informes de anomalías semanales y bitácora de dictámenes / objetivos / planes.
anomaly_rows=None
anomaly_sources=[]
management_events=None
with st.sidebar:
    st.divider()
    st.header('Anomalías semanales')
    try:
        if months and manual is None:
            found=(list_anomaly_reports(drive,folder,read_bytes=_download_from_drive_cached) if drive is not None
                   else local_anomaly_reports(Path(__file__).parent/'data'))
            anomaly_sources=found.get(month,[])
        st.caption(f'{len(anomaly_sources)} reporte(s) disponibles del período elegido.')
    except Exception as exc:
        st.error('No se pudo listar los reportes de anomalías: '+str(exc))
    preview_anomalies=st.file_uploader('Previsualizar anomalías (opcional)',type=['xlsx','xlsm','csv'],
                                      accept_multiple_files=True,key='anomaly_manual')
    st.divider()
    st.header('Edición de seguimiento')
    secret=editor_passphrase()
    key_entered=st.text_input('Clave de editor',type='password',key='bees_editor_secret',
                             help='Necesaria para clasificar anomalías, fijar objetivos y guardar planes. No es una autenticación completa del sitio.')
    editor_name=st.text_input('Nombre o iniciales del revisor',key='bees_editor_name',
                              placeholder='Ej.: Supervisor 2')
    key_ok=bool(secret and key_entered and hmac.compare_digest(key_entered,secret))
    can_edit=bool(key_ok and editor_name.strip())
    if not secret:
        st.caption('Edición deshabilitada: faltó configurar BEES_EDITOR_PASSWORD en Render.')
    elif can_edit:
        st.success('Edición habilitada para esta sesión.')
    elif key_entered and not key_ok:
        st.error('Clave de editor incorrecta.')
    elif key_ok and not editor_name.strip():
        st.caption('Ingresá tu identificación para dejar constancia de quién hace los cambios.')

try:
    if management_configured(st.secrets):
        management_events=_management_events_cached()
    else:
        management_events=pd.DataFrame()
except Exception as exc:
    st.warning('No se pudo leer la bitácora de gestión de Drive: '+str(exc))
    management_events=None

if months and manual is None:
    try:
        frames=[]
        for ai in anomaly_sources:
            payload=(_download_from_drive_cached(ai['id'],ai.get('modifiedTime',''))
                     if drive is not None else Path(ai['id']).read_bytes())
            frames.append(_parse_anomalies_cached(ai['name'],payload,df))
        if preview_anomalies:
            for afile in preview_anomalies:
                frames.append(_parse_anomalies_cached(afile.name,afile.getvalue(),df))
        if frames:
            anomaly_rows=combine_anomalies(frames,df)
            anomaly_rows=anomaly_rows[anomaly_rows['Fecha_dt'].dt.strftime('%Y-%m').eq(month)].copy()
    except Exception as exc:
        st.warning('No se pudo procesar un reporte de anomalías: '+str(exc))
else:
    try:
        if preview_anomalies:
            frames=[_parse_anomalies_cached(x.name,x.getvalue(),df) for x in preview_anomalies]
            anomaly_rows=combine_anomalies(frames,df)
    except Exception as exc:
        st.warning('No se pudo procesar la previsualización de anomalías: '+str(exc))


if df.empty:
    st.warning('El archivo no contiene ID de tarea válidos.'); st.stop()

with st.sidebar:
    st.header('Filtros globales')
    ds=sorted(df['Distri/Directa'].unique().tolist())
    distributors=st.multiselect('Distribuidor',ds,default=ds if len(ds)==1 else [])
    channels=st.multiselect('Canal (K+T / AS / REF)',sorted(df['Canal Agrupado'].unique().tolist()),placeholder='Todos')
    pillars=st.multiselect('Pilar',sorted(df['Pilar de la Liga'].unique().tolist()),placeholder='Todos')
    sups=st.multiselect('Supervisor',sorted(df['Supervisor'].unique().tolist()),placeholder='Todos')
    pros=st.multiselect('Promotor',sorted(df['Promotor'].unique().tolist()),placeholder='Todos')
    variables=st.multiselect('Variable de la Liga',sorted(df['Variable de la Liga'].unique().tolist()),placeholder='Todas')
    states=st.multiselect('Estado',STATUS_ORDER,placeholder='Todos')
    clean_dates=df['Fecha_dt'].dropna()
    date_selection=None
    if not clean_dates.empty:
        first,last=clean_dates.min().date(),clean_dates.max().date()
        date_selection=st.date_input('Desde / Hasta',value=(first,last),min_value=first,max_value=last,format='DD/MM/YYYY')
    query=st.text_input('Buscar texto en tarea',placeholder='Ej.: POP EXTERNO')
    poc=st.text_input('Buscar ID de PDV',placeholder='Ej.: 0705490')
    st.caption('Selección vacía = todas las opciones del filtro.')

f=filter_data(df,distributors,pillars,sups,pros,variables,states,date_selection,query,poc,channels=channels)
s=stats(f)

all_reviews = None
filtered_reviews = None
if review_rows is not None:
    try:
        all_reviews = reconcile_reviews(df, review_rows)
        filtered_reviews = filter_reviews(
            all_reviews, distributors=distributors, channels=channels,
            pillars=pillars, supervisors=sups, promoters=pros,
            variables=variables, states=states, dates=date_selection,
            text_q=query, poc_q=poc)
    except Exception as exc:
        st.error('El cruce de revisiones no pudo completarse: '+str(exc))


filtered_anomalies=None
if anomaly_rows is not None:
    try:
        with_decisions=with_verdicts(anomaly_rows,management_events)
        filtered_anomalies=filter_anomalies(with_decisions,
            distributors=distributors,channels=channels,pillars=pillars,
            supervisors=sups,promoters=pros,variables=variables,states=states,
            dates=date_selection,text_q=query,poc_q=poc)
    except Exception as exc:
        st.warning('No se pudieron filtrar las anomalías: '+str(exc))

if f.empty:
    st.warning('No hay tareas que cumplan con los filtros seleccionados.'); st.stop()

k=st.columns(4)
for col,label in zip(k,['Enviadas (oficial)','Validadas','Inválidas','Justificadas']):
    col.metric(label,number(s[label]))
other=st.columns(4)
for col,label in zip(other,['Tareas','Completadas','Pendientes','Bonus excluidas']):
    col.metric(label,number(s[label]))
st.markdown(f'<div class="mini-note"><b>Validación oficial: {percent(s["% Validación"])}</b> (validadas / enviadas computables) · Ejecución bruta: {percent(s["% Completadas"])} (completadas / registros) · Invalidación operativa: {percent(s["% Invalidación"])} (inválidas / completadas) · Justificación: {percent(s["% Justificación"])} (justificadas / registros). Las BONUS no validadas no entran en “Enviadas”, pero permanecen en el análisis operativo.</div>',unsafe_allow_html=True)

overview,reviews_tab,anomalies_tab,action_plans_tab,segmentation,ranking,actions,photos,details=st.tabs([
    'Resumen general','Revisión de inválidas','Anomalías','Plan de acción',
    'Pilar · Supervisor','Ranking promotores','Tareas críticas','Galería de fotos','Detalle y exportación'
])

with overview:
    st.subheader('Rendimiento oficial por canal')
    by_channel=group_summary(f,'Canal Agrupado')
    display_table(by_channel.sort_values('Enviadas (oficial)',ascending=False),height=240)
    st.caption('La tasa de validación se calcula con las tareas enviadas computables. Las justificaciones y las invalidaciones incluyen también BONUS fuera del KPI oficial; se conservan para control.')
    by_pillar=group_summary(f,'Pilar de la Liga')
    a,b=st.columns([1.3,1])
    with a:
        status_chart(by_pillar,'Pilar de la Liga','Distribución de resultados por pilar',380)
    with b:
        pie=px.pie(pd.DataFrame({'Estado':STATUS_ORDER,'Cantidad':[s['Validadas'],s['Inválidas'],s['Justificadas'],s['Pendientes']]}),
                   names='Estado',values='Cantidad',hole=.58,title='Composición total',color='Estado',color_discrete_map=STATUS_COLORS)
        pie.update_layout(height=380,margin=dict(l=10,r=10,t=55,b=8),legend_title='',paper_bgcolor='rgba(0,0,0,0)',font=dict(color='#182334'))
        st.plotly_chart(pie,use_container_width=True,config={'displayModeBar':False})
    st.subheader('Indicadores por pilar')
    display_table(by_pillar.sort_values('Tareas',ascending=False),height=220)
    st.subheader('Supervisor · Resultado')
    by_sup=group_summary(f,'Supervisor')
    status_chart(by_sup,'Supervisor','Volumen de tareas por supervisor',340)
    display_table(by_sup.sort_values('Supervisor'),height=210)

with segmentation:
    st.subheader('Resultados por canal y pilar')
    by_cp=group_summary(f,['Canal Agrupado','Pilar de la Liga'])
    display_table(by_cp.sort_values(['Canal Agrupado','Pilar de la Liga']),height=270)
    st.subheader('Resultados combinados por pilar y supervisor')
    group=group_summary(f,['Pilar de la Liga','Supervisor'])
    display_table(group.sort_values(['Pilar de la Liga','Supervisor']),height=310)
    status_chart(group.assign(Segmento=group['Pilar de la Liga']+' · '+group['Supervisor']),'Segmento','Distribución por pilar × supervisor',390)
    st.subheader('Resultados por promotor y pilar')
    gp=group_summary(f,['Pilar de la Liga','Supervisor','Promotor'])
    display_table(gp.sort_values(['Pilar de la Liga','Inválidas'],ascending=[True,False]),height=450)

with ranking:
    st.subheader('Ranking de promotores')
    st.caption('Los rankings de cantidad miden volumen. Las tasas permiten comparar promotores con cargas de trabajo distintas.')
    pillars_rank=['Todos los pilares']+sorted(f['Pilar de la Liga'].unique().tolist())
    pillar_sel=st.selectbox('Pilar para el ranking',pillars_rank, key='ranking_pillar')
    rf=f if pillar_sel=='Todos los pilares' else f[f['Pilar de la Liga']==pillar_sel]
    gr=group_summary(rf,'Promotor')
    a,b=st.columns(2)
    with a:rank_chart(gr,'Promotor','Inválidas','Mayor cantidad de tareas inválidas')
    with b:rank_chart(gr,'Promotor','Validadas','Mayor cantidad de tareas validadas')
    st.markdown('**Ranking de tasa de invalidación** (solo promotores con al menos 10 tareas completadas)')
    enough=gr[gr['Completadas']>=10].sort_values(['% Invalidación','Inválidas'],ascending=False)
    display_table(enough[['Promotor','Completadas','Validadas','Inválidas','% Validación','% Invalidación','Justificadas','% Justificación']],height=400)
    st.subheader('Ranking por cada pilar')
    all_pillars=sorted(f['Pilar de la Liga'].unique().tolist())
    if all_pillars:
        for tab,pil in zip(st.tabs(all_pillars),all_pillars):
            with tab:
                gpp=group_summary(f[f['Pilar de la Liga']==pil],'Promotor')
                cols=st.columns(2)
                with cols[0]:rank_chart(gpp,'Promotor','Inválidas',f'Inválidas · {pil}')
                with cols[1]:rank_chart(gpp,'Promotor','Validadas',f'Validadas · {pil}')
                display_table(gpp.sort_values('Inválidas',ascending=False),height=350)

with actions:
    st.subheader('¿Qué tareas se invalidan más?')
    tasks=group_summary(f,['Pilar de la Liga','Variable de la Liga','Detalle Tarea'])
    minimum=st.number_input('Mínimo de tareas completadas para evaluar tasas',min_value=1,max_value=300,value=10,step=1,
                            help='Solo afecta el ranking por porcentaje; no oculta tareas del ranking por cantidad.')
    namecols=['Pilar de la Liga','Variable de la Liga','Detalle Tarea','Tareas','Completadas','Validadas','Inválidas','% Invalidación','Justificadas']
    a,b=st.columns(2)
    with a:
        st.markdown('**Más inválidas — cantidad**')
        display_table(tasks.sort_values(['Inválidas','Completadas'],ascending=False)[namecols].head(15),height=430)
    with b:
        st.markdown('**Mayor tasa de invalidación**')
        rate=tasks[tasks['Completadas']>=minimum].sort_values(['% Invalidación','Inválidas'],ascending=False)
        display_table(rate[namecols].head(15),height=430)
    st.subheader('¿Qué tareas se justifican más?')
    display_table(tasks.sort_values(['Justificadas','Tareas'],ascending=False)[namecols].head(20),height=420)
    st.subheader('Motivos de justificación')
    reasons=f[f['Justificada_bool']].groupby(['Justificacion Motivo'],dropna=False).size().reset_index(name='Justificaciones').sort_values('Justificaciones',ascending=False)
    left,right=st.columns([1.3,1])
    with left:
        if not reasons.empty:
            fig=px.bar(reasons.iloc[::-1],x='Justificaciones',y='Justificacion Motivo',orientation='h',
                       title='Motivos registrados',text='Justificaciones',color_discrete_sequence=['#d97706'])
            fig.update_layout(height=max(320,65+30*len(reasons)),margin=dict(l=10,r=22,t=48,b=5),
                              xaxis_title='Cantidad',yaxis_title='',font=dict(color='#182334'),
                              paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)')
            fig.update_xaxes(gridcolor='#e8eef5')
            st.plotly_chart(fig,use_container_width=True,config={'displayModeBar':False})
        else:st.info('No hay justificaciones en la selección.')
    with right:display_table(reasons,height=420)

with photos:
    st.subheader('Galería de evidencias fotográficas')
    st.caption('Miniatura completa sin recorte. Hacé clic en la imagen para abrirla ampliada en otra pestaña. El enlace depende de los permisos y vigencia del servidor BEES Force.')
    a,b,c=st.columns([1.2,1.3,1])
    with a:
        photo_status=st.selectbox('Estado en galería',['Todas']+STATUS_ORDER,index=2,key='gallery_status')
    with b:
        only_photos=st.checkbox('Solo con fotografía',value=True)
    with c:
        page_size=st.selectbox('Imágenes por página',[9,12,18,24],index=1)
    pf=f
    if photo_status!='Todas':pf=pf[pf['Estado']==photo_status]
    if only_photos:pf=pf[pf['FotoURL']!='']
    pf=pf.sort_values(['Fecha_dt','Promotor'],ascending=[False,True]).reset_index(drop=True)
    n=len(pf); total_pages=max(1,(n+page_size-1)//page_size)
    pg=st.number_input(f'Página (de {total_pages})',min_value=1,max_value=total_pages,value=1,step=1)
    st.markdown(f'**{number(n)} tareas** coinciden con los filtros de la galería. Página {pg}/{total_pages}.')
    subset=pf.iloc[(pg-1)*page_size:pg*page_size]
    if subset.empty:st.info('No hay imágenes para mostrar con estos filtros.')
    else:
        cols=st.columns(3)
        for i,(_,item) in enumerate(subset.iterrows()):
            with cols[i%3]: st.markdown(photo_card(item),unsafe_allow_html=True)
    st.info('Las evidencias no se descargan ni se copian a GitHub: se muestran directamente desde el enlace del Excel. Si el servidor bloquea o vence el enlace, la miniatura tampoco estará disponible.')

with reviews_tab:
    st.subheader('Revisión de inválidas · Cierre anticipado')
    st.caption('Los tickets revisados entre el 15 y el 23 pueden anticipar correcciones que impactan oficialmente a fin de mes. La proyección suma solo fallas de algoritmo que aún aparecen inválidas en la bajada seleccionada.')
    if filtered_reviews is None:
        a,b = st.columns(2)
        a.metric('Validadas oficiales',number(s['Validadas']))
        b.metric('% validación oficial',percent(s['% Validación']))
        st.info('No hay tickets de revisión para el mes seleccionado. Subí el libro trimestral de tickets con las hojas por mes (octubre, noviembre y diciembre) a Drive.')
    else:
        rm=review_metrics(filtered_reviews)
        projection=estimated_close(f, filtered_reviews)
        st.markdown('**El indicador oficial permanece intacto.** El cierre proyectado usa la misma población filtrada y reconoce las BONUS recuperadas en el denominador.')
        c1,c2,c3,c4=st.columns(4)
        c1.metric('Validación oficial',percent(projection['porcentaje_oficial']),help=f"{number(projection['validadas_oficiales'])} / {number(projection['enviadas_oficiales'])} tareas")
        c2.metric('Fallas recuperables',number(projection['recuperaciones_adicionales']),help='Dictamen Falla de algoritmo y tarea todavía inválida en la bajada. No incluye las ya corregidas.')
        c3.metric('Cierre proyectado',percent(projection['porcentaje_estimado']),delta=f"{(projection['porcentaje_estimado']-projection['porcentaje_oficial'])*100:+.2f} pp")
        c4.metric('Validadas proyectadas',number(projection['validadas_estimadas']),help=f"{number(projection['enviadas_estimadas'])} tareas computables proyectadas")
        st.caption(f"Fórmula: ({number(projection['validadas_oficiales'])} validadas oficiales + {number(projection['recuperaciones_adicionales'])} recuperaciones pendientes) / ({number(projection['enviadas_oficiales'])} enviadas oficiales + {number(projection['bonus_recuperadas'])} BONUS recuperadas). Actualizado a la última bajada disponible; no anticipa ejecuciones futuras ni decisiones todavía no cargadas.")
        if rm['Revisadas']==0:
            st.warning('No hay dictámenes de revisión para los filtros seleccionados. El proyectado coincide con la base oficial por falta de recuperaciones acreditadas.')
        r1,r2,r3,r4,r5=st.columns(5)
        for slot,label in zip((r1,r2,r3,r4,r5),('Revisadas','Fallas de algoritmo','Inválidas confirmadas','Sin dictamen','Ya validadas')):
            slot.metric(label,number(rm[label]))
        if rm['Sin correspondencia'] or rm['Conflictos']:
            st.warning(f"Hay {number(rm['Sin correspondencia'])} tickets sin correspondencia y {number(rm['Conflictos'])} con dictamen de inválida que aparecen validados en la bajada. Se muestran para control y NO suman al proyectado.")
        inner1, inner2, inner3, inner4 = st.tabs(['Análisis de revisiones','Ranking de promotores','Fotos revisadas','Detalle y conciliación'])
        with inner1:
            decision=st.selectbox('Dictamen de revisión',['Todos','Falla de algoritmo','Inválida confirmada','Sin dictamen'],key='decision_review')
            rview=filtered_reviews if decision=='Todos' else filtered_reviews[filtered_reviews['Estado_revision']==decision]
            a,b=st.columns([1,1.4])
            with a:
                st.markdown('**Resultado de los tickets**')
                summary=pd.DataFrame({'Dictamen':['Falla de algoritmo','Inválida confirmada','Sin dictamen'],
                   'Cantidad':[int(rview['Falla_algoritmo_bool'].sum()),int(rview['Invalida_confirmada_bool'].sum()),int(rview['Sin_dictamen_bool'].sum())]})
                fig=px.bar(summary, x='Cantidad',y='Dictamen',orientation='h',text='Cantidad',
                    color='Dictamen',color_discrete_map=REVIEW_COLORS)
                fig.update_layout(height=300,showlegend=False,margin=dict(l=8,r=18,t=12,b=8),font=dict(color='#182334'),paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig,use_container_width=True,config={'displayModeBar':False})
            with b:
                st.markdown('**Por pilar**')
                rr=ranking_reviews(rview,'Pilar de la Liga')
                display_table(rr,height=300)
            st.markdown('**Por supervisor y canal**')
            display_table(ranking_reviews(rview,['Supervisor','Canal Agrupado']).sort_values('Revisadas',ascending=False),height=330)
            st.markdown('**Por tarea**')
            display_table(ranking_reviews(rview,['Pilar de la Liga','Detalle Tarea']).sort_values('Fallas de algoritmo',ascending=False).head(25),height=420)
        with inner2:
            rank_pillar=st.selectbox('Pilar del ranking de revisiones',['Todos']+sorted(filtered_reviews['Pilar de la Liga'].dropna().unique().tolist()),key='review_pillar')
            rr=filtered_reviews if rank_pillar=='Todos' else filtered_reviews[filtered_reviews['Pilar de la Liga']==rank_pillar]
            rank=ranking_reviews(rr,'Promotor').sort_values(['Fallas de algoritmo','Recuperables'],ascending=False)
            st.caption('Ranking por cantidad de fallas del algoritmo detectadas; recuperables identifica las que todavía sumarían al cierre proyectado.')
            a,b=st.columns(2)
            with a:st.markdown('**Mayor cantidad de fallas de algoritmo**');display_table(rank.head(25),height=460)
            with b:st.markdown('**Mayor cantidad de inválidas confirmadas**');display_table(rank.sort_values('Inválidas confirmadas',ascending=False).head(25),height=460)
            st.markdown('**Promotores por pilar (todas las revisiones)**')
            display_table(ranking_reviews(filtered_reviews,['Pilar de la Liga','Promotor']).sort_values(['Pilar de la Liga','Fallas de algoritmo'],ascending=[True,False]),height=450)
        with inner3:
            st.caption('Fotografías de las tareas revisadas: clic para ampliar. Si el enlace está vencido o es privado, puede no mostrarse.')
            photo_decision=st.selectbox('Dictamen de las fotos',['Todos','Falla de algoritmo','Inválida confirmada','Sin dictamen'],key='photo_review_decision')
            gallery=filtered_reviews if photo_decision=='Todos' else filtered_reviews[filtered_reviews['Estado_revision']==photo_decision]
            gallery=gallery[gallery['FotoURL'].astype(str).ne('')].sort_values('Fecha_dt',ascending=False).reset_index(drop=True)
            per_page=9
            total_pages=max(1,(len(gallery)+per_page-1)//per_page)
            page=st.number_input('Página de fotos revisadas',min_value=1,max_value=total_pages,value=1,step=1,key='rev_page')
            st.caption(f"{number(len(gallery))} fotografías disponibles · Página {page}/{total_pages}")
            piccols=st.columns(3)
            for idx,(_,row) in enumerate(gallery.iloc[(page-1)*per_page:page*per_page].iterrows()):
                with piccols[idx%3]:
                    photo=dict(row)
                    photo['Estado']=row['Estado_revision']
                    st.markdown(photo_card(photo),unsafe_allow_html=True)
            if gallery.empty:st.info('No hay fotografías disponibles para este criterio.')
        with inner4:
            st.markdown('**Conciliación por ID Tarea**')
            match_choice=st.selectbox('Situación del ticket',['Todas']+sorted(filtered_reviews['Conciliacion'].dropna().unique().tolist()),key='review_match_choice')
            detail=filtered_reviews if match_choice=='Todas' else filtered_reviews[filtered_reviews['Conciliacion']==match_choice]
            cols=['Fecha_etiqueta','Canal Agrupado','Pilar de la Liga','Supervisor','Promotor','POC ID','Detalle Tarea',
                  'ID Tarea','Estado_revision','Estado_origen','Conciliacion','FotoURL']
            display=detail[cols].rename(columns={'Fecha_etiqueta':'Fecha','Estado_revision':'Dictamen ticket','Estado_origen':'Estado oficial','FotoURL':'Foto'})
            st.dataframe(display,hide_index=True,use_container_width=True,height=490,column_config={'Foto':st.column_config.LinkColumn('Foto',display_text='Abrir foto')})
            st.download_button('Exportar revisiones filtradas',data=display.to_csv(index=False,sep=';').encode('utf-8-sig'),file_name='BEES_Force_revisiones_filtradas.csv',mime='text/csv')
            with st.expander('Control de calidad de los tickets'):
                st.write('Filas del archivo:',number(review_quality['registros']))
                st.write('Sin ID Tarea:',number(review_quality['sin_id']))
                st.write('ID Tarea duplicados retirados:',number(review_quality['duplicados']))
                st.write('Sin dictamen interpretable:',number(review_quality['sin_dictamen']))
                st.caption('Los tickets sin correspondencia no modifican el cierre proyectado; revisalos antes de ajustar el origen.')


with anomalies_tab:
    st.subheader('Anomalías fotográficas · Distribuidora del Valle')
    st.caption('Solo reportes del distribuidor ID 70549. Se consolidan archivos semanales por foto, sin duplicar imágenes repetidas. La clasificación es manual y no modifica los KPI oficiales ni el cierre proyectado de tickets.')
    if filtered_anomalies is None:
        st.info('No hay reporte semanal para este mes. Subí a Drive un BEES_FORCE_ANOMALIAS_YYYY-MM_YYYY-MM-DD.xlsx, o previsualizá un Excel desde la barra lateral.')
    else:
        ac=filtered_anomalies.copy()
        dictamen_filter=st.multiselect('Dictamen de anomalía',ANOMALY_CHOICES,
                                     default=[],key='anomaly_verdict_filter',placeholder='Todos los dictámenes')
        if dictamen_filter:ac=ac[ac['Dictamen'].isin(dictamen_filter)]
        col=st.columns(4)
        for cell, label, value in zip(col,['Anomalías únicas','Pendientes','Falla de algoritmo','Inválida / Fraude'],[
                len(ac),int(ac['Dictamen'].eq('Pendiente').sum()),int(ac['Dictamen'].eq('Falla de algoritmo').sum()),
                int(ac['Dictamen'].isin(['Inválida','Fraude']).sum())]):
            cell.metric(label,number(value))
        if not ac.empty:
            st.markdown('**Ranking por promotor**')
            ar=ac.groupby(['Promotor','Supervisor'],dropna=False).agg(
                Anomalías=('Anomalia_key','count'),Pendientes=('Dictamen',lambda s:int(s.eq('Pendiente').sum())),
                Algoritmo=('Dictamen',lambda s:int(s.eq('Falla de algoritmo').sum())),
                **{'Inválidas':('Dictamen',lambda s:int(s.eq('Inválida').sum())),
                   'Fraude':('Dictamen',lambda s:int(s.eq('Fraude').sum()))}).reset_index()
            st.dataframe(ar.sort_values('Anomalías',ascending=False),hide_index=True,use_container_width=True,height=235)
            st.markdown('**Fotografías para revisión**')
            page_size=9
            ac=ac.sort_values(['Fecha_dt','Promotor'],ascending=[False,True]).reset_index(drop=True)
            apages=max(1,(len(ac)+page_size-1)//page_size)
            apage=st.number_input(f'Página de anomalías (1–{apages})',min_value=1,max_value=apages,value=1,key='anom_page')
            displayed=ac.iloc[(apage-1)*page_size:apage*page_size]
            for start in range(0,len(displayed),3):
                group=st.columns(3)
                for pos,(_,row) in enumerate(displayed.iloc[start:start+3].iterrows()):
                    with group[pos]:
                        st.markdown(anomaly_image_card(row),unsafe_allow_html=True)
                        key=str(row['Anomalia_key'])
                        with st.form('form_anom_'+key,clear_on_submit=False):
                            choice=st.selectbox('Dictamen',ANOMALY_CHOICES,
                                index=ANOMALY_CHOICES.index(row['Dictamen']),key='verdict_'+key)
                            note=st.text_area('Observación',value=row['Observacion'],
                                height=84,key='anom_note_'+key,placeholder='Justificación de la clasificación')
                            saved=st.form_submit_button('Guardar clasificación',use_container_width=True,
                                disabled=not can_edit or management_events is None or not management_configured(st.secrets))
                            if saved:
                                try:
                                    event={'tipo':'anomalia','mes':row['Fecha_dt'].strftime('%Y-%m'),
                                        'clave':key,'valor':choice,'detalle':note,'referencia':row['bdrid'],
                                        'origen':row['Fuente_semanal']}
                                    if choice=='Fraude' and not note.strip():
                                        raise ValueError('Para clasificar como Fraude, escribí el motivo en Observación.')
                                    append_events(st.secrets,[event],username=editor_name)
                                    _management_events_cached.clear()
                                    st.success('Clasificación guardada en Drive.')
                                    st.rerun()
                                except Exception as exc:st.error('No se guardó: '+str(exc))
                        st.caption('Origen: '+str(row['Fuente_semanal'])[:120])
            detailcols=['Fecha_etiqueta','Promotor','Supervisor','Pilar de la Liga','Variable de la Liga',
                        'Detalle Tarea','Dictamen','Observacion','Estado','POC ID','bdrid',
                        'Coincide_tarea','Fuente_repeticiones','FotoURL']
            st.dataframe(ac[detailcols].rename(columns={'FotoURL':'Foto'}),hide_index=True,
                         use_container_width=True,height=300,
                         column_config={'Foto':st.column_config.LinkColumn('Foto',display_text='Ampliar')})
            st.download_button('Exportar anomalías revisadas (CSV)',
                ac[detailcols].to_csv(index=False,sep=';').encode('utf-8-sig'),
                file_name=f'BEES_Anomalias_{month}.csv',mime='text/csv')
        else:
            st.info('No hay anomalías para estos filtros.')
        if not can_edit:
            st.caption('Clasificaciones en modo lectura. Para guardar, configurá la conexión privada con Drive e ingresá la clave de editor en la barra lateral.')
        st.caption('“Fraude” es un dictamen interno ingresado por una persona autorizada; el tablero no determina fraude automáticamente.')

with action_plans_tab:
    st.subheader('Objetivo mensual y planes de acción por promotor')
    st.caption('Comparación por promotor con el objetivo guardado para el mes elegido. Un diagnóstico identifica el pilar que más aporta al desvío y las tareas que concentran las invalidaciones.')
    if not months or manual is not None:
        st.warning('Para guardar el objetivo y los planes, seleccioná un mes desde Drive; la previsualización manual no guarda datos.')
    else:
        prev=last_value(management_events,'objetivo',month) if management_events is not None else None
        previous_goal=float(prev['valor']) if prev is not None and prev['valor'].replace('.','',1).isdigit() else None
        top=st.columns([1,1,2])
        with top[0]:
            objective=st.number_input('Objetivo de validación (%)',min_value=0.0,max_value=100.0,
                value=previous_goal,step=0.5,format='%.2f',key=f'monthly_target_{month}',
                help='El objetivo se guarda por mes, nunca cambia la cifra oficial.')
        with top[1]:
            st.caption('Guardar valor mensual')
            if st.button('Guardar objetivo en Drive',disabled=not can_edit or objective is None or management_events is None,
                         use_container_width=True,key='save_target'):
                try:
                    append_events(st.secrets,[{'tipo':'objetivo','mes':month,'clave':'global','valor':objective}],username=editor_name)
                    _management_events_cached.clear()
                    st.success('Objetivo mensual guardado.');st.rerun()
                except Exception as exc:st.error('No se guardó el objetivo: '+str(exc))
        with top[2]:
            official_or_estimated=st.radio('Resultado a comparar',
                ['Oficial','Cierre proyectado'] if filtered_reviews is not None else ['Oficial'],
                horizontal=True,key=f'action_compare_{month}')
            st.caption('El proyectado suma solo fallas de algoritmo reconocidas y aún no incorporadas en BEES.')
        if objective is None:
            st.info('Ingresá el objetivo mensual arriba para identificar promotores bajo la meta. Sin objetivo no se calcula una brecha.')
        else:
            threshold=objective/100.0
            use_projected=official_or_estimated=='Cierre proyectado'
            people=promoter_summary(f,filtered_reviews,projected=use_projected)
            below=people[(people['Resultado']<threshold) & people['Enviadas'].gt(0)].copy() if not people.empty else pd.DataFrame()
            metrics=st.columns(4)
            metrics[0].metric('Objetivo',f'{objective:.2f}%'.replace('.',','))
            metrics[1].metric('Promotores debajo',number(len(below)))
            metrics[2].metric('Promotores evaluados',number(len(people)))
            metrics[3].metric('Brecha promedio (pp)',
                f'{100*(threshold-below["Resultado"]).mean():.2f}'.replace('.',',') if not below.empty else '—')
            if states or query or poc or variables or (date_selection and len(date_selection)==2 and
                 (pd.Timestamp(date_selection[0])>df['Fecha_dt'].min() or pd.Timestamp(date_selection[1])<df['Fecha_dt'].max())):
                st.warning('Hay filtros de estado, variable, fecha o búsqueda activos. Los porcentajes se calculan sobre ese subconjunto, no necesariamente sobre todas las tareas del mes.')
            if not below.empty:
                st.subheader('Promotores bajo objetivo · resultado y plan de acción')
                stored_plans={}
                if management_events is not None and not management_events.empty:
                    x=management_events[(management_events['tipo']=='plan')&(management_events['mes']==month)]
                    stored_plans={str(r['clave']):r['valor'] for _,r in x.drop_duplicates('clave',keep='last').iterrows()}
                below['Brecha (pp)']=(threshold-below['Resultado'])*100
                below['Plan de acción']=below['bdrid'].map(stored_plans).fillna('')
                # El diagnóstico se compone en el mismo renglón de la tabla para actuar sin abrir otra vista.
                explanations=[]
                for bdr in below['bdrid']:
                    d=diagnostic(f,bdr,threshold,filtered_reviews,projected=use_projected)
                    explanations.append(d['texto'])
                below['Diagnóstico']=explanations
                view=below[['bdrid','Promotor','Supervisor','Enviadas','Validadas','Inválidas',
                            'Justificadas','Recuperables','Resultado','Brecha (pp)','Diagnóstico','Plan de acción']].copy()
                view['Resultado']=view['Resultado'].map(lambda x:f'{x*100:.2f}%'.replace('.',','))
                view['Brecha (pp)']=view['Brecha (pp)'].map(lambda x:f'{x:+.2f}'.replace('.',','))
                st.caption('Podés escribir o cambiar el plan directamente en la última columna. Los restantes campos son solo lectura. Las ediciones se conservan únicamente cuando presionás Guardar planes.')
                with st.form('action_plan_table_form'):
                    edited=st.data_editor(view,hide_index=True,use_container_width=True,
                        num_rows='fixed',disabled=[c for c in view.columns if c!='Plan de acción'],
                        column_config={'Plan de acción':st.column_config.TextColumn('Plan de acción',width='large',max_chars=12000),
                                       'Diagnóstico':st.column_config.TextColumn('Causa principal',width='large')},
                        height=min(650,90+len(view)*38),key=f'action_plan_grid_{month}')
                    save_plans=st.form_submit_button('Guardar planes de acción en Drive',type='primary',
                        disabled=not can_edit or management_events is None)
                    if save_plans:
                        changed=[]
                        for i in range(len(edited)):
                            bdr=str(view.iloc[i]['bdrid']);new=str(edited.iloc[i]['Plan de acción']).strip()
                            if new!=stored_plans.get(bdr,'').strip():
                                changed.append({'tipo':'plan','mes':month,'clave':bdr,'valor':new,
                                                'referencia':str(view.iloc[i]['Promotor'])})
                        if not changed:st.info('No hay planes modificados para guardar.')
                        else:
                            try:
                                append_events(st.secrets,changed,username=editor_name)
                                _management_events_cached.clear()
                                st.success(f'{len(changed)} plan(es) guardado(s) en Drive.');st.rerun()
                            except Exception as exc:st.error('No se pudieron guardar los planes: '+str(exc))
                st.download_button('Exportar plan y diagnóstico (CSV)',
                    view.to_csv(index=False,sep=';').encode('utf-8-sig'),
                    file_name=f'BEES_planes_{month}.csv',mime='text/csv')
                st.subheader('Detalle por pilar y tareas del promotor')
                selected=st.selectbox('Analizar promotor',below['bdrid'].tolist(),
                    format_func=lambda b:below.set_index('bdrid').loc[b,'Promotor']+' · '+b,key='action_detail_prom')
                d=diagnostic(f,selected,threshold,filtered_reviews,projected=use_projected)
                st.markdown(d['texto'])
                pil_df=d['pilares'].copy()
                pil_df['% Validación']=pil_df['Resultado usado']
                display_table(pil_df[['Pilar de la Liga','Enviadas del cálculo','Validadas del cálculo',
                                       'Inválidas','Justificadas','% Validación','Déficit neto (tareas)']].rename(columns={
                                           'Enviadas del cálculo':'Enviadas','Validadas del cálculo':'Validadas'}),height=230)
                top_tasks=d.get('tareas_criticas',pd.DataFrame())
                if not top_tasks.empty:
                    st.markdown('**Tareas con más invalidaciones del pilar que más aporta a la brecha**')
                    display_table(top_tasks[['Variable de la Liga','Detalle Tarea','Enviadas (oficial)',
                                             'Inválidas','Justificadas','% Invalidación']].head(8),height=320)
            else:
                st.success('No hay promotores por debajo del objetivo con los filtros aplicados.')
            if not can_edit:st.caption('Para guardar objetivos o planes, ingresá la clave de editor en la barra lateral.')

with details:
    st.subheader('Detalle de tareas y exportación')
    with st.expander('Definiciones de indicadores',expanded=False):
        st.markdown('''
- **Completada:** `Completada = 1`.
- **Validada:** `Completada = 1` y `Validada = 1`.
- **Inválida:** `Completada = 1` y `Validada = 0`. Esta es una interpretación operativa de la exportación; no se incluye la tarea no realizada.
- **Justificada:** `Completada = 0` y `Justificacion = 1`.
- **Pendiente:** `Completada = 0` y `Justificacion = 0`.
- **BONUS:** tarea cuyo detalle contiene la palabra `BONUS`.
- **Enviada oficial:** tarea estándar, o BONUS validada. Una BONUS inválida o justificada se excluye del denominador oficial, pero se conserva en el resto del tablero.
- **% validación oficial:** validadas / enviadas oficiales (coincide con el 74,50 % del reporte oficial de septiembre 2026).
- **% invalidación operativa:** inválidas / completadas. Incluye las BONUS inválidas para permitir su revisión.
- **% justificación operativa:** justificadas / todas las tareas del Excel, incluidas las BONUS justificadas.

Todas las métricas respetan los filtros globales. La fecha del reporte no implica que contenga todos los días del mes: se conservan los filtros aplicados en la fuente.
''')
    usecols=['Fecha_etiqueta','Distri/Directa','Canal Agrupado','Pilar de la Liga','Variable de la Liga','Detalle Tarea',
             'Estado','Bonus_bool','Enviada_oficial_bool','Promotor','Supervisor','POC ID','Justificacion Motivo','Visita Valida','ID Tarea','FotoURL']
    st.dataframe(f[usecols].rename(columns={'Fecha_etiqueta':'Fecha','FotoURL':'Foto (enlace)','Bonus_bool':'Es BONUS','Enviada_oficial_bool':'Cuenta en KPI oficial'}),use_container_width=True,height=530,hide_index=True,
                 column_config={'Foto (enlace)':st.column_config.LinkColumn('Foto (enlace)',display_text='Abrir foto')})
    export=f[usecols].rename(columns={'Fecha_etiqueta':'Fecha','FotoURL':'Foto (enlace)','Bonus_bool':'Es BONUS','Enviada_oficial_bool':'Cuenta en KPI oficial'})
    st.download_button('Descargar tareas filtradas (CSV para Excel)',
                       data=export.to_csv(index=False,sep=';',encoding='utf-8-sig').encode('utf-8-sig'),
                       file_name='BEES_Force_tareas_filtradas.csv',mime='text/csv',type='primary')
    with st.expander('Control de calidad de la fuente'):
        st.write('Registros leídos:',number(quality['rows_in_export']))
        st.write('Filas de notas/pie excluidas:',number(quality['footer_rows']))
        st.write('ID Tarea duplicados consolidados:',number(quality['duplicate_ids_removed']))
        st.write('Fechas no reconocidas:',number(quality['invalid_dates']))
        st.write('Fotografías con enlace válido:',number(quality['image_count']))
        st.write('Inconsistencias en los indicadores originales:',number(quality['inconsistent_status']))
        if quality['origin_filter_description']:
            st.markdown('**Filtros aplicados en el archivo de origen:**')
            st.code(quality['origin_filter_description'],language=None)
        if quality['inconsistent_status']:
            st.warning('Se detectaron filas con indicadores contradictorios. Consultá la definición de estados y la exportación original.')
