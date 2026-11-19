"""Private-LAN Docker adapter for the unmodified Lolipop v2.20 FastAPI app.

Runs in a single Uvicorn process, with a persistent /data volume for secrets,
SQLite and logs. The CGI route is intentionally not available over HTTP.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import html
import ipaddress
import os
import re
import secrets
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import parse_qs

# Fail closed at startup if explicit LAN scoping is invalid.
RFC1918 = [ipaddress.ip_network(v) for v in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')]
BIND_RAW = os.environ.get('LAN_BIND_IP','')
CIDR_RAW = os.environ.get('LAN_ALLOWED_CIDR','')
try:
    BIND_IP = ipaddress.IPv4Address(BIND_RAW)
    ALLOWED_NET = ipaddress.ip_network(CIDR_RAW, strict=True)
    if not isinstance(ALLOWED_NET, ipaddress.IPv4Network):
        raise ValueError('Only IPv4 CIDRs supported')
    if not any(BIND_IP in net for net in RFC1918):
        raise ValueError('LAN_BIND_IP must be an RFC1918 private address')
    if BIND_IP not in ALLOWED_NET or not any(ALLOWED_NET.subnet_of(net) for net in RFC1918):
        raise ValueError('LAN_ALLOWED_CIDR must be a private IPv4 subnet containing LAN_BIND_IP')
    if ALLOWED_NET.prefixlen < 16:
        raise ValueError('CIDR too broad: require /16 or narrower, preferably /24')
    PORT = int(os.environ.get('RYOIKU_PORT','18080'))
    if not 1024 <= PORT <= 65535:
        raise ValueError('Port must be 1024-65535')
except (ValueError,TypeError) as exc:
    raise SystemExit(f'LAN configuration error: {exc}') from exc

DATA_ROOT = Path(os.environ.get('RYOIKU_DATA_DIR','/data')).resolve()
ENVFILE = DATA_ROOT / 'secrets.env'
CODEFILE = DATA_ROOT / 'INITIAL_ADMIN_CODE.txt'
DBFILE = DATA_ROOT / 'ryoiku.sqlite3'
LOGDIR = DATA_ROOT / 'logs'


def _write_atomic(path:Path, data:str):
    fd, name = tempfile.mkstemp(prefix='.ryoiku-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name,0o600)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def init_secrets():
    os.umask(0o077)
    if DATA_ROOT.is_symlink() or ENVFILE.is_symlink() or DBFILE.is_symlink() or CODEFILE.is_symlink():
        raise RuntimeError('Symlink in private storage path')
    DATA_ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    LOGDIR.mkdir(mode=0o700,parents=True,exist_ok=True)
    lockpath = DATA_ROOT / '.init.lock'
    fd = os.open(lockpath,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        if not ENVFILE.is_file():
            if DBFILE.exists():
                raise RuntimeError('Database exists without encryption secrets. Restore secrets.env; data not overwritten.')
            token=secrets.token_urlsafe(48)
            encoded_key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii')
            token_hash=hashlib.sha256(token.encode('utf-8')).hexdigest()
            _write_atomic(CODEFILE,token+'\n')
            _write_atomic(ENVFILE, '\n'.join([
                'APP_SECRET='+secrets.token_urlsafe(48),
                'DATA_ENCRYPTION_KEY='+encoded_key,
                'APP_SETUP_TOKEN_SHA256='+token_hash,
                'APP_COOKIE_SECURE=false', # LAN demo is HTTP; NEVER deploy real data to public internet.
                '',
            ]))
        if ENVFILE.stat().st_mode & 0o077:
            raise RuntimeError('Secrets file permission too permissive')
        for line in ENVFILE.read_text(encoding='utf-8').splitlines():
            if not line or line.startswith('#'):continue
            k,sep,v=line.partition('=')
            if sep and k in ('APP_SECRET','DATA_ENCRYPTION_KEY','APP_SETUP_TOKEN_SHA256','APP_COOKIE_SECURE'):
                os.environ[k]=v
        if not os.environ.get('APP_SECRET') or not os.environ.get('DATA_ENCRYPTION_KEY'):
            raise RuntimeError('Invalid secrets.env')
    os.environ['APP_DB_PATH']=str(DBFILE)
    os.environ['APP_LOG_DIR']=str(LOGDIR)
    os.environ['APP_COOKIE_SECURE']='false'
    os.environ.pop('LOLI_CGI_MODE',None)

init_secrets()

# Import the *same* v2.20 application without modifying its source.
from app import app as fastapi_app
import storage
from argon2 import PasswordHasher


def http_response(status:int,content:bytes,content_type:str='text/plain; charset=utf-8',extra:list[tuple[str,str]]|None=None):
    headers=[(b'content-type',content_type.encode()),(b'cache-control',b'no-store, private'),
             (b'x-content-type-options',b'nosniff'),(b'x-frame-options',b'DENY'),
             (b'content-security-policy',b"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")]
    headers.extend((k.encode(),v.encode()) for k,v in (extra or []))
    return {'type':'http.response.start','status':status,'headers':headers}, {'type':'http.response.body','body':content}

async def send_content(send,status:int,content:bytes,content_type='text/plain; charset=utf-8',extra=None):
    for message in http_response(status,content,content_type,extra):await send(message)

SETUP_HTML = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>初回管理者登録</title><style>body{font:16px system-ui,sans-serif;max-width:620px;margin:40px auto;padding:0 18px;line-height:1.7;color:#17283c}label{display:block;margin-top:15px}input{box-sizing:border-box;width:100%;padding:12px;border:1px solid #9da9b6;border-radius:6px}button{margin-top:22px;background:#203f62;color:white;border:0;border-radius:6px;padding:12px 24px;cursor:pointer}code{font-size:14px}</style></head><body><h1>初回管理者登録</h1><p>Ubuntu Serverで次のコマンドを実行し、表示された<strong>初回登録コード</strong>を入力してください。</p><p><code>sudo docker compose exec -T ryoiku cat /data/INITIAL_ADMIN_CODE.txt</code></p><p>管理者パスワードは16文字以上としてください。登録後はコードが破棄されます。</p><form action="/first-setup" method="post" autocomplete="off"><label>初回登録コード<input type="password" name="token" required></label><label>ユーザー名（英数字・記号）<input name="username" minlength="3" maxlength="40" required></label><label>管理者パスワード<input type="password" name="password" minlength="16" required></label><label>パスワード（確認）<input type="password" name="confirm" minlength="16" required></label><button type="submit">管理者を登録</button></form><p>実際の児童情報はテスト環境に入力しないでください。</p></body></html>'''

class LANOnlySetup:
    def __init__(self,app):self.app=app

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':
            return await self.app(scope,receive,send)
        raw_client=scope.get('client')
        try:
            client=ipaddress.ip_address(raw_client[0] if raw_client else '')
            if not isinstance(client,ipaddress.IPv4Address) or client not in ALLOWED_NET:
                raise ValueError('not within LAN')
        except ValueError:
            return await send_content(send,403,b'LAN access only')
        # Reject DNS rebinding / arbitrary Host headers. Only the numeric LAN URL is supported.
        host_header=dict(scope.get('headers',[])).get(b'host',b'').decode('latin-1','replace')
        if host_header not in (str(BIND_IP),f'{BIND_IP}:{PORT}'):
            return await send_content(send,400,b'Invalid LAN host')
        method=scope['method'].upper()
        path=scope.get('path','/')
        if path=='/healthz':
            return await send_content(send,200,b'OK')
        # Startup for the FastAPI app initializes the database.
        try:
            with storage.conn() as c:
                count=c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        except (sqlite3.Error,OSError):
            return await send_content(send,503,b'Database not ready')
        if path=='/first-setup':
            if count:
                return await send_content(send,404,b'Not found')
            if method=='GET':
                return await send_content(send,200,SETUP_HTML.encode('utf-8'),'text/html; charset=utf-8')
            if method!='POST':
                return await send_content(send,405,b'Method not allowed')
            header_dict=dict(scope.get('headers',[]))
            ctype=header_dict.get(b'content-type',b'').lower()
            if not ctype.startswith(b'application/x-www-form-urlencoded'):
                return await send_content(send,415,b'Unsupported content type')
            raw=b''
            while True:
                m=await receive()
                if m['type']=='http.disconnect':return
                raw+=m.get('body',b'')
                if len(raw)>8192:return await send_content(send,413,b'Too large')
                if not m.get('more_body',False):break
            form=parse_qs(raw.decode('utf-8','replace'),keep_blank_values=True)
            token=form.get('token',[''])[0]
            username=form.get('username',[''])[0]
            password=form.get('password',[''])[0]
            confirm=form.get('confirm',[''])[0]
            expected=os.environ.get('APP_SETUP_TOKEN_SHA256','')
            valid=bool(expected) and hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(),expected)
            if (not valid or not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}',username) or
                not (16<=len(password)<=256) or not hmac.compare_digest(password,confirm)):
                return await send_content(send,403,'登録情報が正しくありません。'.encode('utf-8'))
            try:
                # Single worker; DB transaction ensures no second admin can be registered.
                with storage.conn() as c:
                    c.execute('BEGIN IMMEDIATE')
                    if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
                        return await send_content(send,403,b'Already configured')
                    c.execute('INSERT INTO users(username,pass_hash,role,created_at) VALUES(?,?,?,?)',
                              (username,PasswordHasher().hash(password),'admin',storage.now()))
                CODEFILE.unlink(missing_ok=True)
                # Remove the one-time token hash from persistent config as an additional defense.
                text=ENVFILE.read_text(encoding='utf-8')
                _write_atomic(ENVFILE,'\n'.join(z for z in text.splitlines() if not z.startswith('APP_SETUP_TOKEN_SHA256='))+'\n')
                os.environ.pop('APP_SETUP_TOKEN_SHA256',None)
                return await send_content(send,303,b'','text/plain; charset=utf-8',[('location','/login')])
            except (sqlite3.Error,OSError):
                return await send_content(send,503,b'Admin setup failed')
        if count==0:
            return await send_content(send,303,b'','text/plain; charset=utf-8',[('location','/first-setup')])
        return await self.app(scope,receive,send)

application=LANOnlySetup(fastapi_app)

if __name__=='__main__':
    import uvicorn
    # Host-network binding ensures the process cannot listen on WAN/0.0.0.0.
    uvicorn.run(application,host=str(BIND_IP),port=PORT,workers=1,
                proxy_headers=False,access_log=False,server_header=False,forwarded_allow_ips='')
