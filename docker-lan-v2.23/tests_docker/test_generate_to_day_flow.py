"""End-to-end: curriculum builder -> daily-flow editor -> one-page PDF.
All test identities fictional and all generation in demo mode; no external AI calls.
"""
import asyncio
from io import BytesIO
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'upload_to_domain_root/_private/app'),str(ROOT/'upload_to_domain_root/_private/vendor')]
from cryptography.fernet import Fernet

with tempfile.TemporaryDirectory(prefix='ryoiku-daily-gen-') as td:
    os.environ.update(APP_SECRET='S'*64,DATA_ENCRYPTION_KEY=Fernet.generate_key().decode(),
        APP_DB_PATH=str(Path(td)/'db.sqlite3'),APP_LOG_DIR=str(Path(td)/'logs'),APP_COOKIE_SECURE='false')
    import app as webapp
    import storage
    import httpx
    from pypdf import PdfReader
    webapp.startup()
    storage.create_user('test_staff','fictional-testing-password-1234','staff')
    actor=storage.auth('test_staff','fictional-testing-password-1234')
    cid=storage.new_child('GEN-TEST-0001',{'name':'架空テスト利用者','grade':'中学2年','age_band':'junior'},actor['id'])
    sid,_=storage.new_support(cid,{'short_goal':'2択から本人の希望を表現する','long_goal':'自分から相談する','assessment':'5分前の予告が役立つ'},actor['id'])

    def csrf(page):
        found=re.search(r'name="_csrf"\s+value="([^"]+)"',page)
        assert found,'Missing CSRF'
        return found.group(1)

    async def main():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webapp.app),base_url='http://testserver',follow_redirects=False) as client:
            page=await client.get('/login')
            signed=await client.post('/login',data=dict(_csrf=csrf(page.text),username='test_staff',password='fictional-testing-password-1234'))
            assert signed.status_code==303,(signed.status_code,signed.text[:250])
            url=f'/children/{cid}/generate'
            screen=await client.get(url)
            assert screen.status_code==200
            assert 'name="after_generate" value="day_flow"' in screen.text
            assert 'name="after_generate" value="detail"' in screen.text
            for choice in ['day_flow','detail']:
                post=await client.post(url,data=dict(_csrf=csrf(screen.text),consent='yes',activity_mode='minecraft',
                    duration='45',theme='架空の活動',after_generate=choice))
                assert post.status_code==303,(choice,post.status_code,post.text[:300])
                target=post.headers['location'];match=re.fullmatch(r'/plans/(\d+)(/day-flow)?',target)
                assert match,(choice,target)
                pid=int(match.group(1))
                assert target.endswith('/day-flow') == (choice=='day_flow')
                plan=storage.get_plan(pid)
                assert plan and plan['child_id']==cid and plan['provider']=='demo'
                if choice=='day_flow':
                    flow=await client.get(target)
                    assert flow.status_code==200
                    assert f'name="include_{pid}"' in flow.text
                    assert f'name="order_{pid}"' in flow.text
                    resp=await client.post(f'/plans/{pid}/day-flow/export/pdf',data=dict(_csrf=csrf(flow.text),
                        **{f'include_{pid}':'yes',f'order_{pid}':'1'},start_time='14:00',audience='child',
                        child_review='yes',child_view='steps'))
                    assert resp.status_code==200,(resp.status_code,resp.text[:250])
                    assert resp.content.startswith(b'%PDF-')
                    pdf=PdfReader(BytesIO(resp.content));assert len(pdf.pages)==1
                    print(f'PASS direct curriculum -> daily flow -> student PDF (plan={pid}, {len(resp.content)} bytes)')
                else:
                    print(f'PASS standard curriculum -> detail (plan={pid})')
                screen=await client.get(url)
                assert screen.status_code==200
                assert f'href="/plans/{pid}/day-flow"' in screen.text
            # External AI review must preserve the post-generation destination;
            # no real API requests are made, because only the preview is rendered.
            storage.set_setting('provider','openai')
            storage.set_setting('model','gpt-4o-mini')
            preview=await client.post(url,data=dict(_csrf=csrf(screen.text),consent='yes',
                activity_mode='minecraft',duration='45',after_generate='day_flow'))
            assert preview.status_code==200
            assert 'name="privacy_nonce"' in preview.text
            assert 'name="after_generate" value="day_flow"' in preview.text
            assert '氏名' in preview.text or '個人' in preview.text
            print('PASS external AI privacy preview retains daily-flow destination without API call')

    asyncio.run(main())
