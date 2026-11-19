"""職員確認用の活動計画書。既存の正式な個別支援計画を代替しない。"""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,KeepTogether
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import xlsxwriter

OFFICIAL='https://www.cfa.go.jp/policies/shougaijishien/shisaku/guideline_tebiki/'
VERIFY='2026-11-14'

def program_name(plan):
    d=plan.get('data',{})
    return (d.get('curriculum_label') or 'Minecraft') if d.get('activity_mode','minecraft')=='other' else 'Minecraft'



def descriptors(plan,child,support):
    p=plan['data']
    support_data=support['data'] if support else {}
    support_label=(f"第{support['version']}版（登録日 {support['created_at'][:10]}）"
                   if support else '未登録：一般的な活動の仮案（正式な個別支援計画と未照合）')
    missing=p.get('missing_inputs',[])
    return [
      ('カリキュラム分類',('Minecraft以外 / '+program_name(plan)) if p.get('activity_mode')=='other' else 'Minecraft'),
      ('タイトル',p['title']),('利用者名',child['data']['name']),('個別支援計画の版',support_label),
      ('状態','職員確認済' if plan['status']=='approved' else '保存済み・職員確認前'),
      ('作成日',plan['created_at'][:10]),('利用したモデル',plan['provider']+' / '+plan['model']),
      ('活動のねらい',p['overview']),('個別支援計画：長期目標',support_data.get('long_goal') or '未入力・要確認'),
      ('個別支援計画：短期目標',support_data.get('short_goal') or '未入力・要確認'),
      ('個別支援計画：配慮事項',support_data.get('accommodation') or '未入力・要確認'),
      ('今回の目標','\n'.join(p['objectives'])),('4つの基本活動との関連',' / '.join(p['basic_activities'])),
      ('準備物','\n'.join(p['materials'])),('合理的配慮','\n'.join(p['accommodations'])),
      ('本人の選択肢','\n'.join(p['child_choices'])),('家族支援の観点',p['family_support']),
      ('移行支援の観点',p['transition_support']),('地域支援・地域連携の観点',p['community_support']),
      ('安全管理','\n'.join(p['safety'])),('観察ポイント','\n'.join(p['observations'])),
      ('大分類',p.get('curriculum_group','未設定（旧版の計画）')),
      ('活動場所',p.get('activity_place','未指定')),('利用可能な材料',p.get('available_materials','未指定')),
      ('未入力とAI提案',f'未入力 {len(missing)} 件。活動条件のみ提案可能。個別支援計画の事実は自動補完せず、要確認。'),
      ('その他・要確認事項',p['note']),('確認メモ',plan['review_note']),
      ('根拠',f'こども家庭庁「放課後等デイサービスガイドライン」（令和6年7月）\n資料確認日：{VERIFY}\n{OFFICIAL}'),
      ('重要', '本書は日々の支援に向けた活動計画書案であり、法定の個別支援計画そのものではありません。')]


def make_pdf(plan,child,support):
    buf=BytesIO()
    # IPAex Gothicがある場合はTrueTypeをPDF内に埋め込んで閲覧互換性を高める。
    # フォント本体をアプリに同梱するのではなく、ホストOSのインストール済みフォントを使用。
    font='HeiseiKakuGo-W5'
    candidates=[Path('/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf'),
                Path('/usr/share/fonts/truetype/ipaexfont-gothic/ipaexg.ttf'),
                Path('/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf')]
    jpfont=next((x for x in candidates if x.is_file()),None)
    if jpfont:
        if 'RyoikuJapanese' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('RyoikuJapanese',str(jpfont)))
        font='RyoikuJapanese'
    else:
        pdfmetrics.registerFont(UnicodeCIDFont(font))
    normal=ParagraphStyle('body',fontName=font,fontSize=9.1,leading=15,wordWrap='CJK',spaceAfter=5)
    head=ParagraphStyle('head',parent=normal,fontSize=13.5,leading=21,textColor=colors.HexColor('#1d4967'),spaceBefore=10)
    sub=ParagraphStyle('sub',parent=normal,fontSize=10,leading=17,textColor=colors.HexColor('#174966'),spaceBefore=8)
    small=ParagraphStyle('small',parent=normal,fontSize=8.4,leading=13)
    def par(s,sty=normal):return Paragraph(escape(str(s or '—')).replace('\n','<br/>'),sty)
    doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=39,leftMargin=39,topMargin=40,bottomMargin=38,
                          title='療育カリキュラム計画書（職員確認用）')
    parts=[par('療育カリキュラム計画書',head),par('個別支援計画に基づく活動案｜職員が実施前に確認してください',small)]
    for label,value in descriptors(plan,child,support):
        parts.extend([par(label,sub),par(value)])
    p=plan['data']
    parts.append(par('未入力項目とAI補完案',head))
    if p.get('missing_inputs'):
        for x in p['missing_inputs']:
            parts.append(par(f"{x['section']} / {x['label']}：{x['handling']}",small))
    else:
        parts.append(par('主要項目の未入力は検出されませんでした。',small))
    for x in p.get('ai_assumptions',[]):
        parts.append(par(f"AI提案：{x['field']}　{x['proposal']}（{x['reason']}）",small))
    parts.append(par('活動手順',head))
    for i,x in enumerate(p['steps'],1):
        parts.append(par(f"{i}. {x.get('phase','')} （{x.get('minutes',0)}分）",sub))
        for name,key in [('児童の活動','child_action'),('職員の支援','staff_support'),('観察・評価','evaluation')]:
            parts.append(par(f'{name}：{x.get(key,"")}',normal))
    parts.append(par('5領域の関連づけ',head))
    for x in p['domains']:
        parts.append(par(f"{x.get('name','')} ［{x.get('weight','')}］",sub))
        for label,key in [('理由','reason'),('活動','activity'),('評価','assessment')]:
            parts.append(par(f'{label}：{x.get(key,"")}'))
    parts.append(par('個別支援計画の目標との対応',head))
    for i,x in enumerate(p['goal_links'],1):
        parts.append(par(f"{i}. 元の目標：{x.get('source_goal','')}"))
        parts.append(par(f"活動への接続：{x.get('program_link','')}"))
        parts.append(par(f"確認ポイント：{x.get('check','')}"))
    def foot(canvas,document):
        canvas.setFont(font,8)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawString(40,24,'職員確認用｜個別支援計画の代替不可')
        canvas.drawRightString(A4[0]-40,24,f'{document.page}ページ')
    doc.build(parts,onFirstPage=foot,onLaterPages=foot)
    buf.seek(0)
    return buf


def make_docx(plan,child,support):
    p=plan['data']
    doc=Document()
    sec=doc.sections[0];sec.page_width=Cm(21.0);sec.page_height=Cm(29.7);sec.top_margin=Cm(1.8);sec.bottom_margin=Cm(1.8)
    sec.left_margin=Cm(2);sec.right_margin=Cm(2)
    style=doc.styles['Normal'];style.font.name='Yu Gothic';style.font.size=Pt(10)
    style._element.rPr.rFonts.set(qn('w:eastAsia'),'Yu Gothic')
    doc.add_heading('療育カリキュラム計画書',0)
    doc.add_paragraph('個別支援計画に基づく活動案｜職員が実施前に確認してください')
    for label,value in descriptors(plan,child,support):
        doc.add_heading(label,level=2)
        doc.add_paragraph(str(value or '—'))
    doc.add_heading('未入力項目とAI補完案',level=1)
    for x in p.get('missing_inputs',[]):
        doc.add_paragraph(f"{x['section']} / {x['label']}：{x['handling']}")
    for x in p.get('ai_assumptions',[]):
        doc.add_paragraph(f"AI提案：{x['field']}　{x['proposal']}（{x['reason']}）")
    doc.add_heading('活動手順',level=1)
    for i,x in enumerate(p['steps'],1):
        doc.add_heading(f"{i}. {x.get('phase','')}（{x.get('minutes',0)}分）",level=2)
        for label,key in [('児童の活動','child_action'),('職員の支援','staff_support'),('観察・評価','evaluation')]:
            doc.add_paragraph(f"{label}：{x.get(key,'')}")
    doc.add_heading('5領域との関連',level=1)
    for x in p['domains']:
        doc.add_heading(f"{x.get('name','')}［{x.get('weight','')}］",level=2)
        for label,key in [('理由','reason'),('活動','activity'),('評価','assessment')]:
            doc.add_paragraph(f"{label}：{x.get(key,'')}")
    doc.add_heading('個別支援計画の目標との対応',level=1)
    for x in p['goal_links']:
        doc.add_paragraph(f"元の目標：{x.get('source_goal','')}")
        doc.add_paragraph(f"活動への接続：{x.get('program_link','')}")
        doc.add_paragraph(f"確認ポイント：{x.get('check','')}")
    foot=sec.footer.paragraphs[0];foot.text='職員確認用｜個別支援計画の代替不可'
    buf=BytesIO();doc.save(buf);buf.seek(0);return buf


def make_xlsx(plan,child,support):
    p=plan['data'];buf=BytesIO()
    wb=xlsxwriter.Workbook(buf,{'in_memory':True})
    hd=wb.add_format({'bold':True,'bg_color':'#194963','font_color':'#FFFFFF','valign':'top','text_wrap':True,'border':1,'border_color':'#D8E3E8'})
    cell=wb.add_format({'valign':'top','text_wrap':True,'border':1,'border_color':'#D8E3E8'})
    title=wb.add_format({'bold':True,'font_size':16,'font_color':'#174966'})
    notice=wb.add_format({'bold':True,'bg_color':'#FFF4CE','text_wrap':True})
    def sheet(name,headers,rows):
        ws=wb.add_worksheet(name)
        ws.freeze_panes(1,0);ws.set_default_row(30)
        ws.set_column(0,0,23);ws.set_column(1,len(headers)-1,44)
        for col,h in enumerate(headers): ws.write_string(0,col,h,hd)
        for ridx,record in enumerate(rows,1):
            for col,val in enumerate(record):
                if isinstance(val,(int,float)):ws.write_number(ridx,col,val,cell)
                else: ws.write_string(ridx,col,str(val or ''),cell) # 式として評価させない
            ws.set_row(ridx,min(135,max(30,max(len(str(v or '')) for v in record)//40*15+26)))
        if rows: ws.autofilter(0,0,len(rows),len(headers)-1)
        ws.set_landscape();ws.fit_to_pages(1,0);ws.set_paper(9)
        ws.set_header('&C療育カリキュラム計画書')
        ws.set_footer('&L職員確認用 / 個別支援計画の代替不可&R&P / &N')
        return ws
    overview=sheet('概要',['項目','内容'],descriptors(plan,child,support))
    sheet('活動手順',['順序','時間（分）','場面','児童の活動','職員の支援','観察・評価'],
          [[i,x.get('minutes',0),x.get('phase',''),x.get('child_action',''),x.get('staff_support',''),x.get('evaluation','')] for i,x in enumerate(p['steps'],1)])
    sheet('５領域',['領域','関係の程度','関連理由','活動','評価方法'],
          [[x.get('name',''),x.get('weight',''),x.get('reason',''),x.get('activity',''),x.get('assessment','')] for x in p['domains']])
    sheet('目標との対応',['個別支援計画の目標','活動との対応','確認方法'],
          [[x.get('source_goal',''),x.get('program_link',''),x.get('check','')] for x in p['goal_links']])
    sheet('評価と注意',['種別','内容'],[['観察ポイント',v] for v in p['observations']]+[['安全管理',v] for v in p['safety']]+[['配慮事項',v] for v in p['accommodations']])
    sheet('未入力とAI提案',['区分','項目','分類','AI提案・内容','提案の根拠・注意'],
        [[x['section'],x['label'],x['handling'],'',''] for x in p.get('missing_inputs',[])]+
        [['活動案','AI補完：'+x['field'],'仮案',x['proposal'],x['reason']] for x in p.get('ai_assumptions',[])])
    wb.close();buf.seek(0);return buf
