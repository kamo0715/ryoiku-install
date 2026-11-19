import os
from pathlib import Path
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent

def load_env():
    path = ROOT / '.env'
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())

load_env()
APP_SECRET = os.environ.get('APP_SECRET', '')
KEY = os.environ.get('DATA_ENCRYPTION_KEY', '')
DB_PATH = Path(os.environ.get('APP_DB_PATH', str(ROOT / 'data' / 'ryoiku.sqlite3'))).resolve()
LOG_DIR = Path(os.environ.get('APP_LOG_DIR', str(ROOT / 'data' / 'logs'))).resolve()
COOKIE_SECURE = os.environ.get('APP_COOKIE_SECURE', 'false').lower() == 'true'
OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434/v1').rstrip('/')


def check_settings():
    if len(APP_SECRET) < 32 or APP_SECRET.startswith('REPLACE'):
        raise RuntimeError('APP_SECRET に32文字以上のランダム文字列を設定してください')
    try:
        Fernet(KEY.encode())
    except Exception as exc:
        raise RuntimeError('DATA_ENCRYPTION_KEY を Fernet 形式で設定してください') from exc
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
