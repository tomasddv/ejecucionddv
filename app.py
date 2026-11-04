"""BEES Force · Vista operativa simplificada / cierres compactos.

Streamlit: gráficos por pilar y promotor, filtros superiores, lectura diferida
por sección y cierres de un archivo que preservan planes/anomalías.
"""
from __future__ import annotations
import hmac
import html
import os
from io import BytesIO
from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st

from bees_logic import STATUS_COLORS, STATUS_ORDER, load_source, prepare, filter_data, group_summary, stats
from drive_source import (service as drive_service, folder_id as drive_folder_id, download,
                          _list_files, _index_monthly, _index_reviews, _index_anomalies,
                          choose, current_month, local_monthly_files)
from monthly_snapshot import (build_snapshot, load_snapshot, file_name, index_snapshots)
from review_logic import load_review_source, prepare_reviews, reconcile_reviews, estimated_close, review_metrics
from anomaly_logic import (read_anomalies, prepare_anomalies, combine_anomalies,
                           with_verdicts, filter_anomalies, ANOMALY_CHOICES)
from action_plan_logic import promoter_summary, diagnostic
from management_store import (read_events as store_read_events, append_events, last_value,
                              configured as management_configured)

st.set_page_config(page_title='BEES Force · DDV', page_icon='📊', layout='wide', initial_sidebar_state='collapsed')

st.markdown('''<style>
:root {color-scheme:light}
.stApp {background:#f7f9fc; color:#111827}
.stApp, .stApp p, .stApp label, .stApp h1, .stApp h2, .stApp h3,
.stApp button, .stApp input, .stApp textarea, .stApp span {color:#111827}
h1 {font-size:2rem !important; letter-spacing:-.04em}
h2, h3 {letter-spacing:-.025em}
[data-testid="stMetric"] {background:#fff;border:1px solid #e1e8f1;border-radius:16px;padding:16px;box-shadow:0 4px 20px #101d3209}
[data-testid="stMetricLabel"] *, [data-testid="stMetricValue"] * {color:#111827 !important}
.stButton button, .stDownloadButton button {border-radius:11px; border:1px solid #d4e0ef; background:#eff6ff; color:#111827}
[data-baseweb="select"] > div, [data-baseweb="input"] > div {background:#fff !important;border:1px solid #d6e2ef !important;border-radius:12px !important}
[data-baseweb="tag"] {background:#e7f0fd !important;color:#153b67 !important; border-radius:20px !important}
[data-baseweb="tag"] * {color:#153b67 !important}
[data-baseweb="popover"] *, [role="listbox"] * {color:#111827 !important}
.dash-table-wrap {border:1px solid #e3eaf3; background:#fff;border-radius:16px;padding:7px;box-shadow:0 4px 18px #1723340a;overflow:auto}
.dash-table {border-collapse:separate;border-spacing:0;width:100%;font-size:.89rem}
.dash-table th {position:sticky;top:0;background:#eef4fb;color:#18283c;text-align:left;padding:12px;white-space:nowrap;font-weight:750}
.dash-table td {border-bottom:1px solid #edf1f6;padding:11px 12px;color:#263548;background:#fff}
.dash-table tr:last-child td {border-bottom:0}
.dash-table tr:hover td {background:#f7fbff}
.photo {background:#fff;border:1px solid #e3eaf3;border-radius:16px;padding:12px;margin-bottom:14px}
.photo img {display:block;width:100%;height:205px;object-fit:contain;background:#eef3f9;border-radius:10px}
.photo p {font-size:.85rem;margin:8px 0;color:#263548}
.photo a {font-weight:700;color:#17507b;text-decoration:underline}
[data-testid="stRadio"] [role="radiogroup"] {gap:10px}
[data-testid="stRadio"] label {background:#fff;border:1px solid #e1e8f1;border-radius:13px;padding:7px 11px}
</style>''', unsafe_allow_html=True)


def n(v): return f'{int(v):,}'.replace(',','.')
def pct(v): return f'{float(v)*100:.1f}%'.replace('.',',')


def table(frame, height=360):
    if frame is None or frame.empty:
        st.info('Sin registros para los filtros elegidos.'); return
    data=frame.copy().head(100)
    for col in data.columns:
        if col.startswith('% '):
            data[col]=data[col].apply(lambda v:pct(v) if pd.notna(v) else '—')
    data=data.fillna('')
    rows=data.to_html(index=False,escape=True,classes='dash-table')
    st.markdown(f'<div class="dash-table-wrap" style="max-height:{height}px">{rows}</div>',unsafe_allow_html=True)
    if len(frame)>100:st.caption('Se muestran los primeros 100 registros. Aplicá filtros para acotar la lista.')


def chart(frame,key,title,*, horizontal=False):
    if frame is None or frame.empty:return
    top=frame.sort_values('Enviadas (oficial)',ascending=False).head(20).copy()
    vals=top.melt(id_vars=[key],value_vars=['Validadas','Inválidas','Justificadas'],var_name='Estado',value_name='Cantidad')
    axis={'y':key,'x':'Cantidad'} if horizontal else {'x':key,'y':'Cantidad'}
    fig=px.bar(vals,**axis,color='Estado',barmode='stack',orientation='h' if horizontal else 'v',
               color_discrete_map={'Validadas':'#15803d','Inválidas':'#dc2626','Justificadas':'#d97706'})
    fig.update_layout(title=dict(text=title,font=dict(color='#111827',size=17)),
        height=max(320,40*len(top)+100) if horizontal else 370,
        font=dict(color='#111827',size=12),legend=dict(orientation='h',y=1.17,title=''),
        margin=dict(l=4,r=6,t=75,b=8),paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
        xaxis_title='' if not horizontal else 'Cantidad',yaxis_title='' if horizontal else 'Tareas')
    fig.update_xaxes(tickfont=dict(color='#111827'),title_font=dict(color='#111827'))
    fig.update_yaxes(tickfont=dict(color='#111827'),title_font=dict(color='#111827'))
    st.plotly_chart(fig,use_container_width=True,config={'displayModeBar':False})


def image_card(url,promoter,detail,subtitle=''):
    def esc(s):return html.escape(str(s or ''),quote=True)
    url=esc(url)
    return f'<div class="photo"><a href="{url}" target="_blank" rel="noopener noreferrer"><img loading="lazy" referrerpolicy="no-referrer" src="{url}" alt="Evidencia"></a><p><strong>{esc(promoter)}</strong> · {esc(subtitle)}</p><p>{esc(str(detail)[:155])}</p><a href="{url}" target="_blank" rel="noopener noreferrer">Ampliar imagen</a></div>'


@st.cache_data(show_spinner=False,ttl=60)
def catalog(folder):
    svc=drive_service(st.secrets)
    return _list_files(svc,folder)


@st.cache_data(show_spinner=False,ttl=180)
def indexed_months(metadata):
    return _index_monthly(metadata,drive_service(st.secrets),read_bytes=file_bytes)


@st.cache_data(show_spinner=False,ttl=180)
def indexed_reviews(metadata):
    return _index_reviews(metadata,drive_service(st.secrets),read_bytes=file_bytes)


@st.cache_data(show_spinner=False,ttl=180)
def indexed_anomalies(metadata):
    return _index_anomalies(metadata,drive_service(st.secrets),read_bytes=file_bytes)


@st.cache_data(show_spinner=False,ttl=3600)
def parsed_snapshot(blob,month):
    return load_snapshot(blob,expected_month=month)


@st.cache_data(show_spinner=False,ttl=270)
def file_bytes(fid,modified=''):
    svc=drive_service(st.secrets)
    return download(svc,fid)


@st.cache_data(show_spinner=False,ttl=3600)
def parsed_tasks(name,blob):
    return prepare(load_source(BytesIO(blob),filename=name))[0]


@st.cache_data(show_spinner=False,ttl=3600)
def parsed_review(name,blob,month):
    data=load_review_source(BytesIO(blob),filename=name)
    if 'Mes_revision' in data:
        data=data[data['Mes_revision'].eq(month)].copy()
    return prepare_reviews(data)[0]


@st.cache_data(show_spinner=False,ttl=3600)
def parsed_anomaly(name,blob,base):
    return prepare_anomalies(read_anomalies(BytesIO(blob),name=name),base,source=name)


@st.cache_data(show_spinner=False,ttl=600)
def events_cached():
    return store_read_events(st.secrets)


def editor_password():
    secret=os.environ.get('BEES_EDITOR_PASSWORD','').strip()
    if not secret:
        try:secret=str(st.secrets.get('BEES_EDITOR_PASSWORD','')).strip()
        except Exception:pass
    return secret


st.title('BEES Force · Ejecución DDV')
st.caption('Seguimiento por pilar y promotor · Cierres históricos con planes y anomalías')

manual = None
try:
    svc=drive_service(st.secrets)
    root=drive_folder_id(st.secrets)
    files=catalog(root) if svc is not None else []
    months_available=indexed_months(files) if svc is not None else {}
    snapshots=index_snapshots(files)
except Exception as exc:
    st.error('No se pudo consultar la carpeta de Google Drive: '+str(exc))
    svc=None;files=[];months_available={};snapshots={}

months=sorted(set(months_available)|set(snapshots),reverse=True)
now=current_month()
with st.container(border=True):
    left,right=st.columns([2.5,1])
    with left:
        if months:
            month=st.selectbox('Mes',months,index=months.index(now) if now in months else 0,
                               format_func=lambda v:pd.Timestamp(v+'-01').strftime('%m/%Y'))
        else:
            month=now
            st.warning('No hay meses detectados en Drive. Podés usar la previsualización manual.')
    with right:
        if st.button('↻ Actualizar Drive',use_container_width=True):
            catalog.clear();file_bytes.clear();indexed_months.clear();indexed_reviews.clear();indexed_anomalies.clear();events_cached.clear();st.rerun()
    with st.expander('Carga manual y acceso de edición',expanded=False):
        manual=st.file_uploader('Previsualizar planatareas.xlsx (no guarda en Drive)',type=['xlsx','xlsm','csv'])
        e1,e2=st.columns(2)
        with e1:passphrase=st.text_input('Clave de editor',type='password')
        with e2:editor_name=st.text_input('Nombre del revisor',placeholder='Ej.: Supervisor 2')
        st.caption('Los datos y contraseñas no se incluyen en GitHub. Las clasificaciones y planes se guardan en Google Sheets.')

secret=editor_password()
can_edit=bool(secret and passphrase and editor_name.strip() and hmac.compare_digest(secret,passphrase))
source=None
archived=False
archive=None
if manual is not None:
    source={'name':manual.name,'id':'manual'}
    tasks_blob=manual.getvalue()
    df=parsed_tasks(source['name'],tasks_blob)
    period=df['Fecha_dt'].dropna().dt.strftime('%Y-%m').unique().tolist()
    month=period[0] if len(period)==1 else now
    st.warning('Vista previa manual: no reemplaza ningún dato de Drive.')
elif month in snapshots:
    archived=True
    source=snapshots[month]
    try:
        archive=parsed_snapshot(file_bytes(source['id'],source.get('modifiedTime','')),month)
        df=archive['tasks']
    except Exception as exc:
        st.error('No se pudo abrir el cierre consolidado: '+str(exc));st.stop()
elif month in months_available:
    source=choose(months_available,month)
    try:
        df=parsed_tasks(source['name'],file_bytes(source['id'],source.get('modifiedTime','')))
    except Exception as exc:
        st.error('Error al leer las tareas: '+str(exc));st.stop()
else:
    st.info('Subí planatareas.xlsx a la carpeta de Drive.');st.stop()

if df.empty:
    st.warning('No hay tareas en el período seleccionado.');st.stop()
if manual is None and not archived:
    actual=df['Fecha_dt'].dropna().dt.strftime('%Y-%m').unique().tolist()
    if actual!=[month]:
        st.error(f'El archivo no corresponde solo a {month}: {actual}');st.stop()

st.caption(('🔒 Cierre consolidado' if archived else '● Mes en seguimiento')+' · '+month+' · '+source['name'])

filter_opts=[('Canal (opcional)','Canal Agrupado'),('Pilar','Pilar de la Liga'),('Supervisor','Supervisor'),('Promotor','Promotor')]
cols=st.columns(4)
selections={}
for col,(label,field) in zip(cols,filter_opts):
    with col:
        selections[field]=st.multiselect(label,sorted(df[field].fillna('').unique().tolist()),placeholder='Todos',key=f'flt_{month}_{field}')

f=filter_data(df,distributors=None,channels=selections['Canal Agrupado'],
              pillars=selections['Pilar de la Liga'],supervisors=selections['Supervisor'],
              promoters=selections['Promotor'],variables=None,states=None,dates=None)
if f.empty:
    st.warning('No hay tareas para los filtros seleccionados.');st.stop()
s=stats(f)

sections=['Resumen','Promotores','Revisiones','Anomalías','Planes de acción','Fotografías','Cierre mensual']
section=st.radio('Sección',sections,horizontal=True,label_visibility='collapsed',key='selected_section')

# Diferido: únicamente consultar tickets/anomalías/eventos al entrar en la sección.
def read_tickets():
    if archived:return archive['reviews']
    if svc is None or manual is not None:return None
    mapping=indexed_reviews(files)
    if month not in mapping:return None
    item=choose(mapping,month)
    rows=parsed_review(item['name'],file_bytes(item['id'],item.get('modifiedTime','')),month)
    return reconcile_reviews(df,rows)


def get_events():
    if archived:return archive['events']
    if not management_configured(st.secrets):return pd.DataFrame()
    return events_cached()


def read_anomalies_for_month(ev):
    if archived:return archive['anomalies']
    if svc is None or manual is not None:return None
    mapping=indexed_anomalies(files)
    selected=mapping.get(month,[])
    if not selected:return None
    frames=[]
    for item in selected:
        data=parsed_anomaly(item['name'],file_bytes(item['id'],item.get('modifiedTime','')),df)
        frames.append(data)
    merged=combine_anomalies(frames,df)
    merged=merged.loc[merged['Fecha_dt'].dt.strftime('%Y-%m').eq(month)].copy()
    return with_verdicts(merged,ev)


if section == 'Resumen':
    k=st.columns(4)
    for c,label,value in zip(k,['Validación oficial','Enviadas','Validadas','Inválidas'],
                             [pct(s['% Validación']),n(s['Enviadas (oficial)']),n(s['Validadas']),n(s['Inválidas'])]):
        c.metric(label,value)
    a,b=st.columns([1.25,1])
    with a:
        st.subheader('Pilares')
        p=group_summary(f,'Pilar de la Liga').sort_values('% Validación',ascending=True)
        chart(p,'Pilar de la Liga','Ejecución por pilar')
    with b:
        st.subheader('Resultado de pilares')
        table(p[['Pilar de la Liga','Enviadas (oficial)','Validadas','Inválidas','% Validación']],height=330)
    st.caption('Las BONUS no validadas se excluyen de enviadas oficiales; permanecen en el control operativo.')

elif section == 'Promotores':
    g=group_summary(f,['Supervisor','Promotor']).sort_values('% Validación',ascending=True)
    c=st.columns(3)
    c[0].metric('Promotores',n(g['Promotor'].nunique()))
    c[1].metric('Pilar más débil',str(group_summary(f,'Pilar de la Liga').sort_values('% Validación').iloc[0]['Pilar de la Liga']))
    c[2].metric('Inválidas',n(s['Inválidas']))
    st.subheader('Resultados por promotor')
    table(g[['Supervisor','Promotor','Enviadas (oficial)','Validadas','Inválidas','% Validación']],height=550)
    with st.expander('Ver detalle por pilar'):
        p=group_summary(f,['Promotor','Pilar de la Liga']).sort_values(['Promotor','% Validación'])
        table(p[['Promotor','Pilar de la Liga','Enviadas (oficial)','Validadas','Inválidas','% Validación']],height=420)

elif section == 'Revisiones':
    st.subheader('Revisión de inválidas · Cierre proyectado')
    try:r=read_tickets()
    except Exception as exc:st.error('No se pudieron leer los tickets: '+str(exc));r=None
    if r is None or r.empty:st.info('Aún no hay tickets para este mes.')
    else:
        r=r[(r['Pilar de la Liga'].isin(selections['Pilar de la Liga']) if selections['Pilar de la Liga'] else True) &
            (r['Promotor'].isin(selections['Promotor']) if selections['Promotor'] else True) &
            (r['Supervisor'].isin(selections['Supervisor']) if selections['Supervisor'] else True) &
            (r['Canal Agrupado'].isin(selections['Canal Agrupado']) if selections['Canal Agrupado'] else True)].copy()
        result=estimated_close(f,r);rm=review_metrics(r)
        m=st.columns(3)
        m[0].metric('Validación oficial',pct(result['porcentaje_oficial']))
        m[1].metric('Fallas recuperables',n(result['recuperaciones_adicionales']))
        m[2].metric('Cierre proyectado',pct(result['porcentaje_estimado']))
        st.caption('La proyección solo suma fallas de algoritmo que todavía figuran inválidas. No altera el oficial.')
        table(r[['Promotor','Pilar de la Liga','Detalle Tarea','Estado_revision','Conciliacion']].sort_values('Promotor'),height=440)

elif section == 'Anomalías':
    st.subheader('Anomalías fotográficas · Distribuidora del Valle')
    try:
        ev=get_events()
        anomalies=read_anomalies_for_month(ev)
    except Exception as exc:
        st.error('No se pudo cargar el relevamiento: '+str(exc));anomalies=None;ev=None
    if anomalies is None or anomalies.empty:st.info('Este mes todavía no tiene un reporte de anomalías.')
    else:
        a=filter_anomalies(anomalies,pillars=selections['Pilar de la Liga'],
            supervisors=selections['Supervisor'],promoters=selections['Promotor'],
            channels=selections['Canal Agrupado'])
        m=st.columns(3)
        m[0].metric('Anomalías',n(len(a)))
        m[1].metric('Pendientes',n(a['Dictamen'].eq('Pendiente').sum()))
        m[2].metric('Falla algoritmo',n(a['Dictamen'].eq('Falla de algoritmo').sum()))
        st.markdown('**Por promotor**')
        ranking=a.groupby('Promotor',dropna=False).agg(Anomalías=('Anomalia_key','count'),
            Pendientes=('Dictamen',lambda v:int(v.eq('Pendiente').sum()))).reset_index()
        table(ranking.sort_values('Anomalías',ascending=False),height=230)
        if archived:
            st.caption('Cierre congelado: dictámenes y observaciones tal como estaban al cierre.')
            table(a[['Promotor','Pilar de la Liga','Detalle Tarea','Dictamen','Observacion']],height=330)
            enabled=st.toggle('Habilitar fotos de anomalías del cierre',value=False,key=f'anomaly_photos_{month}')
        else:
            enabled=True
            if not can_edit:
                st.caption('Para clasificar, abrí “Carga manual y acceso de edición” arriba e ingresá clave y nombre.')
        if enabled:
            page=st.number_input('Página de fotografías',min_value=1,max_value=max(1,(len(a)+5)//6),value=1)
            show=a.iloc[(page-1)*6:page*6]
            for i in range(0,len(show),3):
                cards=st.columns(3)
                for c,(_,row) in zip(cards,show.iloc[i:i+3].iterrows()):
                    with c:
                        st.markdown(image_card(row['FotoURL'],row['Promotor'],row['Detalle Tarea'],row['Pilar de la Liga']),unsafe_allow_html=True)
                        st.caption(f"Dictamen: {row['Dictamen']} · {row.get('Observacion','')}")
                        if not archived:
                            with st.form('anomaly_'+str(row['Anomalia_key'])):
                                choice=st.selectbox('Clasificación',ANOMALY_CHOICES,
                                    index=ANOMALY_CHOICES.index(row['Dictamen']))
                                note=st.text_area('Observación',value=str(row['Observacion'] or ''))
                                saved=st.form_submit_button('Guardar',disabled=not can_edit or ev is None)
                                if saved:
                                    try:
                                        if choice=='Fraude' and not note.strip():
                                            raise ValueError('Para Fraude se requiere una observación.')
                                        append_events(st.secrets,[{'tipo':'anomalia','mes':month,'clave':str(row['Anomalia_key']),
                                          'valor':choice,'detalle':note,'referencia':str(row.get('bdrid',''))}],username=editor_name)
                                        events_cached.clear();st.rerun()
                                    except Exception as exc:st.error('No se guardó: '+str(exc))
        st.caption('Las clasificaciones no modifican el resultado oficial; requieren revisión humana.')

elif section == 'Planes de acción':
    st.subheader('Promotores por debajo del objetivo')
    try:ev=get_events()
    except Exception as exc:st.error('No se pudo leer el registro de planes: '+str(exc));ev=None
    prev=last_value(ev,'objetivo',month) if ev is not None else None
    try:goal=float(prev['valor']) if prev else 80.0
    except (ValueError,TypeError):goal=80.0
    if prev is None and not archived:
        st.caption('El 80% es un valor de ejemplo. Indicá y guardá el objetivo real de este mes.')
    goal=st.number_input('Objetivo del mes (%)',min_value=0.0,max_value=100.0,value=goal,step=0.5,
                         disabled=archived,key=f'goal_{month}')
    if archived:
        st.caption('Objetivo y planes guardados dentro del cierre. Esta vista es de solo lectura.')
    elif st.button('Guardar objetivo',disabled=not can_edit or ev is None):
        try:
            append_events(st.secrets,[{'tipo':'objetivo','mes':month,'clave':'global','valor':goal}],username=editor_name)
            events_cached.clear();st.rerun()
        except Exception as exc:st.error('No se guardó el objetivo: '+str(exc))
    summary=promoter_summary(f)
    below=summary[(summary['Resultado']<goal/100) & summary['Enviadas'].gt(0)].copy()
    k=st.columns(3)
    k[0].metric('Meta',f'{goal:.1f}%'.replace('.',','))
    k[1].metric('Promotores bajo meta',n(len(below)))
    k[2].metric('Evaluados',n(len(summary)))
    plans={}
    if ev is not None and not ev.empty:
        p=ev[(ev['tipo']=='plan') & (ev['mes']==month)].drop_duplicates('clave',keep='last')
        plans=dict(zip(p['clave'],p['valor']))
    if below.empty:
        st.success('No hay promotores por debajo del objetivo con los filtros seleccionados.')
    else:
        view=below[['bdrid','Promotor','Supervisor','Enviadas','Validadas','Inválidas','Resultado']].copy()
        view['Resultado']=view['Resultado'].map(pct)
        view['Causa principal']=[diagnostic(f,b,goal/100)['texto'] for b in below['bdrid']]
        view['Plan de acción']=below['bdrid'].map(plans).fillna('')
        if archived:
            table(view[['Promotor','Supervisor','Enviadas','Validadas','Inválidas','Resultado','Causa principal','Plan de acción']],height=480)
        else:
            with st.form('edit_plans'):
                edited=st.data_editor(view,hide_index=True,use_container_width=True,
                    disabled=[c for c in view if c!='Plan de acción'],
                    column_config={'Plan de acción':st.column_config.TextColumn('Plan de acción',width='large'),
                                   'Causa principal':st.column_config.TextColumn('Causa principal',width='large')},
                    height=min(600,100+len(view)*42),key='plan_grid')
                saved=st.form_submit_button('Guardar planes',disabled=not can_edit or ev is None)
                if saved:
                    changes=[]
                    for i in range(len(edited)):
                        rid=str(view.iloc[i]['bdrid']);val=str(edited.iloc[i]['Plan de acción']).strip()
                        if val!=str(plans.get(rid,'')).strip():
                            changes.append({'tipo':'plan','mes':month,'clave':rid,'valor':val,'referencia':str(view.iloc[i]['Promotor'])})
                    if changes:
                        try:
                            append_events(st.secrets,changes,username=editor_name)
                            events_cached.clear();st.rerun()
                        except Exception as exc:st.error('No se guardaron los planes: '+str(exc))
                    else:st.info('No hay cambios para guardar.')
        st.caption('El diagnóstico identifica el pilar que más contribuye a la brecha y sus tareas inválidas.')

    if archived and plans:
        with st.expander('Planes guardados al cierre (incluye promotores que superaron la meta)',expanded=False):
            prom=summary[['bdrid','Promotor']].drop_duplicates('bdrid')
            historical=pd.DataFrame([{'bdrid':bid,'Plan de acción':txt} for bid,txt in plans.items()])
            historical=historical.merge(prom,on='bdrid',how='left')
            table(historical[['Promotor','Plan de acción']],height=350)

elif section == 'Fotografías':
    st.subheader('Galería de evidencias')
    if archived and not st.toggle('Habilitar fotografías del cierre',value=False,key=f'photos_closed_{month}'):
        st.info('Las imágenes de los meses cerrados están desactivadas. Activá el interruptor para consultarlas.')
    else:
        mode=st.selectbox('Estado',['Todas','Inválida','Validada','Justificada'])
        photos=f[(f['FotoURL'].fillna('')!='') & ((f['Estado']==mode) if mode!='Todas' else True)]
        photos=photos.sort_values('Fecha_dt',ascending=False)
        pages=max(1,(len(photos)+8)//9)
        page=st.number_input('Página',min_value=1,max_value=pages,value=1,key='photo_page')
        rows=photos.iloc[(page-1)*9:page*9]
        st.caption(f'{n(len(photos))} fotografías disponibles · Página {page}/{pages}')
        for i in range(0,len(rows),3):
            c=st.columns(3)
            for cell,(_,row) in zip(c,rows.iloc[i:i+3].iterrows()):
                with cell:st.markdown(image_card(row['FotoURL'],row['Promotor'],row['Detalle Tarea'],row['Estado']),unsafe_allow_html=True)
        if photos.empty:st.info('No hay fotos para estos filtros.')

elif section == 'Cierre mensual':
    st.subheader('Cierre mensual consolidado')
    if archived:
        st.success('Este mes ya tiene un cierre consolidado, leído desde un solo archivo.')
        st.caption('Incluye tareas, tickets, relevamiento de anomalías, dictámenes, planes y objetivo a la fecha del cierre.')
        st.caption('Para cambiar un plan después de cerrado se debe generar una nueva versión del cierre de forma explícita.')
    elif manual is not None:
        st.info('Para cerrar el mes, seleccioná una fuente de Drive en lugar de una previsualización manual.')
    else:
        st.markdown('El cierre genera **un solo archivo comprimido**. Las fotos no se descargan: conserva únicamente sus enlaces.')
        st.warning('Antes de generarlo, revisá y guardá los planes y dictámenes pendientes. El cierre reflejará el estado registrado en ese momento.')
        confirmed=st.checkbox('Confirmo que quiero generar una copia de cierre de este mes.')
        if not can_edit:
            st.caption('Para generar un cierre, ingresá la clave de editor y tu nombre en el panel de acceso de arriba.')
        if st.button('Preparar archivo de cierre',disabled=not confirmed or not can_edit):
            try:
                if not management_configured(st.secrets):
                    raise RuntimeError('No se pudo verificar la conexión a la planilla de gestión. Se evita un cierre sin planes ni dictámenes.')
                events_cached.clear()  # Obtener la versión más reciente antes de congelar.
                ev=get_events()
                rv=read_tickets()
                av=read_anomalies_for_month(ev)
                blob=build_snapshot(month,df,reviews=rv,anomalies=av,events=ev,
                    sources={'tareas':source['name'],'tickets':'registrados si disponibles','anomalias':'reportes semanales del período'})
                st.session_state['closure_package']=(month,blob)
                st.success('Cierre preparado con los planes y anomalías disponibles.')
            except Exception as exc:st.error('No se pudo preparar el cierre: '+str(exc))
        pkg=st.session_state.get('closure_package')
        if pkg and pkg[0]==month:
            st.download_button('Descargar cierre para Drive',data=pkg[1],file_name=file_name(month),
                mime='application/gzip',type='primary',disabled=not can_edit)
            st.caption('Subí este archivo a la carpeta BEES Force en Drive. No sobrescribas el Excel original: el consolidado será la fuente preferida cuando vuelvas a elegir este mes.')
        st.caption('Por las limitaciones de cuota de la cuenta de servicio, la subida del cierre a Mi unidad se hace manualmente.')
