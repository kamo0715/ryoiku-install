"""活動計画から「1日の支援の流れ（職員・関係機関用）」を作る。\n\n単一カリキュラムから1日全体は推定しない。前後の予定は職員の明示入力のみ。\n"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
import re
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepInFrame
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from docx import Document
from docx.shared import Cm, Pt
from docx.oxml.ns import qn
import xlsxwriter
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_LINE_SPACING
from docx.oxml import OxmlElement

class FlowError(ValueError):
    pass

MAX_EXTRA=4
MAX_STEPS=60
MAX_TOTAL=720
MAX_FIELD_LEN=800


def parse_input(plan, form):
    """認識済みの活動手順から日程を組み立てる。入力が不正なら何も生成しない。"""
    start=str(form.get('start_time','')).strip()
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',start):
        raise FlowError('開始時刻を24時間形式（例：14:00）で入力してください。')
    h,m=map(int,start.split(':'))
    event_date=str(form.get('event_date','')).strip()
    if event_date:
        try:date.fromisoformat(event_date)
        except ValueError:raise FlowError('実施日の形式を確認してください。')
    location=str(form.get('location','')).strip()[:MAX_FIELD_LEN]
    staff_notes=str(form.get('staff_notes','')).strip()[:3000]
    agency_notes=str(form.get('agency_notes','')).strip()[:3000]
    shared_title=str(form.get('shared_title','')).strip()[:160]
    audience=str(form.get('audience','staff')).strip()
    if audience not in ('staff','agency','child'):raise FlowError('出力先が正しくありません。')
    if audience=='agency' and str(form.get('share_review',''))!='yes':
        raise FlowError('関係機関用は、共有内容を確認するチェックが必要です。')
    def extra(position):
        rows=[]
        for i in range(MAX_EXTRA):
            prefix=f'{position}_{i}_'
            values={k:str(form.get(prefix+k,'')).strip() for k in ('phase','minutes','child_action','staff_support','handoff','child_label')}
            if not any(values.values()):continue
            if not values['phase'] or not values['minutes']:
                raise FlowError('追加する予定には「場面」と「所要時間」の入力が必要です。')
            if not values['minutes'].isdigit():raise FlowError('所要時間は1～180分の整数で入力してください。')
            minutes=int(values['minutes'])
            if not 1<=minutes<=180:raise FlowError('追加予定の所要時間は1～180分で入力してください。')
            if any(len(v)>MAX_FIELD_LEN for v in values.values()):raise FlowError('追加予定の文章が長すぎます。')
            if not values['child_action'] and not values['staff_support']:
                raise FlowError('追加予定には「こどもの活動」か「職員の支援」の少なくとも一方を入力してください。')
            rows.append(dict(source='職員入力',minutes=minutes,**{k:values[k] for k in ('phase','child_action','staff_support','handoff','child_label')}))
        return rows
    before=extra('before');after=extra('after')
    saved=(plan.get('data') or {}).get('steps',[])
    if not isinstance(saved,list) or not 1<=len(saved)<=MAX_STEPS:
        raise FlowError('元のカリキュラムに活動手順がありません。活動計画の詳細・編集画面を確認してください。空白の支援シートは出力しません。')
    middle=[]
    for i,step in enumerate(saved):
        if not isinstance(step,dict):
            raise FlowError(f'カリキュラムの手順{i+1}を読み取れませんでした。')
        prefix=f'source_{i}_'
        def field(key,aliases=()):
            # 保存済みカリキュラムを既定値とする。画面で修正された場合は修正後の仮入力を優先する。
            stored=step.get(key,None)
            if stored is None:
                stored=next((step.get(k) for k in aliases if step.get(k) is not None),'')
            value=form.get(prefix+key,stored)
            result=str(value or '').strip()
            if len(result)>MAX_FIELD_LEN:
                raise FlowError(f'手順{i+1}の文章が長すぎます（{MAX_FIELD_LEN}字以内）。')
            return result
        minutes_raw=form.get(prefix+'minutes',step.get('minutes',0))
        try:
            if isinstance(minutes_raw,bool): raise ValueError()
            minutes=int(str(minutes_raw).strip())
            if not 1<=minutes<=180:raise ValueError()
        except (ValueError,TypeError):
            raise FlowError(f'手順{i+1}の所要時間を1～180分で入力してください。')
        phase=field('phase',('title','name'))
        child_action=field('child_action',('child_activity','activity'))
        staff_support=field('staff_support',('support','staff_action'))
        evaluation=field('evaluation',('assessment','observation'))
        child_label=field('child_label')
        missing=[label for label,value in [('場面',phase),('こどもの活動',child_action),('職員の支援',staff_support)] if not value]
        if missing:
            raise FlowError(f'手順{i+1}の「{ "・".join(missing) }」が空欄です。画面の「活動手順の転記内容」で修正してください。空白の支援シートは出力しません。')
        middle.append(dict(source='カリキュラム',phase=phase,minutes=minutes,
                           child_action=child_action,staff_support=staff_support,handoff=evaluation,child_label=child_label))
    rows=before+middle+after
    total=sum(row['minutes'] for row in rows)
    if total>MAX_TOTAL:raise FlowError('合計時間が12時間を超えています。')
    current=datetime(2000,1,1,h,m)
    if current+timedelta(minutes=total)>datetime(2000,1,2,0,0):
        raise FlowError('終了時刻が翌日になっています。開始時刻と予定を確認してください。')
    for row in rows:
        end=current+timedelta(minutes=row['minutes'])
        row['clock']=f'{current:%H:%M}～{end:%H:%M}'
        current=end
    return dict(rows=rows, event_date=event_date, start_time=start, end_time=f'{current:%H:%M}',
        total_minutes=total,location=location,staff_notes=staff_notes,agency_notes=agency_notes,
        shared_title=shared_title,audience=audience)


def _text(s):return str(s or '—')

def _public_rows(flow):
    """関係機関版へ氏名・内部評価・職員専用活動タイトルを持ち込まない。"""
    if not flow.get('rows') or not any(row.get('phase') and (row.get('child_action') or row.get('staff_support')) for row in flow['rows']):
        raise FlowError('出力する支援の流れが空欄です。内容のあるカリキュラムを選択してください。')
    result=[]
    numbers={int(p['id']):i for i,p in enumerate(flow.get('selected_plans',[]),1)}
    for row in flow['rows']:
        values=[row['clock'],row['phase'],row['child_action'],row['staff_support'],
                row['handoff'] if flow['audience']=='staff' else '']
        if flow.get('multi'):
            if row.get('plan_id') is None: label='共通予定'
            elif flow['audience']=='staff':label=row.get('curriculum','活動計画')
            else:label=f'活動{numbers.get(int(row["plan_id"]),"?")}'
            values.insert(1,label)
        result.append(values)
    return result


def _meta(plan,child,flow):
    audience=flow['audience']
    selected=flow.get('selected_plans') or []
    if selected:
        if audience=='staff':
            title=' / '.join(x['title'] for x in selected)
            source=' / '.join(f'#{x["id"]}（'+('確認済' if x['status']=='approved' else '未承認')+'）' for x in selected)
        else:
            title=flow['shared_title'] or '複数の活動による支援の流れ'
            source=f'承認済み計画 {len(selected)}件'
    else:
        title=(plan['data'].get('title') or '活動計画') if audience=='staff' else (flow['shared_title'] or '活動支援の流れ')
        source=f'計画 #{plan["id"]}・'+('確認済' if plan['status']=='approved' else '未承認・下書き')
    return [('区分','職員用（内部共有）' if audience=='staff' else '関係機関用（共有内容確認済）'),
            ('活動名',title),('対象利用者',child.get('data',{}).get('name','未設定') if audience=='staff' else '共有先で必要に応じて記入'),
            ('実施日',flow['event_date'] or '未記入'),('活動場所',flow['location'] or '未記入'),
            ('予定時間',flow['start_time']+'～'+flow['end_time']+'（合計'+str(flow['total_minutes'])+'分）'),
            ('元カリキュラム',source)]


def _staff_details(plan,flow):
    if flow.get('multi') and plan.get('_day_plans'):
        details=[]
        for item in plan['_day_plans']:
            p=item.get('data',{})
            heading='活動：'+str(p.get('title') or '無題')
            details.append((heading,' / '.join(str(v) for v in p.get('objectives',[])[:3])))
            details.append(('配慮事項',' / '.join(str(v) for v in p.get('accommodations',[])[:4])))
        details.append(('職員メモ',flow['staff_notes']))
        return details
    supp=plan.get('_support') or {}
    p=plan.get('data',{});sd=supp.get('data') or {}
    details=[('支援のねらい','\n'.join(str(x) for x in p.get('objectives',[])[:4])),
             ('配慮事項','\n'.join(str(x) for x in p.get('accommodations',[])[:6])),
             ('安全管理','\n'.join(str(x) for x in p.get('safety',[])[:6])),
             ('職員メモ',flow['staff_notes'])]
    if sd.get('short_goal'):details.insert(1,('個別支援計画の短期目標',sd['short_goal']))
    return details

def _register_font():
    font='HeiseiKakuGo-W5'
    candidates=[Path('/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf'),
                Path('/usr/share/fonts/truetype/ipaexfont-gothic/ipaexg.ttf'),
                Path('/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf')]
    jpfont=next((x for x in candidates if x.is_file()),None)
    if jpfont:
        if 'FlowJP' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('FlowJP',str(jpfont)))
        return 'FlowJP'
    pdfmetrics.registerFont(UnicodeCIDFont(font));return font


def _one_sheet_headers(flow):
    heads = ['時間', '場面', 'こどもの活動', '職員の支援・関わり',
             '観察・申し送り' if flow['audience'] == 'staff' else '共有・連携事項（共有先で記入）']
    if flow.get('multi'):
        heads.insert(1, 'カリキュラム')
    return heads


def _one_sheet_details(plan, flow):
    if flow['audience'] == 'staff':
        return _staff_details(plan, flow)
    return [('連携・共有メモ', flow.get('agency_notes', ''))]


def _page_safety(flow):
    """One-page output must not become illegible or silently clip content."""
    rows = _public_rows(flow)
    if len(rows) > 30:
        raise FlowError('1枚に読みやすく収めるには工程が多すぎます（最大30行）。予定を分けるか工程を統合してください。')
    return rows


def _pdf_story(plan, child, flow, font):
    width = 786
    normal = ParagraphStyle('flow_one_normal',fontName=font,fontSize=8.7,leading=11.6,wordWrap='CJK',spaceBefore=0,spaceAfter=0)
    small = ParagraphStyle('flow_one_small',parent=normal,fontSize=8.25,leading=10.7)
    header_style = ParagraphStyle('flow_one_header',parent=small,textColor=colors.white,fontSize=8.1,leading=10.5)
    head = ParagraphStyle('flow_one_head',parent=normal,fontSize=15,leading=18,textColor=colors.HexColor('#194963'),spaceAfter=0)
    def P(value, st=small):
        return Paragraph(escape(str(value or '')).replace('\n','<br/>'),st)
    items = [P('1日の支援の流れ　｜　'+('職員用' if flow['audience']=='staff' else '関係機関用'),head),Spacer(1,3)]
    meta = _meta(plan,child,flow)
    # Metadata in a compact, four-column grid.
    for i in range(0,len(meta),2):
        one=meta[i:i+2]
        values=[]
        for label,value in one:
            values.extend([P(label),P(value)])
        if len(one)<2:values.extend([P(''),P('')])
        t=Table([values],colWidths=[76,300,76,width-452],hAlign='LEFT')
        t.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(0,0),colors.HexColor('#EDF4F6')),
            ('BACKGROUND',(2,0),(2,0),colors.HexColor('#EDF4F6')),
            ('TOPPADDING',(0,0),(-1,-1),3.0),('BOTTOMPADDING',(0,0),(-1,-1),3.0),
            ('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3),
            ('LINEBELOW',(0,0),(-1,-1),.25,colors.HexColor('#E1E9ED'))]))
        items.append(t)
    items.append(Spacer(1,6))
    rows = _page_safety(flow)
    grid = [[P(x,header_style) for x in _one_sheet_headers(flow)]]
    for values in rows:
        grid.append([P(v) for v in values])
    widths=[90,119,186,205,186] if not flow.get('multi') else [81,104,92,164,196,149]
    assert sum(widths)==width
    t=Table(grid,colWidths=widths,repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#194963')),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F1F7F9')]),
        ('GRID',(0,0),(-1,-1),.3,colors.HexColor('#C8D9E0')),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('TOPPADDING',(0,0),(-1,-1),3.0),('BOTTOMPADDING',(0,0),(-1,-1),3.0),
        ('LEFTPADDING',(0,0),(-1,-1),3.3),('RIGHTPADDING',(0,0),(-1,-1),3.3)]))
    items.append(t)
    details=[(str(k),str(v or '')) for k,v in _one_sheet_details(plan,flow) if str(v or '').strip()]
    if details:
        items.append(Spacer(1,5))
        cells=[[P(k),P(v)] for k,v in details]
        d=Table(cells,colWidths=[90,width-90],hAlign='LEFT')
        d.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('BACKGROUND',(0,0),(0,-1),colors.HexColor('#EDF4F6')),
            ('LINEBELOW',(0,0),(-1,-1),.25,colors.HexColor('#DBE7EB')),
            ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
            ('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2)]))
        items.append(d)
    items.append(Spacer(1,4))
    foot = ParagraphStyle('flow_foot',parent=small,fontSize=7.5,leading=9.2,textColor=colors.HexColor('#516779'))
    items.append(P('※ カリキュラムにない送迎・登所・休憩等は自動で追加しません。実施前に内容・時間・共有範囲を確認してください。正式な個別支援計画の代替ではありません。',foot))
    return items


def make_flow_pdf(plan,child,flow):
    from reportlab.pdfgen.canvas import Canvas
    _page_safety(flow)
    buf=BytesIO();font=_register_font()
    doc=SimpleDocTemplate(buf,pagesize=landscape(A4),rightMargin=20,leftMargin=20,topMargin=21,bottomMargin=24,
         title='1日の支援の流れ（A4横・1枚）',allowSplitting=0)
    parts=_pdf_story(plan,child,flow,font)
    # KeepInFrame fits the full text without trimming. Do not permit unreadably small type.
    max_w=786;max_h=516
    box=KeepInFrame(max_w,max_h,parts,mode='shrink',hAlign='LEFT',vAlign='TOP')
    box.wrapOn(Canvas(BytesIO(),pagesize=landscape(A4)),max_w,max_h)
    shrink=getattr(box,'_scale',1.0)
    if shrink > 1.16:
        raise FlowError('A4横1枚では文字が小さくなりすぎます。工程を統合するか、活動の文章や補足メモを短く整理してください（文章は自動削除しません）。')
    pages=[]
    def footer(canvas, document):
        pages.append(document.page)
        canvas.saveState();canvas.setFont(font,7);canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawString(22,12,'支援の流れ（案）｜内容確認後に使用');canvas.drawRightString(landscape(A4)[0]-22,12,'A4横・1枚');canvas.restoreState()
    doc.build([box],onFirstPage=footer,onLaterPages=footer)
    if pages != [1]:
        raise FlowError('1ページに収まりませんでした。内容を短く整理して再生成してください。')
    buf.seek(0)
    return buf


def _docx_compact_cell(cell,value,bold=False,shade=False):
    cell.text=str(value or '')
    cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
    for par in cell.paragraphs:
        par.paragraph_format.space_before=Pt(0)
        par.paragraph_format.space_after=Pt(0)
        par.paragraph_format.line_spacing=1.0
        for run in par.runs:
            run.font.name='Yu Gothic'
            run.font.size=Pt(8)
            run.font.bold=bold
            run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Yu Gothic')
    if shade:
        tcPr=cell._tc.get_or_add_tcPr()
        shd=OxmlElement('w:shd');shd.set(qn('w:fill'),'EDF4F6');tcPr.append(shd)


def _docx_nobreak(row):
    trPr=row._tr.get_or_add_trPr()
    el=OxmlElement('w:cantSplit');trPr.append(el)


def make_flow_docx(plan,child,flow):
    # Match PDF single-page design while keeping Word table cells editable.
    _page_safety(flow)
    # Shared fit check catches extreme content before Word gets a chance to overflow silently.
    make_flow_pdf(plan,child,flow)
    buf=BytesIO();doc=Document();sec=doc.sections[0]
    sec.page_width=Cm(29.7);sec.page_height=Cm(21.0)
    sec.top_margin=sec.bottom_margin=Cm(.65);sec.left_margin=sec.right_margin=Cm(.65)
    style=doc.styles['Normal'];style.font.name='Yu Gothic';style.font.size=Pt(8)
    style._element.rPr.rFonts.set(qn('w:eastAsia'),'Yu Gothic')
    style.paragraph_format.space_before=Pt(0);style.paragraph_format.space_after=Pt(0)
    style.paragraph_format.line_spacing=1.0
    title=doc.add_paragraph('1日の支援の流れ｜'+('職員用' if flow['audience']=='staff' else '関係機関用'))
    for r in title.runs:r.bold=True;r.font.size=Pt(13)
    title.paragraph_format.space_after=Pt(3)
    meta=_meta(plan,child,flow)
    t=doc.add_table(rows=0,cols=4);t.style='Table Grid';t.autofit=False
    for i in range(0,len(meta),2):
        pairs=meta[i:i+2];r=t.add_row();_docx_nobreak(r)
        vals=[pairs[0][0],pairs[0][1],pairs[1][0] if len(pairs)>1 else '',pairs[1][1] if len(pairs)>1 else '']
        for j,(c,value) in enumerate(zip(r.cells,vals)):_docx_compact_cell(c,value,bold=(j%2==0),shade=(j%2==0))
    for row in t.rows:
        for j,c in enumerate(row.cells):c.width=Cm([2.5,10.1,2.5,12.7][j])
    gap=doc.add_paragraph();gap.paragraph_format.space_after=Pt(1)
    heads=_one_sheet_headers(flow)
    widths=[3.0,4.0,6.4,7.1,6.9] if not flow.get('multi') else [2.8,3.7,3.1,5.4,6.3,6.1]
    tbl=doc.add_table(rows=1,cols=len(heads));tbl.style='Table Grid';tbl.autofit=False
    for j,(c,v) in enumerate(zip(tbl.rows[0].cells,heads)):
        _docx_compact_cell(c,v,bold=True,shade=True);c.width=Cm(widths[j])
    _docx_nobreak(tbl.rows[0])
    for row in _public_rows(flow):
        rr=tbl.add_row();_docx_nobreak(rr)
        for j,(c,v) in enumerate(zip(rr.cells,row)):
            _docx_compact_cell(c,v);c.width=Cm(widths[j])
    details=[(str(k),str(v or '')) for k,v in _one_sheet_details(plan,flow) if str(v or '').strip()]
    if details:
        gap=doc.add_paragraph();gap.paragraph_format.space_after=Pt(1)
        dt=doc.add_table(rows=0,cols=2);dt.style='Table Grid';dt.autofit=False
        for label,value in details:
            rr=dt.add_row();_docx_nobreak(rr)
            _docx_compact_cell(rr.cells[0],label,bold=True,shade=True)
            _docx_compact_cell(rr.cells[1],value)
            rr.cells[0].width=Cm(3.0);rr.cells[1].width=Cm(24.5)
    foot=doc.add_paragraph('※ カリキュラムにない予定は自動で追加されません。実施前に内容・時間・共有範囲を確認。正式な個別支援計画の代替ではありません。')
    foot.paragraph_format.space_before=Pt(2)
    for r in foot.runs:r.font.size=Pt(6.5)
    sec.footer.paragraphs[0].text='支援の流れ（案）｜A4横・1枚'
    doc.save(buf);buf.seek(0);return buf


def make_flow_xlsx(plan,child,flow):
    _page_safety(flow)
    make_flow_pdf(plan,child,flow)
    buf=BytesIO();wb=xlsxwriter.Workbook(buf,{'in_memory':True})
    header=wb.add_format({'bold':True,'bg_color':'#194963','font_color':'#FFFFFF','text_wrap':True,'valign':'vcenter','border':1,'border_color':'#C9D8E0','font_size':9})
    cell=wb.add_format({'text_wrap':True,'valign':'top','border':1,'border_color':'#C9D8E0','font_size':9})
    label=wb.add_format({'bold':True,'bg_color':'#EDF4F6','font_size':8,'valign':'top'})
    title=wb.add_format({'bold':True,'font_size':14,'font_color':'#194963'})
    ws=wb.add_worksheet('1日の支援の流れ')
    ws.set_landscape();ws.fit_to_pages(1,1);ws.set_paper(9);ws.hide_gridlines(2)
    ws.set_margins(.23,.23,.28,.28)
    widths=[13,18,32,35,30] if not flow.get('multi') else [13,22,15,28,34,26]
    for n,w in enumerate(widths):ws.set_column(n,n,w)
    last='F' if flow.get('multi') else 'E'
    ws.merge_range('A1:'+last+'2','1日の支援の流れ（'+('職員用' if flow['audience']=='staff' else '関係機関用')+'）',title)
    for ix,(k,v) in enumerate(_meta(plan,child,flow),3):
        ws.write_string(ix-1,0,k,label)
        ws.merge_range(ix-1,1,ix-1,len(widths)-1,str(v),cell)
        ws.set_row(ix-1,17)
    start=10
    for j,v in enumerate(_one_sheet_headers(flow)):ws.write_string(start,j,v,header)
    ws.set_row(start,23)
    rows=_public_rows(flow)
    for idx,row in enumerate(rows,start+1):
        for j,v in enumerate(row):ws.write_string(idx,j,str(v or ''),cell)
        # Approximate wrapped height; never clip cells while fitting print area to one page.
        # Excel's fit-to-one-page controls physical pagination.
        longest=max(len(str(v or '')) / max(10,(widths[j]*1.25)) for j,v in enumerate(row))
        ws.set_row(idx,max(22,min(88,16*(int(longest)+1))))
    pos=start+len(rows)+2
    for k,v in _one_sheet_details(plan,flow):
        if not str(v or '').strip():continue
        ws.write_string(pos,0,k,label)
        ws.merge_range(pos,1,pos,len(widths)-1,str(v),cell)
        ws.set_row(pos,max(19,min(56,15*(1+len(str(v))//115))))
        pos+=1
    ws.merge_range(pos,0,pos,len(widths)-1,'※ 実施前に支援内容を確認。正式な個別支援計画の代替ではありません。',cell)
    ws.set_row(pos,22)
    ws.print_area(0,0,pos,len(widths)-1)
    ws.set_footer('&L支援の流れ（案） / A4横1枚&R&P / &N')
    wb.close();buf.seek(0);return buf
