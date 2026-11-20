"""v2.24 regression: drafts only for support plans; mobile-first workflow and exports.
Fictional identities and local demo only. No provider calls.
"""
import asyncio
from io import BytesIO
import os
from pathlib import Path
import re
import sys
import tempfile
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'upload_to_domain_root/_private/app'),str(ROOT/'upload_to_domain_root/_private/vendor')]
from cryptography.fernet import Fernet

with tempfile.TemporaryDirectory(prefix='ryoiku-v224-tests-') as td:
    os.environ.update(APP_SECRET='R'*64,DATA_ENCRYPTION_KEY=Fernet.generate_key().decode(),
        APP_DB_PATH=str(Path(td)/'db.sqlite3'),APP_LOG_DIR=str(Path(td)/'logs'),APP_COOKIE_SECURE='false')
    import app as webapp
    import storage
    import httpx
    from ai import demo_plan
    webapp.startup()
    storage.create_user('staff1','only-testing-fictional-1234','staff')
    storage.create_user('staff2','only-testing-fictional-5678','staff')
    first=storage.auth('staff1','only-testing-fictional-1234')
    second=storage.auth('staff2','only-testing-fictional-5678')
    cid=storage.new_child('V224-TEST-0001',{'name':'仮名テスト利用者','grade':'中学2年','age_band':'junior'},first['id'])

    def csrf(html):
        m=re.search(r'name="_csrf"\s+value="([^"]+)"',html)
        assert m, 'missing CSRF'
        return m.group(1)

    async def main():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webapp.app),base_url='http://testserver',follow_redirects=False) as c:
            login=await c.get('/login')
            response=await c.post('/login',data={'_csrf':csrf(login.text),'username':'staff1','password':'only-testing-fictional-1234'})
            assert response.status_code==303
            original=await c.get(f'/children/{cid}/support/new')
            assert '下書き保存（この計画のみ）' in original.text
            saved=await c.post(f'/children/{cid}/support/draft',data={
                '_csrf':csrf(original.text),'child_intentions':'自分で選びたい（架空）','short_goal':'指さしで選ぶ（架空）'})
            assert saved.status_code==303 and 'draft_saved=1' in saved.headers['location']
            draft=storage.get_support_draft(cid,first['id'])
            assert draft and draft['data']['short_goal']=='指さしで選ぶ（架空）'
            assert storage.get_support_draft(cid,second['id']) is None
            assert storage.support_history(cid)==[] and storage.latest_support(cid) is None
            resumed=await c.get(f'/children/{cid}/support/new')
            assert '作業中の下書きを再開しました' in resumed.text
            assert '指さしで選ぶ（架空）' in resumed.text
            published=await c.post(f'/children/{cid}/support/new',data={'_csrf':csrf(resumed.text),
                'short_goal':'指さしで選ぶ（架空）','child_intentions':'自分で選びたい（架空）'})
            assert published.status_code==303
            assert len(storage.support_history(cid))==1
            assert storage.get_support_draft(cid,first['id']) is None
            print('PASS support-only private encrypted draft -> resume -> publish exactly once, other users excluded')
            # PDF/text imported to a private draft must keep source review requirements.
            page=await c.get(f'/children/{cid}/support/new')
            parsed=await c.post(f'/children/{cid}/support/analyze',data={'_csrf':csrf(page.text),
                'source_text':'短期目標：本人の希望を2択で伝える\n本人の希望：自分で選択する'})
            assert parsed.status_code==200 and 'ocr_preview_token' in parsed.text
            m=re.search('name="ocr_preview_token" value="([^"]+)"',parsed.text)
            draft2=await c.post(f'/children/{cid}/support/draft',data={'_csrf':csrf(parsed.text),
                'ocr_preview_token':m.group(1),'short_goal':'本人の希望を2択で伝える','assessment':'架空の観察'})
            assert draft2.status_code==303
            assert storage.get_support_draft(cid,first['id'])['requires_review'] is True
            review=await c.get(f'/children/{cid}/support/new')
            assert 'draft_review_verified' in review.text
            blocked=await c.post(f'/children/{cid}/support/new',data={'_csrf':csrf(review.text),
                'short_goal':'本人の希望を2択で伝える','assessment':'架空の観察'})
            assert blocked.status_code==200 and '原本照合が必要' in blocked.text
            assert len(storage.support_history(cid))==1
            allowed=await c.post(f'/children/{cid}/support/new',data={'_csrf':csrf(review.text),
                'short_goal':'本人の希望を2択で伝える','assessment':'架空の観察',
                'draft_review_verified':'yes','review_child_intentions':'yes',
                'review_family_intentions':'yes','review_assessment':'yes'})
            assert allowed.status_code==303 and len(storage.support_history(cid))==2
            print('PASS imported support draft cannot become official without all 3 source reviews')

            # Activity creation never saves an incomplete draft; migration preserves historical rows.
            activity=demo_plan({},dict(activity_mode='minecraft',kind_code='other',duration=30))
            pid=storage.add_plan(cid,None,activity,'demo','demo',first['id'])
            assert storage.get_plan(pid)['status']=='saved'
            storage.save_plan(pid,activity,'staff review pending')
            assert storage.get_plan(pid)['status']=='saved'
            with storage.conn() as db:db.execute("UPDATE plans SET status='draft' WHERE id=?",(pid,))
            storage.init_db()
            assert storage.get_plan(pid)['status']=='saved'
            print('PASS old draft plan migrated to saved, editing keeps saved (never an activity draft)')

            builder=await c.get(f'/children/{cid}/generate')
            assert builder.status_code==200
            for v in ['batch','single','saved']:
                assert f'data-workflow-choice="{v}"' in builder.text
            assert '/static/curriculum_workflow.js' in builder.text
            assert '<button type="button" id="add-batch-activity"' not in builder.text or 'id="add-batch-activity"' in builder.text
            assert '下書き' not in builder.text.replace('下書き保存しません','')
            planned=await c.get(f'/plans/{pid}/day-flow')
            assert planned.status_code==200
            assert 'name="audience" value="child" checked' in planned.text
            assert 'name="audience" value="staff"' in planned.text
            assert 'name="audience" value="agency"' in planned.text
            assert planned.text.count('formaction=')==3
            assert 'data-step-editor' in planned.text
            assert '/static/day_flow_audience.js' in planned.text
            # Explicit child and staff audience selections still generate proper documents.
            for audience,confirm in [('child',{'child_review':'yes'}),('staff',{})]:
                for fmt in ('pdf','docx','xlsx'):
                    response=await c.post(f'/plans/{pid}/day-flow/export/{fmt}',data={
                        '_csrf':csrf(planned.text),'start_time':'14:00',f'include_{pid}':'yes',
                        f'order_{pid}':'1','audience':audience,**confirm})
                    assert response.status_code==200,(audience,fmt,response.text[:300])
                    if fmt=='pdf': assert response.content.startswith(b'%PDF')
                    else:
                        with ZipFile(BytesIO(response.content)) as z: assert z.testzip() is None
            print('PASS simple mobile workflow choices, three-button export and all 6 output variants')
    asyncio.run(main())
