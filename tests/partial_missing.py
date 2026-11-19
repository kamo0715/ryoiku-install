"""実行: python tests/partial_missing.py。テストはすべて架空の情報だけを使用する。"""
import io,os,re,sqlite3,sys,tempfile,zipfile
from pathlib import Path
from cryptography.fernet import Fernet
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
tmp=tempfile.TemporaryDirectory(prefix='ryoiku_partial_')
os.environ['APP_SECRET']='m'*64
os.environ['DATA_ENCRYPTION_KEY']=Fernet.generate_key().decode()
os.environ['APP_DB_PATH']=str(Path(tmp.name)/'db.sqlite3')
os.environ['APP_LOG_DIR']=str(Path(tmp.name)/'logs')
from fastapi.testclient import TestClient
from app import app
from storage import create_user,get_plan,get_support,conn

def check(response,expected=200):
    assert response.status_code==expected,(response.status_code,str(response.url),response.text[:1300]);return response

def csrf(page):
    m=re.search(r'name="_csrf" value="([^\"]+)"',page.text)
    assert m,page.text[:1500]
    return m.group(1)

with TestClient(app) as client:
    create_user('testadmin','a_very_long_testing_password','admin')
    t=csrf(check(client.get('/login')))
    check(client.post('/login',data={'_csrf':t,'username':'testadmin','password':'a_very_long_testing_password'},follow_redirects=False),303)
    t=csrf(check(client.get('/children/new')))
    check(client.post('/children/new',data={'_csrf':t,'name':'架空児童Ａ','code':'FAKE_01'},follow_redirects=False),303)
    # 個別支援計画なし、テーマ・人数・Edition空欄でも一般活動案を生成
    r=check(client.get('/children/1/generate'))
    assert '未登録' in r.text
    check(client.post('/children/1/generate',data={'_csrf':csrf(r),'consent':'yes','duration':'40','theme':'','group_size':'','edition':''},follow_redirects=False),303)
    plan=get_plan(1)
    assert plan['support_id'] is None
    assert '【未登録】' in plan['data']['goal_links'][0]['source_goal']
    assert len(plan['data']['missing_inputs'])>12
    assert any(x['field']=='theme' for x in plan['data']['missing_inputs'])
    assert '未入力情報あり' in plan['data']['note']
    r=check(client.get('/plans/1'))
    assert '要確認' in r.text and '未入力項目・AI補完の確認' in r.text
    for ext,magic in [('pdf',b'%PDF'),('docx',b'PK'),('xlsx',b'PK')]:
        r=check(client.get(f'/plans/1/export/{ext}'))
        assert r.content.startswith(magic)
    r=check(client.get('/plans/1/export/pdf?view=1'))
    assert 'inline' in r.headers['content-disposition']
    # 参照計画がない案は管理者でも確認済みにできない
    r=check(client.get('/plans/1'))
    r=check(client.post('/plans/1/approve',data={'_csrf':csrf(r),'review_missing':'yes'}))
    assert '個別支援計画が未登録' in r.text
    # 部分入力でも保存と生成が可能
    r=check(client.get('/children/1/support/new'))
    check(client.post('/children/1/support/new',data={'_csrf':csrf(r),'short_goal':'自分で役割を選ぶ'},follow_redirects=False),303)
    r=check(client.get('/children/1/generate'))
    check(client.post('/children/1/generate',data={'_csrf':csrf(r),'consent':'yes','duration':'45'},follow_redirects=False),303)
    p=get_plan(2)
    assert get_support(p['support_id'])['data']['short_goal']=='自分で役割を選ぶ'
    assert any(x['field']=='long_goal' for x in p['data']['missing_inputs'])
    assert '【原文との一致未確認' not in p['data']['goal_links'][0]['source_goal']
    # 登録済みの正式目標のもとレビュー担当者が未入力欄を確認できる
    r=check(client.get('/plans/2'))
    r=check(client.post('/plans/2/approve',data={'_csrf':csrf(r),'review_missing':'yes'}))
    assert 'デモモード' in r.text
    assert get_plan(2)['status']=='draft', 'デモは確認済みにできない想定'
print('PASS: 個別支援計画なし/部分入力/AI仮案の区別/要確認/出力/ブラウザ内表示/確認制限')
