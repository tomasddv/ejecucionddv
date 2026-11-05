"""Cierre de BEES Force en un solo archivo comprimido, sin imágenes binarias.

El archivo contiene tareas preparadas, tickets conciliados, dictámenes de anomalía,
planes y objetivos (incluido el historial de eventos) y referencias a evidencias.
No realiza escrituras automáticas a Google Drive.
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import pandas as pd
from bees_logic import fill_missing_pillars

SNAPSHOT_RE = re.compile(r'^BEES_FORCE_CIERRE_(20\d{2}-(?:0[1-9]|1[0-2]))\.json\.gz$', re.I)
SNAPSHOT_VERSION = 1


def month_for_name(name):
    m = SNAPSHOT_RE.fullmatch(Path(str(name)).name)
    return m.group(1) if m else None


TASK_FIELDS = [
    'ID Tarea','Fecha_dt','Distri/Directa','Promotor','Supervisor','bdrid',
    'Pilar de la Liga','Pilar_fuente','Pilar_inferido_bool','Canal Agrupado','Variable de la Liga','Detalle Tarea',
    'Estado','FotoURL','POC ID','Justificacion Motivo','Completada_bool',
    'Validada_bool','Invalida_bool','Justificada_bool','Pendiente_bool',
    'Bonus_bool','Bonus_excluida_bool','Enviada_oficial_bool',
]


def _serialize_frame(frame):
    if frame is None:
        return []
    # Campos originales procesados: guardamos registros para preservar filtros,
    # rankings y diagnósticos sin releer Excel. Las fotos son solo URL, no bytes.
    safe = frame.copy()
    for col in safe.select_dtypes(include=['datetime64[ns]', 'datetimetz']).columns:
        safe[col] = safe[col].dt.strftime('%Y-%m-%dT%H:%M:%S').fillna('')
    safe = safe.astype(object).where(pd.notna(safe), None)
    return safe.to_dict(orient='records')


def build_snapshot(month, tasks, *, reviews=None, anomalies=None, events=None, sources=None):
    if not re.fullmatch(r'20\d{2}-(?:0[1-9]|1[0-2])', month):
        raise ValueError('Mes inválido para cierre')
    if tasks is None or tasks.empty:
        raise ValueError('No se puede cerrar un mes sin tareas')
    dates = pd.to_datetime(tasks['Fecha_dt'], errors='coerce')
    wrong = dates.notna() & dates.dt.strftime('%Y-%m').ne(month)
    if wrong.any():
        raise ValueError(f'La bajada contiene {int(wrong.sum())} tareas de otros meses')
    scoped = events[events['mes'].eq(month)].copy() if events is not None and not events.empty else None
    payload = {
        'schema_version': SNAPSHOT_VERSION,
        'month': month,
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source_labels': sources or {},
        'tasks': _serialize_frame(tasks[[c for c in TASK_FIELDS if c in tasks.columns]]),
        'reviews': _serialize_frame(reviews),
        'anomalies': _serialize_frame(anomalies),
        'events': _serialize_frame(scoped),
    }
    return gzip.compress(json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8'), compresslevel=6)


def _restore_frame(rows, *, kind):
    frame = pd.DataFrame(rows)
    for date_field in ('Fecha_dt', 'Fecha_ticket_dt'):
        if date_field in frame:
            frame[date_field] = pd.to_datetime(frame[date_field], errors='coerce')
    if kind == 'tasks':
        frame = fill_missing_pillars(frame)
        bool_fields = ('Completada_bool','Validada_bool','Invalida_bool','Justificada_bool',
                       'Pendiente_bool','Bonus_bool','Bonus_excluida_bool','Enviada_oficial_bool',
                       'Pilar_inferido_bool','Pilar_sin_identificar_bool')
    elif kind == 'reviews':
        frame = fill_missing_pillars(frame)
        bool_fields = ('Recuperable_bool','Ya_validada_bool','Falla_algoritmo_bool',
                       'Invalida_confirmada_bool','Sin_dictamen_bool','Revisada_bool',
                       'Bonus_excluida_bool','Enviada_oficial_bool','Coincide_fuente_bool')
    else:
        if kind == 'anomalies':
            frame = fill_missing_pillars(frame)
        bool_fields = ('Coincide_tarea',)
    for col in bool_fields:
        if col in frame:
            frame[col] = frame[col].fillna(False).astype(bool)
    return frame


def load_snapshot(blob, expected_month=None):
    if len(blob) > 50_000_000:
        raise ValueError('Archivo de cierre demasiado grande')
    payload = json.loads(gzip.decompress(blob).decode('utf-8'))
    if payload.get('schema_version') != SNAPSHOT_VERSION:
        raise ValueError('Versión de cierre no compatible')
    month = payload.get('month', '')
    if expected_month is not None and month != expected_month:
        raise ValueError(f'Cierre de {month}, se esperaba {expected_month}')
    return {
        'month': month,
        'created_utc': payload.get('created_utc', ''),
        'source_labels': payload.get('source_labels', {}),
        'tasks': _restore_frame(payload.get('tasks', []),kind='tasks'),
        'reviews': _restore_frame(payload.get('reviews', []),kind='reviews'),
        'anomalies': _restore_frame(payload.get('anomalies', []),kind='anomalies'),
        'events': _restore_frame(payload.get('events', []),kind='events'),
    }


def file_name(month):
    return f'BEES_FORCE_CIERRE_{month}.json.gz'


def index_snapshots(files):
    result={}
    for f in files:
        month=month_for_name(f.get('name',''))
        if month:
            prior=result.get(month)
            if prior is None or (f.get('modifiedTime',''),f.get('id','')) > (prior.get('modifiedTime',''),prior.get('id','')):
                result[month]=f
    return result
