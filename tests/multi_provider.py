"""外部APIへの実通信をせず、全プロバイダのプロトコル・秘匿を検証する。"""
import asyncio, copy, json, os, re, sys, tempfile
from pathlib import Path
from cryptography.fernet import Fernet
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
tmp=tempfile.TemporaryDirectory(prefix='ryoiku_multi_')
os.environ.update({
 'APP_SECRET':'k'*64,
 'DATA_ENCRYPTION_KEY':Fernet.generate_key().decode(),
 'APP_DB_PATH':str(Path(tmp.name)/'db.sqlite3'),
 'APP_LOG_DIR':str(Path(tmp.name)/'logs'),
 'ANTHROPIC_API_KEY':'ENV_CLAUDE_SECRET_12345',
})
import ai
from providers import PROVIDERS,endpoint
from storage import (init_db,set_ai_credential,get_ai_credential,ai_credential_status,
                     delete_ai_credential,get_setting,create_user)
from fastapi.testclient import TestClient
from app import app

init_db()
assert len(PROVIDERS)>=12
set_ai_credential('anthropic','SAVED_CLAUDE_SECRET_98765')
assert get_ai_credential('anthropic')=='SAVED_CLAUDE_SECRET_98765'
assert ai_credential_status('anthropic')=='WebUIで登録済み'
with __import__('sqlite3').connect(os.environ['APP_DB_PATH']) as con:
    row=con.execute("SELECT encrypted_key FROM ai_credentials WHERE provider='anthropic'").fetchone()[0]
    assert 'SAVED_CLAUDE_SECRET' not in row

delete_ai_credential('anthropic')
assert get_ai_credential('anthropic')=='ENV_CLAUDE_SECRET_12345'
set_ai_credential('anthropic','SAVED_CLAUDE_SECRET_98765')

try: endpoint('gemini','../../../secrets')
except ValueError: pass
else: raise AssertionError('Gemini path injected')

expected=ai.demo_plan({'short_goal':'選択する'},{'duration':45})
assert len(ai.validate(expected)['domains'])==5
child={'name':'テスト児童','strengths':'テスト児童は活動を選べる'}
support={'short_goal':'テスト児童の選択を支援する'}
options={'activity_mode':'other','kind_code':'other','custom_activity':'折り紙','duration':45}
seen=[]
class Response:
    def __init__(self,body, status_code=200):self.body=body;self.status_code=status_code
    def json(self):return self.body
class Client:
    def __init__(self,**kwargs):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def post(self,url,headers,json,follow_redirects):
        assert follow_redirects is False
        assert 'テスト児童' not in str(json)
        assert headers.get('Content-Type')=='application/json'
        provider=active[0]
        assert url==endpoint(provider,models[provider]),(provider,url)
        if provider=='anthropic':
            assert headers['anthropic-version']=='2026-10-21'
            assert headers['Authorization']=='Bearer SAVED_CLAUDE_SECRET_98765'
            assert 'system' in json and json['max_tokens']>0
            body={'content':[{'type':'text','text':__import__('json').dumps(expected,ensure_ascii=False)}], 'stop_reason':'end_turn'}
        elif provider=='gemini':
            assert headers['x-goog-api-key']=='TEST_GEMINI_KEY_123'
            assert 'contents' in json and 'systemInstruction' in json
            body={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':__import__('json').dumps(expected,ensure_ascii=False)}]}}]}
        elif provider=='cohere':
            assert 'stream' in json and json['stream'] is False
            body={'message':{'content':[{'type':'text','text':__import__('json').dumps(expected,ensure_ascii=False)}]}}
        else:
            assert 'temperature' not in json
            assert isinstance(json['messages'],list)
            body={'choices':[{'message':{'content':__import__('json').dumps(expected,ensure_ascii=False)},'finish_reason':'stop'}]}
        seen.append(provider)
        return Response(body)

ai.httpx.AsyncClient=Client
active=['']
models={p:('gemini-3.5-flash' if p=='gemini' else 'model-test-123') for p in PROVIDERS if p!='demo'}
for p in PROVIDERS:
    if p in ('demo','ollama'):continue
    if p=='anthropic':continue
    os.environ[PROVIDERS[p]['env']]='TEST_'+p.upper()+'_KEY_123'
# Gemini explicit expected key
os.environ['GEMINI_API_KEY']='TEST_GEMINI_KEY_123'
async def run():
    for provider in models:
        active[0]=provider
        result=await ai.generate(provider,models[provider],child,support,options)
        assert result['title']==expected['title'],provider
asyncio.run(run())
assert set(models)==set(seen)

# UIでのキー編集は管理者だけ。秘密をGETとログへ出さない。
def csrf(response):
    match=re.search(r'name="_csrf" value="([^"]+)"',response.text)
    assert match,response.text[:150]
    return match.group(1)
with TestClient(app) as c:
    create_user('admin_mock','admin_secret_12345678','admin')
    r=c.get('/login')
    assert c.post('/login',data={'_csrf':csrf(r),'username':'admin_mock','password':'admin_secret_12345678'},follow_redirects=False).status_code==303
    r=c.get('/admin/settings');assert r.status_code==200
    assert 'Anthropic Claude' in r.text and 'Google Gemini' in r.text
    assert 'SAVED_CLAUDE_SECRET_98765' not in r.text
    data={'_csrf':csrf(r),'provider':'gemini','model':'gemini-3.5-flash','api_key':'WEB_UI_GEMINI_KEY_1234'}
    assert c.post('/admin/settings',data=data,follow_redirects=False).status_code==303
    assert get_setting('provider')=='gemini'
    assert get_setting('model')=='gemini-3.5-flash'
    assert get_ai_credential('gemini')=='WEB_UI_GEMINI_KEY_1234'
    r=c.get('/admin/settings');assert 'WEB_UI_GEMINI_KEY_1234' not in r.text
    assert 'WebUIで登録済み' in r.text
    for file in (Path(tmp.name)/'logs').glob('*.csv'):
        contents=file.read_text(encoding='utf-8')
        assert 'WEB_UI_GEMINI_KEY_1234' not in contents
    # 変更は遅延反映せず即時DBに保存。既存データに触らない。
    assert c.post('/admin/settings',data={'_csrf':csrf(r),'provider':'gemini','model':'gemini-3.5-flash','clear_key':'yes'},follow_redirects=False).status_code==303
    assert get_ai_credential('gemini')=='TEST_GEMINI_KEY_123'

print(f'PASS: {len(seen)} providers mocked, Claude/Gemini/Cohere native, key encryption, WebUI RBAC, non-leaking logs')
