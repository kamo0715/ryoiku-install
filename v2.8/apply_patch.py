#!/usr/bin/env python3
"""Apply bounded text-field mapping changes to an exact v2.7 source tree."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
ocr = root/'ocr_import.py'
app = root/'app.py'
form = root/'templates/support_form.html'
version = root/'VERSION'
assert version.read_text().strip() == '2.7', 'Requires v2.7'
assert (root/'support_analyzer.py').is_file(), 'Missing local analyzer'

src = ocr.read_text(encoding='utf-8')
assert src.count('def parse_support_text(raw):') == 1
assert src.count('# v2.7:') == 1
first = src.index('def parse_support_text(raw):')
last = src.index('# v2.7:', first)
replacement = '''def parse_support_text(raw):
    """Analyze recognized text into explicit, human-reviewable support-plan fields."""
    from support_analyzer import analyze_support_text
    try:
        return analyze_support_text(raw)
    except ValueError as exc:
        raise OCRImportError('文字を読み取れませんでした。原本を確認して再試行してください。', 'OCR_EMPTY') from exc


'''
new_ocr = src[:first] + replacement + src[last:]

src = app.read_text(encoding='utf-8')
anchor = "@app.post('/children/{cid}/support/new')"
assert src.count(anchor) == 1
assert 'def support_text_analyze(' not in src
route = '''@app.post('/children/{cid}/support/analyze')
async def support_text_analyze(request:Request,cid:int):
    """Analyze pasted/OCR-copied plain text; suggestions only, never save here."""
    user=actor(request)
    child=get_child(cid)
    if not child:raise HTTPException(404)
    form=await checked_form(request)
    original=str(form.get('source_text',''))
    previous=latest_support(cid)
    if len(original)>18000:
        return view(request,'support_form.html',child=child,previous=previous,form_data={},
                    ocr_message='原文は18,000文字以下にしてください。')
    try:
        data,count,warnings,names=parse_support_text(original)
        actual_name=re.sub(r'[\\s　]+','',child['data'].get('name',''))
        possible=[x for x in names if x and re.sub(r'[\\s　]+','',x)!=actual_name]
        if possible:
            warnings.insert(0,'原文の氏名と選択した利用者が一致しない可能性があります。登録先を確認してください。')
        token=secrets.token_urlsafe(20)
        request.session['ocr_preview']={'token':token,'cid':cid,'expires':int(time.time())+1800}
        activity(request.state.request_id,user['id'],'support_text_analyze_preview',cid,
                 detail=f'fields={count},name_warning={bool(possible)}')
        return view(request,'support_form.html',child=child,previous=previous,form_data=data,
                    ocr_preview=True,ocr_kind='原文',ocr_token=token,ocr_count=count,ocr_warnings=warnings)
    except OCRImportError as exc:
        activity(request.state.request_id,user['id'],'support_text_analyze_preview',cid,
                 status='failed',detail=exc.code)
        return view(request,'support_form.html',child=child,previous=previous,form_data={},
                    ocr_message=exc.message)

'''
new_app = src.replace(anchor,route+anchor)

src = form.read_text(encoding='utf-8')
anchor = '{% if ocr_message %}'
assert src.count(anchor)==1
block = '''<div class="notice">OCRで読み取った原文やコピーした個別支援計画の文章を、見出し・表の区切りから解析して各項目へ転記できます。自動保存はされません。</div>
<form method="post" action="/children/{{child.id}}/support/analyze" class="stack">
<input type="hidden" name="_csrf" value="{{csrf}}">
<label for="source-text">原文の解析・再転記（18,000文字以内）</label>
<textarea id="source-text" name="source_text" rows="5" maxlength="18000" required placeholder="OCR結果や個別支援計画書の文章を貼り付けてください。例：長期目標：集団活動に参加する">{{form_data.get('original_text','')}}</textarea>
<p class="muted">写真・PDFの読取時も自動解析します。誤った欄に転記された場合は、読み取った原文をここに貼り付けて再解析できます。保存前に原本と必ず照合してください。</p>
<button type="submit" class="secondary">原文を解析して各項目へ仮転記</button>
</form>
'''
old = '{{ocr_kind|default("写真")}}の読み取りが終わりました。'
new = '{% if ocr_kind|default("") == "原文" %}原文からの転記候補を作成しました。{% else %}{{ocr_kind|default("写真")}}の読み取りが終わりました。{% endif %}'
assert src.count(old) == 1
new_form = src.replace(anchor,block+anchor).replace(old,new)
for name,source in [('ocr_import.py',new_ocr),('app.py',new_app)]:
    compile(source,name,'exec')
# Prepare and validate all edits before writing.
ocr.write_text(new_ocr,encoding='utf-8')
app.write_text(new_app,encoding='utf-8')
form.write_text(new_form,encoding='utf-8')
version.write_text('2.8\n',encoding='utf-8')
print('OK: v2.8 field mappings + raw-text re-analysis UI patched')
