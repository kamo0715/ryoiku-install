"""Modern Web Guidance regression tests. Uses fictional data and an isolated database."""
from pathlib import Path
import os, sys, tempfile, re
from cryptography.fernet import Fernet
root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
with tempfile.TemporaryDirectory(prefix='ryoiku_modern_test_') as d:
    os.environ['APP_SECRET']='M'*64
    os.environ['DATA_ENCRYPTION_KEY']=Fernet.generate_key().decode()
    os.environ['APP_DB_PATH']=str(Path(d)/'db.sqlite3')
    os.environ['APP_LOG_DIR']=str(Path(d)/'logs')
    from fastapi.testclient import TestClient
    from app import app
    from storage import create_user
    with TestClient(app) as c:
        r=c.get('/login')
        assert r.status_code==200
        assert "script-src 'self'" in r.headers['content-security-policy']
        assert "frame-ancestors 'none'" in r.headers['content-security-policy']
        assert "require-trusted-types-for 'script'" in r.headers['content-security-policy']
        assert r.headers['cache-control'].startswith('no-store')
        assert r.headers['x-frame-options']=='DENY'
        assert r.headers['referrer-policy']=='no-referrer'
        assert '<a class="skip-link"' in r.text
        assert '<main class="shell" id="main-content"' in r.text
        assert '<dialog id="confirm-dialog"' in r.text
        assert '<script src="/static/app.js" defer>' in r.text
        assert not re.search(r'<script(?![^>]*\bsrc=)[^>]*>',r.text)
        assert not re.search(r'\son\w+\s*=',r.text)
        css=c.get('/static/app.css')
        assert css.status_code==200 and 'prefers-reduced-motion' in css.text
        assert 'forced-colors' in css.text
        js=c.get('/static/app.js')
        assert js.status_code==200 and 'showModal' in js.text
        assert 'innerHTML' not in js.text and 'eval(' not in js.text
        assert css.headers['cache-control'].startswith('public')
        create_user('modern_admin','secure_password_12345','admin')
        token=re.search(r'name="_csrf" value="([^"]+)"',r.text).group(1)
        resp=c.post('/login',data={'username':'modern_admin','password':'secure_password_12345','_csrf':token},follow_redirects=False)
        assert resp.status_code==303
        r=c.get('/')
        assert '<nav aria-label="メインナビゲーション"' in r.text
        assert 'id="filter" type="search"' not in r.text  # no children yet
        r=c.get('/children/new');token=re.search(r'name="_csrf" value="([^"]+)"',r.text).group(1)
        res=c.post('/children/new',data={'_csrf':token,'name':'架空児童','code':'FAKE009'},follow_redirects=False)
        assert res.status_code==303
        r=c.get('/')
        assert 'id="filter" type="search"' in r.text
        r=c.get('/children/1/generate')
        assert 'data-focus-by-group=' in r.text
        assert 'id="kind_wrap"' in r.text
        assert not re.search(r'<script(?![^>]*\bsrc=)[^>]*>',r.text)
        assert 'onchange=' not in r.text and 'onsubmit=' not in r.text
        r=c.get('/admin/users')
        assert 'data-confirm=' in r.text
        r=c.get('/admin/logs')
        assert r.status_code==200 and 'CSV' in r.text
        r=c.post('/children/new', data={'name':'違反'},headers={'Sec-Fetch-Site':'cross-site'})
        assert r.status_code==403
print('PASS: CSP・安全な静的JS・HTTPヘッダー・スキップリンク・確認ダイアログ・フォーム・管理画面・Fetch Metadata')
