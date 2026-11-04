"""Regresiones de lectura de archivos con nombres usados por la operación."""
import os
import tempfile
import unittest
from pathlib import Path
from openpyxl import Workbook
from io import BytesIO
from drive_source import (
    is_planatareas, is_ticket, is_anomaly, months_from_name, months_from_content,
    local_monthly_files, local_review_files, local_anomaly_reports, choose,
    _index_monthly, _index_reviews, _index_anomalies
)
from review_logic import load_review_source


def excel_with_sheets(rows_by_tab):
    book = Workbook()
    book.remove(book.active)
    for name, rows in rows_by_tab.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    binary=BytesIO()
    book.save(binary)
    return binary.getvalue()


class TestDriveFilenames(unittest.TestCase):
    def test_aliases(self):
        self.assertTrue(is_planatareas('planatareas.xlsx'))
        self.assertTrue(is_planatareas('plana tareas (1).xlsx'))
        self.assertTrue(is_ticket('Q4 2026 DEL VALLE - Ticket (1).xlsx'))
        self.assertTrue(is_anomaly('Anomalías Octubre 2026 - 26.10.xlsx'))
        self.assertEqual(months_from_name('Anomalias Octubre 2026 - 26.10.xlsx'), {'2026-10'})
        self.assertEqual(months_from_name('Anomalías Noviembre 2026 - 09.11.xlsx'), {'2026-11'})
        self.assertEqual(months_from_name('Q4 2026 DEL VALLE - Ticket.xlsx'), set())

    def test_three_file_types_and_close(self):
        tasks=excel_with_sheets({'Export':[['Fecha','ID Tarea','Estado'],['2026-11-05','1','Validada']]})
        ticket=excel_with_sheets({'noviembre':[['Fecha','ID Tarea','STATUS'],['2026-11-16','1','Falla de algoritmo']]})
        anomalies=excel_with_sheets({'base':[['task_executed_datetime','wholesaler_id'],['2026-11-07','70549']]})
        with tempfile.TemporaryDirectory() as tmp:
            for name,content in [('planatareas.xlsx',tasks),('Q4 2026 DEL VALLE - Ticket.xlsx',ticket),('Anomalias Noviembre 2026 - 16.11.xlsx',anomalies)]:
                Path(tmp,name).write_bytes(content)
            self.assertEqual(choose(_index_monthly([{'id':str(Path(tmp,'planatareas.xlsx')),'name':'planatareas.xlsx'}]),'2026-11')['name'],'planatareas.xlsx')
            self.assertIn('2026-11', local_monthly_files(tmp))
            self.assertIn('2026-11', local_review_files(tmp))
            self.assertEqual(len(local_anomaly_reports(tmp)['2026-11']),1)
            closed = [{'id':'frozen','name':'BEES_FORCE_2026-11_CIERRE.xlsx'}, {'id':str(Path(tmp,'planatareas.xlsx')),'name':'planatareas.xlsx'}]
            indexed=_index_monthly(closed)
            self.assertEqual(choose(indexed,'2026-11')['id'],'frozen')

    def test_quarter_sheet_support(self):
        content=excel_with_sheets({
          'octubre':[['Fecha','ID Tarea','STATUS'],['2026-10-17','100','Inválida']],
          'noviembre':[['Fecha','ID Tarea','STATUS'],['2026-11-17','101','Falla de algoritmo']]})
        self.assertEqual(months_from_content(content,'review','Q4 2026 DEL VALLE - Ticket.xlsx'),{'2026-10','2026-11'})
        records=load_review_source(BytesIO(content),filename='Q4 2026 DEL VALLE - Ticket.xlsx')
        self.assertEqual(len(records),2)
        self.assertSetEqual(set(records['ID Tarea']),{'100','101'})

    def test_multiple_weekly_reports(self):
        indexed = _index_anomalies([
            {'id':'a','name':'Anomalias Noviembre 2026 - 09.11.xlsx'},
            {'id':'b','name':'Anomalias Noviembre 2026 - 16.11.xlsx'},
            {'id':'c','name':'Anomalias Octubre 2026 - 26.10.xlsx'},
        ])
        self.assertEqual(len(indexed['2026-11']),2)
        self.assertEqual(len(indexed['2026-10']),1)

if __name__=='__main__':unittest.main()

# Casos de regresión adicionales añadidos tras incorporar Q4 multimes.
class TestMoreRealisticAliases(unittest.TestCase):
    def test_month_aliases(self):
        options=['Anomalias nov 2026.xlsx','Anomalias noviembre 2026.xlsx',
                 'Anomalias 11-26.xlsx','Anomalias 11/26.xlsx',
                 'Anomalias NOV/26 - 23.11.xlsx','Anomalias 11-2026.xlsx']
        for name in options:
            with self.subTest(name=name):
                self.assertTrue(is_anomaly(name))
                self.assertEqual(months_from_name(name),{'2026-11'})
        self.assertEqual(months_from_name('Q4 2026 DEL VALLE - Ticket.xlsx'),set())
        self.assertEqual(months_from_name('octubre',default_year=2026),{'2026-10'})
        self.assertEqual(months_from_name('nov',default_year=2026),{'2026-11'})
        self.assertEqual(months_from_name('11/26',default_year=2026),{'2026-11'})

    def test_quarter_months_and_missing_dates(self):
        from drive_source import _index_reviews
        from review_logic import prepare_reviews
        rows={
          'octubre':[['Fecha','ID Tarea','STATUS'],['12/10/2026','100','Inválida']],
          'noviembre':[['Fecha','ID Tarea','STATUS'],['10/11/2026','101','Falla de algoritmo'],['','102','Invalida']],
          'Diciembre':[['Fecha','ID Tarea','STATUS'],['','103','Falla de algoritmo']],
          'resumen':[['Fecha','Resultado'],['08/11/2026','valor']],
        }
        content=excel_with_sheets(rows)
        self.assertEqual(months_from_content(content,'review','Q4 2026 DEL VALLE - Ticket.xlsx'),
                         {'2026-10','2026-11','2026-12'})
        parsed=load_review_source(BytesIO(content),'Q4 2026 DEL VALLE - Ticket.xlsx')
        self.assertEqual(len(parsed),4)
        self.assertEqual(dict(zip(parsed['ID Tarea'],parsed['Mes_revision'])),
                         {'100':'2026-10','101':'2026-11','102':'2026-11','103':'2026-12'})
        base=parsed[parsed['Mes_revision'].eq('2026-11')]
        prepared,quality=prepare_reviews(base)
        self.assertEqual(len(prepared),2)
        self.assertEqual(prepared.loc[prepared['ID Tarea'].eq('101'),'Fecha_ticket_dt'].iloc[0].month,11)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder,'Q4 2026 DEL VALLE - Ticket.xlsx')
            path.write_bytes(content)
            available=local_review_files(folder)
            self.assertEqual(set(available),{'2026-10','2026-11','2026-12'})
            for month in available:
                self.assertEqual(available[month]['ACTUAL'][0]['id'],str(path))

    def test_anomaly_names_across_weeks(self):
        files=[{'id':'1','name':'Anomalias Noviembre 2026 09.11.xlsx'},
               {'id':'2','name':'Anomalias nov 2026 16.11.xlsx'},
               {'id':'3','name':'Anomalias 11-26 23.11.xlsx'},
               {'id':'4','name':'Anomalias 11/26 30.11.xlsx'}]
        index=_index_anomalies(files)
        self.assertEqual(len(index['2026-11']),4)
        self.assertEqual(len(index),1)
