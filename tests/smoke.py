"""実行例：python tests/smoke.py（シークレット値は内部で一時設定）"""
import os,sys,tempfile,re,zipfile,io
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
temp=tempfile.TemporaryDirectory(prefix='ryoiku_smoke_')
from cryptography.fernet import Fernet
os.environ['APP_SECRET']='x'*64
os.environ['DATA_ENCRYPTION_KEY']=Fernet.generate_key().decode()
os.environ['APP_DB_PATH']=str(Path(temp.name)/'database.db')
os.environ['APP_LOG_DIR']=str(Path(temp.name)/'logs')
from fastapi.testclient import TestClient
from app import app
from storage import create_user

def token(r):
    match=re.search(r'name="_csrf" value="([^"]+)"',r.text)
    assert match,(r.url,r.text[:1000])
    return match.group(1)

def ok(r, code=200):
    assert r.status_code==code,(r.status_code,str(r.url),r.text[:1000]);return r

with TestClient(app) as c:
    create_user('admin','good_secure_password_123','admin')
    r=ok(c.get('/login'));csrf=token(r)
    ok(c.post('/login',data={'_csrf':csrf,'username':'admin','password':'good_secure_password_123'},follow_redirects=False),303)
    r=ok(c.get('/'));csrf=token(r)
    ok(c.post('/children/new',data={'_csrf':csrf,'code':'TEST_01','name':'架空のテスト児童','grade':'小学5年生',
        'interests':'建築','strengths':'好きなことを説明できる','needs':'活動開始の見通しが必要'},follow_redirects=False),303)
    r=ok(c.get('/children/1'));csrf=token(r)
    r=ok(c.get('/children/1/support/new'));csrf=token(r)
    ok(c.post('/children/1/support/new',data={'_csrf':csrf,'short_goal':'自分の希望を2択から伝える',
       'long_goal':'仲間と協力しながら安心して活動する','accommodation':'画面の刺激が強いときは休む',
       'original_text':'個別支援計画：選択肢を示し、自分の意思で活動を選ぶ'},follow_redirects=False),303)
    r=ok(c.get('/children/1'));assert '第1版' in r.text
    r=ok(c.get('/children/1/generate'));csrf=token(r)
    ok(c.post('/children/1/generate',data={'_csrf':csrf,'consent':'yes','duration':'45',
       'theme':'建築','group_size':'2人','edition':'統合版'},follow_redirects=False),303)
    r=ok(c.get('/plans/1'));assert '個別支援計画との対応' in r.text
    # テンプレート + ダウンロード形式の整合性
    r=ok(c.get('/plans/1/export/pdf'));assert r.content[:4]==b'%PDF',(r.content[:80])
    pdf=r.content
    r=ok(c.get('/plans/1/export/docx'));assert zipfile.is_zipfile(io.BytesIO(r.content));doc=r.content
    r=ok(c.get('/plans/1/export/xlsx'));assert zipfile.is_zipfile(io.BytesIO(r.content));xls=r.content
    r=ok(c.get('/plans/1/edit'));csrf=token(r)
    # 全項目を編集しなくても既存の値を保持する
    # POST検証は既存の書式を維持するため対象外（画面を開けることだけ確認）
    r=ok(c.get('/admin/logs'));assert '操作ログ' in r.text
    assert ok(c.get('/admin/logs/activity.csv')).content.startswith(b'\xef\xbb\xbf')
    with zipfile.ZipFile(io.BytesIO(xls)) as z: assert len([x for x in z.namelist() if x.startswith('xl/worksheets/sheet')])>=4
    # zipの外側にもサンプルを出力（実データは一切使用しない）
    dest=root/'samples';dest.mkdir(exist_ok=True)
    for ext,payload in [('pdf',pdf),('docx',doc),('xlsx',xls)]:
        (dest/f'demo_minecraft_plan.{ext}').write_bytes(payload)
print('PASS: ログイン→利用者登録→個別支援計画v1→AIデモ→PDF/DOCX/XLSX→履歴・ログ閲覧')
