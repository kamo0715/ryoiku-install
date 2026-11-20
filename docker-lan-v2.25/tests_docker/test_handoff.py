"""v2.25 independent encrypted student handoff: authenticated E2E and migration.
All names, progress notes, and dates in these tests are fictional.
"""
import asyncio
import os
import re
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'upload_to_domain_root/_private/app'),
              str(root/'upload_to_domain_root/_private/vendor')]
from cryptography.fernet import Fernet


def csrf(html):
    match=re.search(r'name="_csrf"\s+value="([^"]+)"',html)
    assert match,html[:400]
    return match.group(1)


async def run():
    import app as site
    import storage
    import httpx
    site.startup()
    storage.create_user('teacher_a','fictional-strong-password-1','staff')
    storage.create_user('teacher_b','fictional-strong-password-2','staff')
    author=storage.auth('teacher_a','fictional-strong-password-1')
    cid=storage.new_child('DEMO-HANDOFF-001',{'name':'テスト生徒ひかり','grade':'中学2年','age_band':'junior'},author['id'])
    other=storage.new_child('DEMO-HANDOFF-002',{'name':'テスト生徒あおい','grade':'高校1年','age_band':'senior'},author['id'])
    transport=httpx.ASGITransport(app=site.app)
    async with httpx.AsyncClient(transport=transport,base_url='http://localhost',follow_redirects=False) as client:
        anon=await client.get(f'/children/{cid}/handoff')
        assert anon.status_code==303 and anon.headers['location']=='/login'
        first=await client.get('/login')
        login=await client.post('/login',data={'_csrf':csrf(first.text),'username':'teacher_a','password':'fictional-strong-password-1'})
        assert login.status_code==303
        page=await client.get(f'/children/{cid}/handoff')
        assert page.status_code==200 and 'まだ登録されていません' in page.text
        assert '下書きは作成しません' in page.text
        assert 'name="last_id" value="0"' in page.text
        assert 'カリキュラムや個別支援計画の項目は増えません' in page.text
        invalid=await client.post(f'/children/{cid}/handoff',data={'_csrf':csrf(page.text),'last_id':'0','state':'not_started'})
        assert invalid.status_code==200 and '少なくとも1項目' in invalid.text
        assert storage.handoff_count(cid)==0
        forged=await client.post(f'/children/{cid}/handoff',data={'last_id':'0','state':'in_progress','progress':'偽装'})
        assert forged.status_code==403
        invalid_state=await client.post(f'/children/{cid}/handoff',data={'_csrf':csrf(page.text),'last_id':'0','state':'unrecognized','progress':'テスト'})
        assert invalid_state.status_code==400
        too_long=await client.post(f'/children/{cid}/handoff',data={'_csrf':csrf(page.text),'last_id':'0','state':'in_progress','progress':'x'*1501})
        assert too_long.status_code==413
        fictional='タイピングの練習 ＜script＞& 引き継ぎ確認'
        progress='<script>alert(42)</script> ホームポジション20文字まで到達'
        post={'_csrf':csrf(page.text),'last_id':'0','state':'in_progress','current_work':fictional,
              'progress':progress,'next_step':'数字キーを5分だけ練習','support_notes':'活動開始の5分前に予告'}
        saved=await client.post(f'/children/{cid}/handoff',data=post)
        assert saved.status_code==303 and saved.headers['location'].endswith('saved=1')
        assert storage.handoff_count(cid)==1
        item=storage.latest_handoff(cid)
        assert item['author_username']=='teacher_a' and item['data']['progress']==progress
        with sqlite3.connect(os.environ['APP_DB_PATH']) as con:
            blob=con.execute('SELECT payload FROM student_handoffs WHERE child_id=?',(cid,)).fetchone()[0]
            assert 'タイピング' not in blob and 'script' not in blob and '数字キー' not in blob
            assert con.execute('SELECT count(*) FROM plans').fetchone()[0]==0
            assert con.execute('SELECT count(*) FROM support_drafts').fetchone()[0]==0
            assert con.execute('SELECT count(*) FROM support_plans').fetchone()[0]==0
        detail=await client.get(f'/children/{cid}')
        assert detail.status_code==200 and '引き継ぎ情報' in detail.text
        assert '数字キーを5分だけ練習' in detail.text
        assert '<script>alert(42)</script>' not in detail.text
        assert '&lt;script&gt;alert(42)&lt;/script&gt;' in detail.text
        handoff=await client.get(f'/children/{cid}/handoff?saved=1')
        assert handoff.status_code==200 and '引き継ぎ情報を保存しました' in handoff.text
        assert 'name="last_id" value="1"' in handoff.text
        assert '20文字まで到達' in handoff.text
        assert 'JST' in handoff.text
        # Concurrent stale form cannot silently overwrite the latest staff note.
        conflict=await client.post(f'/children/{cid}/handoff',data=post)
        assert conflict.status_code==200 and '別の職員が先に更新しました' in conflict.text
        assert storage.handoff_count(cid)==1
        # A second staff member can share the same student record, independently.
        client.cookies.clear()
        second_login=await client.get('/login')
        response=await client.post('/login',data={'_csrf':csrf(second_login.text),'username':'teacher_b','password':'fictional-strong-password-2'})
        assert response.status_code==303
        second_page=await client.get(f'/children/{cid}/handoff')
        second=await client.post(f'/children/{cid}/handoff',data={
           '_csrf':csrf(second_page.text),'last_id':str(item['id']),'state':'completed',
           'current_work':fictional,'progress':'数字キーの練習が終わった',
           'next_step':'次回は短い文章に挑戦','support_notes':'5分前の予告を継続'})
        assert second.status_code==303
        assert storage.handoff_count(cid)==2
        current=storage.latest_handoff(cid)
        assert current['author_username']=='teacher_b' and current['data']['state']=='completed'
        assert storage.handoff_count(other)==0 and storage.latest_handoff(other) is None
        # Stored content persists through startup / normal existing DB migration.
        site.startup()
        assert storage.latest_handoff(cid)['id']==current['id']
        # Student archival hides all handoff pages and prevents writing.
        assert storage.archive_child(cid)==1
        gone=await client.get(f'/children/{cid}/handoff')
        assert gone.status_code==404
        assert storage.latest_handoff(cid) is None
        blocked=await client.post(f'/children/{cid}/handoff',data={
            '_csrf':csrf(second_page.text),'last_id':str(current['id']),
            'state':'in_progress','current_work':'記録しない'})
        assert blocked.status_code==404
        assert storage.restore_child(cid)==1
        assert storage.latest_handoff(cid)['id']==current['id']
        # History pagination is server-side, append-only and scoped to this student.
        for idx in range(22):
            before=storage.latest_handoff(cid)
            storage.add_handoff(cid,{
              'state':'in_progress','current_work':'架空の活動',
              'progress':f'テスト進捗 {idx}','next_step':'次の課題','support_notes':''},
              author['id'],before['id'])
        hist1=await client.get(f'/children/{cid}/handoff?page=1')
        hist2=await client.get(f'/children/{cid}/handoff?page=2')
        assert hist1.status_code==200 and hist2.status_code==200
        assert '古い履歴' in hist1.text and '新しい履歴' in hist2.text
        assert 'テスト進捗 0' in hist2.text
        assert 'テスト進捗 21' in hist1.text
        assert storage.handoff_count(cid)==24
        assert storage.handoff_count(other)==0
        print('PASS: handoff is separate, encrypted, per-student, CSRF-protected, append-only')
        print('PASS: history, previous-staff preservation, conflict detection, archival, mobile templates')


with TemporaryDirectory(prefix='ryoiku-handoff-') as temp:
    os.environ.update(APP_SECRET='S'*64,DATA_ENCRYPTION_KEY=Fernet.generate_key().decode(),
       APP_DB_PATH=str(Path(temp)/'handoff.sqlite3'),APP_LOG_DIR=str(Path(temp)/'logs'),APP_COOKIE_SECURE='false')
    asyncio.run(run())
