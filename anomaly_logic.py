"""Anomalías BEES Force: solo DDV, deduplicación semanal y vínculo por foto/ID Tarea.

No toma la palabra 'anomaly_detected' como dictamen de fraude o falla.
"""
from __future__ import annotations
import hashlib
import re
import unicodedata
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
import pandas as pd
from bees_logic import valid_photo_url, _parse_dates

DDV_ID = '70549'
DDV_NAME = 'DISTRIBUIDORA DEL VALLE S.A.'
COLUMNS = ['PocId','bdr_id','task_executed_datetime','task_name','photo_image_url',
           'anomaly_detected','wholesaler_id','wholesaler_desc','region']
PHOTO_ID = re.compile(r'/photo_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:-|\.|$)',re.I)
ANOMALY_CHOICES = ['Pendiente','Falla de algoritmo','Inválida','Fraude']


def clean(s):
    s=unicodedata.normalize('NFKD',str(s).strip().upper())
    return ''.join(c for c in s if not unicodedata.combining(c))


def read_anomalies(file_or_path, name=''):
    label=(name or getattr(file_or_path,'name','') or str(file_or_path)).lower()
    if label.endswith(('.xlsx','.xlsm')):
        return pd.read_excel(file_or_path, sheet_name='base', dtype=str, engine='openpyxl',usecols='A:I')
    if label.endswith('.csv'):
        return pd.read_csv(file_or_path,dtype=str,encoding='utf-8-sig')
    raise ValueError('El reporte de anomalías debe ser XLSX o CSV y contener la hoja base.')


def photo_id(url):
    if not url:return ''
    m=PHOTO_ID.search(urlsplit(url).path)
    return m.group(1).lower() if m else ''


def anomaly_key(row):
    p=photo_id(row['FotoURL'])
    if p:return p
    # No usar SAS de URL en huella: la firma cambia entre exportaciones.
    path=urlsplit(row['FotoURL']).path
    raw='|'.join([row['bdr_id'],row['PocId'],str(row['Fecha_dt'].date()),clean(row['task_name']),path])
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


def prepare_anomalies(raw, base, *, source=''):
    missing=set(COLUMNS)-set(raw.columns)
    if missing:raise ValueError('Faltan columnas en hoja base de anomalías: '+', '.join(sorted(missing)))
    data=raw[COLUMNS].copy()
    for col in COLUMNS:
        data[col]=data[col].fillna('').astype(str).str.strip()
    # Un reporte mezcla ~100 distribuidores. Selección estricta por código o nombre.
    ddc=data['wholesaler_id'].str.replace(r'\.0$','',regex=True).eq(DDV_ID)
    name=data['wholesaler_desc'].map(clean).str.contains('DISTRIBUIDORA DEL VALLE',regex=False)
    data=data.loc[ddc | name].copy()
    data=data[data['photo_image_url'].ne('')].copy()
    data['FotoURL']=data['photo_image_url'].map(valid_photo_url)
    data=data[data['FotoURL'].ne('')].copy()
    data['Fecha_dt']=_parse_dates(data['task_executed_datetime'])
    data=data[data['Fecha_dt'].notna()].copy()
    data['Foto_ID']=data['FotoURL'].map(photo_id)
    data['Anomalia_key']=data.apply(anomaly_key,axis=1)
    data['ID Tarea']=data['Foto_ID']
    data['PocId']=data['PocId'].str.replace(r'\.0$','',regex=True)
    data['Distri/Directa']=DDV_NAME
    data['Detalle Tarea']=data['task_name']
    data['POC ID']=data['PocId']
    data['bdrid']=data['bdr_id']
    data['Fuente_semanal']=source
    data['Fuente_repeticiones']=1
    return enrich_anomalies(data,base)


def combine_anomalies(frames, base):
    if not frames:return enrich_anomalies(pd.DataFrame(columns=COLUMNS+['Anomalia_key','FotoURL','Fecha_dt','ID Tarea','bdrid','Distri/Directa','Detalle Tarea','POC ID','Fuente_semanal','Fuente_repeticiones','Foto_ID']),base)
    all_records=pd.concat(frames,ignore_index=True)
    # Preserve all source files where a photo repeats; one manual verdict per photo.
    count=all_records.groupby('Anomalia_key').size()
    sources=all_records.groupby('Anomalia_key')['Fuente_semanal'].agg(lambda s:', '.join(sorted(set(s))))
    all_records=all_records.drop_duplicates('Anomalia_key',keep='last').copy()
    all_records['Fuente_repeticiones']=all_records['Anomalia_key'].map(count).astype(int)
    all_records['Fuente_semanal']=all_records['Anomalia_key'].map(sources)
    return enrich_anomalies(all_records,base)


def enrich_anomalies(rows, base):
    rows=rows.copy()
    original=['ID Tarea','Promotor','Supervisor','Pilar de la Liga','Variable de la Liga','Canal Agrupado','Estado','POC ID','bdrid']
    b=base[[c for c in original if c in base]].copy()
    if 'ID Tarea' not in b:raise ValueError('La bajada de tareas requiere ID Tarea.')
    b['ID Tarea']=b['ID Tarea'].str.lower()
    # Quitar atributos base existentes si se llama combine sobre filas ya enriquecidas.
    for c in ['Promotor','Supervisor','Pilar de la Liga','Variable de la Liga','Canal Agrupado','Estado','Coincide_tarea']:
        if c in rows:rows=rows.drop(columns=[c])
    merged=rows.merge(b.drop(columns=['POC ID','bdrid'],errors='ignore'),on='ID Tarea',how='left',indicator=True,validate='many_to_one')
    merged['Coincide_tarea']=merged['_merge'].eq('both')
    merged=merged.drop(columns=['_merge'])
    promoters=base[['bdrid','Promotor','Supervisor']].copy() if {'bdrid','Promotor','Supervisor'}.issubset(base.columns) else pd.DataFrame(columns=['bdrid','Promotor','Supervisor'])
    promoters=promoters.dropna().drop_duplicates()
    unique=promoters.groupby('bdrid').agg({'Promotor':'nunique','Supervisor':'nunique'})
    valid_ids=unique[(unique['Promotor']==1)&(unique['Supervisor']==1)].index
    promoters=promoters[promoters['bdrid'].isin(valid_ids)].drop_duplicates('bdrid')
    promoters=promoters.rename(columns={'Promotor':'Promotor_por_bdr','Supervisor':'Supervisor_por_bdr'})
    merged=merged.merge(promoters,on='bdrid',how='left',validate='many_to_one')
    for col in ['Promotor','Supervisor']:
        merged[col]=merged[col].fillna(merged[col+'_por_bdr']).fillna('Sin identificar')
    merged=merged.drop(columns=['Promotor_por_bdr','Supervisor_por_bdr'])
    # No inventar métricas, canales o estados cuando no se encontró la tarea.
    for col in ['Pilar de la Liga','Variable de la Liga','Canal Agrupado','Estado']:
        merged[col]=merged[col].fillna('No disponible')
    merged['Pilar de la Liga']=merged['Pilar de la Liga'].where(merged['Pilar de la Liga'].ne('No disponible'),merged['Detalle Tarea'].str.extract(r'^\s*([A-Za-zÁÉÍÓÚ]+):',expand=False).fillna('No disponible').str.upper())
    merged['Fecha_etiqueta']=merged['Fecha_dt'].dt.strftime('%d/%m/%Y').fillna('Sin fecha')
    return merged


def with_verdicts(anomalies, events):
    result=anomalies.copy()
    if events is None or events.empty:
        result['Dictamen']='Pendiente';result['Observacion']=''
        return result
    e=events[(events['tipo']=='anomalia')].drop_duplicates(['mes','clave'],keep='last')
    e=e[['mes','clave','valor','detalle']].rename(columns={'clave':'Anomalia_key','valor':'Dictamen','detalle':'Observacion'})
    result['mes']=result['Fecha_dt'].dt.strftime('%Y-%m')
    result=result.merge(e,on=['mes','Anomalia_key'],how='left',validate='many_to_one')
    result['Dictamen']=result['Dictamen'].where(result['Dictamen'].isin(ANOMALY_CHOICES),'Pendiente')
    result['Observacion']=result['Observacion'].fillna('')
    return result


def filter_anomalies(data, *, distributors=None, channels=None, pillars=None, supervisors=None,
                     promoters=None, variables=None, states=None, dates=None, text_q='',poc_q='', verdicts=None):
    mask=pd.Series(True,index=data.index)
    for col,selection in [('Distri/Directa',distributors),('Canal Agrupado',channels),('Pilar de la Liga',pillars),
                          ('Supervisor',supervisors),('Promotor',promoters),('Variable de la Liga',variables),('Estado',states),('Dictamen',verdicts)]:
        if selection:mask &= data[col].isin(selection)
    if dates is not None and len(dates)==2:
        mask &= data['Fecha_dt'].between(pd.Timestamp(dates[0]),pd.Timestamp(dates[1]))
    if text_q.strip():mask &= data['Detalle Tarea'].str.contains(text_q.strip(),regex=False,case=False,na=False)
    if poc_q.strip():mask &= data['POC ID'].str.contains(poc_q.strip(),regex=False,case=False,na=False)
    return data.loc[mask].copy()
