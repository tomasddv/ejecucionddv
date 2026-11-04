"""Lógica validada para la bajada plana de tareas BEES Force.

Grano: un ID Tarea por ejecución. No identifica una foto separadamente.
"""
from __future__ import annotations

import re
import unicodedata
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

REQUIRED_COLUMNS = [
    'Fecha', 'Distri/Directa', 'Promotor', 'Supervisor ID',
    'Pilar de la Liga', 'Variable de la Liga', 'ID Tarea',
    'Detalle Tarea', 'Completada', 'Validada', 'Justificacion',
]
OPTIONAL_COLUMNS = [
    'POC ID','Marca Familia','Canal Agrupado','Visita Valida',
    'Justificacion Motivo','TaskImageUrl','Img',
]
STATUS_ORDER = ['Validada', 'Inválida', 'Justificada', 'Pendiente']
STATUS_COLORS = {
    'Validada': '#15803d', 'Inválida': '#dc2626',
    'Justificada': '#d97706', 'Pendiente': '#64748b',
}


def _normalise_text(s: str) -> str:
    t = unicodedata.normalize('NFKD', str(s).strip().lower())
    return ''.join(c for c in t if not unicodedata.combining(c))


def _parse_dates(col: pd.Series) -> pd.Series:
    """Fechas ISO/Excel; evita el overflow de pandas con columnas sin seriales."""
    numeric = pd.to_numeric(col, errors='coerce')
    valid_serial = numeric.notna() & numeric.between(1, 100000)
    serial = pd.Series(pd.NaT, index=col.index, dtype='datetime64[ns]')
    if valid_serial.any():
        serial.loc[valid_serial] = pd.to_datetime(
            numeric.loc[valid_serial], unit='D', origin='1899-12-30', errors='coerce'
        )
    actual = pd.to_datetime(
        col.where(~valid_serial), errors='coerce', format='mixed', dayfirst=False
    )
    return serial.combine_first(actual).dt.normalize()


def _is_one(col: pd.Series) -> pd.Series:
    return col.fillna('').astype(str).str.strip().str.lower().isin({'1', '1.0','true','verdadero','sí','si','yes'})


def load_source(file_or_path, filename: str | None = None) -> pd.DataFrame:
    """Lee un XLSX o CSV exportado de BEES Force; nunca infiere los estados del enlace."""
    name = (filename or getattr(file_or_path, 'name', '') or str(file_or_path)).lower()
    if name.endswith(('.xlsx','.xlsm','.xls')):
        return pd.read_excel(file_or_path, dtype=str, engine='openpyxl')
    if name.endswith('.csv'):
        data = file_or_path.read() if hasattr(file_or_path, 'read') else Path(file_or_path).read_bytes()
        if isinstance(data, str): data = data.encode('utf-8')
        try:
            return pd.read_csv(BytesIO(data), dtype=str, sep=None, engine='python', encoding='utf-8-sig')
        except UnicodeDecodeError:
            return pd.read_csv(BytesIO(data), dtype=str, sep=None, engine='python', encoding='latin1')
    raise ValueError('Formato no admitido: cargá un archivo Excel (.xlsx) o CSV.')


def prepare(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Limpia filas de filtros al pie; elimina duplicados y calcula partición excluyente."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError('Faltan columnas en la bajada: ' + ', '.join(missing))
    for c in OPTIONAL_COLUMNS:
        if c not in df.columns: df[c] = ''
    origin_filters = [v for v in df['Fecha'].dropna().astype(str) if 'filtros aplicados' in _normalise_text(v)]
    total_raw = len(df)
    # La exportación agrega filas de pie con comentarios de filtros, y pueden existir filas vacías.
    df = df[df['ID Tarea'].notna() & df['ID Tarea'].astype(str).str.strip().ne('')].copy()
    df['ID Tarea'] = df['ID Tarea'].astype(str).str.strip()
    footer_rows = total_raw - len(df)
    dup_count = int(df['ID Tarea'].duplicated(keep='last').sum())
    df = df.drop_duplicates(subset=['ID Tarea'], keep='last')
    for c in REQUIRED_COLUMNS + OPTIONAL_COLUMNS:
        if c != 'Fecha': df[c] = df[c].fillna('').astype(str).str.strip()
    df['Fecha_dt'] = _parse_dates(df['Fecha'])
    a = _is_one(df['Completada'])
    b = _is_one(df['Validada'])
    j = _is_one(df['Justificacion'])
    # Estados excluyentes: una tarea validada es completada; inválida = completada sin validar.
    df['Estado'] = 'Pendiente'
    df.loc[(~a) & j, 'Estado'] = 'Justificada'
    df.loc[a & (~b), 'Estado'] = 'Inválida'
    df.loc[a & b, 'Estado'] = 'Validada'
    df['Completada_bool'] = a
    df['Validada_bool'] = a & b
    df['Invalida_bool'] = a & (~b)
    df['Justificada_bool'] = (~a) & j
    df['Pendiente_bool'] = (~a) & (~j)
    # Regla contrastada con el reporte oficial de BEES Force (septiembre 2026):
    # una BONUS se contabiliza como tarea enviada solo si está VALIDADA.
    # Las BONUS justificadas e inválidas se mantienen para auditoría y galería.
    df['Bonus_bool'] = df['Detalle Tarea'].str.contains(r'\bBONUS\b', case=False, na=False, regex=True)
    df['Bonus_excluida_bool'] = df['Bonus_bool'] & ~df['Validada_bool']
    df['Enviada_oficial_bool'] = ~df['Bonus_excluida_bool']
    df['FotoURL'] = df.apply(lambda row: valid_photo_url(row['TaskImageUrl']) or valid_photo_url(row['Img']), axis=1)
    df['Supervisor'] = df['Supervisor ID'].apply(lambda x: 'Supervisor ' + str(x) if str(x) else 'Sin supervisor')
    df['Fecha_etiqueta'] = df['Fecha_dt'].dt.strftime('%d/%m/%Y').fillna('Sin fecha')
    df['Tarea_corta'] = df['Detalle Tarea'].str.slice(0, 115)
    info = {
        'rows_in_export': total_raw,
        'footer_rows': footer_rows,
        'duplicate_ids_removed': dup_count,
        'invalid_dates': int(df['Fecha_dt'].isna().sum()),
        'image_count': int(df['FotoURL'].ne('').sum()),
        'origin_filter_description': origin_filters[0] if origin_filters else '',
        'inconsistent_status': int((b & (~a)).sum() + (a & j).sum()),
    }
    return df, info


def valid_photo_url(value) -> str:
    if pd.isna(value): return ''
    s = str(value).strip()
    try:
        p = urlsplit(s)
        if p.scheme in ('https', 'http') and p.hostname and p.hostname.lower().endswith('.blob.core.windows.net'):
            return s
    except ValueError:
        pass
    return ''


def stats(df: pd.DataFrame) -> dict:
    total = len(df)
    sent = int(df['Enviada_oficial_bool'].sum()) if total else 0
    bonus_excluded = int(df['Bonus_excluida_bool'].sum()) if total else 0
    completed = int(df['Completada_bool'].sum()) if total else 0
    valid = int(df['Validada_bool'].sum()) if total else 0
    invalid = int(df['Invalida_bool'].sum()) if total else 0
    justified = int(df['Justificada_bool'].sum()) if total else 0
    pending = int(df['Pendiente_bool'].sum()) if total else 0
    return {
        'Tareas':total,'Enviadas (oficial)':sent,'Bonus excluidas':bonus_excluded,
        'Completadas':completed,'Validadas':valid,
        'Inválidas':invalid,'Justificadas':justified,'Pendientes':pending,
        '% Completadas':completed/total if total else 0,
        '% Validación':valid/sent if sent else 0,
        '% Validación de completadas':valid/completed if completed else 0,
        '% Invalidación':invalid/completed if completed else 0,
        '% Justificación':justified/total if total else 0,
    }


def group_summary(df: pd.DataFrame, grouping: list[str] | str) -> pd.DataFrame:
    """Calcula tasas desde sumas de grupos, nunca promedio simple de porcentajes."""
    keys = grouping if isinstance(grouping, list) else [grouping]
    if df.empty:
        return pd.DataFrame(columns=keys + ['Tareas','Enviadas (oficial)','Bonus excluidas','Completadas','Validadas','Inválidas','Justificadas','Pendientes', '% Validación','% Invalidación','% Justificación'])
    grp = df.groupby(keys, dropna=False, observed=True).agg(
        Tareas=('ID Tarea','count'),
        **{'Enviadas (oficial)':('Enviada_oficial_bool','sum'),'Bonus excluidas':('Bonus_excluida_bool','sum')},
        Completadas=('Completada_bool','sum'),
        Validadas=('Validada_bool','sum'),
        **{'Inválidas':('Invalida_bool','sum'), 'Justificadas':('Justificada_bool','sum'), 'Pendientes':('Pendiente_bool','sum')},
    ).reset_index()
    grp['% Validación'] = (grp['Validadas'] / grp['Enviadas (oficial)'].where(grp['Enviadas (oficial)'].ne(0))).fillna(0)
    grp['% Invalidación'] = (grp['Inválidas'] / grp['Completadas'].where(grp['Completadas'].ne(0))).fillna(0)
    grp['% Justificación'] = (grp['Justificadas'] / grp['Tareas'].where(grp['Tareas'].ne(0))).fillna(0)
    return grp


def filter_data(df, distributors, pillars, supervisors, promoters, variables, states, dates, text_q='', poc_q='', channels=None):
    mask = pd.Series(True, index=df.index)
    for name, selected in [('Distri/Directa',distributors),('Canal Agrupado',channels),('Pilar de la Liga',pillars),('Supervisor',supervisors),('Promotor',promoters),('Variable de la Liga',variables),('Estado',states)]:
        if selected: mask &= df[name].isin(selected)
    if dates and len(dates) == 2:
        mask &= df['Fecha_dt'].between(pd.Timestamp(dates[0]), pd.Timestamp(dates[1]), inclusive='both')
    if text_q.strip():mask &= df['Detalle Tarea'].str.contains(text_q.strip(), case=False, na=False, regex=False)
    if poc_q.strip():mask &= df['POC ID'].str.contains(poc_q.strip(), case=False, na=False, regex=False)
    return df.loc[mask].copy()
