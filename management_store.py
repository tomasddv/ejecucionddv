"""Registro append-only en Google Sheets. No escribir archivos locales de Render.

Cada cambio es un evento que conserva el historial, incluso con usuarios concurrentes.
"""
from __future__ import annotations
import os
import json
from datetime import datetime,timezone
import pandas as pd
from drive_source import credentials_dict

DEFAULT_SPREADSHEET='1eC3hioLGQLb1AmerMyIhUcJAgJNS7vjjUZ-1vrjKE_Y'
FIELDS=['timestamp_utc','tipo','mes','clave','valor','detalle','usuario','referencia','origen','version']
ALLOWED_TYPES={'objetivo','anomalia','plan'}


def spreadsheet_id(secrets=None):
    val=os.getenv('BEES_GESTION_SHEET_ID','').strip()
    if not val and secrets is not None:
        try:val=str(secrets.get('BEES_GESTION_SHEET_ID','')).strip()
        except Exception:pass
    return val or DEFAULT_SPREADSHEET


def configured(secrets=None):
    return credentials_dict(secrets) is not None


def _sheets_service(secrets=None):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    data=credentials_dict(secrets)
    if not data:raise RuntimeError('Faltan credenciales de cuenta de servicio para guardar en Drive.')
    creds=service_account.Credentials.from_service_account_info(data,scopes=[
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ])
    return build('sheets','v4',credentials=creds,cache_discovery=False)


def read_events(secrets=None):
    if not configured(secrets):return pd.DataFrame(columns=FIELDS)
    svc=_sheets_service(secrets)
    result=svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id(secrets),range="'Eventos'!A2:J",valueRenderOption='UNFORMATTED_VALUE').execute()
    data=result.get('values',[])
    padded=[(list(row)+['']*len(FIELDS))[:len(FIELDS)] for row in data]
    df=pd.DataFrame(padded,columns=FIELDS)
    for col in FIELDS:df[col]=df[col].fillna('').astype(str)
    return df


def last_value(events,tipo,mes,clave='global'):
    if events is None or events.empty:return None
    x=events.loc[events['tipo'].eq(tipo)&events['mes'].eq(mes)&events['clave'].eq(clave)]
    if x.empty:return None
    return x.iloc[-1].to_dict()


def append_events(secrets,items,*,username='Editor BEES Force'):
    if not items:return None
    if not configured(secrets):raise RuntimeError('Guardado en Drive no disponible: configurá la cuenta de servicio.')
    values=[]
    when=datetime.now(timezone.utc).isoformat(timespec='seconds')
    for item in items:
        tipo=str(item['tipo']);month=str(item['mes']);key=str(item['clave']);value=str(item['valor'])
        if tipo not in ALLOWED_TYPES:raise ValueError('Tipo de evento no permitido.')
        if not len(month)==7 or month[4]!='-':raise ValueError('Mes de evento inválido.')
        if not key.strip():raise ValueError('La clave de registro está vacía.')
        if len(value)>15000:raise ValueError('Texto excesivamente extenso (máximo 15.000 caracteres).')
        values.append([when,tipo,month,key,value,str(item.get('detalle',''))[:5000],str(username)[:120],
                       str(item.get('referencia',''))[:180],str(item.get('origen','Dashboard BEES Force')), '1'])
    svc=_sheets_service(secrets)
    return svc.spreadsheets().values().append(spreadsheetId=spreadsheet_id(secrets),range="'Eventos'!A:J",
        valueInputOption='RAW',insertDataOption='INSERT_ROWS',body={'values':values}).execute()
