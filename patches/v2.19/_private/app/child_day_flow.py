"""児童・生徒向け「きょうのよてい」。A4横1枚・予定時刻を忠実に表す。

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
            name=overrides.get(pid,'') or selected[pid].get('title') or 'かつどう'
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
    heading=_simple_text(flow.get('child_heading') or 'きょうの よてい','見出し',18)
    message=_simple_text(flow.get('child_message') or 'こまったら せんせいに きいてね','最後のひとこと',40)
    name=''
    if flow.get('child_show_name',False):
        name=_simple_text((child or {}).get('data',{}).get('name') or '', '利用者のお名前', 24)
    when=flow.get('event_date','')
    if when:
        try:
            d=date.fromisoformat(when)
            when=f'{d.year}年{d.month}月{d.day}日'
        except ValueError:
            raise FlowError('実施日の形式を確認してください。')
    return items,heading,message,name,when


def _kind(name):
    text=str(name).lower()
    if any(k in text for k in ('休憩','やすみ','水分','ひとやすみ','クールダウン')):
        return ('やすむ','#E8F2FE','#2D70AD')
    if any(k in text for k in ('片づけ','かたづけ','帰り','かえり','おやつ','じゅんび','手洗','てあらい')):
        return ('せいかつ','#FFF1D9','#B45A0B')
    if any(k in text for k in ('運動','うんどう','サーキット','ストレッチ')):
        return ('からだ','#E9F7E9','#318550')
    if any(k in text for k in ('工作','こうさく','つくる','つくろう','せいさく','制作')):
        return ('つくる','#F4EAFE','#7450AD')
    if any(k in text for k in ('マイクラ','minecraft','ゲーム','あそぶ','あそび')):
        return ('あそぶ','#E8F6F7','#247F83')
    return ('かつどう','#F0F4FB','#5375A1')


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
    items,heading,message,name,when=_info(child,flow)
    font=_register_font()
    buf=BytesIO()
    W,H=landscape(A4)
    c=canvas.Canvas(buf,pagesize=(W,H),pageCompression=1)
    c.setTitle('きょうのよてい｜利用者用（A4横・1枚）')
    c.setFillColor(colors.HexColor('#F4F8FF'));c.rect(0,0,W,H,stroke=0,fill=1)
    c.setFillColor(colors.HexColor('#1D4268'));c.roundRect(22,H-84,W-44,64,12,stroke=0,fill=1)
    c.setFillColor(colors.white);c.setFont(font,22)
    if pdfmetrics.stringWidth(heading,font,22)>450:
        raise FlowError('見出しが長すぎます。18文字以内でも少し短くしてください。')
    c.drawString(43,H-57,heading)
    c.setFont(font,11)
    detail=(when+'　' if when else '')+(f'{flow["start_time"]}～{flow["end_time"]}')
    c.drawRightString(W-45,H-48,detail)
    if name:
        c.setFont(font,10);c.drawRightString(W-45,H-66,name+' さん')

    n=len(items)
    cols=1 if n<=6 else 2
    per_col=(n+cols-1)//cols
    left=23;right=23;gap=17
    top=H-101;bottom=71
    cw=(W-left-right-gap*(cols-1))/cols
    available=top-bottom
    h=min(76, available/per_col-7)
    row_gap=(available-per_col*h)/(per_col-1) if per_col>1 else 0
    if h<51:
        raise FlowError('A4横1ページに読みやすく配置できません。項目をまとめてください。')
    for idx, item in enumerate(items):
        col=idx//per_col; row=idx%per_col
        x=left+col*(cw+gap); y=top-h-row*(h+row_gap)
        kind,bg,accent=_kind(item['label'])
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor('#D3DEEC'))
        c.roundRect(x,y,cw,h,9,stroke=1,fill=1)
        c.setFillColor(colors.HexColor(accent))
        c.roundRect(x,y,6,h,3,stroke=0,fill=1)
        c.circle(x+27,y+h-24,14,stroke=0,fill=1)
        c.setFillColor(colors.white);c.setFont(font,13)
        c.drawCentredString(x+27,y+h-28,str(idx+1))
        c.setFillColor(colors.HexColor('#536A7D'));c.setFont(font,9.6)
        c.drawString(x+53,y+h-21,f'{item["start"]} ～ {item["end"]}')
        # Category label is intentionally informational, not an invented activity.
        c.setFillColor(colors.HexColor(accent));c.setFont(font,8.5)
        c.drawRightString(x+cw-16,y+h-20,kind)
        size=15.2 if n<=6 else 14.4
        label_x=x+53
        max_label_width=cw-105
        pieces=_lines(item['label'],font,size,max_label_width,2)
        c.setFillColor(colors.HexColor('#153B5C'));c.setFont(font,size)
        if len(pieces)==1:
            c.drawString(label_x,y+(h-43)/2+9,pieces[0])
        else:
            c.drawString(label_x,y+28,pieces[0])
            c.drawString(label_x,y+11,pieces[1])
        c.setStrokeColor(colors.HexColor('#52708A'));c.setLineWidth(1.5)
        cbx=x+cw-34; cby=y+13
        c.roundRect(cbx,cby,15,15,2,stroke=1,fill=0)
        c.setFillColor(colors.HexColor('#536A7D'));c.setFont(font,8)
        c.drawRightString(cbx-4,cby+3,'できた')

    c.setFillColor(colors.HexColor('#1D4268'))
    c.roundRect(23,20,W-46,37,9,stroke=0,fill=1)
    c.setFillColor(colors.white);c.setFont(font,12)
    if pdfmetrics.stringWidth(message,font,12)>550:
        raise FlowError('最後のひとことが長すぎます。短い言葉に変更してください。')
    c.drawString(40,34,message)
    c.setFont(font,9)
    c.drawRightString(W-40,34,'おわったら  □ に チェック！')
    c.showPage();c.save();buf.seek(0)
    return buf


def _docx_cell(cell,value,size=13,bold=False,color='153B5C'):
    cell.text=str(value)
    cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
    for paragraph in cell.paragraphs:
        paragraph.paragraph_format.space_before=Pt(0)
        paragraph.paragraph_format.space_after=Pt(0)
        paragraph.paragraph_format.line_spacing=1.0
        for run in paragraph.runs:
            run.font.name='Yu Gothic'
            run.font.size=Pt(size)
            run.font.bold=bold
            run.font.color.rgb=RGBColor.from_string(color)
            run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Yu Gothic')


def _keep_row(row):
    el=OxmlElement('w:cantSplit');row._tr.get_or_add_trPr().append(el)


def make_child_flow_docx(plan,child,flow):
    items,heading,message,name,when=_info(child,flow)
    # PDF is a strict one-page readibility check for the same labels.
    make_child_flow_pdf(plan,child,flow)
    buf=BytesIO();d=Document(); sec=d.sections[0]
    sec.page_width=Cm(29.7);sec.page_height=Cm(21)
    sec.top_margin=sec.bottom_margin=Cm(.75);sec.left_margin=sec.right_margin=Cm(.75)
    n=d.add_paragraph();n.style='Normal';n.alignment=WD_ALIGN_PARAGRAPH.LEFT
    r=n.add_run(heading);r.font.name='Yu Gothic';r.font.size=Pt(22);r.bold=True
    r._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Yu Gothic')
    n.paragraph_format.space_after=Pt(2)
    meta=(when+'　' if when else '')+flow['start_time']+'～'+flow['end_time']
    if name:meta+='　'+name+' さん'
    n=d.add_paragraph(meta);n.paragraph_format.space_after=Pt(7)
    t=d.add_table(rows=0,cols=4);t.style='Table Grid';t.autofit=False
    widths=[1.6,4,19.5,2.5]
    for j, width in enumerate(widths):
        t.columns[j].width=Cm(width)
    for i,it in enumerate(items,1):
        row=t.add_row();_keep_row(row)
        values=[str(i),it['start']+'～'+it['end'],it['label'],'□']
        for j,(cell,val) in enumerate(zip(row.cells,values)):
            _docx_cell(cell,val,size=15 if j==2 else (12 if j==1 else 15),bold=(j in (0,2)))
            cell.width=Cm(widths[j])
    n=d.add_paragraph();n.paragraph_format.space_before=Pt(8)
    r=n.add_run(message+'　　おわったら □ に チェック！')
    r.font.name='Yu Gothic';r.font.size=Pt(12);r._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Yu Gothic')
    d.save(buf);buf.seek(0);return buf


def make_child_flow_xlsx(plan,child,flow):
    items,heading,message,name,when=_info(child,flow)
    make_child_flow_pdf(plan,child,flow)
    buf=BytesIO();w=xlsxwriter.Workbook(buf,{'in_memory':True})
    s=w.add_worksheet('きょうのよてい')
    s.hide_gridlines(2);s.set_landscape();s.set_paper(9);s.fit_to_pages(1,1)
    s.set_margins(.3,.3,.3,.3)
    s.set_column('A:A',7);s.set_column('B:B',22)
    s.set_column('C:C',63);s.set_column('D:D',15)
    heading_fmt=w.add_format({'font_size':23,'bold':True,'font_color':'#1D4268','valign':'vcenter'})
    small=w.add_format({'font_size':12,'font_color':'#536A7D'})
    header=w.add_format({'bold':True,'font_size':13,'bg_color':'#1D4268','font_color':'#FFFFFF', 'align':'center','valign':'vcenter'})
    row_no=w.add_format({'font_size':16,'bold':True,'align':'center','valign':'vcenter','border':1,'border_color':'#C8D9E6'})
    when_fmt=w.add_format({'font_size':12,'align':'center','valign':'vcenter','border':1,'border_color':'#C8D9E6'})
    label_fmt=w.add_format({'font_size':16,'bold':True,'valign':'vcenter','text_wrap':True,'border':1,'border_color':'#C8D9E6'})
    check=w.add_format({'font_size':18,'align':'center','valign':'vcenter','border':1,'border_color':'#C8D9E6'})
    s.merge_range('A1:D2',heading,heading_fmt)
    meta=(when+'　' if when else '')+flow['start_time']+'～'+flow['end_time']
    if name:meta+='　'+name+' さん'
    s.merge_range('A3:D3',meta,small)
    for j,h in enumerate(('じゅんばん','じかん','なにを する？','できた')):s.write(4,j,h,header)
    s.set_row(4,30)
    for i,it in enumerate(items,5):
        s.set_row(i,33)
        s.write_number(i,0,i-4,row_no)
        s.write_string(i,1,it['start']+'～'+it['end'],when_fmt)
        s.write_string(i,2,it['label'],label_fmt)
        s.write_string(i,3,'□',check)
    end=len(items)+6
    s.merge_range(end,0,end,3,message+'　　おわったら □ に チェック！',small)
    s.print_area(0,0,end,3)
    w.close();buf.seek(0);return buf
