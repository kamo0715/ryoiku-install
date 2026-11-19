"""複数の保存済みカリキュラムを、職員の選択・順番・追加予定に沿って連結する。

原本を書き換えず、別利用者の計画・未承認の関係機関出力・空欄帳票を拒否する。
"""
from __future__ import annotations
from datetime import datetime, timedelta
import re
from day_flow import parse_input, FlowError, MAX_FIELD_LEN, MAX_STEPS, MAX_TOTAL

MAX_PLANS = 8
MAX_BETWEEN = MAX_PLANS-1


def _selected(plans, form, anchor_id):
    index = {int(p['id']): p for p in plans}
    if anchor_id not in index:
        raise FlowError('開始元のカリキュラムが見つかりません。')
    chosen=[]
    for key in form.keys():
        match=re.fullmatch(r'include_(\d+)',str(key))
        if not match: continue
        pid=int(match.group(1))
        if pid not in index:
            raise FlowError('選択されたカリキュラムが同じ利用者に属していません。')
        if form.get(key)!='yes':
            raise FlowError('カリキュラムの選択値が正しくありません。')
        if pid not in [p['id'] for p in chosen]:chosen.append(index[pid])
    if anchor_id not in [p['id'] for p in chosen]:
        raise FlowError('開始元のカリキュラムを含めてください。')
    if not 1 <= len(chosen) <= MAX_PLANS:
        raise FlowError(f'1日に登録できるカリキュラムは最大{MAX_PLANS}件です。')
    ranks=[]
    for p in chosen:
        raw=str(form.get(f'order_{p["id"]}','')).strip()
        if not re.fullmatch(r'[1-8]',raw):
            raise FlowError('選択したカリキュラムの実施順を1～8の数字で入力してください。')
        ranks.append(int(raw))
    if len(set(ranks))!=len(ranks):
        raise FlowError('カリキュラムの実施順が重複しています。1から順に異なる番号を指定してください。')
    return [p for _,p in sorted(zip(ranks,chosen),key=lambda x:x[0])]


def _plan_form(p,form,include_common=False):
    """各計画の編集欄を既存の安全な単一計画パーサーへ渡す。"""
    base={key:str(form.get(key,'')) for key in (
        'start_time','event_date','location','staff_notes','agency_notes','shared_title','audience','share_review')}
    if not base['audience']: base['audience']='staff'
    for i,_step in enumerate(p.get('data',{}).get('steps',[])):
        for field in ('phase','minutes','child_action','staff_support','evaluation','child_label'):
            pref=f'plan_{p["id"]}_source_{i}_{field}'
            if pref in form:base[f'source_{i}_{field}']=str(form.get(pref,''))
    if include_common:
        for position in ('before','after'):
            for i in range(4):
                for field in ('phase','minutes','child_action','staff_support','handoff','child_label'):
                    key=f'{position}_{i}_{field}'
                    if key in form:base[key]=str(form.get(key,''))
    return base


def _between(p,form):
    prefix=f'between_{p["id"]}_'
    raw={key:str(form.get(prefix+key,'')).strip() for key in ('phase','minutes','child_action','staff_support','handoff','child_label')}
    if not any(raw.values()):return None
    if any(len(v)>MAX_FIELD_LEN for v in raw.values()):
        raise FlowError('カリキュラム間の予定が長すぎます。')
    if not raw['phase'] or not raw['minutes']:
        raise FlowError('カリキュラム間の予定には「場面」と「分数」が必要です。')
    if not raw['minutes'].isdigit() or not 1 <= int(raw['minutes']) <= 180:
        raise FlowError('カリキュラム間の予定は1～180分で入力してください。')
    if not(raw['child_action'] or raw['staff_support']):
        raise FlowError('カリキュラム間の予定に「こどもの活動」または「職員の支援」が必要です。')
    return {'source':'職員入力','plan_id':None,'curriculum':'共通予定',
            'phase':raw['phase'],'minutes':int(raw['minutes']),
            'child_action':raw['child_action'],'staff_support':raw['staff_support'],
            'handoff':raw['handoff']}


def parse_multi_input(plans,form,anchor_id):
    """同一利用者の計画一覧とHTTP formから1日の予定を構成。状態変更はしない。"""
    selected=_selected(plans,form,int(anchor_id))
    child_ids={p['child_id'] for p in selected}
    if len(child_ids)!=1:
        raise FlowError('異なる利用者のカリキュラムを一つの支援表に混在させることはできません。')
    audience=str(form.get('audience','staff'))
    if audience not in ('staff','agency','child'):raise FlowError('出力先を確認してください。')
    if audience=='agency':
        if any(p['status']!='approved' or p.get('provider')=='demo' for p in selected):
            raise FlowError('関係機関用は、選択したすべてのカリキュラムがAI連携による承認済み計画である必要があります。')
        if str(form.get('share_review',''))!='yes':
            raise FlowError('関係機関用は、共有内容の確認チェックが必要です。')
    total_steps=sum(len(p.get('data',{}).get('steps',[])) for p in selected)
    if total_steps>MAX_STEPS:
        raise FlowError(f'全カリキュラムの手順数が{MAX_STEPS}件を超えています。')
    anchor=next(p for p in selected if int(p['id'])==int(anchor_id))
    rows_by_id={}
    before=after=[]
    common=None
    for p in selected:
        part=parse_input(p,_plan_form(p,form,include_common=(p['id']==anchor_id)))
        if common is None:common=part
        source_rows=[r for r in part['rows'] if r.get('source')=='カリキュラム']
        if len(source_rows)!=len(p['data'].get('steps',[])):
            raise FlowError('活動手順と出力内容の件数が一致しません。')
        label=str(p['data'].get('title') or '無題のカリキュラム').strip()[:160]
        rows_by_id[p['id']]=[dict(r,plan_id=p['id'],curriculum=label) for r in source_rows]
        if p['id']==anchor_id:
            before_end=part['rows'].index(source_rows[0])
            before=[dict(r,plan_id=None,curriculum='共通予定') for r in part['rows'][:before_end]]
            after=[dict(r,plan_id=None,curriculum='共通予定') for r in part['rows'][before_end+len(source_rows):]]
    rows=list(before)
    for i,p in enumerate(selected):
        rows.extend(rows_by_id[p['id']])
        if i<len(selected)-1:
            gap=_between(p,form)
            if gap:rows.append(gap)
    rows.extend(after)
    minutes=sum(r['minutes'] for r in rows)
    if minutes>MAX_TOTAL:raise FlowError('合計時間が12時間を超えています。')
    hour,minute=map(int,common['start_time'].split(':'))
    current=datetime(2000,1,1,hour,minute)
    if current+timedelta(minutes=minutes)>datetime(2000,1,2):
        raise FlowError('終了時刻が翌日になっています。開始時刻と予定を確認してください。')
    for row in rows:
        end=current+timedelta(minutes=row['minutes'])
        row['clock']=f'{current:%H:%M}～{end:%H:%M}'
        current=end
    if audience=='child':
        if str(form.get('child_review',''))!='yes':
            raise FlowError('利用者用は、表示される活動名・時刻・個人情報を確認するチェックが必要です。')
        view=str(form.get('child_view','activities')).strip()
        if view not in ('activities','steps'):
            raise FlowError('利用者用の表示形式が正しくありません。')
        title=str(form.get('child_heading','')).strip()
        message=str(form.get('child_message','')).strip()
        if len(title)>18 or len(message)>40:
            raise FlowError('利用者用の見出し・ひとことは短く入力してください。')
        if str(form.get('child_show_name','')) not in ('','yes'):
            raise FlowError('氏名の表示設定が正しくありません。')
        plan_labels={}
        for item in selected:
            value=str(form.get(f'child_plan_{item["id"]}_label','')).strip()
            if len(value)>26:raise FlowError('利用者用の活動名は26文字以内で入力してください。')
            plan_labels[item['id']]=value
        common.update(child_view=view,child_heading=title,child_message=message,
             child_show_name=str(form.get('child_show_name',''))=='yes',child_plan_labels=plan_labels)
    common.update(rows=rows,end_time=f'{current:%H:%M}',total_minutes=minutes,
         selected_plans=[{'id':p['id'],'title':str(p['data'].get('title',''))[:160],
             'status':p['status'],'provider':p.get('provider','')} for p in selected],
         multi=True)
    return common
