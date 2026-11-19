"""v2.10 fake-client safe delete & restore regression test. Never reads production DB."""
import os,re,sys,tempfile
from pathlib import Path
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
with tempfile.TemporaryDirectory(prefix='ryoiku_deleted_test_') as directory:
    os.environ['APP_SECRET']='Z'*64
    os.environ['DATA_ENCRYPTION_KEY']=Fernet.generate_key().decode()
    os.environ['APP_DB_PATH']=str(Path(directory)/'fake.sqlite3')
    os.environ['APP_LOG_DIR']=str(Path(directory)/'logs')
    from app import app
    from storage import (create_user,new_child,get_child,all_children,deleted_children,
                         new_support,add_plan,get_plan,get_support,support_history,plans_for_child,conn)
    def token(resp):
        match=re.search(r'name="_csrf" value="([^"]+)"',resp.text)
        assert match,resp.text[:800]
        return match.group(1)
    with TestClient(app) as admin,TestClient(app) as staff:
        create_user('admin_v210','test_admin_123456789','admin')
        create_user('staff_v210','test_staff_123456789','staff')
        for client,user,pw in [(admin,'admin_v210','test_admin_123456789'),(staff,'staff_v210','test_staff_123456789')]:
            page=client.get('/login')
            assert client.post('/login',data={'username':user,'password':pw,'_csrf':token(page)},follow_redirects=False).status_code==303
        from storage import auth
        admin_id=auth('admin_v210','test_admin_123456789')['id']
        cid=new_child('FICTION_01',{'name':'架空利用者A','grade':'小学生'},admin_id)
        support_id,version=new_support(cid,{'short_goal':'架空の短期目標'},admin_id)
        plan_id=add_plan(cid,support_id,{'title':'架空の活動'},'demo','demo',admin_id)
        assert len(all_children())==1
        assert admin.get(f'/children/{cid}').status_code==200
        assert staff.get(f'/children/{cid}/delete').status_code==403
        assert staff.get('/children/deleted').status_code==403
        # not even a previous direct archive endpoint can bypass admin role
        s=staff.get(f'/children/{cid}')
        assert staff.post(f'/children/{cid}/archive',data={'_csrf':token(s),'confirm_code':'FICTION_01'}).status_code==403
        page=admin.get(f'/children/{cid}/delete')
        assert page.status_code==200 and '架空利用者A' in page.text
        assert '1 件 / 活動計画 1 件' in page.text
        assert admin.post(f'/children/{cid}/delete',data={'_csrf':'INVALID','confirm_code':'FICTION_01'}).status_code==403
        incorrect=admin.post(f'/children/{cid}/delete',data={'_csrf':token(page),'confirm_code':'WRONG'},follow_redirects=False)
        assert incorrect.status_code==200 and '一致しません' in incorrect.text
        assert len(all_children())==1
        gone=admin.post(f'/children/{cid}/delete',data={'_csrf':token(page),'confirm_code':'FICTION_01'},follow_redirects=False)
        assert gone.status_code==303 and gone.headers['location']=='/children/deleted'
        assert get_child(cid) is None and get_child(cid,include_archived=True)['archived']==1
        assert len(all_children())==0 and len(deleted_children())==1
        assert get_plan(plan_id) is None and get_support(support_id) is None
        for url in [f'/children/{cid}',f'/children/{cid}/support/{support_id}',f'/plans/{plan_id}',f'/plans/{plan_id}/edit',f'/plans/{plan_id}/export/pdf']:
            r=admin.get(url)
            assert r.status_code==404,(url,r.status_code)
        removed=admin.get('/children/deleted')
        assert removed.status_code==200 and 'FICTION_01' in removed.text
        assert admin.post(f'/children/{cid}/restore',data={'_csrf':token(removed),'confirm_code':'BAD'}).status_code==200
        assert get_child(cid) is None
        restored=admin.post(f'/children/{cid}/restore',data={'_csrf':token(removed),'confirm_code':'FICTION_01'},follow_redirects=False)
        assert restored.status_code==303 and restored.headers['location']==f'/children/{cid}'
        assert get_child(cid)['archived']==0 and len(deleted_children())==0
        assert get_plan(plan_id) is not None and get_support(support_id) is not None
        assert admin.get(f'/children/{cid}').status_code==200
        assert admin.get(f'/plans/{plan_id}').status_code==200
        assert admin.post(f'/children/{cid}/restore',data={'_csrf':token(removed),'confirm_code':'FICTION_01'}).status_code==404
        # Confirm DB records were not erased, and no duplicate created.
        with conn() as db:
            assert db.execute('SELECT count(*) FROM children').fetchone()[0]==1
            assert db.execute('SELECT count(*) FROM support_plans').fetchone()[0]==1
            assert db.execute('SELECT count(*) FROM plans').fetchone()[0]==1
print('PASS: v2.10 admin-only soft-delete/restore, typed confirmation, CSRF, archived access blocked, record retention')
