#!/usr/local/bin/python3.13
"""Experimental FastAPI-to-CGI adapter for Lolipop new Python 3.13 hosts."""
import asyncio
import html
import os
import re
import sys
import secrets
import hmac
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

WEBROOT=Path(__file__).resolve().parent
APP_ROOT=WEBROOT/'_private'/'app'
VENDOR_ROOT=WEBROOT/'_private'/'vendor'
sys.path.insert(0,str(VENDOR_ROOT))
sys.path.insert(0,str(APP_ROOT))
os.environ['PYTHONDONTWRITEBYTECODE']='1'
os.environ['LOLI_CGI_MODE']='true'
# Prevent writing compiled bytecode into FTP-uploaded library folders.
sys.dont_write_bytecode=True

def write_response(code, body, headers=None):
    reason={200:'OK',302:'Found',303:'See Other',400:'Bad Request',403:'Forbidden',404:'Not Found',413:'Content Too Large',500:'Internal Server Error',503:'Service Unavailable'}.get(code,'OK')
    body=body if isinstance(body,bytes) else str(body).encode('utf8')
    print(f'Status: {code} {reason}\r')
    for k,v in (headers or []):
        print(f'{k}: {v}\r')
    print('Cache-Control: no-store, private\r')
    print('X-Content-Type-Options: nosniff\r')
    print(f'Content-Length: {len(body)}\r')
    print('\r')
    sys.stdout.flush()
    if os.environ.get('REQUEST_METHOD','GET').upper()!='HEAD':
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()

def fail(message,code=503):
    # No credentials or stack traces in responses.
    write_response(code,html.escape(message),[('Content-Type','text/plain; charset=utf-8')])

def bootstrap(method, payload, user_count, storage):
    """Token-gated one-time admin creation. Secret generated on the web server."""
    token=os.environ.get('APP_SETUP_TOKEN','')
    token_hash=os.environ.get('APP_SETUP_TOKEN_SHA256','')
    if user_count>0:
        return fail('初期セットアップはすでに終了しました。',404)
    if not (token_hash or (token and len(token)>=48)):
        return fail('初期設定ファイルがありません。FTP配置を確認してください。',503)
    if method=='GET':
        body="""<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>初期管理者設定</title><h2>初期管理者の登録</h2><p>FTPSソフトで <code>_private/app/data/INITIAL_ADMIN_CODE.txt</code> を開き、そこに記載された初回登録コードを入力してください。コードはWeb画面やメールでは配布しません。</p><p>管理者パスワードは16文字以上にしてください。</p><form action="/first-setup" method="post" autocomplete="off"><label>トークン<input type="password" name="token" required></label><p><label>ユーザー名<input name="username" minlength="3" maxlength="40" required></label></p><p><label>管理者パスワード<input type="password" name="password" minlength="16" required></label></p><p><label>パスワード（確認）<input type="password" name="confirm" minlength="16" required></label></p><button type="submit">登録</button></form></html>""".encode('utf8')
        return write_response(200,body,[('Content-Type','text/html; charset=utf-8'),('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")])
    if method!='POST':return fail('この操作はできません。',400)
    if len(payload)>5120:return fail('入力が大きすぎます。',413)
    fields=parse_qs(payload.decode('utf8','replace'),keep_blank_values=True)
    candidate=fields.get('token',[''])[0]
    username=fields.get('username',[''])[0]
    passwd=fields.get('password',[''])[0]
    confirm=fields.get('confirm',[''])[0]
    if token_hash:
        import hashlib
        candidate_hash=hashlib.sha256(candidate.encode('utf-8')).hexdigest()
        ok=hmac.compare_digest(token_hash,candidate_hash)
    else:
        ok=hmac.compare_digest(token,candidate)
    if not ok:return fail('登録内容を確認してください。',403)
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}',username) or len(passwd)<16 or len(passwd)>256 or not hmac.compare_digest(passwd,confirm):
        return fail('ユーザー名またはパスワードを確認してください。',400)
    # DB unique username ensures double submission cannot create a second admin.
    try:
        with storage.conn() as c:
            number=c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            if number: return fail('初期管理者はすでに作成済みです。',403)
            c.execute('BEGIN IMMEDIATE')
            from argon2 import PasswordHasher
            c.execute('INSERT INTO users(username,pass_hash,role,created_at) VALUES(?,?,?,?)',
                      (username,PasswordHasher().hash(passwd),'admin',storage.now()))
    except Exception:
        return fail('管理者を作成できませんでした。管理者にご連絡ください。',503)
    # Consume setup token; stored .env is rewritten without it, if writable.
    envfile=APP_ROOT/'.env'
    try:
        import tempfile
        rows=[line for line in envfile.read_text(encoding='utf8').splitlines() if not line.startswith(('APP_SETUP_TOKEN=','APP_SETUP_TOKEN_SHA256='))]
        fd, filename=tempfile.mkstemp(prefix='.env-new-',dir=APP_ROOT)
        try:
            with os.fdopen(fd,'w',encoding='utf8') as out:out.write('\n'.join(rows)+'\n')
            os.chmod(filename,0o600)
            os.replace(filename,envfile)
        finally:
            if os.path.exists(filename):os.unlink(filename)
    except Exception:
        pass  # Existing admin count prevents using the bootstrap endpoint again.
    try:
        (APP_ROOT/'data'/'INITIAL_ADMIN_CODE.txt').unlink(missing_ok=True)
    except OSError:
        pass  # Already consumed by user count, but code removal needs operator attention.
    return write_response(303,b'',[('Location','/login')])

async def serve_asgi(app,env,body,path,query):
    sent=False
    disconnected=asyncio.Event()
    status=500
    reason='Internal Server Error'
    header_list=[]
    body_chunks=[]
    method=env.get('REQUEST_METHOD','GET').upper()
    request_headers=[]
    for key,value in env.items():
        if key.startswith('HTTP_'):
            header=key[5:].lower().replace('_','-')
            if header not in ('proxy','connection','transfer-encoding'):
                request_headers.append((header.encode('latin-1'),value.encode('latin-1','replace')))
    for header in ('CONTENT_TYPE','CONTENT_LENGTH'):
        if header in env:
            request_headers.append((header.lower().replace('_','-').encode('latin-1'),env[header].encode('latin-1','replace')))
    # RFC: avoid using client-provided forwarded headers to decide cookie security.
    host=env.get('HTTP_HOST',env.get('SERVER_NAME','localhost'))
    if not env.get('HTTP_HOST'):
        request_headers.append((b'host',host.encode('latin-1','replace')))
    https=(env.get('HTTPS','').lower() in ('on','1','yes'))
    scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.3'},'http_version':'1.1',
           'method':method,'scheme':'https' if https else 'http','path':path,'raw_path':path.encode('utf8'),
           'query_string':query.encode('latin-1','replace'),'root_path':'','headers':request_headers,
           'client':(env.get('REMOTE_ADDR','0.0.0.0'),0),
           'server':(env.get('SERVER_NAME','localhost'),int(env.get('SERVER_PORT','443' if https else '80')))}
    async def receive():
        nonlocal sent
        if not sent:
            sent=True
            return {'type':'http.request','body':body,'more_body':False}
        await disconnected.wait()
        return {'type':'http.disconnect'}
    async def send(message):
        nonlocal status,reason,header_list
        kind=message['type']
        if kind=='http.response.start':
            status=message['status']
            reason={200:'OK',201:'Created',302:'Found',303:'See Other',400:'Bad Request',401:'Unauthorized',403:'Forbidden',404:'Not Found',413:'Content Too Large',422:'Unprocessable Entity',500:'Internal Server Error'}.get(status,'OK')
            header_list=[(k.decode('latin-1'),v.decode('latin-1')) for k,v in message.get('headers',[]) if k.lower() not in (b'transfer-encoding',b'connection')]
        elif kind=='http.response.body':
            body_chunks.append(message.get('body',b''))
    try:
        await app(scope,receive,send)
    finally:
        disconnected.set()
    payload=b''.join(body_chunks)
    # Headers include multiple Set-Cookie values; do not collapse.
    header_list=[(k,v) for k,v in header_list if k.lower()!='content-length']
    header_list.append(('Content-Length',str(len(payload))))
    print(f'Status: {status} {reason}\r')
    for name,value in header_list:print(f'{name}: {value}\r')
    print('\r')
    sys.stdout.flush()
    if method!='HEAD':
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()

def main():
    # This must happen before settings imports, otherwise first visit fails.
    try:
        from server_bootstrap import ensure_initial_config, BootstrapError
        ensure_initial_config(APP_ROOT)
    except BootstrapError:
        return fail('初回設定を作成できません。FTPSで書込権限と既存DBの有無を確認してください。',503)
    from settings import check_settings
    import storage
    try:
        check_settings()
        storage.init_db()
        storage.init_records()
    except Exception:
        return fail('療育システムの初期設定またはデータ領域を確認してください。',503)
    method=os.environ.get('REQUEST_METHOD','GET').upper()
    url=os.environ.get('REQUEST_URI') or os.environ.get('REDIRECT_URL') or os.environ.get('PATH_INFO') or '/'
    url=urlsplit(url)
    path=url.path or '/'
    try:
        count=storage.conn().execute('SELECT COUNT(*) FROM users').fetchone()[0]
    except Exception:
        return fail('初期設定の確認に失敗しました。',503)
    content_length=os.environ.get('CONTENT_LENGTH','0')
    try: n=int(content_length)
    except ValueError:return fail('不正な送信データです。',400)
    if n<0 or n>20*1024*1024:return fail('送信サイズが大きすぎます。',413)
    body=sys.stdin.buffer.read(n) if n else b''
    if len(body)!=n:return fail('送信データが途中で途切れました。',400)
    if path=='/first-setup':return bootstrap(method,body,count,storage)
    if count==0:return write_response(303,b'',[('Location','/first-setup')])
    # CGI processes do not share memory, so use DB-backed login attempt throttling.
    if method=='POST' and path=='/login':
        from settings import APP_SECRET
        import hashlib,time
        ip_key=hmac.new(APP_SECRET.encode('utf8'),
                        os.environ.get('REMOTE_ADDR','unknown').encode('utf8'),hashlib.sha256).hexdigest()
        now=int(time.time())
        try:
            with storage.conn() as c:
                c.execute('CREATE TABLE IF NOT EXISTS cgi_login_throttle (ip_key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires_at INTEGER NOT NULL)')
                c.execute('DELETE FROM cgi_login_throttle WHERE expires_at<?',(now,))
                record=c.execute('SELECT attempts,expires_at FROM cgi_login_throttle WHERE ip_key=?',(ip_key,)).fetchone()
                if record and record[0]>=8 and record[1]>now:
                    return fail('ログインの試行回数が上限に達しました。15分後に再試行してください。',429)
                c.execute('INSERT INTO cgi_login_throttle(ip_key,attempts,expires_at) VALUES(?,1,?) ON CONFLICT(ip_key) DO UPDATE SET attempts=attempts+1',
                          (ip_key,now+900))
        except Exception:
            return fail('ログイン保護処理を確認できません。管理者に連絡してください。',503)
    from app import app
    asyncio.run(serve_asgi(app,os.environ,body,path,url.query))

if __name__=='__main__':
    try:main()
    except Exception:
        fail('処理に失敗しました。管理者がサーバーのログを確認してください。',500)
