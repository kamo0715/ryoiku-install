"""小学校高学年〜高校生向け「1日の活動スケジュール」。A4横1枚。

This intentionally never copies internal goals, staff notes, staff_support,
assessment/evaluation, handoff, support-plan text, or agency notes.
"""
from __future__ import annotations
from io import BytesIO
from datetime import date
import re
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import xlsxwriter
from day_flow import FlowError

MAX_CHILD_ITEMS = 12
MAX_CHILD_LABEL = 26


def _simple_text(value, label, maximum):
    raw=re.sub(r'\s+', ' ', str(value or '')).strip()
    if len(raw)>maximum:
        raise FlowError(f'{label}は{maximum}文字以内に短く書き直してください。自動で省略しません。')
    return raw


def _time_parts(clock):
    parts=str(clock).split('～')
    if len(parts)!=2 or not re.fullmatch(r'\d\d:\d\d',parts[0]) or not re.fullmatch(r'\d\d:\d\d',parts[1]):
        raise FlowError('予定時刻に問題があります。もう一度作成してください。')
    return parts


def _child_items(flow):
    """Build a safe view: only clock, explicit child labels and phase/title.

    Staff-only material is never used as a fallback, even when child_action exists.
    """
    if flow.get('audience')!='child':
        raise FlowError('利用者用の出力指定が必要です。')
    rows=flow.get('rows') or []
    if not rows:
        raise FlowError('予定がありません。カリキュラムを選択してください。')
    view=flow.get('child_view','activities')
    if view not in ('activities','steps'):
        raise FlowError('利用者用の表示形式が正しくありません。')
    selected={int(p['id']):p for p in flow.get('selected_plans',[])}
    overrides=flow.get('child_plan_labels',{})
    items=[]
    for row in rows:
        begin,end=_time_parts(row.get('clock',''))
        pid=row.get('plan_id')
        if pid is not None and view=='activities':
            try:pid=int(pid)
            except (TypeError,ValueError):raise FlowError('活動計画の識別子が正しくありません。')
            if pid not in selected:
                raise FlowError('選択した活動の情報を確認してください。')
            name=overrides.get(pid,'') or selected[pid].get('title') or '活動'
            name=_simple_text(name,'利用者用の活動名',MAX_CHILD_LABEL)
            if items and items[-1].get('plan_id')==pid:
                # Consecutive steps are represented by exactly one activity; the end time is the last step's end.
                items[-1]['end']=end
            else:
                items.append({'start':begin,'end':end,'label':name,'plan_id':pid})
        else:
            # In step view, optional staff-authored child_label wins over the phase.
            # In free-text before/after/break rows, the same rule applies.
            name=_simple_text(row.get('child_label') or row.get('phase'),'利用者用の表示名',MAX_CHILD_LABEL)
            if not name:
                raise FlowError('利用者用の活動名が空欄です。出力前に入力してください。')
            items.append({'start':begin,'end':end,'label':name,'plan_id':pid})
    if len(items)>MAX_CHILD_ITEMS:
        raise FlowError(f'利用者用は読みやすさを保つためA4横1枚に最大{MAX_CHILD_ITEMS}項目まで表示します。'
            '「活動ごと」を選ぶか、休憩・移動等をまとめてから再出力してください。予定は自動削除しません。')
    return items




def _info(child,flow):
    items=_child_items(flow)
    heading=_simple_text(flow.get('child_heading') or '1日の活動スケジュール','見出し',18)
    message=_simple_text(flow.get('child_message') or '予定の変更や休憩が必要なときは、スタッフに相談してください。','連絡メモ',40)
    name=''
    if flow.get('child_show_name',False):
        name=_simple_text((child or {}).get('data',{}).get('name') or '', '利用者名', 24)
    when=flow.get('event_date','')
    if when:
        try:
            d=date.fromisoformat(when)
            when=f'{d.year}年{d.month}月{d.day}日'
        except ValueError:
            raise FlowError('実施日の形式を確認してください。')
    return items,heading,message,name,when


def _register_font():
    name='HeiseiKakuGo-W5'
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(name))
    return name


def _lines(value,font,size,max_width,max_lines=2):
    current='';lines=[]
    for char in value:
        if current and pdfmetrics.stringWidth(current+char,font,size)>max_width:
            lines.append(current)
            current=char
        else:current+=char
    if current:lines.append(current)
    if len(lines)>max_lines:
        raise FlowError('利用者用の表示名が帳票に入りません。短い表現に変更してください。')
    return lines


def make_child_flow_pdf(plan,child,flow):
    """Neutral, accessible schedule with no infantilizing language or illustrations.

    Always one A4 landscape page. No internal support material is accessed.
    """
    items,heading,message,name,when=_info(child,flow)
    font=_register_font()
    buf=BytesIO()
    W,H=landscape(A4)
    c=canvas.Canvas(buf,pagesize=(W,H),pageCompression=1)
    c.setTitle('1日の活動スケジュール｜利用者用（A4横）')
    navy=colors.HexColor('#182E49')
    ink=colors.HexColor('#182E49')
    quiet=colors.HexColor('#56677B')
    teal=colors.HexColor('#0A727B')
    light=colors.HexColor('#F3F6FA')
    rule=colors.HexColor('#CAD5DE')
    c.setFillColor(colors.white);c.rect(0,0,W,H,stroke=0,fill=1)
    # Compact, neutral header
    c.setFillColor(navy);c.rect(0,H-91,W,91,fill=1,stroke=0)
    c.setFillColor(colors.HexColor('#5AD0C6'));c.rect(0,H-91,6,91,fill=1,stroke=0)
    c.setFont(font,20.5)
    if pdfmetrics.stringWidth(heading,font,20.5)>430:
        raise FlowError('見出しが長すぎます。少し短くしてください。')
    c.setFillColor(colors.white);c.drawString(33,H-53,heading)
    c.setFont(font,10)
    meta=when if when else '実施日：未指定'
    c.drawRightString(W-33,H-43,meta)
    c.setFont(font,10.2)
    c.drawRightString(W-33,H-63,f'{flow["start_time"]} - {flow["end_time"]}')
    if name:
        c.setFont(font,9)
        c.drawRightString(W-33,H-80,'対象：'+name)
    else:
        c.setFont(font,8.5)
        c.setFillColor(colors.HexColor('#CBDEED'))
        c.drawRightString(W-33,H-80,'利用者用')
    # Cards are aligned like a timetable; for 7-12 items use two balanced columns.
    n=len(items)
    cols=1 if n<=6 else 2
    per_col=(n+cols-1)//cols
    left=27;right=27;gap=18
    top=H-117;bottom=83
    cw=(W-left-right-gap*(cols-1))/cols
    available=top-bottom
    row_gap=8 if per_col>1 else 0
    h=min(67,(available-(per_col-1)*row_gap)/per_col)
    if h<53:
        raise FlowError('A4横1ページに読みやすく配置できません。活動名や予定数を見直してください。')
    # For less dense schedules, spread the rows gently over the page.
    if per_col>1:
        row_gap=min(23,(available-per_col*h)/(per_col-1))
    for idx,item in enumerate(items):
        col=idx//per_col;row=idx%per_col
        x=left+col*(cw+gap); y=top-h-row*(h+row_gap)
        c.setFillColor(colors.white if idx%2==0 else light)
        c.setStrokeColor(rule);c.setLineWidth(.8)
        c.roundRect(x,y,cw,h,6,stroke=1,fill=1)
        # Thin accent line only for breaks; avoid invented activity categories.
        rest=any(word in item['label'] for word in ('休憩','休息','水分補給','クールダウン'))
        c.setFillColor(teal if rest else navy)
        c.roundRect(x,y,3.8,h,2,fill=1,stroke=0)
        c.setFillColor(ink);c.setFont(font,13)
        c.drawCentredString(x+25,y+h/2-4,str(idx+1))
        c.setStrokeColor(rule);c.line(x+43,y+10,x+43,y+h-10)
        c.setFillColor(quiet);c.setFont(font,9.3)
        c.drawString(x+55,y+h-18,f'{item["start"]} - {item["end"]}')
        label_size=15 if cols==1 else 13.7
        label_width=cw-110
        lines=_lines(item['label'],font,label_size,label_width,2)
        c.setFillColor(ink);c.setFont(font,label_size)
        if len(lines)==1:
            c.drawString(x+55,y+15,lines[0])
        else:
            c.drawString(x+55,y+23,lines[0]);c.drawString(x+55,y+8,lines[1])
        # Check square, deliberately unlabeled here (column key explains it).
        check_x=x+cw-29; check_y=y+h/2-8
        c.setStrokeColor(quiet);c.setLineWidth(1.2)
        c.roundRect(check_x,check_y,16,16,2,fill=0,stroke=1)
    c.setFont(font,9);c.setFillColor(quiet)
    c.drawRightString(W-30,65,'右端の □ は完了のチェック欄')
    # Footer provides age-neutral self-advocacy language.
    c.setFillColor(light);c.roundRect(27,21,W-54,37,6,stroke=0,fill=1)
    c.setFillColor(teal);c.rect(27,21,4,37,stroke=0,fill=1)
    c.setFillColor(ink);c.setFont(font,10.4)
    if pdfmetrics.stringWidth(message,font,10.4)>W-93:
        raise FlowError('連絡メモが長すぎます。少し短くしてください。')
    c.drawString(42,34,message)
    c.showPage();c.save();buf.seek(0)
    return buf


def _docx_cell(cell,value,size=13,bold=False,color='182E49',background=None):
    cell.text=str(value)
    cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
    if background:
        tcPr=cell._tc.get_or_add_tcPr();shd=OxmlElement('w:shd');shd.set(qn('w:fill'),background);tcPr.append(shd)
    for paragraph in cell.paragraphs:
        paragraph.paragraph_format.space_before=Pt(0)
        paragraph.paragraph_format.space_after=Pt(0)
        paragraph.paragraph_format.line_spacing=1.0
        for run in paragraph.runs:
            run.font.name='Yu Gothic';run.font.size=Pt(size)
            run.font.bold=bold;run.font.color.rgb=RGBColor.from_string(color)
            run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Yu Gothic')


def _keep_row(row):
    el=OxmlElement('w:cantSplit');row._tr.get_or_add_trPr().append(el)


def make_child_flow_docx(plan,child,flow):
    items,heading,message,name,when=_info(child,flow)
    make_child_flow_pdf(plan,child,flow)  # readability / 12-row validation
    buf=BytesIO();d=Document(); sec=d.sections[0]
    sec.page_width=Cm(29.7);sec.page_height=Cm(21)
    sec.top_margin=sec.bottom_margin=Cm(.8)
    sec.left_margin=sec.right_margin=Cm(.85)
    n=d.add_paragraph();n.style='Normal';n.alignment=WD_ALIGN_PARAGRAPH.LEFT
    r=n.add_run(heading);r.font.name='Yu Gothic';r.font.size=Pt(20);r.bold=True
    r.font.color.rgb=RGBColor(24,46,73)
    r._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Yu Gothic')
    n.paragraph_format.space_after=Pt(3)
    meta=(when+'　' if when else '')+flow['start_time']+' - '+flow['end_time']
    if name:meta+='　対象：'+name
    n=d.add_paragraph(meta);n.paragraph_format.space_after=Pt(6)
    t=d.add_table(rows=0,cols=4);t.style='Table Grid';t.autofit=False
    widths=[1.7,4.5,19.1,2.3]
    for j,width in enumerate(widths):t.columns[j].width=Cm(width)
    head=t.add_row();_keep_row(head)
    for j,text in enumerate(('No.','時間','活動内容','完了')):
        _docx_cell(head.cells[j],text,size=10,bold=True,color='FFFFFF',background='182E49')
    for i,it in enumerate(items,1):
        row=t.add_row();_keep_row(row)
        vals=[str(i),it['start']+' - '+it['end'],it['label'],'□']
        for j,(cell,val) in enumerate(zip(row.cells,vals)):
            _docx_cell(cell,val,size=13 if j==2 else (10 if j==1 else 12),bold=(j in (0,2)),background='F3F6FA' if i%2==0 else None)
            cell.width=Cm(widths[j])
    p=d.add_paragraph();p.paragraph_format.space_before=Pt(9)
    r=p.add_run(message);r.font.name='Yu Gothic';r.font.size=Pt(11)
    r._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Yu Gothic')
    d.save(buf);buf.seek(0);return buf


def make_child_flow_xlsx(plan,child,flow):
    items,heading,message,name,when=_info(child,flow)
    make_child_flow_pdf(plan,child,flow)
    buf=BytesIO();w=xlsxwriter.Workbook(buf,{'in_memory':True})
    s=w.add_worksheet('活動スケジュール')
    s.hide_gridlines(2);s.set_landscape();s.set_paper(9);s.fit_to_pages(1,1)
    s.set_margins(.3,.3,.3,.3)
    s.set_column('A:A',8);s.set_column('B:B',22)
    s.set_column('C:C',67);s.set_column('D:D',12)
    title_fmt=w.add_format({'font_size':21,'bold':True,'font_color':'#182E49','valign':'vcenter'})
    meta_fmt=w.add_format({'font_size':11,'font_color':'#56677B'})
    header=w.add_format({'bold':True,'font_size':12,'bg_color':'#182E49','font_color':'#FFFFFF','align':'center','valign':'vcenter'})
    row_no=w.add_format({'font_size':14,'bold':True,'align':'center','valign':'vcenter','border':1,'border_color':'#CAD5DE'})
    time_fmt=w.add_format({'font_size':11,'align':'center','valign':'vcenter','border':1,'border_color':'#CAD5DE'})
    activity=w.add_format({'font_size':14,'bold':True,'valign':'vcenter','text_wrap':True,'border':1,'border_color':'#CAD5DE'})
    check=w.add_format({'font_size':17,'align':'center','valign':'vcenter','border':1,'border_color':'#CAD5DE'})
    s.merge_range('A1:D2',heading,title_fmt)
    meta=(when+'　' if when else '')+flow['start_time']+' - '+flow['end_time']
    if name:meta+='　対象：'+name
    s.merge_range('A3:D3',meta,meta_fmt)
    for j,h in enumerate(('No.','時間','活動内容','完了')):s.write(4,j,h,header)
    s.set_row(4,28)
    for i,it in enumerate(items,5):
        s.set_row(i,33)
        s.write_number(i,0,i-4,row_no)
        s.write_string(i,1,it['start']+' - '+it['end'],time_fmt)
        s.write_string(i,2,it['label'],activity)
        s.write_string(i,3,'□',check)
    end=len(items)+6
    s.merge_range(end,0,end,3,message,meta_fmt)
    s.print_area(0,0,end,3)
    w.close();buf.seek(0);return buf
