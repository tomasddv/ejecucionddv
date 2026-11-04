"""Diagnóstico del % de validación para cada promotor, por pilar y tarea."""
from __future__ import annotations
import pandas as pd
from bees_logic import group_summary, stats
from review_logic import estimated_close


def promoter_summary(source, reviewed=None, *, projected=False):
    if source.empty:return pd.DataFrame()
    records=[]
    for (bdr,name,supervisor),grp in source.groupby(['bdrid','Promotor','Supervisor'],dropna=False):
        s=stats(grp)
        row={'bdrid':bdr,'Promotor':name,'Supervisor':supervisor,'Tareas':s['Tareas'],
             'Enviadas':s['Enviadas (oficial)'],'Validadas':s['Validadas'],
             'Inválidas':s['Inválidas'],'Justificadas':s['Justificadas'],
             'Resultado oficial':s['% Validación'], 'Resultado':s['% Validación'],
             'Recuperables':0}
        if projected and reviewed is not None:
            t=reviewed[reviewed['ID Tarea'].isin(grp['ID Tarea'])]
            p=estimated_close(grp,t)
            row['Resultado']=p['porcentaje_estimado']
            row['Recuperables']=p['recuperaciones_adicionales']
        records.append(row)
    return pd.DataFrame(records).sort_values(['Resultado','Enviadas'],ascending=[True,False]).reset_index(drop=True)


def diagnostic(source, promoter_id, target, reviewed=None, *, projected=False):
    rows=source[source['bdrid'].eq(promoter_id)]
    if rows.empty:return {'pilares':pd.DataFrame(),'texto':'No hay tareas para este promotor con los filtros aplicados.'}
    pillars=group_summary(rows,'Pilar de la Liga')
    pillars=pillars.rename(columns={'Enviadas (oficial)':'Enviadas'})
    pillars['Validadas del cálculo']=pillars['Validadas'].astype(int)
    pillars['Enviadas del cálculo']=pillars['Enviadas'].astype(int)
    recovered=set()
    if projected and reviewed is not None and not reviewed.empty:
        pending=reviewed.loc[reviewed['Recuperable_bool'] & reviewed['ID Tarea'].isin(rows['ID Tarea'])]
        recovered=set(pending['ID Tarea'])
        for idx,p in pillars.iterrows():
            rs=rows[(rows['Pilar de la Liga']==p['Pilar de la Liga']) & rows['ID Tarea'].isin(recovered)]
            pillars.loc[idx,'Validadas del cálculo']+=len(rs)
            pillars.loc[idx,'Enviadas del cálculo']+=int(rs['Bonus_excluida_bool'].sum())
    pillars['Resultado usado']=(pillars['Validadas del cálculo']/pillars['Enviadas del cálculo'].where(pillars['Enviadas del cálculo'].ne(0))).fillna(0)
    # Contribución firmada: sumatoria por pilares = déficit mensual neto vs objetivo (en tareas).
    pillars['Déficit neto (tareas)']=target*pillars['Enviadas del cálculo']-pillars['Validadas del cálculo']
    counted=pillars[pillars['Enviadas del cálculo']>0]
    if counted.empty:return {'pilares':pillars,'texto':'No hay tareas computables en la selección.'}
    weakest=counted.sort_values(['Resultado usado','Enviadas del cálculo']).iloc[0]
    driver=counted.sort_values(['Déficit neto (tareas)','Enviadas del cálculo'],ascending=[False,False]).iloc[0]
    pil=driver['Pilar de la Liga']
    sub=rows[rows['Pilar de la Liga'].eq(pil)]
    tasks=group_summary(sub,['Variable de la Liga','Detalle Tarea'])
    tasks=tasks.sort_values(['Inválidas','Justificadas','Enviadas (oficial)'],ascending=False)
    top=tasks.iloc[0] if not tasks.empty else None
    label=f'{str(top["Variable de la Liga"])} ({int(top["Inválidas"])} inválidas)' if top is not None and top['Inválidas'] else ''
    just=group_summary(sub,'Variable de la Liga').sort_values('Justificadas',ascending=False)
    jtop=just.iloc[0] if not just.empty else None
    fragment=(f' En {pil}, la mayor concentración de inválidas está en {label}.' if label else '')
    if jtop is not None and int(jtop['Justificadas']):
        fragment+=f' También registra {int(jtop["Justificadas"])} justificadas en {jtop["Variable de la Liga"]}.'
    # Además del principal aporte al déficit, explicar la tarea problemática
    # del pilar con MENOR porcentaje, aunque sea un pilar de volumen pequeño.
    weakest_name=weakest['Pilar de la Liga']
    low_grp=group_summary(rows[rows['Pilar de la Liga'].eq(weakest_name)],'Variable de la Liga')
    low_grp=low_grp.sort_values(['Inválidas','Justificadas'],ascending=False)
    low_top=low_grp.iloc[0] if not low_grp.empty else None
    status=f'El pilar con menor tasa es {weakest_name} ({weakest["Resultado usado"]:.1%}).'
    if low_top is not None and int(low_top['Inválidas'])>0:
        invalid_n=int(low_top['Inválidas'])
        invalid_name='tarea inválida' if invalid_n==1 else 'tareas inválidas'
        status+=(f' Dentro de {weakest_name}, {low_top["Variable de la Liga"]} concentra '
                 f'{invalid_n} {invalid_name}.')
    if low_top is not None and int(low_top['Justificadas'])>0:
        status+=(f' Esa variable registra además {int(low_top["Justificadas"])} justificadas.')
    if driver['Déficit neto (tareas)']>0:
        status+=(f' El mayor aporte al desvío frente al objetivo es {pil} '
                 f'({driver["Resultado usado"]:.1%}, {int(driver["Enviadas del cálculo"])} enviadas, '
                 f'{int(driver["Validadas del cálculo"])} validadas).')
        if pil!=weakest_name:
            status+=fragment
    else:
        status+=' No se observa un déficit positivo por pilar respecto del objetivo en la selección.'
    return {'pilares':pillars,'tareas_criticas':tasks,'texto':status,
            'pilar_mas_bajo':weakest['Pilar de la Liga'],'pilar_impacto':pil,
            'tarea_critica':str(top['Variable de la Liga']) if top is not None else ''}
