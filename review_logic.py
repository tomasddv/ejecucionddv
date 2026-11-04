"""Cruce entre tickets revisados y tareas BEES Force por ID Tarea.

Nunca reescribe el estado oficial. Solo una falla de algoritmo que SIGUE
inválida en la bajada aporta una recuperación adicional al cierre estimado.
"""
from __future__ import annotations

import re
import unicodedata
from io import BytesIO
from pathlib import Path

import pandas as pd
from bees_logic import _parse_dates, valid_photo_url, stats
from drive_source import months_from_name, year_from_quarter_name

STATUS_REVIEW = ['Falla de algoritmo', 'Inválida confirmada', 'Sin dictamen']
REVIEW_COLORS = {'Falla de algoritmo':'#0284c7','Inválida confirmada':'#dc2626','Sin dictamen':'#d97706'}


def _normalize(s):
    norm = unicodedata.normalize('NFKD',str(s).strip().lower())
    return ''.join(ch for ch in norm if not unicodedata.combining(ch))


def _review_status(value):
    v=_normalize(value)
    if 'falla de algoritmo' in v: return 'Falla de algoritmo'
    if v in ('invalida','invalidada','invalido','invalida confirmada'): return 'Inválida confirmada'
    return 'Sin dictamen'


def _parse_review_dates(series):
    """Respeta DD/MM/AAAA para fechas de Argentina, ISO y seriales Excel."""
    result=_parse_dates(series).copy()
    values=series.fillna('').astype(str).str.strip()
    regional=values.str.match(r'^\d{1,2}[/-]\d{1,2}[/-](?:\d{2}|20\d{2})$')
    if regional.any():
        result.loc[regional]=pd.to_datetime(values.loc[regional],dayfirst=True,errors='coerce')
    return result


def load_review_source(content, filename=None):
    name=(filename or getattr(content,'name','') or str(content)).lower()
    if name.endswith(('.xlsx','.xlsm','.xls')):
        # Q4: una hoja por mes, año inferido del nombre del libro.
        # Conservar mes por fila para seleccionar el período sin mezclar pestañas.
        tabs=pd.read_excel(content,sheet_name=None,dtype=str,engine='openpyxl')
        frames=[]
        year=year_from_quarter_name(name)
        for tab,frame in tabs.items():
            frame.columns=[str(col).strip() for col in frame.columns]
            if not {'ID Tarea','STATUS'}.issubset(frame.columns):
                continue
            tab_periods=months_from_name(tab,default_year=year)
            tab_month=next(iter(tab_periods)) if len(tab_periods)==1 else ''
            if 'Fecha' in frame:
                dates=_parse_review_dates(frame['Fecha']).dt.strftime('%Y-%m').fillna('')
            else:
                dates=pd.Series('',index=frame.index,dtype=str)
                frame['Fecha']=''
            frame['Mes_revision']=dates.where(dates.ne(''),tab_month)
            frame['Hoja_ticket']=tab
            frames.append(frame)
        if not frames:
            raise ValueError('No se encontró ninguna hoja con ID Tarea y STATUS en el archivo de tickets.')
        return pd.concat(frames,ignore_index=True)
    if name.endswith('.csv'):
        data=content.read() if hasattr(content,'read') else Path(content).read_bytes()
        if isinstance(data,str):data=data.encode('utf-8')
        for enc in ('utf-8-sig','latin1'):
            try:
                frame=pd.read_csv(BytesIO(data),dtype=str,sep=None,engine='python',encoding=enc)
                if 'Fecha' in frame:
                    frame['Mes_revision']=_parse_review_dates(frame['Fecha']).dt.strftime('%Y-%m').fillna('')
                return frame
            except UnicodeDecodeError:
                continue
    raise ValueError('El archivo de revisiones debe ser .xlsx o .csv')


def prepare_reviews(source):
    data=source.copy()
    data.columns=[str(c).strip() for c in data.columns]
    required={'ID Tarea','STATUS'}
    if not required.issubset(data):
        raise ValueError('Faltan columnas del ticket: '+', '.join(sorted(required-set(data.columns))))
    original=len(data)
    data=data[data['ID Tarea'].notna() & data['ID Tarea'].astype(str).str.strip().ne('')].copy()
    data['ID Tarea']=data['ID Tarea'].astype(str).str.strip()
    dup=int(data['ID Tarea'].duplicated(keep='last').sum())
    data=data.drop_duplicates(subset='ID Tarea',keep='last')
    for c in ['Fecha','Distri/Directa','Promotor','Supervisor ID','POC ID','Detalle Tarea',
              'Pilar de la Liga','Variable de la Liga','Canal Agrupado','Img','FOTO']:
        if c not in data:data[c]=''
        data[c]=data[c].fillna('').astype(str).str.strip()
    data['STATUS_original']=data['STATUS'].fillna('').astype(str).str.strip()
    data['Estado_revision']=data['STATUS_original'].map(_review_status)
    data['Revisada_bool']=data['Estado_revision'].ne('Sin dictamen')
    data['Falla_algoritmo_bool']=data['Estado_revision'].eq('Falla de algoritmo')
    data['Invalida_confirmada_bool']=data['Estado_revision'].eq('Inválida confirmada')
    data['Sin_dictamen_bool']=data['Estado_revision'].eq('Sin dictamen')
    data['Fecha_ticket_dt']=_parse_review_dates(data['Fecha'])
    data['Foto_ticket_URL']=data.apply(lambda r:valid_photo_url(r['Img']) or valid_photo_url(r['FOTO']),axis=1)
    return data,{'registros':original,'duplicados':dup,'sin_id':original-len(data)-dup,
                 'sin_dictamen':int(data['Sin_dictamen_bool'].sum()),
                 'valores_no_reconocidos':data.loc[data['Sin_dictamen_bool'],'STATUS_original'].value_counts().to_dict()}


def reconcile_reviews(base, reviews):
    """Preserva el ticket aunque no exista en la bajada (marca no conciliado).

    Utiliza atributos de la bajada cuando hay correspondencia para que filtros,
    rankings y el cierre estimado compartan la misma población.
    """
    if reviews['ID Tarea'].duplicated().any():
        raise ValueError('Tickets con ID Tarea repetido: normalizá antes de cruzar.')
    original_fields=['ID Tarea','Estado','Fecha_dt','Distri/Directa','Promotor','Supervisor',
        'Canal Agrupado','Pilar de la Liga','Variable de la Liga','Detalle Tarea','POC ID',
        'FotoURL','Bonus_bool','Bonus_excluida_bool','Enviada_oficial_bool']
    avail=[c for c in original_fields if c in base.columns]
    result=reviews.merge(base[avail],on='ID Tarea',how='left',indicator=True,suffixes=('_ticket','_base'),validate='one_to_one')
    result['Coincide_fuente_bool']=result['_merge'].eq('both')
    result['Estado_origen']=result['Estado'].fillna('No encontrada en bajada')
    fallback={'Distri/Directa':'Distri/Directa','Promotor':'Promotor',
      'Canal Agrupado':'Canal Agrupado','Pilar de la Liga':'Pilar de la Liga',
      'Variable de la Liga':'Variable de la Liga','Detalle Tarea':'Detalle Tarea','POC ID':'POC ID'}
    for k,ticket_col in fallback.items():
        b=k+'_base'; t=ticket_col+'_ticket'
        if b not in result:result[b]=''
        if t not in result: result[t]=''
        result[k]=result[b].fillna('').astype(str).str.strip()
        is_blank=result[k].eq('')
        result.loc[is_blank,k]=result.loc[is_blank,t].fillna('').astype(str).str.strip()
    result['Supervisor']=result.get('Supervisor',pd.Series(index=result.index,dtype=str)).fillna('').astype(str).str.strip()
    result.loc[result['Supervisor'].eq(''),'Supervisor']=result.loc[result['Supervisor'].eq(''),'Supervisor ID'].apply(lambda s:'Supervisor '+str(s) if str(s) else 'Sin supervisor')
    result['Fecha_dt']=result['Fecha_dt'].combine_first(result['Fecha_ticket_dt'])
    result['Fecha_etiqueta']=result['Fecha_dt'].dt.strftime('%d/%m/%Y').fillna('Sin fecha')
    result['Estado']=result['Estado_origen']
    result['FotoURL']=result['FotoURL'].fillna('').astype(str).str.strip()
    result.loc[result['FotoURL'].eq(''),'FotoURL']=result.loc[result['FotoURL'].eq(''),'Foto_ticket_URL']
    result['Bonus_bool']=result['Bonus_bool'].fillna(False).astype(bool)
    result['Bonus_excluida_bool']=result['Bonus_excluida_bool'].fillna(False).astype(bool)
    result['Enviada_oficial_bool']=result['Enviada_oficial_bool'].fillna(False).astype(bool)
    result['Recuperable_bool']=result['Falla_algoritmo_bool'] & result['Estado_origen'].eq('Inválida') & result['Coincide_fuente_bool']
    result['Ya_validada_bool']=result['Falla_algoritmo_bool'] & result['Estado_origen'].eq('Validada') & result['Coincide_fuente_bool']
    result['Sin_correspondencia_bool']=~result['Coincide_fuente_bool']
    result['Conflicto_bool']=result['Invalida_confirmada_bool'] & result['Estado_origen'].eq('Validada') & result['Coincide_fuente_bool']
    result['Conciliacion']='Pendiente de dictamen'
    result.loc[result['Invalida_confirmada_bool'],'Conciliacion']='Inválida confirmada'
    result.loc[result['Falla_algoritmo_bool'],'Conciliacion']='Falla de algoritmo'
    result.loc[result['Ya_validada_bool'],'Conciliacion']='Ya figura validada (no suma)'
    result.loc[result['Recuperable_bool'],'Conciliacion']='Recuperable (suma al estimado)'
    result.loc[result['Conflicto_bool'],'Conciliacion']='Ticket inválido / bajada validada'
    result.loc[result['Sin_correspondencia_bool'],'Conciliacion']='Sin coincidencia en bajada'
    return result


def review_metrics(ticket_rows):
    return {
      'Tickets':len(ticket_rows),'Revisadas':int(ticket_rows['Revisada_bool'].sum()),
      'Fallas de algoritmo':int(ticket_rows['Falla_algoritmo_bool'].sum()),
      'Inválidas confirmadas':int(ticket_rows['Invalida_confirmada_bool'].sum()),
      'Sin dictamen':int(ticket_rows['Sin_dictamen_bool'].sum()),
      'Recuperables':int(ticket_rows['Recuperable_bool'].sum()),
      'Ya validadas':int(ticket_rows['Ya_validada_bool'].sum()),
      'Sin correspondencia':int(ticket_rows['Sin_correspondencia_bool'].sum()),
      'Conflictos':int(ticket_rows['Conflicto_bool'].sum()),
    }


def estimated_close(base_filtered, tickets_filtered):
    """Retorna indicador oficial inalterado y proyección sin doble conteo.

    Las BONUS inválidas no están en denominador oficial. Si se recuperan,
    pasan a ser validadas Y recién entonces entran también al denominador.
    """
    official=stats(base_filtered)
    eligible=tickets_filtered.loc[tickets_filtered['Recuperable_bool']]
    # El cálculo se basa en ID: base filtrada debe contener esos IDs.
    eligible=eligible[eligible['ID Tarea'].isin(base_filtered['ID Tarea'])]
    new_ids=int(eligible['ID Tarea'].nunique())
    added_bonus=int(eligible.drop_duplicates('ID Tarea')['Bonus_excluida_bool'].sum())
    projected_valid=official['Validadas']+new_ids
    projected_sent=official['Enviadas (oficial)']+added_bonus
    return {
      'validadas_oficiales':official['Validadas'],
      'enviadas_oficiales':official['Enviadas (oficial)'],
      'porcentaje_oficial':official['% Validación'],
      'recuperaciones_adicionales':new_ids,
      'bonus_recuperadas':added_bonus,
      'validadas_estimadas':projected_valid,
      'enviadas_estimadas':projected_sent,
      'porcentaje_estimado':projected_valid/projected_sent if projected_sent else 0,
    }


def ranking_reviews(reviews,group_by):
    keys=[group_by] if isinstance(group_by,str) else group_by
    cols=keys+['Tickets','Revisadas','Fallas de algoritmo','Inválidas confirmadas','Sin dictamen','Recuperables','Ya validadas','% fallas entre revisadas']
    if reviews.empty:return pd.DataFrame(columns=cols)
    grouped=reviews.groupby(keys,dropna=False).agg(
      Tickets=('ID Tarea','count'),Revisadas=('Revisada_bool','sum'),
      **{'Fallas de algoritmo':('Falla_algoritmo_bool','sum'),
      'Inválidas confirmadas':('Invalida_confirmada_bool','sum'),
      'Sin dictamen':('Sin_dictamen_bool','sum'),
      'Recuperables':('Recuperable_bool','sum'),
      'Ya validadas':('Ya_validada_bool','sum')}).reset_index()
    grouped['% fallas entre revisadas']=(grouped['Fallas de algoritmo']/grouped['Revisadas'].where(grouped['Revisadas'].ne(0))).fillna(0)
    return grouped[cols]


def filter_reviews(reviews, *, distributors=None, channels=None, pillars=None,
                   supervisors=None, promoters=None, variables=None,
                   states=None, dates=None, text_q='', poc_q=''):
    """Aplica los mismos filtros globales; tickets sin match permanecen auditables."""
    mask = pd.Series(True, index=reviews.index, dtype=bool)
    for name, selected in [
        ('Distri/Directa', distributors), ('Canal Agrupado', channels),
        ('Pilar de la Liga', pillars), ('Supervisor', supervisors),
        ('Promotor', promoters), ('Variable de la Liga', variables),
        ('Estado', states),
    ]:
        if selected:
            mask &= reviews[name].isin(selected)
    if dates and len(dates) == 2:
        mask &= reviews['Fecha_dt'].between(pd.Timestamp(dates[0]),pd.Timestamp(dates[1]), inclusive='both')
    if text_q.strip():
        mask &= reviews['Detalle Tarea'].str.contains(text_q.strip(), case=False, na=False, regex=False)
    if poc_q.strip():
        mask &= reviews['POC ID'].str.contains(poc_q.strip(), case=False, na=False, regex=False)
    return reviews.loc[mask].copy()
