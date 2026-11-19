"""Smoke-test all three v2.20 student-facing report formats with fabricated data."""
import os,sys,pathlib,zipfile
root=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'upload_to_domain_root/_private/vendor'),str(root/'upload_to_domain_root/_private/app')]
from child_day_flow import make_child_flow_pdf,make_child_flow_docx,make_child_flow_xlsx
flow={'audience':'child','child_view':'steps','rows':[
  {'clock':'15:00～15:20','phase':'Minecraftで共同設計','child_label':'Minecraftで共同設計'},
  {'clock':'15:20～15:30','phase':'休憩','child_label':'休憩'},
  {'clock':'15:30～16:00','phase':'タイピング学習','child_label':'タイピング学習'}],
 'start_time':'15:00','end_time':'16:00','event_date':'2026-11-19',
 'child_heading':'1日の活動スケジュール','child_message':'変更が必要なときはスタッフに相談してください。',
 'child_show_name':False}
for fmt,fn in [('pdf',make_child_flow_pdf),('docx',make_child_flow_docx),('xlsx',make_child_flow_xlsx)]:
 b=fn({}, {'data':{'name':'非表示のテスト名'}},flow).getvalue()
 assert len(b)>1000,(fmt,len(b))
 if fmt=='pdf':
  assert b.startswith(b'%PDF-')
  from pypdf import PdfReader
  from io import BytesIO
  reader=PdfReader(BytesIO(b));assert len(reader.pages)==1
 else:
  with zipfile.ZipFile(__import__('io').BytesIO(b)) as z:assert z.testzip() is None
 print(f'PASS {fmt} output: {len(b)} bytes')