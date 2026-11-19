import os
import base64
import csv
import hashlib
import hmac
import secrets
import time
import json
import sqlite3
import threading
import traceback
from datetime import datetime, timezone
from cryptography.fernet import Fernet
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from settings import DB_PATH, LOG_DIR, KEY, APP_SECRET

hasher = PasswordHasher()
cipher = Fernet(KEY.encode()) if KEY and not KEY.startswith('REPLACE') else None
lock = threading.Lock()

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def enc(value):
    return cipher.encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()

def dec(value):
    return json.loads(cipher.decrypt(value.encode()).decode())

def conn():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=15000')
    return c

def init_db():
    with conn() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          pass_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','reviewer','staff')),
          active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS children(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL,
          payload TEXT NOT NULL, archived INTEGER DEFAULT 0, created_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          FOREIGN KEY(created_by) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS support_plans(id INTEGER PRIMARY KEY, child_id INTEGER NOT NULL,
          version INTEGER NOT NULL, payload TEXT NOT NULL, author_id INTEGER NOT NULL,
          created_at TEXT NOT NULL, UNIQUE(child_id,version),
          FOREIGN KEY(child_id) REFERENCES children(id),FOREIGN KEY(author_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY, child_id INTEGER NOT NULL,
          support_id INTEGER, content TEXT NOT NULL, provider TEXT NOT NULL,
          model TEXT NOT NULL, author_id INTEGER NOT NULL, created_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft', approved_by INTEGER, approved_at TEXT,
          review_note TEXT NOT NULL DEFAULT '', revised_at TEXT,
          FOREIGN KEY(child_id) REFERENCES children(id), FOREIGN KEY(support_id) REFERENCES support_plans(id));
        CREATE TABLE IF NOT EXISTS password_reset_codes(
          user_id INTEGER PRIMARY KEY, token_hash TEXT NOT NULL,
          expires_at INTEGER NOT NULL, failed_attempts INTEGER NOT NULL DEFAULT 0,
          issued_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ai_credentials(
          provider TEXT PRIMARY KEY, encrypted_key TEXT NOT NULL, updated_at TEXT NOT NULL);
        ''')
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('provider','demo')")
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('model','demo')")
    migrate_support_nullable()
    migrate_users_session_version()



def migrate_users_session_version():
    """旧ユーザーを消さず、パスワード変更/無効化時のセッション無効化を追加。"""
    with conn() as c:
        columns={row['name'] for row in c.execute('PRAGMA table_info(users)')}
        if 'session_version' not in columns:
            c.execute('ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1')

def migrate_support_nullable():
    """旧版の NOT NULL 制約を解除し、既存レコードIDを保持する。"""
    with conn() as c:
        fields=c.execute('PRAGMA table_info(plans)').fetchall()
        old=next((x for x in fields if x['name']=='support_id'),None)
        if not old or not old['notnull']:
            return
        c.execute('PRAGMA foreign_keys=OFF')
        try:
            c.execute('BEGIN IMMEDIATE')
            sql=("CREATE TABLE plans_new(id INTEGER PRIMARY KEY, child_id INTEGER NOT NULL, "
                 "support_id INTEGER, content TEXT NOT NULL, provider TEXT NOT NULL, "
                 "model TEXT NOT NULL, author_id INTEGER NOT NULL, created_at TEXT NOT NULL, "
                 "status TEXT NOT NULL DEFAULT 'draft', approved_by INTEGER, approved_at TEXT, "
                 "review_note TEXT NOT NULL DEFAULT '', revised_at TEXT, "
                 "FOREIGN KEY(child_id) REFERENCES children(id), "
                 "FOREIGN KEY(support_id) REFERENCES support_plans(id))")
            c.execute(sql)
            cols=('id,child_id,support_id,content,provider,model,author_id,created_at,'
                  'status,approved_by,approved_at,review_note,revised_at')
            c.execute(f'INSERT INTO plans_new({cols}) SELECT {cols} FROM plans')
            c.execute('DROP TABLE plans')
            c.execute('ALTER TABLE plans_new RENAME TO plans')
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.execute('PRAGMA foreign_keys=ON')
        if c.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('データ移行後に参照整合性エラーが発生しました')


def get_setting(key, fallback=''):
    with conn() as c:
        r=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return r['value'] if r else fallback

def set_setting(key,value):
    with conn() as c: c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,value))

def set_ai_credential(provider, api_key):
    # APIキーはFernet暗号化して保存し、ログには含めない。
    from providers import PROVIDERS
    if provider not in PROVIDERS or not PROVIDERS[provider]['env']:
        raise ValueError('この提供元はAPIキーを使用しません')
    if not 8 <= len(api_key) <= 4096 or any(ord(c) < 32 or ord(c) == 127 for c in api_key):
        raise ValueError('APIキーは8〜4096文字の制御文字を含まない文字列にしてください')
    encrypted = cipher.encrypt(api_key.encode('utf-8')).decode('ascii')
    with conn() as c:
        c.execute('''INSERT INTO ai_credentials(provider,encrypted_key,updated_at)
          VALUES(?,?,?) ON CONFLICT(provider) DO UPDATE SET
          encrypted_key=excluded.encrypted_key,updated_at=excluded.updated_at''',
          (provider,encrypted,now()))


def get_ai_credential(provider):
    with conn() as c:
        row=c.execute('SELECT encrypted_key FROM ai_credentials WHERE provider=?',(provider,)).fetchone()
    if row:
        return cipher.decrypt(row['encrypted_key'].encode('ascii')).decode('utf-8')
    from providers import PROVIDERS
    entry=PROVIDERS.get(provider)
    return os.getenv(entry['env'],'') if entry and entry['env'] else ''


def ai_credential_status(provider):
    from providers import PROVIDERS
    entry=PROVIDERS.get(provider)
    if not entry or not entry['env']: return '不要'
    with conn() as c:
        row=c.execute('SELECT 1 FROM ai_credentials WHERE provider=?',(provider,)).fetchone()
    if row: return 'WebUIで登録済み'
    return '環境変数で設定済み' if bool(os.getenv(entry['env'])) else '未登録'


def delete_ai_credential(provider):
    # WebUIで保存したキーだけ削除。環境変数に設定があればそちらに戻る。
    with conn() as c: c.execute('DELETE FROM ai_credentials WHERE provider=?',(provider,))


def create_user(username,password,role='staff'):
    with conn() as c:
        c.execute('INSERT INTO users(username,pass_hash,role,created_at) VALUES(?,?,?,?)',
                 (username,hasher.hash(password),role,now()))

def auth(username,password):
    with conn() as c:
        row=c.execute('SELECT * FROM users WHERE username=? AND active=1',(username,)).fetchone()
    if not row: return None
    try:
        if hasher.verify(row['pass_hash'],password): return dict(row)
    except (VerifyMismatchError,VerificationError): pass
    return None

def user_by_id(uid):
    with conn() as c: r=c.execute('SELECT id,username,role,active,session_version FROM users WHERE id=?',(uid,)).fetchone()
    return dict(r) if r and r['active'] else None

def list_users():
    with conn() as c: return [dict(x) for x in c.execute('SELECT id,username,role,active,created_at FROM users ORDER BY id')]

def change_user_role(uid,role):
    if role not in ('admin','reviewer','staff'):
        raise ValueError('不正な権限です')
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT role,active FROM users WHERE id=?',(uid,)).fetchone()
        if not old:raise ValueError('対象の職員は存在しません')
        if old['role']=='admin' and old['active'] and role!='admin':
            remaining=c.execute("SELECT count(*) AS n FROM users WHERE role='admin' AND active=1").fetchone()['n']
            if remaining<=1:raise ValueError('最後の有効な管理者は権限変更できません')
        c.execute('UPDATE users SET role=?,session_version=session_version+1 WHERE id=?',(role,uid))

def change_user_status(uid,active):
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT role,active FROM users WHERE id=?',(uid,)).fetchone()
        if not old:raise ValueError('対象の職員は存在しません')
        if old['role']=='admin' and old['active'] and not active:
            remaining=c.execute("SELECT count(*) AS n FROM users WHERE role='admin' AND active=1").fetchone()['n']
            if remaining<=1:raise ValueError('最後の有効な管理者は停止できません')
        c.execute('UPDATE users SET active=?,session_version=session_version+1 WHERE id=?',(int(bool(active)),uid))

def reset_user_password(uid,password):
    if not (12<=len(password)<=256):raise ValueError('パスワードは12～256文字で入力してください')
    digest=hasher.hash(password)
    with conn() as c:
        cur=c.execute('UPDATE users SET pass_hash=?,session_version=session_version+1 WHERE id=?',(digest,uid))
        if cur.rowcount!=1:raise ValueError('対象の職員は存在しません')

# The CLI prints the one-time code once. Only its keyed digest is stored.
# Codes may be used from the browser, but must be issued by an OS administrator.
RESET_CODE_TTL = 15 * 60
RESET_CODE_ATTEMPTS = 5

def _reset_digest(uid, code):
    return hmac.new(APP_SECRET.encode('utf-8'),
                    f'{uid}:{code}'.encode('utf-8'), hashlib.sha256).hexdigest()

def issue_password_reset_code(username):
    username = username.strip()
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        user = c.execute('SELECT id FROM users WHERE username=? AND active=1',
                         (username,)).fetchone()
        if not user:
            raise ValueError('そのユーザー名の有効なアカウントが見つかりません。')
        code = secrets.token_urlsafe(32)
        uid = user['id']
        c.execute("""INSERT INTO password_reset_codes
            (user_id,token_hash,expires_at,failed_attempts,issued_at) VALUES(?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
            token_hash=excluded.token_hash, expires_at=excluded.expires_at,
            failed_attempts=0, issued_at=excluded.issued_at""",
            (uid, _reset_digest(uid,code), int(time.time())+RESET_CODE_TTL,0,now()))
    return uid,code

def consume_password_reset_code(username,code,new_password):
    # All invalid codes get the same response; no account existence disclosure.
    if not (12<=len(new_password)<=256):
        raise ValueError('新しいパスワードは12～256文字で入力してください。')
    if len(username)>80 or len(code)>150:
        return False
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        u = c.execute('SELECT id FROM users WHERE username=? AND active=1',
                      (username.strip(),)).fetchone()
        if not u: return False
        uid=u['id']
        token=c.execute('SELECT token_hash,expires_at,failed_attempts '
                        'FROM password_reset_codes WHERE user_id=?',(uid,)).fetchone()
        if not token: return False
        if token['expires_at']<int(time.time()) or token['failed_attempts']>=RESET_CODE_ATTEMPTS:
            c.execute('DELETE FROM password_reset_codes WHERE user_id=?',(uid,))
            return False
        if not hmac.compare_digest(token['token_hash'],_reset_digest(uid,code.strip())):
            c.execute('UPDATE password_reset_codes SET failed_attempts=failed_attempts+1 '
                      'WHERE user_id=?',(uid,))
            return False
        digest=hasher.hash(new_password)
        c.execute('UPDATE users SET pass_hash=?,session_version=session_version+1 '
                  'WHERE id=?',(digest,uid))
        c.execute('DELETE FROM password_reset_codes WHERE user_id=?',(uid,))
        return True

def user_exists(uid):
    with conn() as c:return c.execute('SELECT id FROM users WHERE id=?',(uid,)).fetchone() is not None


def new_child(code,payload,uid):
    timestamp=now()
    with conn() as c:
        cur=c.execute('INSERT INTO children(code,payload,created_by,created_at,updated_at) VALUES(?,?,?,?,?)',
             (code,enc(payload),uid,timestamp,timestamp))
        return cur.lastrowid

def get_child(cid, include_archived=False):
    # 削除（保管）中の利用者は通常アクセスから遮断する。
    with conn() as c:
        r=c.execute('SELECT * FROM children WHERE id=?' +
                    ('' if include_archived else ' AND archived=0'), (cid,)).fetchone()
    return ({**dict(r), 'data':dec(r['payload'])} if r else None)

def all_children():
    with conn() as c: rows=c.execute('SELECT * FROM children WHERE archived=0 ORDER BY id DESC').fetchall()
    return [{**dict(r),'data':dec(r['payload'])} for r in rows]

def deleted_children():
    with conn() as c:
        rows=c.execute('SELECT * FROM children WHERE archived=1 ORDER BY updated_at DESC, id DESC').fetchall()
    return [{**dict(r),'data':dec(r['payload'])} for r in rows]

def child_history_counts(cid):
    with conn() as c:
        supports=c.execute('SELECT COUNT(*) FROM support_plans WHERE child_id=?',(cid,)).fetchone()[0]
        plans=c.execute('SELECT COUNT(*) FROM plans WHERE child_id=?',(cid,)).fetchone()[0]
    return {'supports':supports, 'plans':plans}

def edit_child(cid,payload):
    with conn() as c: c.execute('UPDATE children SET payload=?,updated_at=? WHERE id=?',(enc(payload),now(),cid))

def archive_child(cid):
    with conn() as c: return c.execute('UPDATE children SET archived=1,updated_at=? WHERE id=? AND archived=0',(now(),cid)).rowcount

def restore_child(cid):
    with conn() as c:
        return c.execute('UPDATE children SET archived=0,updated_at=? WHERE id=? AND archived=1',
                         (now(),cid)).rowcount

def new_support(cid,payload,uid):
    with conn() as c:
        version=c.execute('SELECT COALESCE(MAX(version),0)+1 AS v FROM support_plans WHERE child_id=?',(cid,)).fetchone()['v']
        cur=c.execute('INSERT INTO support_plans(child_id,version,payload,author_id,created_at) VALUES(?,?,?,?,?)',
                      (cid,version,enc(payload),uid,now()))
        return cur.lastrowid,version

def get_support(sid):
    with conn() as c: r=c.execute('SELECT s.* FROM support_plans s JOIN children ch ON s.child_id=ch.id WHERE s.id=? AND ch.archived=0',(sid,)).fetchone()
    return ({**dict(r),'data':dec(r['payload'])} if r else None)

def support_history(cid):
    with conn() as c: rows=c.execute('SELECT * FROM support_plans WHERE child_id=? ORDER BY version DESC',(cid,)).fetchall()
    return [{**dict(r),'data':dec(r['payload'])} for r in rows]

def latest_support(cid):
    with conn() as c: r=c.execute('SELECT id FROM support_plans WHERE child_id=? ORDER BY version DESC LIMIT 1',(cid,)).fetchone()
    return get_support(r['id']) if r else None

def add_plan(cid,support_id,content,provider,model,uid):
    with conn() as c:
        cur=c.execute('INSERT INTO plans(child_id,support_id,content,provider,model,author_id,created_at) VALUES(?,?,?,?,?,?,?)',
                     (cid,support_id,enc(content),provider,model,uid,now()))
        return cur.lastrowid

def get_plan(pid):
    with conn() as c: r=c.execute('SELECT p.* FROM plans p JOIN children ch ON p.child_id=ch.id WHERE p.id=? AND ch.archived=0',(pid,)).fetchone()
    return ({**dict(r),'data':dec(r['content'])} if r else None)

def plans_for_child(cid):
    with conn() as c: rows=c.execute('SELECT id,child_id,support_id,provider,model,author_id,created_at,status,content FROM plans WHERE child_id=? ORDER BY id DESC',(cid,)).fetchall()
    return [{**{k:v for k,v in dict(x).items() if k!='content'}, 'curriculum_label':dec(x['content']).get('curriculum_label','Minecraft')} for x in rows]

def save_plan(pid,content,note):
    with conn() as c: c.execute("UPDATE plans SET content=?,review_note=?,status='draft',approved_by=NULL,approved_at=NULL,revised_at=? WHERE id=?",
                                (enc(content),note,now(),pid))

def approve_plan(pid,uid):
    with conn() as c: c.execute("UPDATE plans SET status='approved',approved_by=?,approved_at=? WHERE id=?",(uid,now(),pid))

ACTIVITY_HEADER=['timestamp_utc','request_id','user_id','action','resource_id','status','detail']
ERROR_HEADER=['timestamp_utc','request_id','user_id','action','error_code','user_message','technical_type','trace_location','technical_summary']

def csv_append(path, header,values):
    LOG_DIR.mkdir(parents=True,exist_ok=True)
    with lock:
        new=not path.exists()
        with path.open('a',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f)
            if new:w.writerow(header)
            # CSVをExcelで開いた際、式として解釈されるセルを無効化する。
            safe=[("'"+v if v.startswith(('=','+','-','@','\t','\r','\n')) else v) if isinstance(v,str) else v for v in values]
            w.writerow(safe)

def activity(request_id,user_id,action,resource_id='',status='ok',detail=''):
    csv_append(LOG_DIR/'activity.csv',ACTIVITY_HEADER,[now(),request_id,user_id or '',action,str(resource_id),status,detail[:160]])

def error(request_id,user_id,action,code,message,exc=None):
    # ユーザー・支援計画・AIの入出力本文はログに書き込まない
    technical_type=type(exc).__name__ if exc is not None else ''
    # スタックのファイル名・関数・行番号は調査に有用で、入力内容そのものを含まない
    frames=traceback.extract_tb(exc.__traceback__) if exc is not None and exc.__traceback__ else []
    location=' > '.join(f'{f.filename.rsplit("/",1)[-1]}:{f.lineno}:{f.name}' for f in frames[-4:])
    summary= '入力本文・API応答本文はプライバシー保護のため未保存。詳細はエラーコードと位置情報から確認。' if exc is not None else ''
    csv_append(LOG_DIR/'errors.csv',ERROR_HEADER,[now(),request_id,user_id or '',action,code,message,technical_type,location,summary])

def init_records():
    with conn() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS execution_records(id INTEGER PRIMARY KEY,
            plan_id INTEGER NOT NULL, author_id INTEGER NOT NULL, observed_on TEXT NOT NULL,
            payload TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(plan_id) REFERENCES plans(id),FOREIGN KEY(author_id) REFERENCES users(id))''')

def add_record(pid,uid,observed_on,payload):
    with conn() as c:
        cur=c.execute('INSERT INTO execution_records(plan_id,author_id,observed_on,payload,created_at) VALUES(?,?,?,?,?)',
          (pid,uid,observed_on,enc(payload),now()))
        return cur.lastrowid

def plan_records(pid):
    with conn() as c: rows=c.execute('SELECT * FROM execution_records WHERE plan_id=? ORDER BY id DESC',(pid,)).fetchall()
    return [{**dict(r),'data':dec(r['payload'])} for r in rows]
