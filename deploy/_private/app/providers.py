"""固定・確認済みAPI転送先。管理画面から外部URLを指定できない設計でSSRFを防ぐ。
モデル名は公式の変更に対応するため自由入力（接続時に検証）。
"""
from collections import OrderedDict
from urllib.parse import urlsplit
import os

PROVIDERS = OrderedDict([
 ('demo', {'name':'デモ（外部AIには送信しない）','kind':'demo','env':'','example':'demo','docs':''}),
 ('openai', {'name':'OpenAI','kind':'chat','env':'OPENAI_API_KEY','example':'gpt-4.1-mini','docs':'https://platform.openai.com/docs/'}),
 ('anthropic', {'name':'Anthropic Claude','kind':'anthropic','env':'ANTHROPIC_API_KEY','example':'claude-sonnet-5-5','docs':'https://platform.claude.com/docs/'}),
 ('gemini', {'name':'Google Gemini','kind':'gemini','env':'GEMINI_API_KEY','example':'gemini-3.5-flash','docs':'https://ai.google.dev/gemini-api/docs'}),
 ('groq', {'name':'Groq','kind':'chat','env':'GROQ_API_KEY','example':'openai/gpt-oss-20b','docs':'https://console.groq.com/docs/'}),
 ('mistral', {'name':'Mistral AI','kind':'chat','env':'MISTRAL_API_KEY','example':'mistral-small-latest','docs':'https://docs.mistral.ai/'}),
 ('openrouter', {'name':'OpenRouter（複数社モデル）','kind':'chat','env':'OPENROUTER_API_KEY','example':'モデルIDを公式一覧から指定','docs':'https://openrouter.ai/models'}),
 ('deepseek', {'name':'DeepSeek','kind':'chat','env':'DEEPSEEK_API_KEY','example':'deepseek-flash','docs':'https://api-docs.deepseek.com/'}),
 ('together', {'name':'Together AI','kind':'chat','env':'TOGETHER_API_KEY','example':'モデルIDを公式一覧から指定','docs':'https://docs.together.ai/'}),
 ('fireworks', {'name':'Fireworks AI','kind':'chat','env':'FIREWORKS_API_KEY','example':'accounts/.../models/...','docs':'https://docs.fireworks.ai/'}),
 ('cerebras', {'name':'Cerebras','kind':'chat','env':'CEREBRAS_API_KEY','example':'モデルIDを公式一覧から指定','docs':'https://inference-docs.cerebras.ai/'}),
 ('xai', {'name':'xAI Grok','kind':'chat','env':'XAI_API_KEY','example':'モデルIDを公式一覧から指定','docs':'https://docs.x.ai/'}),
 ('cohere', {'name':'Cohere','kind':'cohere','env':'COHERE_API_KEY','example':'command-a-plus-05-2026','docs':'https://docs.cohere.com/'}),
 ('ollama', {'name':'Ollama（ローカルAI）','kind':'chat','env':'','example':'qwen3:8b','docs':'https://docs.ollama.com/'}),
 ('compatible', {'name':'その他 OpenAI互換API','kind':'chat','env':'COMPATIBLE_API_KEY','example':'利用先のモデルID','docs':''}),
])

# アプリ側で外部API URLをハードコードし、ドメインのすり替えを防ぐ。
ENDPOINTS = {
 'anthropic':'https://api.anthropic.com/v1/messages',
 'groq':'https://api.groq.com/openai/v1/chat/completions',
 'mistral':'https://api.mistral.ai/v1/chat/completions',
 'openrouter':'https://openrouter.ai/api/v1/chat/completions',
 'deepseek':'https://api.deepseek.com/chat/completions',
 'together':'https://api.together.xyz/v1/chat/completions',
 'fireworks':'https://api.fireworks.ai/inference/v1/chat/completions',
 'cerebras':'https://api.cerebras.ai/v1/chat/completions',
 'xai':'https://api.x.ai/v1/chat/completions',
 'cohere':'https://api.cohere.com/v2/chat',
}


def endpoint(provider,model=''):
    if provider == 'openai':
        return _safe_env_url('OPENAI_BASE_URL','https://api.openai.com/v1') + '/chat/completions'
    if provider == 'ollama':
        return _safe_env_url('OLLAMA_BASE_URL','http://127.0.0.1:11434/v1',allow_http=True) + '/chat/completions'
    if provider == 'compatible':
        return _safe_env_url('COMPATIBLE_BASE_URL','https://api.example.invalid/v1') + '/chat/completions'
    if provider == 'gemini':
        # Geminiのモデル名にパスやURLを埋め込めないようにする。
        import re
        if not re.fullmatch(r'[A-Za-z0-9_.-]{2,100}',model):
            raise ValueError('Geminiのモデル名に使用できない文字が含まれています')
        return f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
    return ENDPOINTS[provider]


def _safe_env_url(key,default,allow_http=False):
    value=os.environ.get(key,default).strip().rstrip('/')
    parsed=urlsplit(value)
    if parsed.scheme != 'https' and not (allow_http and parsed.scheme == 'http'):
        raise ValueError(f'{key} はHTTPS URLを指定してください')
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path.endswith('/chat/completions'):
        raise ValueError(f'{key} のURL形式を確認してください')
    # 追加のOpenAI互換ゲートウェイは管理者が.envでのみ構成する。
    return value
