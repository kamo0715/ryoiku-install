"""療育カリキュラム計画書案の職員用Webアプリ。外部公開には追加認証が必要。"""
import asyncio
import time
import re
import secrets
import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime
from io import BytesIO, StringIO
from zipfile import ZipFile, ZIP_DEFLATED
import csv
from collections import deque
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from settings import ROOT, APP_SECRET, COOKIE_SECURE, check_settings, LOG_DIR
from storage import (init_db,init_records,conn,now,create_user,auth,user_by_id,list_users,
  new_child,get_child,all_children,deleted_children,child_history_counts,edit_child,archive_child,restore_child,new_support,get_support,
  support_history,latest_support,add_plan,get_plan,plans_for_child,save_plan,approve_plan,
  add_record,plan_records,get_setting,set_setting,activity,error,
  change_user_role,change_user_status,reset_user_password,user_exists,
  consume_password_reset_code, set_ai_credential, delete_ai_credential, ai_credential_status)
from ai import generate,GenerationError,validate,DOMAINS,BASIC,attach_completion_metadata,ACTIVITY_MODES,OTHER_KINDS,curriculum_context
from providers import PROVIDERS
from privacy import build_minimal_payload, check_minimal_payload
from catalog import CATEGORY_GROUPS, CATEGORY_FOCUS, CATEGORY_SAFETY
from exporters import make_pdf,make_docx,make_xlsx,OFFICIAL,VERIFY
from text_import import TextImportError, parse_support_text
from day_flow import FlowError, make_flow_pdf, make_flow_docx, make_flow_xlsx
from day_flow_multi import parse_multi_input, MAX_PLANS
from child_day_flow import make_child_flow_pdf, make_child_flow_docx, make_child_flow_xlsx
from pdf_text_only import extract_support_pdf, MAX_PDF_BYTES

app=FastAPI(title='療育カリキュラム計画システム',docs_url=None,redoc_url=None,openapi_url=None)
app.add_middleware(SessionMiddleware,secret_key=APP_SECRET,https_only=COOKIE_SECURE,
                  same_site='lax',max_age=60*60*8,session_cookie='ryoiku_session')
app.mount('/static', StaticFiles(directory=str(ROOT/'static')), name='static')
templates=Jinja2Templates(directory=str(ROOT/'templates'))

def safe_route(request):
    route=request.scope.get('route')
    return getattr(route,'path','unmatched_request')

@app.on_event('startup')
def startup():
    check_settings()
    init_db();init_records()
    activity('startup','','service_start',status='success')

# Strict CSP is possible because scripts and styles are served as local files.
CSP = "; ".join([
    "default-src 'self'", "script-src 'self'", "style-src 'self'",
    "img-src 'self' data:", "font-src 'self'", "connect-src 'self'",
    "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'",
    "form-action 'self'", "manifest-src 'self'",
    "require-trusted-types-for 'script'",
])

def security_headers(request: Request, response):
    response.headers['Content-Security-Policy'] = CSP
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=(), payment=()'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    if COOKIE_SECURE and request.url.scheme == 'https':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    if request.url.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=3600'
    else:
        response.headers['Cache-Control'] = 'no-store, private'
    return response

@app.middleware('http')
async def audit(request:Request,call_next):
    request.state.request_id=uuid.uuid4().hex[:12]
    try:
        # Extra browser-origin defense; CSRF tokens remain mandatory for all POSTs.
        if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('sec-fetch-site') == 'cross-site':
            error(request.state.request_id, '', safe_route(request), 'FETCH_METADATA',
                  '別のサイトからの操作は許可されていません。画面に戻ってやり直してください。')
            activity(request.state.request_id, '', 'blocked_cross_site_request', status='failed')
            return security_headers(request, PlainTextResponse(
                '別のサイトからの操作は許可されていません。画面に戻ってやり直してください。',status_code=403))
        response=await call_next(request)
        try: uid=request.scope.get('session',{}).get('uid','')
        except Exception:uid=''
        if not request.url.path.startswith('/static'):
            activity(request.state.request_id,uid,f'{request.method} {safe_route(request)}',
                     status='ok' if response.status_code<400 else 'failed',detail=str(response.status_code))
        return security_headers(request,response)
    except Exception as exc:
        try: uid=request.scope.get('session',{}).get('uid','')
        except Exception:uid=''
        error(request.state.request_id,uid,safe_route(request),'SERVER',
              '処理中に問題が発生しました。管理者に表示された受付番号をお伝えください。',exc)
        activity(request.state.request_id,uid,safe_route(request),status='error',detail='500')
        return security_headers(request,templates.TemplateResponse(request,'message.html',{'message':
           'サーバーで処理を完了できませんでした。管理者へ受付番号をお伝えください。',
           'request_id':request.state.request_id},status_code=500))

@app.exception_handler(HTTPException)
async def http_error(request:Request,exc:HTTPException):
    if exc.status_code==401: return RedirectResponse('/login',status_code=303)
    msg={403:'この操作を行う権限がありません。',404:'指定されたデータが見つかりません。',
         400:'入力内容を確認してください。',413:'入力データが大きすぎます。'}.get(exc.status_code,'操作を完了できませんでした。')
    error(request.state.request_id,request.session.get('uid',''),safe_route(request),
          f'HTTP_{exc.status_code}',msg,exc)
    return templates.TemplateResponse(request,'message.html',{'message':msg,'request_id':request.state.request_id},status_code=exc.status_code)

@app.exception_handler(RequestValidationError)
async def validation_error(request:Request,exc:RequestValidationError):
    msg='入力が不足しているか、書式に誤りがあります。必須項目を確認してください。'
    error(request.state.request_id,request.session.get('uid',''),safe_route(request),'FORM',msg,exc)
    return templates.TemplateResponse(request,'message.html',{'message':msg,'request_id':request.state.request_id},status_code=422)


def csrf(request:Request):
    if not request.session.get('csrf'):
        request.session['csrf']=secrets.token_urlsafe(32)
    return request.session['csrf']

async def checked_form(request:Request):
    form=await request.form()
    if not secrets.compare_digest(str(form.get('_csrf','')),str(csrf(request))):
        raise HTTPException(403)
    return form

def actor(request:Request,roles=None):
    uid=request.session.get('uid')
    user=user_by_id(uid) if uid else None
    if not user or request.session.get('sv')!=user['session_version']:raise HTTPException(401)
    if roles and user['role'] not in roles:raise HTTPException(403)
    return user

def view(request:Request,page:str,**ctx):
    user=user_by_id(request.session.get('uid')) if request.session.get('uid') else None
    if user and request.session.get('sv')!=user['session_version']: user=None
    data=dict(request=request, user=user, csrf=csrf(request), domains=DOMAINS,
              source_url=OFFICIAL, source_date=VERIFY,provider=get_setting('provider','demo'),
              model=get_setting('model','demo'),activity_modes=ACTIVITY_MODES,other_kinds=OTHER_KINDS,category_groups=CATEGORY_GROUPS,category_focus=CATEGORY_FOCUS,category_safety=CATEGORY_SAFETY,**ctx)
    return templates.TemplateResponse(request,page,data)

def go(path):return RedirectResponse(path,status_code=303)

def form_values(form,names,limit=8000):
    d={}
    for key in names:
        val=str(form.get(key,'')).strip()
        if len(val)>limit: raise HTTPException(413)
        d[key]=val
    return d

CHILD_FIELDS=['name','age_band','grade','interests','strengths','needs','sensory_notes','participation_notes']
SUPPORT_FIELDS=['period_start','period_end','child_intentions','family_intentions','assessment',
 'long_goal','short_goal','support_policy','domain_health','domain_motor','domain_cognition',
 'domain_language','domain_social','accommodation','family_support','transition_support',
 'community_support','other_notes','original_text']

@app.get('/login',response_class=HTMLResponse)
async def login_page(request:Request):
    if request.session.get('uid'):
        u=user_by_id(request.session['uid'])
        if u and request.session.get('sv')==u['session_version']:return go('/')
    return view(request,'login.html',success=('パスワードが変更されました。新しいパスワードでログインしてください。' if request.query_params.get('password_changed')=='1' else ''))

LOGIN_ATTEMPTS={}
@app.post('/login')
async def login(request:Request):
    form=await checked_form(request)
    username=str(form.get('username','')).strip()[:80]
    password=str(form.get('password',''))
    # 簡易レート制限。複数ワーカー/複数サーバーではリバースプロキシ側で制限が必要。
    ip=request.client.host if request.client else ''
    current=datetime.utcnow().timestamp()
    prior=[t for t in LOGIN_ATTEMPTS.get(ip,[]) if current-t<600]
    if len(prior)>=10:
        return view(request,'login.html',message='ログイン試行が多すぎます。10分後に再度お試しください。')
    user=auth(username,password)
    if not user:
        prior.append(current);LOGIN_ATTEMPTS[ip]=prior
        error(request.state.request_id,'','login','LOGIN_FAIL','ユーザー名またはパスワードが一致しません。')
        return view(request,'login.html',message='ユーザー名またはパスワードを確認してください。')
    LOGIN_ATTEMPTS.pop(ip,None)
    request.session.clear();request.session['uid']=user['id'];request.session['sv']=user['session_version'];csrf(request)
    activity(request.state.request_id,user['id'],'login',status='success')
    return go('/')

@app.post('/logout')
async def logout(request:Request):
    user=actor(request);await checked_form(request)
    activity(request.state.request_id,user['id'],'logout',status='success')
    request.session.clear();return go('/login')

# Log-in required for self-service change; an unauthenticated reset needs a
# server-generated one-time code (never a public "reset admin" button).
@app.get('/account/password')
async def account_password_page(request:Request):
    actor(request)
    return view(request,'account_password.html')

@app.post('/account/password')
async def account_password_post(request:Request):
    user=actor(request)
    f=await checked_form(request)
    old=str(f.get('current_password',''))
    new=str(f.get('new_password',''))
    confirm=str(f.get('confirm_password',''))
    if new!=confirm:
        return view(request,'account_password.html',message='新しいパスワードと確認用の入力が一致しません。')
    if not (12<=len(new)<=256):
        return view(request,'account_password.html',message='新しいパスワードは12～256文字にしてください。')
    if not auth(user['username'],old):
        activity(request.state.request_id,user['id'],'change_own_password',status='failed')
        return view(request,'account_password.html',message='現在のパスワードが一致しません。')
    if old==new:
        return view(request,'account_password.html',message='現在とは異なるパスワードを指定してください。')
    reset_user_password(user['id'],new)
    activity(request.state.request_id,user['id'],'change_own_password',status='success')
    request.session.clear()
    return go('/login?password_changed=1')

@app.get('/password/recover')
async def password_recover_page(request:Request):
    return view(request,'password_recover.html')

RECOVERY_ATTEMPTS={}
@app.post('/password/recover')
async def password_recover_post(request:Request):
    f=await checked_form(request)
    ip=request.client.host if request.client else ''
    current=datetime.utcnow().timestamp()
    recent=[t for t in RECOVERY_ATTEMPTS.get(ip,[]) if current-t<600]
    if len(recent)>=10:
        activity(request.state.request_id,'','password_recovery',status='rate_limited')
        return view(request,'password_recover.html',message='試行回数が多すぎます。10分後に再度お試しください。')
    recent.append(current);RECOVERY_ATTEMPTS[ip]=recent
    # Keep the in-memory limiter bounded in normal single-worker operation.
    if len(RECOVERY_ATTEMPTS)>3000:
        for key in list(RECOVERY_ATTEMPTS)[:1500]:
            if not any(current-t<600 for t in RECOVERY_ATTEMPTS[key]):
                RECOVERY_ATTEMPTS.pop(key,None)
    username=str(f.get('username','')).strip()
    code=str(f.get('reset_code','')).strip()
    pw=str(f.get('new_password',''))
    confirm=str(f.get('confirm_password',''))
    if pw!=confirm or not (12<=len(pw)<=256):
        return view(request,'password_recover.html',message='新しいパスワードは12～256文字で、確認用と一致させてください。')
    success=consume_password_reset_code(username,code,pw)
    activity(request.state.request_id,'','password_recovery',status='success' if success else 'failed')
    if not success:
        return view(request,'password_recover.html',message='ユーザー名と復旧コードを確認してください。期限切れや使用済みの場合は、新しいコードが必要です。')
    request.session.clear()
    return go('/login?password_changed=1')

@app.get('/')
async def home(request:Request):
    actor(request)
    children=all_children()
    return view(request,'home.html',children=children,total=len(children))

@app.get('/children/deleted')
async def children_deleted(request:Request):
    actor(request,('admin',))
    return view(request,'deleted_children.html',children=deleted_children())

@app.get('/children/new')
async def child_new(request:Request):
    actor(request)
    return view(request,'child_form.html',child=None,title='利用者の新規登録')

@app.post('/children/new')
async def child_add(request:Request):
    user=actor(request);f=await checked_form(request)
    data=form_values(f,CHILD_FIELDS)
    code=str(f.get('code','')).strip()
    if not data['name'] or len(data['name'])>100 or not re.fullmatch(r'[A-Za-z0-9_\-]{2,30}',code):
        return view(request,'child_form.html',child={'code':code,'data':data},title='利用者の新規登録',message='名前と利用者管理番号（英数字2～30文字）を確認してください。')
    try:cid=new_child(code,data,user['id'])
    except sqlite3.IntegrityError:
        return view(request,'child_form.html',child={'code':code,'data':data},title='利用者の新規登録',message='その利用者管理番号は既に登録されています。')
    activity(request.state.request_id,user['id'],'create_child',cid)
    return go(f'/children/{cid}')

@app.get('/children/{cid}')
async def child_page(request:Request,cid:int):
    actor(request)
    child=get_child(cid)
    if not child:raise HTTPException(404)
    supports=support_history(cid)
    return view(request,'child.html',child=child,supports=supports,plans=plans_for_child(cid))

@app.get('/children/{cid}/edit')
async def child_edit_page(request:Request,cid:int):
    actor(request);child=get_child(cid)
    if not child:raise HTTPException(404)
    return view(request,'child_form.html',child=child,title='利用者情報を編集')

@app.post('/children/{cid}/edit')
async def child_update(request:Request,cid:int):
    user=actor(request);child=get_child(cid)
    if not child:raise HTTPException(404)
    f=await checked_form(request);data=form_values(f,CHILD_FIELDS)
    if not data['name']: raise HTTPException(400)
    edit_child(cid,data)
    activity(request.state.request_id,user['id'],'edit_child',cid)
    return go(f'/children/{cid}')

@app.get('/children/{cid}/delete')
async def child_delete_page(request:Request,cid:int):
    actor(request,('admin',))
    child=get_child(cid)
    if not child:raise HTTPException(404)
    return view(request,'child_delete.html',child=child,counts=child_history_counts(cid))

@app.post('/children/{cid}/delete')
@app.post('/children/{cid}/archive')  # older bookmark compatibility; same checks required
async def child_delete(request:Request,cid:int):
    user=actor(request,('admin',))
    form=await checked_form(request)
    child=get_child(cid)
    if not child:raise HTTPException(404)
    confirmed_code=str(form.get('confirm_code','')).strip()
    if not secrets.compare_digest(confirmed_code,child['code']):
        activity(request.state.request_id,user['id'],'delete_child_rejected',cid,status='failed')
        return view(request,'child_delete.html',child=child,counts=child_history_counts(cid),
                    message='利用者管理番号が一致しません。削除は実行していません。')
    if archive_child(cid)!=1:raise HTTPException(404)
    activity(request.state.request_id,user['id'],'soft_delete_child',cid,status='success')
    return go('/children/deleted')

@app.post('/children/{cid}/restore')
async def child_restore(request:Request,cid:int):
    user=actor(request,('admin',))
    form=await checked_form(request)
    child=get_child(cid,include_archived=True)
    if not child or not child['archived']:raise HTTPException(404)
    confirmed_code=str(form.get('confirm_code','')).strip()
    if not secrets.compare_digest(confirmed_code,child['code']):
        activity(request.state.request_id,user['id'],'restore_child_rejected',cid,status='failed')
        return view(request,'deleted_children.html',children=deleted_children(),
                    message='利用者管理番号が一致しません。復元は実行していません。')
    if restore_child(cid)!=1:raise HTTPException(404)
    activity(request.state.request_id,user['id'],'restore_child',cid,status='success')
    return go(f'/children/{cid}')

@app.get('/children/{cid}/support/new')
async def support_page(request:Request,cid:int):
    actor(request);child=get_child(cid)
    if not child:raise HTTPException(404)
    prior=latest_support(cid)
    return view(request,'support_form.html',child=child,previous=prior,
               form_data=prior['data'] if prior else {},support_fields=SUPPORT_FIELDS)

@app.post('/children/{cid}/support/pdf')
async def support_pdf_text_import(request:Request,cid:int):
    """Selectable PDF text -> unconfirmed preview. No OCR, no file persisted."""
    user=actor(request)
    child=get_child(cid)
    if not child:raise HTTPException(404)
    form=await checked_form(request)
    previous=latest_support(cid)
    uploaded=form.get('pdf_file')
    if not hasattr(uploaded,'read') or not getattr(uploaded,'filename',''):
        return view(request,'support_form.html',child=child,previous=previous,form_data={},
                    ocr_message='文字情報があるPDFを選択してください。')
    blob=await uploaded.read(MAX_PDF_BYTES+1)
    await uploaded.close()
    try:
        text,scanned,warnings=await asyncio.to_thread(extract_support_pdf,blob)
        data,count,parse_warnings,names=parse_support_text(text)
        warnings.extend(parse_warnings)
        actual_name=re.sub(r'[\s　]+','',child['data'].get('name',''))
        possible=[x for x in names if x and re.sub(r'[\s　]+','',x)!=actual_name]
        if possible:
            warnings.insert(0,'PDFの氏名と選択した利用者が一致しない可能性があります。原本を確認してください。')
        token=secrets.token_urlsafe(20)
        request.session['ocr_preview']={'token':token,'cid':cid,'expires':int(time.time())+1800}
        activity(request.state.request_id,user['id'],'support_pdf_text_preview',cid,
                 detail=f'fields={count},name_warning={bool(possible)}')
        return view(request,'support_form.html',child=child,previous=previous,form_data=data,
                    ocr_preview=True,ocr_kind='文字PDF',ocr_token=token,ocr_count=count,ocr_warnings=warnings)
    except TextImportError as exc:
        activity(request.state.request_id,user['id'],'support_pdf_text_preview',cid,status='failed',detail=exc.code)
        return view(request,'support_form.html',child=child,previous=previous,form_data={},ocr_message=exc.message)

@app.post('/children/{cid}/support/analyze')
async def support_text_analyze(request:Request,cid:int):
    """Analyze pasted/OCR-copied plain text; suggestions only, never save here."""
    user=actor(request)
    child=get_child(cid)
    if not child:raise HTTPException(404)
    form=await checked_form(request)
    original=str(form.get('source_text',''))
    previous=latest_support(cid)
    if len(original)>18000:
        return view(request,'support_form.html',child=child,previous=previous,form_data={},
                    ocr_message='原文は18,000文字以下にしてください。')
    try:
        data,count,warnings,names=parse_support_text(original)
        actual_name=re.sub(r'[\s　]+','',child['data'].get('name',''))
        possible=[x for x in names if x and re.sub(r'[\s　]+','',x)!=actual_name]
        if possible:
            warnings.insert(0,'原文の氏名と選択した利用者が一致しない可能性があります。登録先を確認してください。')
        token=secrets.token_urlsafe(20)
        request.session['ocr_preview']={'token':token,'cid':cid,'expires':int(time.time())+1800}
        activity(request.state.request_id,user['id'],'support_text_analyze_preview',cid,
                 detail=f'fields={count},name_warning={bool(possible)}')
        return view(request,'support_form.html',child=child,previous=previous,form_data=data,
                    ocr_preview=True,ocr_kind='原文',ocr_token=token,ocr_count=count,ocr_warnings=warnings)
    except TextImportError as exc:
        activity(request.state.request_id,user['id'],'support_text_analyze_preview',cid,
                 status='failed',detail=exc.code)
        return view(request,'support_form.html',child=child,previous=previous,form_data={},
                    ocr_message=exc.message)

@app.post('/children/{cid}/support/new')
async def support_add(request:Request,cid:int):
    user=actor(request);child=get_child(cid)
    if not child:raise HTTPException(404)
    f=await checked_form(request)
    preview_token=str(f.get('ocr_preview_token',''))
    if preview_token:
        pending=request.session.get('ocr_preview') or {}
        if (pending.get('cid')!=cid or pending.get('token')!=preview_token
                or pending.get('expires',0)<int(time.time())
                or str(f.get('ocr_verified',''))!='yes'
                or any(str(f.get(k,''))!='yes' for k in
                       ('review_child_intentions','review_family_intentions','review_assessment'))):
            return view(request,'support_form.html',child=child,form_data={},previous=latest_support(cid),
                        ocr_message='読み取り結果を保存できません。本人・保護者・アセスメントの各確認欄をチェックして原文を照合し、もう一度解析してください。')
    data=form_values(f,SUPPORT_FIELDS,20000)
    if not any(data.get(k) for k in SUPPORT_FIELDS if k not in ('period_start','period_end')):
        return view(request,'support_form.html',child=child,form_data=data,previous=None,
                    support_fields=SUPPORT_FIELDS,message='すべて未入力の場合は保存せず、利用者画面から活動案を生成できます。部分入力の場合は任意の1項目を入力してください。')
    sid,v=new_support(cid,data,user['id'])
    if preview_token: request.session.pop('ocr_preview',None)
    activity(request.state.request_id,user['id'],'new_support_version',sid,detail=f'version={v}')
    return go(f'/children/{cid}')

@app.get('/children/{cid}/support/{sid}')
async def support_show(request:Request,cid:int,sid:int):
    actor(request);child=get_child(cid);sup=get_support(sid)
    if not child or not sup or sup['child_id']!=cid:raise HTTPException(404)
    return view(request,'support_show.html',child=child,sup=sup)

@app.get('/children/{cid}/generate')
async def generate_page(request:Request,cid:int):
    actor(request);child=get_child(cid);sup=latest_support(cid)
    if not child:raise HTTPException(404)
    return view(request,'generate.html',child=child,sup=sup)

@app.post('/children/{cid}/generate')
async def generate_post(request:Request,cid:int):
    user=actor(request);child=get_child(cid)
    if not child:raise HTTPException(404)
    sup=latest_support(cid)
    f=await checked_form(request)
    if str(f.get('consent',''))!='yes':
        return view(request,'generate.html',child=child,sup=sup,
                    message='入力情報をAIに使用することについて、事業所内の承認を確認してください。')
    data=form_values(f,['theme','group_size','edition','preferences','activity_place','available_materials','custom_activity'],2000)
    mode=str(f.get('activity_mode','minecraft')).strip()
    kind=str(f.get('kind_code','other')).strip()
    if mode not in ACTIVITY_MODES:
        return view(request,'generate.html',child=child,sup=sup,message='活動の種類を選び直してください。')
    if mode=='other' and kind not in OTHER_KINDS:
        return view(request,'generate.html',child=child,sup=sup,message='Minecraft以外の活動ジャンルを選び直してください。')
    if mode=='other' and kind=='other' and not data['custom_activity']:
        return view(request,'generate.html',child=child,sup=sup,message='「その他」を選んだ場合は活動ジャンル名を入力してください。')
    data.update({'activity_mode':mode,'kind_code':kind})
    data.update(curriculum_context(data))
    data['completion']='propose'  # 不足データがあっても活動案を提案する
    try:duration=int(f.get('duration','45'))
    except ValueError:duration=0
    if not (15<=duration<=180):
        return view(request,'generate.html',child=child,sup=sup,message='活動時間は15～180分で指定してください。')
    opts={**data,'duration':duration}
    provider=get_setting('provider','demo');model=get_setting('model','demo')
    # Preview/confirm applies to ALL external providers, including compatible gateways.
    # Session stores only a hash and nonce, never the raw/sanitized personal data.
    if provider!='demo':
        support_data=sup['data'] if sup else {}
        try:
            anonymous=build_minimal_payload(child['data'],support_data,opts)
            outgoing=check_minimal_payload(anonymous)
        except (ValueError,TypeError,KeyError):
            return view(request,'generate.html',child=child,sup=sup,
                message='個人名・学校名を含まない安全な送信内容を作れないため、AI送信を中止しました。')
        digest=hashlib.sha256(json.dumps({
            'child_id':cid,'support_id':sup['id'] if sup else None,
            'provider':provider,'model':model,'options':opts,
            'anonymized':anonymous,
        },ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
        approved=(str(f.get('privacy_approved',''))=='yes' and str(f.get('privacy_review_check',''))=='yes')
        saved=request.session.get('ai_privacy_review') or {}
        valid=(approved and saved.get('child_id')==cid and saved.get('digest')==digest
            and saved.get('nonce') and secrets.compare_digest(str(f.get('privacy_nonce','')),saved['nonce'])
            and int(saved.get('expires',0))>=int(time.time()))
        if not valid:
            nonce=secrets.token_urlsafe(24)
            request.session['ai_privacy_review']={'child_id':cid,'digest':digest,
                'nonce':nonce,'expires':int(time.time())+600}
            return view(request,'ai_privacy_preview.html',child=child,sup=sup,
                outgoing=json.dumps(anonymous,ensure_ascii=False,indent=2),
                opts=opts,nonce=nonce,
                message='児童A・学校Aの仮表示と、2択・指差し・タイマーなどの具体的な支援方法を確認してください。元の氏名・学校名・自由記述・病歴・家庭事情は送信しません。')
        # One-use approval, even if the provider fails.
        request.session.pop('ai_privacy_review',None)
    try:
        generated=await generate(provider,model,child['data'],sup['data'] if sup else {},opts)
        generated=validate(generated)
        if sum(step['minutes'] for step in generated['steps'])!=duration:
            raise GenerationError('AI_DURATION','活動手順の時間の合計が設定した活動時間と一致しません。再生成してください。')
        if mode=='other' and re.search(r'minecraft|マインクラフト',generated['title'],flags=re.I):
            raise GenerationError('AI_CATEGORY','指定した「Minecraft以外」のジャンルと活動内容が一致しません。再生成してください。')
    except GenerationError as exc:
        error(request.state.request_id,user['id'],'ai_generate',exc.code,exc.display,exc)
        activity(request.state.request_id,user['id'],'ai_generate',cid,status='failed',detail=exc.code)
        return view(request,'generate.html',child=child,sup=sup,message=exc.display)
    # 既存の正式目標に一致しないAIの言い換えは「原文ではない」と明示する。
    support_data=sup['data'] if sup else {}
    source_text='\n'.join(str(v or '') for v in support_data.values())
    unknown_goals=[]
    for g in generated['goal_links']:
        stated=str(g.get('source_goal','')).strip()
        if sup and stated and stated not in source_text and stated != '支援目標が未入力':
            unknown_goals.append(stated[:90])
            g['source_goal']='【原文との一致未確認・AI案】'+stated
    if sup:
        for goal_key,label in [('short_goal','短期目標'),('long_goal','長期目標')]:
            literal=support_data.get(goal_key,'').strip()
            if literal and not any(literal in x.get('source_goal','') for x in generated['goal_links']):
                generated['goal_links'].append({'source_goal':f'【{label}・原文】{literal}',
                    'program_link':'AIが具体的な対応を示していないため、職員が関連を記入してください。',
                    'check':'実施前に個別支援計画と照合し、整合性を確認してください。'})
    if unknown_goals:
        generated['note']+='\n注意：一部のAIが示した目標表現は個別支援計画の原文に一致しません。元の資料と照合してください。'
    generated=attach_completion_metadata(generated,child['data'],support_data,opts,has_support=bool(sup))
    generated['activity_place']=data['activity_place']
    generated['available_materials']=data['available_materials']
    pid=add_plan(cid,sup['id'] if sup else None,generated,provider,model,user['id'])
    activity(request.state.request_id,user['id'],'ai_generate',pid,status='success',
             detail=f'provider={provider},category={mode}/{kind},support={sup["id"] if sup else "none"},missing={len(generated["missing_inputs"])}')
    return go(f'/plans/{pid}')

@app.get('/plans/{pid}')
async def plan_page(request:Request,pid:int):
    actor(request);plan=get_plan(pid)
    if not plan:raise HTTPException(404)
    return view(request,'plan.html',plan=plan,child=get_child(plan['child_id']),
                sup=get_support(plan['support_id']),records=plan_records(pid))

LIST_KEYS=['objectives','materials','accommodations','child_choices','safety','observations','basic_activities']
STR_KEYS=['title','overview','family_support','transition_support','community_support','note']

@app.get('/plans/{pid}/edit')
async def plan_edit_page(request:Request,pid:int):
    actor(request);p=get_plan(pid)
    if not p:raise HTTPException(404)
    return view(request,'plan_edit.html',plan=p,child=get_child(p['child_id']),
                list_keys=LIST_KEYS,str_keys=STR_KEYS)

@app.post('/plans/{pid}/edit')
async def plan_edit_post(request:Request,pid:int):
    user=actor(request);p=get_plan(pid)
    if not p:raise HTTPException(404)
    f=await checked_form(request);data=p['data'].copy()
    for k in STR_KEYS:data[k]=str(f.get(k,'')).strip()[:8000]
    for k in LIST_KEYS:data[k]=[s.strip() for s in str(f.get(k,'')).splitlines() if s.strip()][:100]
    for i,x in enumerate(data['steps']):
        for key in ['phase','child_action','staff_support','evaluation']:
            x[key]=str(f.get(f'step_{i}_{key}',x.get(key,''))).strip()[:6000]
        try:x['minutes']=int(f.get(f'step_{i}_minutes',x.get('minutes',0)))
        except (ValueError,TypeError):raise HTTPException(400)
    for i,x in enumerate(data['domains']):
        for key in ['weight','reason','activity','assessment']:
            x[key]=str(f.get(f'domain_{i}_{key}',x.get(key,''))).strip()[:6000]
    for i,x in enumerate(data['goal_links']):
        for key in ['source_goal','program_link','check']:
            x[key]=str(f.get(f'goal_{i}_{key}',x.get(key,''))).strip()[:6000]
    try:validate(data)
    except GenerationError as exc:
        return view(request,'plan_edit.html',plan=p,child=get_child(p['child_id']),
                list_keys=LIST_KEYS,str_keys=STR_KEYS,message=exc.display)
    note=str(f.get('review_note','')).strip()[:5000]
    save_plan(pid,data,note)
    activity(request.state.request_id,user['id'],'revise_plan',pid)
    return go(f'/plans/{pid}')

@app.post('/plans/{pid}/approve')
async def plan_approve(request:Request,pid:int):
    user=actor(request,('admin','reviewer'));f=await checked_form(request)
    p=get_plan(pid)
    if not p:raise HTTPException(404)
    sup=get_support(p['support_id']) if p['support_id'] else None
    if not sup:
        return view(request,'message.html',message='個別支援計画が未登録のため、確認済みにできません。計画を登録し、活動案を再生成してください。')
    if p['provider']=='demo':
        return view(request,'message.html',message='デモモードで作った案は確認済みにできません。AI接続後に生成した案を確認してください。')
    if not (sup['data'].get('short_goal','').strip() or sup['data'].get('long_goal','').strip()):
        return view(request,'message.html',message='個別支援計画の目標が未入力のため、確認済みにできません。正式な目標を確認してから再生成してください。')
    if p['data'].get('missing_inputs') and f.get('review_missing')!='yes':
        return view(request,'message.html',message='未入力項目の確認チェックが必要です。内容を確認し、計画画面でチェックしてから再実行してください。')
    approve_plan(pid,user['id'])
    activity(request.state.request_id,user['id'],'approve_plan',pid)
    return go(f'/plans/{pid}')

@app.post('/plans/{pid}/records')
async def add_execution(request:Request,pid:int):
    user=actor(request);p=get_plan(pid)
    if not p:raise HTTPException(404)
    f=await checked_form(request)
    data=form_values(f,['participation','observed','assessment','next_action'],6000)
    on=str(f.get('observed_on','')).strip()
    try:date.fromisoformat(on)
    except ValueError:raise HTTPException(400)
    rid=add_record(pid,user['id'],on,data)
    activity(request.state.request_id,user['id'],'add_execution_record',rid)
    return go(f'/plans/{pid}')

@app.get('/plans/{pid}/day-flow')
async def day_flow_page(request:Request,pid:int):
    actor(request);p=get_plan(pid)
    if not p:raise HTTPException(404)
    candidate_ids=[pid]+[x['id'] for x in plans_for_child(p['child_id']) if x['id']!=pid]
    candidates=[get_plan(x) for x in candidate_ids[:40]]
    candidates=[x for x in candidates if x is not None and x['child_id']==p['child_id']]
    return view(request,'day_flow.html',plan=p,child=get_child(p['child_id']),
                candidate_plans=candidates,max_day_plans=MAX_PLANS,more_plans=len(candidate_ids)>40,
                steps_minutes=sum(int(s.get('minutes',0)) for s in p['data'].get('steps',[])))

@app.post('/plans/{pid}/day-flow/export/{fmt}')
async def day_flow_export(request:Request,pid:int,fmt:str):
    user=actor(request);p=get_plan(pid)
    if not p:raise HTTPException(404)
    if fmt not in ('pdf','docx','xlsx'):raise HTTPException(404)
    f=await checked_form(request)
    # Only explicitly selected plans belonging to the same active child can be combined.
    selected_ids=set()
    for key in f.keys():
        m=re.fullmatch(r'include_(\d+)',str(key))
        if m:selected_ids.add(int(m.group(1)))
    if len(selected_ids)>MAX_PLANS:
        return view(request,'message.html',message=f'カリキュラムは最大{MAX_PLANS}件まで選択できます。')
    selected=[]
    for other_id in selected_ids:
        item=get_plan(other_id)
        if not item or item['child_id']!=p['child_id']:
            raise HTTPException(403)
        selected.append(item)
    try:flow=parse_multi_input(selected,f,pid)
    except FlowError as exc:
        return view(request,'message.html',message=str(exc))
    c=get_child(p['child_id']);s=get_support(p['support_id']) if p['support_id'] else None
    full_plan=dict(p);full_plan['_support']=s;full_plan['_day_plans']=sorted(selected,
                      key=lambda x:next((i for i,t in enumerate(flow['selected_plans']) if t['id']==x['id']),99))
    try:
        if flow['audience']=='child':
            output={'pdf':make_child_flow_pdf,'docx':make_child_flow_docx,'xlsx':make_child_flow_xlsx}[fmt](full_plan,c,flow)
        else:
            output={'pdf':make_flow_pdf,'docx':make_flow_docx,'xlsx':make_flow_xlsx}[fmt](full_plan,c,flow)
    except FlowError as exc:
        return view(request,'message.html',message=str(exc))
    except Exception as exc:
        error(request.state.request_id,user['id'],'day_flow_export','EXPORT',
              '1日の支援の流れの生成に失敗しました。',exc)
        return view(request,'message.html',message='帳票生成に失敗しました。受付番号を管理者へ伝えてください。',
                    request_id=request.state.request_id)
    activity(request.state.request_id,user['id'],'export_day_flow',pid,
             detail='format='+fmt+';audience='+flow['audience']+';plans='+str(len(selected)))
    media={'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
           'xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}[fmt]
    return StreamingResponse(output,media_type=media,
       headers={'Content-Disposition':f'attachment; filename="daily_support_flow_{pid}_{flow["audience"]}.{fmt}"',
                'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

@app.get('/plans/{pid}/export/{fmt}')
async def plan_export(request:Request,pid:int,fmt:str):
    user=actor(request)
    p=get_plan(pid)
    if not p:raise HTTPException(404)
    if fmt not in ('pdf','docx','xlsx'):raise HTTPException(404)
    c=get_child(p['child_id']);s=get_support(p['support_id'])
    try:
        data={'pdf':make_pdf,'docx':make_docx,'xlsx':make_xlsx}[fmt](p,c,s)
    except Exception as exc:
        error(request.state.request_id,user['id'],'export','EXPORT',
              'ファイル作成に失敗しました。開発者に受付番号をお知らせください。',exc)
        return view(request,'message.html',message='出力に失敗しました。管理者に受付番号をお伝えください。',
                    request_id=request.state.request_id)
    activity(request.state.request_id,user['id'],'export_plan',pid,detail=fmt)
    media={'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
           'xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}[fmt]
    disposition='inline' if fmt=='pdf' and request.query_params.get('view')=='1' else 'attachment'
    return StreamingResponse(data,media_type=media,
             headers={'Content-Disposition':f'{disposition}; filename="curriculum_plan_{pid}.{fmt}"',
                      'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

@app.get('/admin/settings')
async def settings_page(request:Request):
    actor(request,('admin',))
    return view(request,'settings.html',providers=PROVIDERS,
                saved_models={p:get_setting('model_'+p,'') for p in PROVIDERS},
                key_status={p:ai_credential_status(p) for p in PROVIDERS})

@app.post('/admin/settings')
async def settings_post(request:Request):
    user=actor(request,('admin',));f=await checked_form(request)
    provider=str(f.get('provider','')).strip()
    model=str(f.get('model','')).strip()
    api_key=str(f.get('api_key','')).strip()
    clear_key=str(f.get('clear_key',''))=='yes'
    message=None
    if provider not in PROVIDERS or not re.fullmatch(r'[\w.\-:/]{2,120}',model):
        message='提供元またはモデル名が正しくありません。'
    elif provider=='gemini' and not re.fullmatch(r'[A-Za-z0-9_.-]{2,100}',model):
        message='Geminiのモデル名には英数字・ハイフン・ピリオド・アンダーバーを使用してください。'
    elif api_key and clear_key:
        message='APIキーの登録と削除は同時に行えません。'
    elif len(api_key)>4096:
        message='APIキーが長すぎます。'
    elif (api_key or clear_key) and not PROVIDERS[provider]['env']:
        message='このAI提供元にはAPIキー設定がありません。'
    if message:
        return view(request,'settings.html',providers=PROVIDERS,
                    saved_models={p:get_setting('model_'+p,'') for p in PROVIDERS},
                    key_status={p:ai_credential_status(p) for p in PROVIDERS},message=message)
    try:
        if api_key:
            set_ai_credential(provider,api_key)
        if clear_key:
            delete_ai_credential(provider)
    except ValueError as exc:
        return view(request,'settings.html',providers=PROVIDERS,
                    saved_models={p:get_setting('model_'+p,'') for p in PROVIDERS},
                    key_status={p:ai_credential_status(p) for p in PROVIDERS},message=str(exc))
    # 提供元ごとに前回のモデル名を保存する（既存グローバル設定も維持）。
    set_setting('model_'+provider,model)
    set_setting('provider',provider);set_setting('model',model)
    # ログに秘密や生成内容は記録しない。
    if api_key or clear_key:
        activity(request.state.request_id,user['id'],'ai_key_change',detail=f'provider={provider},action={"set" if api_key else "clear"}')
    activity(request.state.request_id,user['id'],'settings_model_change',detail=f'provider={provider},model={model}')
    return go('/admin/settings')

@app.get('/admin/users')
async def users_page(request:Request):
    actor(request,('admin',))
    return view(request,'users.html',users=list_users())

@app.post('/admin/users')
async def users_post(request:Request):
    user=actor(request,('admin',));f=await checked_form(request)
    username=str(f.get('username','')).strip();password=str(f.get('password',''))
    role=str(f.get('role','staff'))
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,50}',username) or not (12<=len(password)<=256) or role not in ('admin','reviewer','staff'):
        return view(request,'users.html',users=list_users(),message='ユーザー名は英数字等で3～50文字、パスワードは12～256文字にしてください。')
    try:create_user(username,password,role)
    except sqlite3.IntegrityError:
        return view(request,'users.html',users=list_users(),message='そのユーザー名は使用済みです。')
    activity(request.state.request_id,user['id'],'create_user',detail=role)
    return go('/admin/users')

@app.post('/admin/users/{target_id}/role')
async def user_role_post(request:Request,target_id:int):
    admin=actor(request,('admin',));f=await checked_form(request)
    if admin['id']==target_id:
        return view(request,'users.html',users=list_users(),message='自分自身の権限は変更できません。別の管理者が操作してください。')
    role=str(f.get('role',''))
    try:change_user_role(target_id,role)
    except ValueError as exc:return view(request,'users.html',users=list_users(),message=str(exc))
    activity(request.state.request_id,admin['id'],'change_user_role',resource_id=target_id,detail=role)
    return go('/admin/users')

@app.post('/admin/users/{target_id}/status')
async def user_status_post(request:Request,target_id:int):
    admin=actor(request,('admin',));f=await checked_form(request)
    if admin['id']==target_id:
        return view(request,'users.html',users=list_users(),message='自分自身のアカウントは停止できません。')
    active=str(f.get('active',''))
    if active not in ('0','1'):raise HTTPException(400)
    try:change_user_status(target_id,active=='1')
    except ValueError as exc:return view(request,'users.html',users=list_users(),message=str(exc))
    activity(request.state.request_id,admin['id'],'change_user_status',resource_id=target_id,detail='enabled' if active=='1' else 'disabled')
    return go('/admin/users')

@app.post('/admin/users/{target_id}/password')
async def user_password_post(request:Request,target_id:int):
    admin=actor(request,('admin',));f=await checked_form(request)
    password=str(f.get('password',''))
    try:reset_user_password(target_id,password)
    except ValueError as exc:return view(request,'users.html',users=list_users(),message=str(exc))
    activity(request.state.request_id,admin['id'],'reset_user_password',resource_id=target_id,status='success')
    if target_id==admin['id']:
        request.session.clear()
        return go('/login')
    return go('/admin/users')

LOG_FILES={'activity':'activity.csv','errors':'errors.csv'}

def filter_log_rows(kind, date_from='',date_to='',keyword='',status_filter='',limit=None):
    filename=LOG_FILES[kind]
    path=LOG_DIR/filename
    if not path.exists():return []
    if date_from and (not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date_from) or not _valid_iso(date_from)):
        raise HTTPException(400)
    if date_to and (not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date_to) or not _valid_iso(date_to)):
        raise HTTPException(400)
    if len(keyword)>100:raise HTTPException(400)
    needle=keyword.casefold()
    collection=deque(maxlen=limit) if limit else []
    with path.open('r',encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            ds=row.get('timestamp_utc','')[:10]
            if date_from and ds<date_from:continue
            if date_to and ds>date_to:continue
            if status_filter and row.get('status','')!=status_filter:continue
            if needle and not any(needle in str(v).casefold() for v in row.values()):continue
            collection.append(row)
    return list(collection)

def _valid_iso(s):
    try: date.fromisoformat(s); return True
    except ValueError: return False

def log_filters(request:Request):
    q=request.query_params
    kind=q.get('kind','activity')
    if kind not in LOG_FILES:raise HTTPException(400)
    start=q.get('from','');end=q.get('to','');keyword=q.get('q','').strip()
    status_filter=q.get('status','')
    if status_filter not in ('','ok','success','failed','error'):raise HTTPException(400)
    return kind,start,end,keyword,status_filter

@app.get('/admin/logs')
async def logs_page(request:Request):
    actor(request,('admin',))
    kind,start,end,keyword,status_filter=log_filters(request)
    rows=filter_log_rows(kind,start,end,keyword,status_filter,limit=100)[::-1]
    return view(request,'logs.html',kind=kind,rows=rows,date_from=start,date_to=end,query=keyword,status_filter=status_filter)

@app.get('/admin/logs/download')
async def logs_download(request:Request):
    user=actor(request,('admin',))
    kind,start,end,keyword,status_filter=log_filters(request)
    fields={'activity':['timestamp_utc','request_id','user_id','action','resource_id','status','detail'],
            'errors':['timestamp_utc','request_id','user_id','action','error_code','user_message','technical_type','trace_location','technical_summary']}[kind]
    rows=filter_log_rows(kind,start,end,keyword,status_filter,limit=None)
    result=StringIO();writer=csv.DictWriter(result,fieldnames=fields,extrasaction='ignore');writer.writeheader()
    for row in rows:
        writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r','\n')) else v) for k,v in row.items()})
    raw=result.getvalue().encode('utf-8-sig')
    activity(request.state.request_id,user['id'],'download_log',status='success',detail=f'{kind},records={len(rows)}')
    return StreamingResponse(BytesIO(raw),media_type='text/csv; charset=utf-8',headers={
        'Content-Disposition':f'attachment; filename="ryoiku_{kind}_filtered.csv"',
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

@app.get('/admin/logs/archive.zip')
async def logs_archive(request:Request):
    user=actor(request,('admin',))
    buf=BytesIO()
    with ZipFile(buf,'w',ZIP_DEFLATED) as z:
        for name in LOG_FILES.values():
            path=LOG_DIR/name
            if path.is_file():z.write(path,arcname=name)
    buf.seek(0)
    activity(request.state.request_id,user['id'],'download_all_logs',status='success')
    return StreamingResponse(buf,media_type='application/zip',headers={
        'Content-Disposition':'attachment; filename="ryoiku_audit_logs.zip"',
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

@app.get('/admin/logs/{name}')
async def logs_export_legacy(request:Request,name:str):
    """旧バージョンとのURL互換（個別CSV）。"""
    user=actor(request,('admin',))
    if name not in LOG_FILES.values():raise HTTPException(404)
    path=LOG_DIR/name
    if not path.exists():raise HTTPException(404)
    activity(request.state.request_id,user['id'],'download_log',status='success',detail=name)
    return StreamingResponse(BytesIO(path.read_bytes()),media_type='text/csv; charset=utf-8',headers={
        'Content-Disposition':f'attachment; filename="{name}"', 'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
