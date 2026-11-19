"""v2.23: new multiple curricula created from one form, same-day editor and outputs.
All participants and goals fictional; no third-party AI call is made in this test.
"""
from pathlib import Path
import asyncio, os, re, sys, tempfile
from urllib.parse import urlencode, urlparse, parse_qs
from io import BytesIO
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'upload_to_domain_root/_private/app'),str(ROOT/'upload_to_domain_root/_private/vendor')]
from cryptography.fernet import Fernet

with tempfile.TemporaryDirectory(prefix='ryoiku-batch-v223-') as td:
    os.environ.update(APP_SECRET='B'*64,DATA_ENCRYPTION_KEY=Fernet.generate_key().decode(),
        APP_DB_PATH=str(Path(td)/'demo.sqlite3'),APP_LOG_DIR=str(Path(td)/'logs'),APP_COOKIE_SECURE='false')
    import app as webapp
    import ai
    import storage
    import httpx
    from pypdf import PdfReader
    webapp.startup()
    storage.create_user('demo_teacher','fictional-password-batch-1234567','staff')
    actor=storage.auth('demo_teacher','fictional-password-batch-1234567')
    cid=storage.new_child('BATCH-FAKE-1',{'name':'架空みらい','grade':'中2','age_band':'junior'},actor['id'])
    storage.new_support(cid,{'short_goal':'2択で自分の希望を選ぶ', 'long_goal':'職員に相談できる',
                        'assessment':'手順表を使って工程を見通す'},actor['id'])

    def csrf(html):
        m=re.search(r'name="_csrf"\s+value="([^"]+)"',html)
        assert m
        return m.group(1)

    def fields(csrf_value, n=3):
        data={'_csrf':csrf_value,'batch_consented':'yes'}
        rows=[('minecraft','learning','創作と役割分担',25),
              ('other','typing','タイピング練習',35),
              ('other','sst','相談の伝え方',30)]
        for i,(mode,kind,theme,duration) in enumerate(rows[:n],1):
            data.update({f'batch_enabled_{i}':'yes',f'batch_mode_{i}':mode,
                         f'batch_kind_{i}':kind,f'batch_theme_{i}':theme,
                         f'batch_duration_{i}':str(duration),f'batch_place_{i}':'架空施設'} )
        return data

    async def main():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webapp.app),
                                    base_url='http://testserver',follow_redirects=False) as client:
            page=await client.get('/login')
            signed=await client.post('/login',data={'_csrf':csrf(page.text),'username':'demo_teacher',
                'password':'fictional-password-batch-1234567'})
            assert signed.status_code==303
            page=await client.get(f'/children/{cid}/generate')
            assert page.status_code==200
            assert 'id="batch-generate-form"' in page.text
            assert 'batch_enabled_1' in page.text and 'batch_enabled_8' in page.text
            assert '/static/generate_batch.js' in page.text
            print('PASS batch form exposes 8 selectable new activities')

            request=fields(csrf(page.text))
            r=await client.post(f'/children/{cid}/generate-batch',data=request)
            assert r.status_code==303,(r.status_code,r.text[:450])
            dest=r.headers['location']
            assert dest.startswith(f'/children/{cid}/day-flow?')
            ids=[int(x) for x in parse_qs(urlparse(dest).query)['plan_ids']]
            assert len(ids)==3 and len(set(ids))==3
            assert [sum(x['minutes'] for x in storage.get_plan(i)['data']['steps']) for i in ids]==[25,35,30]
            assert all(storage.get_plan(i)['child_id']==cid for i in ids)
            assert [storage.get_plan(i)['data']['curriculum_label'] for i in ids][0]=='Minecraft'
            print('PASS one submission generated 3 independently configured curricula and saved in order')

            flow=await client.get(dest)
            assert flow.status_code==200
            for order,pid in enumerate(ids,1):
                assert f'name="include_{pid}" value="yes" data-day-include checked' in flow.text
                assert f'name="order_{pid}" type="number" min="1" max="8" value="{order}"' in flow.text
            export={'_csrf':csrf(flow.text),'start_time':'14:00',
                    'event_date':'2026-12-01','audience':'child','child_review':'yes',
                    'child_view':'activities'}
            for order,pid in enumerate(ids,1):
                export[f'include_{pid}']='yes'
                export[f'order_{pid}']=str(order)
                export[f'child_plan_{pid}_label']=f'活動{order}'
            export[f'between_{ids[0]}_phase']='休憩'
            export[f'between_{ids[0]}_minutes']='10'
            export[f'between_{ids[0]}_child_action']='水分補給と休憩'
            for fmt in ('pdf','docx','xlsx'):
                out=await client.post(f'/plans/{ids[0]}/day-flow/export/{fmt}',data=export)
                assert out.status_code==200,(fmt,out.status_code,out.text[:450])
                if fmt=='pdf':
                    assert out.content.startswith(b'%PDF-'),out.text[out.text.find('role="alert"')-60:out.text.find('role="alert"')+550]
                    assert len(PdfReader(BytesIO(out.content)).pages)==1
                else:
                    with ZipFile(BytesIO(out.content)) as z: assert z.testzip() is None
            print('PASS day-flow preselection + 10-minute break + one-page student PDF/DOCX/XLSX')

            # All eight new curricula may be created in a single action.
            eight={'_csrf':csrf(page.text),'batch_consented':'yes'}
            for i in range(1,9):
                eight.update({f'batch_enabled_{i}':'yes',f'batch_mode_{i}':'other',
                    f'batch_kind_{i}':'typing',f'batch_duration_{i}':'20',
                    f'batch_theme_{i}':f'架空の活動{i}'})
            maxout=await client.post(f'/children/{cid}/generate-batch',data=eight)
            assert maxout.status_code==303,(maxout.status_code,maxout.text[:350])
            maxids=parse_qs(urlparse(maxout.headers['location']).query)['plan_ids']
            assert len(maxids)==8 and len(set(maxids))==8
            assert (await client.get(maxout.headers['location'])).status_code==200
            print('PASS 8 independently generated new curricula are selected for one day')

            saved_before=len(storage.plans_for_child(cid))
            bad=fields(csrf(page.text));bad['batch_duration_2']='abc'
            out=await client.post(f'/children/{cid}/generate-batch',data=bad)
            assert out.status_code==200 and '活動時間は15～180分' in out.text
            assert len(storage.plans_for_child(cid))==saved_before
            single=fields(csrf(page.text),n=1)
            out=await client.post(f'/children/{cid}/generate-batch',data=single)
            assert out.status_code==200 and '2～8件' in out.text
            bad=fields(csrf(page.text));bad['batch_kind_2']='fake_category'
            out=await client.post(f'/children/{cid}/generate-batch',data=bad)
            assert out.status_code==200 and 'ジャンル' in out.text
            over=fields(csrf(page.text))
            for i in range(1,4): over[f'batch_duration_{i}']='180'
            for i in range(4,6):
                over.update({f'batch_enabled_{i}':'yes',f'batch_mode_{i}':'minecraft',f'batch_duration_{i}':'180'})
            out=await client.post(f'/children/{cid}/generate-batch',data=over)
            assert out.status_code==200 and '720分' in out.text
            assert len(storage.plans_for_child(cid))==saved_before
            print('PASS invalid duration, category, single activity and overlong day leave DB unchanged')

            # All generation results must be valid before any DB changes.
            orig=webapp.generate
            async def fail_second(provider,model,child,support,opts):
                if opts['theme']=='タイピング練習':
                    raise webapp.GenerationError('TEST_FAILURE','架空の失敗')
                return ai.demo_plan(support,opts)
            webapp.generate=fail_second
            out=await client.post(f'/children/{cid}/generate-batch',data=fields(csrf(page.text)))
            assert out.status_code==200 and '保存はしていません' in out.text
            assert len(storage.plans_for_child(cid))==saved_before
            webapp.generate=orig
            print('PASS failed member causes zero partial plan saves')

            # A DB insert failure on the second item must roll back the first.
            original_encoder=storage.enc
            calls=[0]
            def failing_encoder(value):
                calls[0]+=1
                if calls[0]==2:raise RuntimeError('simulated SQLite encoding failure')
                return original_encoder(value)
            storage.enc=failing_encoder
            try:
                try:
                    storage.add_plans_batch(cid,None,[{'title':'A'},{'title':'B'}],
                                            'demo','demo',actor['id'])
                    raise AssertionError('Expected atomic insert to fail')
                except RuntimeError as exc:
                    assert 'simulated' in str(exc)
            finally:
                storage.enc=original_encoder
            assert len(storage.plans_for_child(cid))==saved_before
            print('PASS atomic database transaction rolls back on second insert failure')

            # With external provider, the preview is for all new activities.
            # Mock generation AFTER preview; do not contact an external API.
            storage.set_setting('provider','openai')
            storage.set_setting('model','gpt-4o-mini')
            count_calls=[]
            async def fake_external(provider,model,child,support,opts):
                count_calls.append(opts['activity_mode'])
                return ai.demo_plan(support,opts)
            webapp.generate=fake_external
            page=await client.get(f'/children/{cid}/generate')
            posted=fields(csrf(page.text),n=2)
            posted['batch_theme_1']='架空の個人名○○を含む非送信テーマ'
            resp=await client.post(f'/children/{cid}/generate-batch',data=posted)
            assert resp.status_code==200 and '複数活動：外部AI送信前の確認' in resp.text
            assert resp.text.count('外部送信本文')==2
            assert 'name="batch_enabled_2"' in resp.text
            assert len(count_calls)==0
            outgoing_blocks=re.findall(r'<pre[^>]*>(.*?)</pre>',resp.text,re.S)
            assert len(outgoing_blocks)==2
            assert all('架空の個人名' not in text for text in outgoing_blocks)
            assert all('架空施設' not in text for text in outgoing_blocks)
            # A newly edited hidden payload must invalidate prior review.
            nonce=re.search(r'name="batch_privacy_nonce" value="([^"]+)"',resp.text).group(1)
            tampered={**posted,'batch_privacy_approved':'yes',
                      'batch_privacy_review_check':'yes','batch_privacy_nonce':nonce}
            tampered['batch_duration_2']='36'
            r=await client.post(f'/children/{cid}/generate-batch',data=tampered)
            assert r.status_code==200 and '複数活動：外部AI送信前の確認' in r.text
            assert len(count_calls)==0
            nonce=re.search(r'name="batch_privacy_nonce" value="([^"]+)"',r.text).group(1)
            confirmed={**tampered,'batch_privacy_approved':'yes',
                       'batch_privacy_review_check':'yes','batch_privacy_nonce':nonce}
            r=await client.post(f'/children/{cid}/generate-batch',data=confirmed)
            assert r.status_code==303,(r.status_code,r.text[:250])
            assert len(count_calls)==2
            assert len(parse_qs(urlparse(r.headers['location']).query)['plan_ids'])==2
            print('PASS batch external privacy preview, tamper rejection, one-time confirmation')
    asyncio.run(main())
