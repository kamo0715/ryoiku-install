"""v2.22 regression: multiple curricula selected on builder and included in one day.
Fictional users, demo-generated plans, no network or external AI.
"""
import asyncio
from io import BytesIO
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlencode, urlparse, parse_qs
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'upload_to_domain_root/_private/app'),str(ROOT/'upload_to_domain_root/_private/vendor')]
from cryptography.fernet import Fernet

with tempfile.TemporaryDirectory(prefix='multi-curriculum-v222-') as td:
    os.environ.update(APP_SECRET='T'*64,DATA_ENCRYPTION_KEY=Fernet.generate_key().decode(),
        APP_DB_PATH=str(Path(td)/'db.sqlite3'),APP_LOG_DIR=str(Path(td)/'logs'),APP_COOKIE_SECURE='false')
    import app as webapp
    import storage
    import httpx
    from day_flow_multi import parse_multi_input
    from pypdf import PdfReader

    webapp.startup()
    storage.create_user('test_staff','fictional-testing-password-1234','staff')
    staff=storage.auth('test_staff','fictional-testing-password-1234')
    cid=storage.new_child('MULTI-001',{'name':'完全架空の利用者','grade':'中学2年','age_band':'junior'},staff['id'])
    other_cid=storage.new_child('MULTI-002',{'name':'別の架空利用者','grade':'高校1年','age_band':'high'},staff['id'])

    def csrf(page):
        m=re.search(r'name="_csrf"\s+value="([^"]+)"',page)
        assert m, 'Missing CSRF field'
        return m.group(1)

    async def generate(client,target_cid,theme,combine=None):
        path=f'/children/{target_cid}/generate'
        page=await client.get(path)
        assert page.status_code==200, page.text[:200]
        fields=[('_csrf',csrf(page.text)),('consent','yes'),('activity_mode','minecraft'),
                ('theme',theme),('duration','30'),('after_generate','day_flow')]
        for other_id in combine or []:
            fields.append(('combine_plan_ids',str(other_id)))
        return await client.post(path,content=urlencode(fields),headers={'content-type':'application/x-www-form-urlencoded'})

    async def main():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webapp.app),base_url='http://testserver',follow_redirects=False) as client:
            page=await client.get('/login')
            login=await client.post('/login',data=dict(_csrf=csrf(page.text),username='test_staff',password='fictional-testing-password-1234'))
            assert login.status_code==303
            created=[]
            for name in ['ICT活動','生活スキル','共同制作']:
                resp=await generate(client,cid,name)
                assert resp.status_code==303,(resp.status_code,resp.text[:180])
                m=re.match(r'/plans/(\d+)/day-flow',resp.headers['location'])
                assert m, resp.headers['location']
                created.append(int(m.group(1)))
            a,b,c=created
            screen=await client.get(f'/children/{cid}/generate')
            assert 'id="curriculum-multi-form"' in screen.text
            assert all(f'name="plan_ids" value="{x}"' in screen.text for x in created)
            assert all(f'name="combine_plan_ids" value="{x}"' in screen.text for x in created)
            assert '/static/generate_multi_select.js' in screen.text
            print('PASS curriculum builder shows multi-select and combine-after-generation controls')

            # Selection order is carried through to the editor; order is NOT database/recent order.
            target=f'/children/{cid}/day-flow?'+urlencode([('plan_ids',str(b)),('plan_ids',str(a))])
            selected=await client.get(target)
            assert selected.status_code==200,(selected.status_code,selected.text[:300])
            assert f'name="include_{a}" value="yes" data-day-include checked' in selected.text
            assert f'name="include_{b}" value="yes" data-day-include checked' in selected.text
            assert f'name="order_{b}" type="number" min="1" max="8" value="1"' in selected.text
            assert f'name="order_{a}" type="number" min="1" max="8" value="2"' in selected.text
            assert f'name="include_{c}" value="yes" data-day-include checked' not in selected.text
            print('PASS browser-selected 2 activities loaded in correct order and third left unselected')

            # Same data shape as the editable screen; test chronological flow and break.
            submitted={'start_time':'14:00','event_date':'2026-12-01','audience':'child',
                       'child_view':'activities','child_review':'yes',
                       f'include_{b}':'yes',f'include_{a}':'yes',
                       f'order_{b}':'1',f'order_{a}':'2',
                       f'between_{b}_phase':'休憩',f'between_{b}_minutes':'10',
                       f'between_{b}_child_action':'休憩と水分補給'}
            parsed=parse_multi_input([storage.get_plan(a),storage.get_plan(b)],submitted,b)
            assert [p['id'] for p in parsed['selected_plans']]==[b,a]
            assert parsed['total_minutes']==70
            assert parsed['start_time']=='14:00' and parsed['end_time']=='15:10'
            assert [r['phase'] for r in parsed['rows']].count('休憩')==1
            assert parsed['rows'][0]['plan_id']==b and parsed['rows'][-1]['plan_id']==a
            assert parsed['rows'][0]['clock'].startswith('14:00')
            print('PASS order + break + cumulative clocks accurately combine multiple plans')

            for fmt in ('pdf','docx','xlsx'):
                resp=await client.post(f'/plans/{b}/day-flow/export/{fmt}',data={'_csrf':csrf(selected.text),**submitted})
                assert resp.status_code==200,(fmt,resp.status_code,resp.text[:350])
                if fmt=='pdf':
                    assert resp.content.startswith(b'%PDF-')
                    pages=PdfReader(BytesIO(resp.content)).pages
                    assert len(pages)==1,len(pages)
                else:
                    with ZipFile(BytesIO(resp.content)) as z:assert z.testzip() is None
                print(f'PASS 2 selected curricula + break: student {fmt} ({len(resp.content)} bytes)')

            # Create fourth plan and preselect previous two during AI generation.
            combined=await generate(client,cid,'タイピング',combine=[b,a])
            assert combined.status_code==303,(combined.status_code,combined.text[:200])
            loc=combined.headers['location'];query=parse_qs(urlparse(loc).query)
            new_id=int(query['plan_ids'][0]);assert query['plan_ids']==[str(new_id),str(b),str(a)],loc
            combined_editor=await client.get(loc)
            assert combined_editor.status_code==200
            assert all(f'name="include_{x}" value="yes" data-day-include checked' in combined_editor.text for x in (new_id,b,a))
            print('PASS newly-generated curriculum is combined with 2 previously selected plans')

            # Combining with a different child is forbidden, and parsing rejects malformed/duplicate IDs.
            outsider=await generate(client,other_cid,'別の利用者')
            assert outsider.status_code==303
            outsider_id=int(re.search(r'/plans/(\d+)/',outsider.headers['location']).group(1))
            unauthorized=await client.get(f'/children/{cid}/day-flow?plan_ids={a}&plan_ids={outsider_id}')
            assert unauthorized.status_code==403,unauthorized.status_code
            invalid=await generate(client,cid,'越境試行',combine=[outsider_id])
            assert invalid.status_code==403
            duplicate=await client.get(f'/children/{cid}/day-flow?plan_ids={a}&plan_ids={a}')
            assert duplicate.status_code==400
            excessive=await client.get('/children/'+str(cid)+'/day-flow?'+urlencode([('plan_ids',str(a))]*9))
            assert excessive.status_code==200 and '1～8件' in excessive.text
            print('PASS cross-child, duplicate and over-limit selections rejected')

            storage.set_setting('provider','openai')
            storage.set_setting('model','gpt-4o-mini')
            preview=await generate(client,cid,'外部AIプレビュー',combine=[a,b])
            assert preview.status_code==200
            assert all(f'name="combine_plan_ids" value="{x}"' in preview.text for x in (a,b))
            assert 'name="privacy_nonce"' in preview.text
            print('PASS external-AI privacy preview carries selected plan IDs but performs no AI call')

    asyncio.run(main())
