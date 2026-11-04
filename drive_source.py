"""Fuentes privadas BEES Force en Google Drive.

Reconoce nombres del usuario (planatareas.xlsx; Q4 2026 DEL VALLE - Ticket.xlsx;
Anomalias Octubre 2026 - 26.10.xlsx) y nombres internos de cierre.
El mes se determina desde las fechas de los archivos si el nombre no lo expresa.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
import json
import os
import re
import unicodedata
from zoneinfo import ZoneInfo

FILE_END = r'(?:xlsx|xlsm|csv)'
FILENAME = re.compile(rf'^BEES_FORCE_(20\d{{2}})-(0[1-9]|1[0-2])_(ACTUAL|CIERRE)\.({FILE_END})$', re.I)
REVISION_FILENAME = re.compile(rf'^BEES_FORCE_REVISIONES_(20\d{{2}})-(0[1-9]|1[0-2])_(ACTUAL|CIERRE)\.({FILE_END})$', re.I)
ANOMALY_FILENAME = re.compile(rf'^BEES_FORCE_ANOMALIAS_(20\d{{2}})-(0[1-9]|1[0-2])_(20\d{{2}}-\d{{2}}-\d{{2}}|S\d{{1,2}})(?:_[A-Za-z0-9-]+)?\.({FILE_END})$', re.I)
DEFAULT_FOLDER_ID = '1j6SZlNNJJzvg8f5MO6mdm5wJ4NNOuCmR'
MONTH_NAMES = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'setiembre': 9,
    'octubre': 10, 'noviembre': 11, 'diciembre': 12,
    'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'ago': 8, 'sep': 9, 'set': 9, 'sept': 9,
    'oct': 10, 'nov': 11, 'dic': 12,
}


def credentials_dict(secrets=None):
    raw = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON', '').strip()
    if not raw and secrets is not None:
        try:
            raw = secrets.get('GOOGLE_SERVICE_ACCOUNT_JSON', '')
            if not raw and 'gcp_service_account' in secrets:
                raw = dict(secrets['gcp_service_account'])
        except Exception:
            pass
    if not raw:
        return None
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


def service(secrets=None):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    data = credentials_dict(secrets)
    if not data:
        return None
    credentials = service_account.Credentials.from_service_account_info(
        data, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=credentials, cache_discovery=False)


def folder_id(secrets=None):
    value = os.getenv('BEES_DRIVE_FOLDER_ID', '').strip()
    if not value and secrets is not None:
        try:
            value = secrets.get('BEES_DRIVE_FOLDER_ID', '')
        except Exception:
            pass
    return value or DEFAULT_FOLDER_ID


def current_month():
    return datetime.now(ZoneInfo('America/Argentina/Buenos_Aires')).strftime('%Y-%m')


def normalize(text):
    text = unicodedata.normalize('NFKD', str(text).casefold())
    return ''.join(c for c in text if not unicodedata.combining(c))


def _stem(name):
    """Conserva barras en nombres remotos de Drive (11/26)."""
    return re.sub(r'\.(?:xlsx|xlsm|csv)$', '', str(name).strip(), flags=re.I)


def is_supported(name):
    return bool(re.search(r'\.(?:xlsx|xlsm|csv)$', str(name), flags=re.I))


def is_planatareas(name):
    if not is_supported(name):
        return False
    stem = normalize(_stem(name))
    return bool(re.fullmatch(r'plana[\s_-]*tareas?(?:\s*\(\d+\))?', stem))


def is_ticket(name):
    if not is_supported(name):
        return False
    stem = normalize(_stem(name))
    return bool((re.search(r'tickets?|revision(?:es)?|revisad[ao]s?', stem)
                 and ('valle' in stem or 'bees' in stem or re.search(r'\bq[1-4]\b', stem))))


def is_anomaly(name):
    return is_supported(name) and bool(re.search(r'anomali', normalize(_stem(name))))


def _year(raw):
    year=int(raw)
    return 2000 + year if year < 100 else year


def year_from_quarter_name(name):
    """Q4 2026 DEL VALLE -> 2026, sin suponer el trimestre como mes."""
    m=re.search(r'\bq[1-4][\s._/-]*(20\d{2})\b', normalize(_stem(name)))
    if m:
        return int(m.group(1))
    years=re.findall(r'(?<!\d)20\d{2}(?!\d)', normalize(_stem(name)))
    return int(years[0]) if len(set(years)) == 1 and years else None


def months_from_name(name, default_year=None):
    """Mes/año en nombre de archivo o pestaña.

    Admite noviembre 2026, nov 2026, nov-26, 11-26, 11/26,
    11-2026, 2026-11 y etiquetas de pestaña 'noviembre' con año Q4.
    No interpreta 'Q4 2026' como abril ni '26.10' como 2026-10.
    """
    txt=normalize(_stem(name))
    txt=re.sub(r'[_]+',' ',txt)
    aliases='|'.join(sorted(MONTH_NAMES, key=len, reverse=True))
    word=re.search(rf'(?<![a-z])({aliases})(?![a-z])[\s./_-]*(?:de[\s_-]+)?(20\d{{2}}|\d{{2}})(?!\d)',txt)
    if word:
        return {f'{_year(word.group(2)):04d}-{MONTH_NAMES[word.group(1)]:02d}'}
    # Fechas año-mes; evitar confundir números de reportes con años.
    iso=re.search(r'(?<!\d)(20\d{2})[\s./_-]+(0?[1-9]|1[0-2])(?!\d)',txt)
    if iso:
        return {f'{int(iso.group(1)):04d}-{int(iso.group(2)):02d}'}
    month_first=re.search(r'(?<![a-z0-9])(0?[1-9]|1[0-2])[\s./_-]+(20\d{2}|\d{2})(?!\d)',txt)
    if month_first:
        return {f'{_year(month_first.group(2)):04d}-{int(month_first.group(1)):02d}'}
    # Un año abreviado delante de mes no es la convención usual; evitar 26.10 (día.mes).
    if default_year is not None:
        lone=re.fullmatch(rf'\s*({aliases})\s*',txt)
        if lone:
            return {f'{int(default_year):04d}-{MONTH_NAMES[lone.group(1)]:02d}'}
        numeric=re.fullmatch(r'\s*(0?[1-9]|1[0-2])\s*',txt)
        if numeric:
            return {f'{int(default_year):04d}-{int(numeric.group(1)):02d}'}
    return set()


def _date_to_month(value):
    if isinstance(value, (datetime, date)):
        return value.strftime('%Y-%m')
    value = str(value or '').strip()
    if not value or value.lower() in {'nan', 'none'}:
        return ''
    match = re.match(r'^(20\d{2})[-/]([01]?\d)[-/]([0-3]?\d)', value)
    if match:
        y, m = int(match.group(1)), int(match.group(2))
        return f'{y:04d}-{m:02d}' if 1 <= m <= 12 else ''
    match = re.match(r'^([0-3]?\d)[-/]([01]?\d)[-/](20\d{2}|\d{2})(?!\d)', value)
    if match:
        y, m = _year(match.group(3)), int(match.group(2))
        return f'{y:04d}-{m:02d}' if 1 <= m <= 12 else ''
    return ''


def months_from_content(data, kind, name=''):
    """Obtiene meses de todas las pestañas con tickets reales.

    Una pestaña 'noviembre' de un Q4 2026 se reconoce como 2026-11.
    Cuando hay fecha de la fila, prevalece sobre el título de la pestaña.
    Pestañas sin tareas (resúmenes, instrucciones) se ignoran.
    """
    result=set()
    if str(name).lower().endswith('.csv'):
        import csv
        import io
        reader=csv.DictReader(io.StringIO(data.decode('utf-8-sig',errors='replace')))
        wanted='task_executed_datetime' if kind=='anomaly' else 'Fecha'
        for row in reader:
            month=_date_to_month(row.get(wanted))
            if month:
                result.add(month)
        return result

    from openpyxl import load_workbook
    workbook=load_workbook(BytesIO(data),read_only=True,data_only=True)
    try:
        if kind=='task':
            sheets=[workbook['Export']] if 'Export' in workbook.sheetnames else workbook.worksheets[:1]
            wanted='fecha'
        elif kind=='anomaly':
            sheets=[workbook['base']] if 'base' in workbook.sheetnames else workbook.worksheets[:1]
            wanted='task_executed_datetime'
        else:
            sheets=workbook.worksheets
            wanted='fecha'
        quarter_year=year_from_quarter_name(name) if kind=='review' else None
        for sheet in sheets:
            rows=sheet.iter_rows(values_only=True)
            # Resumen/instrucciones pueden preceder a la cabecera real.
            header=None
            for row in rows:
                fields=[normalize(str(v or '')).strip() for v in row]
                if kind=='review':
                    if {'id tarea','status'}.issubset(fields):
                        header=fields
                        break
                elif wanted in fields:
                    header=fields
                    break
            if header is None:
                continue
            ix=header.index(wanted) if wanted in header else -1
            ticket_ix=header.index('id tarea') if kind=='review' else -1
            tab_months=months_from_name(sheet.title,default_year=quarter_year) if kind=='review' else set()
            sheet_month=next(iter(tab_months)) if len(tab_months)==1 else ''
            for row in rows:
                if ticket_ix>=0 and (len(row)<=ticket_ix or not str(row[ticket_ix] or '').strip()):
                    continue
                month=_date_to_month(row[ix]) if ix>=0 and len(row)>ix else ''
                if not month and kind=='review':
                    month=sheet_month
                if month:
                    result.add(month)
    finally:
        workbook.close()
    return result


def _list_files(svc, fid):
    result = []
    token = None
    while True:
        response = svc.files().list(
            q=f"'{fid}' in parents and trashed = false",
            fields='nextPageToken,files(id,name,mimeType,modifiedTime,size)',
            page_size=1000, page_token=token).execute()
        result.extend(response.get('files', []))
        token = response.get('nextPageToken')
        if not token:
            break
    return result


def download(svc, file_id):
    import io
    from googleapiclient.http import MediaIoBaseDownload
    stream = io.BytesIO()
    req = svc.files().get_media(fileId=file_id)
    dl = MediaIoBaseDownload(stream, req, chunksize=2*1024*1024)
    done = False
    while not done:
        _, done = dl.next_chunk()
    return stream.getvalue()


def _bytes_for(f, svc=None, read_bytes=None):
    if read_bytes:
        return read_bytes(f['id'], f.get('modifiedTime', ''))
    if svc:
        return download(svc, f['id'])
    return Path(f['id']).read_bytes()


def _resolve_months(f, kind, svc=None, read_bytes=None):
    name = f['name']
    named = months_from_name(name)
    if named and kind != 'review':
        return named
    try:
        months = months_from_content(_bytes_for(f, svc, read_bytes), kind, name)
    except Exception as exc:
        raise ValueError(f'No se pudo determinar el mes de "{name}": {exc}') from exc
    if not months:
        raise ValueError(f'No se encontró ninguna fecha válida en "{name}". Revisá las columnas del archivo.')
    return months


def _sorted(entries):
    return sorted(entries, key=lambda f: (f.get('modifiedTime', ''), f.get('name', ''), f.get('id', '')), reverse=True)


def _add_month(out, month, state, f, origin):
    copy = dict(f)
    copy['_origin'] = origin
    out.setdefault(month, {}).setdefault(state, []).append(copy)


def _validate_closures(result, what):
    for month, states in result.items():
        if len(states.get('CIERRE', [])) > 1:
            raise ValueError(f'Existen varios cierres de {what} para {month}; corregí los duplicados en Drive.')


def _index_monthly(files, svc=None, read_bytes=None):
    result = {}
    for f in files:
        name = f['name']
        m = FILENAME.match(name)
        if m:
            _add_month(result, f'{m.group(1)}-{m.group(2)}', m.group(3).upper(), f, 'canonica')
        elif is_planatareas(name):
            months = _resolve_months(f, 'task', svc, read_bytes)
            if len(months) != 1:
                raise ValueError(f'"{name}" mezcla varios meses: {sorted(months)}. La plana de tareas debe ser mensual.')
            _add_month(result, next(iter(months)), 'ACTUAL', f, 'planatareas')
    _validate_closures(result, 'tareas')
    for states in result.values():
        # Fuentes de usuario más recientes antes que respaldos internos ACTUAL.
        states['ACTUAL'] = sorted(states.get('ACTUAL', []), key=lambda f:
            (0 if f.get('_origin') == 'planatareas' else 1,
             -int(datetime.fromisoformat(f['modifiedTime'].replace('Z', '+00:00')).timestamp()) if f.get('modifiedTime') else 0))
    return result


def list_monthly(svc, fid, read_bytes=None):
    return _index_monthly(_list_files(svc, fid), svc, read_bytes)


def choose(by_month, month):
    records = by_month.get(month, {})
    return (records.get('CIERRE') or records.get('ACTUAL') or [None])[0]


def sync_planatareas(svc, by_month, fid, read_bytes=None):
    """Mantiene una copia ACTUAL actualizada al leer planatareas.

    De este modo un reemplazo de planatareas el primer día del mes siguiente no
    destruye el respaldo del mes pasado. No modifica nunca un CIERRE.
    """
    from io import BytesIO
    from googleapiclient.http import MediaIoBaseUpload
    updates = []
    for month, states in sorted(by_month.items()):
        if states.get('CIERRE'):
            continue
        live = next((x for x in states.get('ACTUAL', []) if x.get('_origin') == 'planatareas'), None)
        if live is None:
            continue
        stored = next((x for x in states.get('ACTUAL', []) if x.get('_origin') == 'canonica'), None)
        if stored is None:
            ext = Path(live['name']).suffix.lower()
            target = f'BEES_FORCE_{month}_ACTUAL{ext}'
            copied = svc.files().copy(fileId=live['id'], body={'name': target, 'parents': [fid]},
                                      fields='id,name').execute()
            updates.append('Respaldo '+copied['name'])
        elif live.get('modifiedTime', '') > stored.get('modifiedTime', ''):
            content = _bytes_for(live, svc, read_bytes)
            mimetype = ('text/csv' if Path(live['name']).suffix.lower() == '.csv' else
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            media = MediaIoBaseUpload(BytesIO(content), mimetype=mimetype, resumable=False)
            svc.files().update(fileId=stored['id'], media_body=media, fields='id,name').execute()
            updates.append('Respaldo actualizado '+stored['name'])
    return updates


def auto_close_old(svc, by_month, fid):
    today = current_month()
    made = []
    for month, records in sorted(by_month.items()):
        if month >= today or records.get('CIERRE') or not records.get('ACTUAL'):
            continue
        backup = next((f for f in records['ACTUAL'] if f.get('_origin') == 'canonica'), None)
        src = backup or records['ACTUAL'][0]
        ext = Path(src['name']).suffix.lower()
        target = f'BEES_FORCE_{month}_CIERRE{ext}'
        result = svc.files().copy(fileId=src['id'], body={'name': target, 'parents': [fid]},
                                  fields='id,name').execute()
        made.append(result['name'])
    return made


def local_monthly_files(folder):
    files = [{'id': str(p), 'name': p.name} for p in Path(folder).glob('*') if p.is_file()]
    index = _index_monthly(files)
    return {month: {state: Path(entries[0]['id']) for state, entries in states.items() if entries}
            for month, states in index.items()}


def _index_reviews(files, svc=None, read_bytes=None):
    result = {}
    for f in files:
        name = f['name']
        m = REVISION_FILENAME.match(name)
        if m:
            _add_month(result, f'{m.group(1)}-{m.group(2)}', m.group(3).upper(), f, 'canonica')
        elif is_ticket(name):
            for month in _resolve_months(f, 'review', svc, read_bytes):
                _add_month(result, month, 'ACTUAL', f, 'ticket')
    _validate_closures(result, 'revisiones')
    for states in result.values():
        states['ACTUAL'] = _sorted(states.get('ACTUAL', []))
    return result


def list_reviews(svc, fid, read_bytes=None):
    return _index_reviews(_list_files(svc, fid), svc, read_bytes)


def local_review_files(folder):
    files = [{'id': str(p), 'name': p.name} for p in Path(folder).glob('*') if p.is_file()]
    return _index_reviews(files)


def auto_close_reviews(svc, by_month, fid):
    today = current_month()
    copied = []
    for month, items in sorted(by_month.items()):
        if month >= today or items.get('CIERRE') or not items.get('ACTUAL'):
            continue
        src = items['ACTUAL'][0]
        ext = Path(src['name']).suffix.lower()
        name = f'BEES_FORCE_REVISIONES_{month}_CIERRE{ext}'
        result = svc.files().copy(fileId=src['id'], body={'name':name, 'parents':[fid]},
                                  fields='id,name').execute()
        copied.append(result['name'])
    return copied


def _index_anomalies(files, svc=None, read_bytes=None):
    result = defaultdict(list)
    for f in files:
        name = f['name']
        m = ANOMALY_FILENAME.match(name)
        if m:
            months = {f'{m.group(1)}-{m.group(2)}'}
        elif is_anomaly(name):
            months = months_from_name(name) or _resolve_months(f, 'anomaly', svc, read_bytes)
        else:
            continue
        for month in months:
            result[month].append(f)
    for month, entries in result.items():
        # Duplicados de nombre son normales al subir reportes semanales.
        result[month] = sorted(entries, key=lambda x: (x.get('name', ''), x.get('modifiedTime', '')))
    return dict(result)


def list_anomaly_reports(svc, fid, read_bytes=None):
    return _index_anomalies(_list_files(svc, fid), svc, read_bytes)


def local_anomaly_reports(folder):
    files = [{'id': str(p), 'name': p.name} for p in Path(folder).glob('*') if p.is_file()]
    return _index_anomalies(files)
