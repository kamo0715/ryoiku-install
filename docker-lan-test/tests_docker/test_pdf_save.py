"""Regression: PDF/text transfer preview must post to the *save* route.

Synthetic data only; no external network, real children or API keys.
"""
from __future__ import annotations
import asyncio
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urljoin
from io import BytesIO

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'upload_to_domain_root/_private/app'
VENDOR=ROOT/'upload_to_domain_root/_private/vendor'
sys.path[:0]=[str(APP),str(VENDOR)]
from cryptography.fernet import Fernet

with tempfile.TemporaryDirectory(prefix='ryoiku-pdf-save-') as tmp:
    os.environ['APP_SECRET']='X'*64
    os.environ['DATA_ENCRYPTION_KEY']=Fernet.generate_key().decode()
    os.environ['APP_DB_PATH']=str(Path(tmp)/'test.sqlite3')
    os.environ['APP_LOG_DIR']=str(Path(tmp)/'logs')
    os.environ['APP_COOKIE_SECURE']='false'
    import app as webapp
    import storage
    import httpx
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    webapp.startup()
    storage.create_user('demo_staff','fictional-password-2026!','staff')
    uid=storage.auth('demo_staff','fictional-password-2026!')['id']
    child_id=storage.new_child('TEST-FICTIONAL',{'name':'テスト太郎','age_band':'junior','grade':'中学1年'},uid)
    save_url=f'/children/{child_id}/support/new'
    pdf_url=f'/children/{child_id}/support/pdf'
    text_url=f'/children/{child_id}/support/analyze'
    test_text='本人の希望：工作をしたい\n保護者の意向：自分から相談してほしい\nアセスメント：活動の切り替えには5分前の予告が役立つ。\n短期目標：2択から選び発言する'
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
    stream=BytesIO()
    canvas=Canvas(stream)
    canvas.setFont('HeiseiKakuGo-W5',11)
    for idx,line in enumerate(test_text.splitlines()):
        canvas.drawString(40,760-30*idx,line)
    canvas.save()
    pdf=stream.getvalue()

    def hidden_csrf(markup):
        m=re.search(r'name="_csrf"\s+value="([^"]+)"',markup)
        assert m,'no CSRF input'
        return m.group(1)

    def save_form(markup):
        # The content is rendered under the PDF/analyze POST URL, not /support/new.
        m=re.search(r'<form\s+class="panel stack"\s+method="post"\s+action="([^"]+)"',markup)
        assert m,'save form action is missing'
        assert m.group(1)==save_url,(m.group(1),save_url)
        names=re.findall(r'<textarea\s+name="([^"]+)"[^>]*>(.*?)</textarea>',markup,re.S)
        import html
        form={n:html.unescape(re.sub(r'<[^>]+>','',v)) for n,v in names}
        form['_csrf']=hidden_csrf(markup)
        form['ocr_preview_token']=re.search(r'name="ocr_preview_token"\s+value="([^"]+)"',markup).group(1)
        for checkbox in ['review_child_intentions','review_family_intentions','review_assessment','ocr_verified']:
            form[checkbox]='yes'
        return m.group(1),form

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webapp.app),base_url='http://testserver',follow_redirects=False) as client:
            login=await client.get('/login')
            r=await client.post('/login',data={'_csrf':hidden_csrf(login.text),'username':'demo_staff','password':'fictional-password-2026!'})
            assert r.status_code==303
            for mode in ['pdf','text']:
                current=await client.get(save_url)
                assert current.status_code==200
                if mode=='pdf':
                    result=await client.post(pdf_url,data={'_csrf':hidden_csrf(current.text)},files={'pdf_file':('fake_plan.pdf',pdf,'application/pdf')})
                    location=pdf_url
                else:
                    result=await client.post(text_url,data={'_csrf':hidden_csrf(current.text),'source_text':test_text})
                    location=text_url
                assert result.status_code==200,result.text[:200]
                assert 'ocr_preview_token' in result.text,'preview was not shown'
                target,data=save_form(result.text)
                assert urljoin(location,target)==save_url
                before=len(storage.support_history(child_id))
                # Safety: missing confirmation must not save.
                unconfirmed=dict(data);unconfirmed.pop('review_assessment')
                blocked=await client.post(target,data=unconfirmed)
                assert blocked.status_code==200 and len(storage.support_history(child_id))==before
                # Reproduce the preview: the failed confirmation returned a page that lacks a usable preview token.
                refreshed=await client.post(pdf_url if mode=='pdf' else text_url,
                    data={'_csrf':data['_csrf']} if mode=='pdf' else {'_csrf':data['_csrf'],'source_text':test_text},
                    files={'pdf_file':('fake_plan.pdf',pdf,'application/pdf')} if mode=='pdf' else None)
                target,data=save_form(refreshed.text)
                saved=await client.post(target,data=data)
                assert saved.status_code==303 and saved.headers['location']==f'/children/{child_id}'
                assert len(storage.support_history(child_id))==before+1
                record=storage.latest_support(child_id)['data']
                assert '2択' in record['short_goal'],record
                assert '5分前' in record['assessment'],record
                print(f'PASS {mode}: preview->confirm->save, data persisted, missing review rejected')
    asyncio.run(run())