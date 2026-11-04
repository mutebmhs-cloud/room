import os, json, re, secrets, time, hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Depends, Request, HTTPException, Response, Body
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, update, delete, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from .db import Base, engine, get_db, SessionLocal
from .models import User, Invite, RecoveryCode, Session as LoginSession, Project, Section, Revision, Fact, Chat, now
from .security import hash_password, digest, secure_random, pw_valid, verify, require_csrf, COOKIE_NAME, SESSION_DAYS, IS_PROD, csrf_for_session
from .ai import analyze
from .provider_gateway import configured as ai_configured
import unicodedata
from .fountain import parse as parse_fountain, FountainError

KINDS={'novel','short','flash','children','screenplay'}
BLOCK_TYPES={'heading','action','character','dialogue','parenthetical','transition','note'}
ROOT=Path(__file__).parent
@asynccontextmanager
async def lifespan(app):
    from .pilot import bootstrap_pilot
    Base.metadata.create_all(bind=engine)
    bootstrap_pilot()
    bootstrap = os.getenv("BOOTSTRAP_INVITE", "").strip()
    if os.getenv("PILOT_EPHEMERAL") == "1" and not bootstrap:
        bootstrap = secrets.token_urlsafe(36)
        print("PILOT_INVITE=" + bootstrap, flush=True)
    if bootstrap:
        if len(bootstrap) < 24:
            raise RuntimeError("BOOTSTRAP_INVITE must be at least 24 characters")
        with SessionLocal() as db:
            if not db.scalar(select(Invite).where(Invite.token_hash == digest(bootstrap))):
                db.add(Invite(token_hash=digest(bootstrap)))
                db.commit()
    diagnostic_task=None
    if os.getenv("WRITER_AI_STARTUP_SMOKE")=="1":
        import asyncio
        from .ai_live_diagnostic import evaluate_live_synthetic
        diagnostic_task=asyncio.create_task(evaluate_live_synthetic())
    try:
        yield
    finally:
        if diagnostic_task and not diagnostic_task.done():
            diagnostic_task.cancel()
app=FastAPI(lifespan=lifespan,title='مساحة الكاتب',docs_url=None if IS_PROD else '/api/docs',redoc_url=None,openapi_url=None if IS_PROD else '/api/openapi.json')
if IS_PROD:
    hosts=[v.strip() for v in os.getenv('APP_ALLOWED_HOSTS','').split(',') if v.strip()]
    # Managed hosting providers set the public hostname dynamically.
    render_host=os.getenv('RENDER_EXTERNAL_HOSTNAME','').strip()
    if render_host and render_host not in hosts: hosts.append(render_host)
    if not hosts or '*' in hosts: raise RuntimeError('APP_ALLOWED_HOSTS or RENDER_EXTERNAL_HOSTNAME must be configured for production')
    pilot = os.getenv('PILOT_EPHEMERAL') == '1'
    db_url = os.getenv('DATABASE_URL','')
    if not db_url.startswith(('postgres://','postgresql://','postgresql+psycopg://')):
        if not (pilot and db_url == 'sqlite:////tmp/writer-space-pilot.db'):
            raise RuntimeError('PostgreSQL is required for production; explicit ephemeral pilot exception only')
    if pilot and os.getenv('OPENAI_API_KEY'):
        raise RuntimeError('AI cannot be enabled in ephemeral public pilot')
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=hosts)

@app.middleware('http')
async def protect(request, call_next):
    if request.url.path.startswith('/api/') and request.method in ('POST','PUT','PATCH','DELETE'):
        ctype=request.headers.get('content-type','').split(';')[0].strip().lower()
        if ctype!='application/json': return JSONResponse({'detail':'مطلوب إرسال JSON'},status_code=415)
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'مصدر الطلب غير مسموح'},status_code=403)
        try:
            n=int(request.headers.get('content-length','0'))
            if n > 60_000_000: return JSONResponse({'detail':'حجم الطلب يتجاوز الحد'},status_code=413)
        except ValueError: return JSONResponse({'detail':'حجم غير صالح'},status_code=400)
    resp=await call_next(request)
    resp.headers['X-Content-Type-Options']='nosniff'
    resp.headers['X-Frame-Options']='DENY'
    resp.headers['Referrer-Policy']='no-referrer'
    resp.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    resp.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    if IS_PROD: resp.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    if request.url.path.startswith('/api/') or request.url.path in ('/', '/admin'):
        resp.headers['Cache-Control']='no-store'
    return resp

app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
@app.get('/')
def index(): return FileResponse(ROOT/'static'/'index.html')
@app.head('/')
def head_index(): return Response(status_code=200)
@app.get('/admin')
def admin_page(): return FileResponse(ROOT/'static'/'admin.html')
@app.get('/robots.txt')
def robots(): return PlainTextResponse('User-agent: *\nDisallow: /\n')
@app.get('/health')
def health(db:OrmSession=Depends(get_db)):
    db.execute(text('SELECT 1'))
    return {'status':'ok','ai_configured':ai_configured(), 'ephemeral':engine.dialect.name=='sqlite','durable_storage':engine.dialect.name=='postgresql','pilot_invites':os.getenv('PILOT_INVITE_MODE')=='1'}

_attempts={}
def throttle(key, limit=9, window=900):
    current=time.monotonic(); hits=[x for x in _attempts.get(key,[]) if current-x<window]
    if len(hits)>=limit: raise HTTPException(429,'محاولات كثيرة. حاول لاحقًا')
    hits.append(current); _attempts[key]=hits

def auth(request:Request,db:OrmSession=Depends(get_db)):
    token=request.cookies.get(COOKIE_NAME,'')
    if not token: raise HTTPException(401,'يرجى تسجيل الدخول')
    sess=db.scalar(select(LoginSession).where(LoginSession.token_hash==digest(token)))
    if not sess or sess.expires_at.replace(tzinfo=timezone.utc)<=now(): raise HTTPException(401,'انتهت الجلسة')
    user=db.get(User,sess.user_id)
    if not user: raise HTTPException(401,'يرجى تسجيل الدخول')
    if os.getenv('PILOT_INVITE_MODE')=='1':
        from .pilot import pilot_entry
        entry=pilot_entry(db,user)
        if not entry or not entry.enabled: raise HTTPException(401,'الدعوة غير مفعّلة')
    if request.method in ('POST','PUT','PATCH','DELETE'): require_csrf(request,sess)
    return user

def owned_project(db,user,pid):
    if not 1<=pid<=9223372036854775806: raise HTTPException(404,'العمل غير موجود')
    p=db.get(Project,pid)
    if not p or p.user_id!=user.id: raise HTTPException(404,'العمل غير موجود')
    return p

def owned_section(db,user,pid,sid):
    owned_project(db,user,pid)
    if not 1<=sid<=9223372036854775806: raise HTTPException(404,'المقطع غير موجود')
    sec=db.get(Section,sid)
    if not sec or sec.project_id!=pid: raise HTTPException(404,'المقطع غير موجود')
    return sec

def _json(raw,default):
    try: return json.loads(raw)
    except (TypeError,ValueError): return default

def proj_json(p): return {'id':p.id,'title':p.title,'kind':p.kind,'premise':p.premise,'structure':_json(p.structure,{}),'scratchpad':p.scratchpad,'checkpoint':_json(p.checkpoint,{}),'version':p.version,'updated_at':p.updated_at.isoformat() if p.updated_at else None}
def sec_json(s): return {'id':s.id,'project_id':s.project_id,'title':s.title,'body':s.body,'blocks':_json(s.blocks,[]),'position':s.position,'version':s.version,'updated_at':s.updated_at.isoformat() if s.updated_at else None}
def fact_json(f,sec_map=None):
    status=f.evidence_status
    if f.evidence and not f.section_id: status='source_missing'
    elif f.evidence and f.section_id and sec_map is not None and (f.section_id not in sec_map or sec_map[f.section_id]!=f.source_version): status='source_changed'
    return {'id':f.id,'subject':f.subject,'predicate':f.predicate,'value':f.value,'evidence':f.evidence,'section_id':f.section_id,'evidence_status':status,'source_version':f.source_version}

class Register(BaseModel):
    email:str=Field(min_length=5,max_length=250)
    password:str=Field(min_length=12,max_length=128)
    invite:str=Field(min_length=10,max_length=160)
class Login(BaseModel):
    email:str; password:str

def normalize_email(s):
    s=s.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',s): raise HTTPException(422,'البريد غير صالح')
    return s

def login_session(db,user,response):
    token=secure_random(); csrf=csrf_for_session(token)
    sess=LoginSession(user_id=user.id,token_hash=digest(token),csrf_hash=digest(csrf),expires_at=now()+timedelta(days=SESSION_DAYS))
    db.add(sess); db.commit()
    response.set_cookie(COOKIE_NAME,token,httponly=True,secure=IS_PROD,samesite='strict',path='/',max_age=SESSION_DAYS*86400)
    return {'email':user.email,'csrf':csrf}

@app.post('/api/auth/register')
def register(data:Register,request:Request,response:Response,db:OrmSession=Depends(get_db)):
    if os.getenv('PILOT_INVITE_MODE')=='1': raise HTTPException(403,'التسجيل التجريبي عبر دعوة يصدرها المدير فقط')
    throttle('register:'+request.client.host,limit=12)
    email=normalize_email(data.email)
    if not pw_valid(data.password): raise HTTPException(422,'كلمة المرور يجب ألا تقل عن 12 حرفًا')
    invite=db.scalar(select(Invite).where(Invite.token_hash==digest(data.invite),Invite.used_by.is_(None)))
    if not invite: raise HTTPException(403,'رمز الدعوة غير صالح أو مستخدم')
    if db.scalar(select(User).where(User.email==email)): raise HTTPException(409,'البريد مستخدم')
    user=User(email=email,password_hash=hash_password.hash(data.password)); db.add(user); db.flush()
    recovery_code=secure_random()
    db.add(RecoveryCode(user_id=user.id,code_hash=digest(recovery_code)))
    claimed=db.execute(update(Invite).where(Invite.id==invite.id, Invite.used_by.is_(None)).values(used_by=user.id))
    if claimed.rowcount!=1: db.rollback(); raise HTTPException(409,'تم استخدام رمز الدعوة')
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,'تم استخدام الدعوة أو البريد')
    session=login_session(db,user,response)
    session['recovery_code']=recovery_code
    return session

@app.post('/api/auth/login')
def login(data:Login,request:Request,response:Response,db:OrmSession=Depends(get_db)):
    if os.getenv('PILOT_INVITE_MODE')=='1': raise HTTPException(403,'ادخل باسم المستخدم ورمز الدعوة')
    email=normalize_email(data.email)
    throttle('login:'+request.client.host+':'+email,limit=8)
    user=db.scalar(select(User).where(User.email==email))
    if not user or not verify(data.password,user.password_hash): raise HTTPException(401,'بيانات الدخول غير صحيحة')
    return login_session(db,user,response)

class RecoverAccount(BaseModel):
    email:str=Field(min_length=5,max_length=250)
    code:str=Field(min_length=32,max_length=160)
    new_password:str=Field(min_length=12,max_length=128)

@app.post('/api/auth/recover')
def recover_account(data:RecoverAccount,request:Request,db:OrmSession=Depends(get_db)):
    if os.getenv('PILOT_INVITE_MODE')=='1': raise HTTPException(403,'أدر رمز الدخول عبر مدير الدعوات')
    email=normalize_email(data.email)
    throttle('recovery:'+request.client.host+':'+email,limit=5,window=3600)
    if not pw_valid(data.new_password): raise HTTPException(422,'كلمة المرور يجب ألا تقل عن 12 حرفًا')
    user=db.scalar(select(User).where(User.email==email))
    rec=db.scalar(select(RecoveryCode).where(RecoveryCode.user_id==user.id)) if user else None
    if not rec or not secrets.compare_digest(rec.code_hash,digest(data.code)):
        raise HTTPException(403,'البريد أو رمز الاستعادة غير صحيح')
    user.password_hash=hash_password.hash(data.new_password)
    new_code=secure_random()
    rec.code_hash=digest(new_code)
    rec.created_at=now()
    db.execute(delete(LoginSession).where(LoginSession.user_id==user.id))
    db.commit()
    return {'ok':True,'recovery_code':new_code}

@app.get('/api/auth/me')
def me(request:Request,db:OrmSession=Depends(get_db)):
    user=auth(request,db)
    sess=db.scalar(select(LoginSession).where(LoginSession.token_hash==digest(request.cookies.get(COOKIE_NAME,''))))
    # Deterministic session-bound CSRF token remains valid across refreshes/tabs.
    csrf=csrf_for_session(request.cookies.get(COOKIE_NAME,''))
    from .pilot import pilot_entry
    entry=pilot_entry(db,user)
    return {'email':user.email,'display_name':entry.display_name if entry else None,'username':entry.username if entry else None,'role':entry.role if entry else 'writer', 'pilot':bool(entry), 'csrf':csrf,'ai_available':ai_configured()}

@app.post('/api/auth/logout')
def logout(request:Request,response:Response,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    db.execute(delete(LoginSession).where(LoginSession.token_hash==digest(request.cookies.get(COOKIE_NAME,''))))
    db.commit(); response.delete_cookie(COOKIE_NAME,path='/'); return {'ok':True}

class CreateProject(BaseModel):
    title:str=Field(min_length=1,max_length=240)
    kind:Literal['novel','short','flash','children','screenplay']

def normalized_title(value:str)->str:
    return ' '.join(unicodedata.normalize('NFKC',value).split()).casefold()

def catalog_project(p):
    return {'id':p.id,'title':p.title,'kind':p.kind,'premise':p.premise[:450],
            'version':p.version,'updated_at':p.updated_at.isoformat() if p.updated_at else None}

@app.get('/api/projects/catalog')
def project_catalog(user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    return [catalog_project(p) for p in db.scalars(
        select(Project).where(Project.user_id==user.id).order_by(Project.updated_at.desc())
    ).all()]

@app.get('/api/projects')
def list_projects(user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    return [proj_json(p) for p in db.scalars(select(Project).where(Project.user_id==user.id).order_by(Project.updated_at.desc())).all()]

@app.post('/api/projects')
def create_project(data:CreateProject,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    title=' '.join(data.title.split())
    if not title: raise HTTPException(422,'اسم العمل لا يمكن أن يكون فارغًا')
    # PostgreSQL transaction lock serializes project creation per author.
    # Legacy projects may already contain duplicate titles; do not destroy them.
    if db.bind.dialect.name=='postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(:lock_id)'),{'lock_id':int(user.id)+913570000})
    existing=db.execute(select(Project.id,Project.title).where(Project.user_id==user.id,Project.kind==data.kind)).all()
    found_id=next((item.id for item in existing if normalized_title(item.title)==normalized_title(title)),None)
    if found_id:
        return {**proj_json(db.get(Project,found_id)),'reused':True}
    p=Project(user_id=user.id,title=title,kind=data.kind,structure='{}',checkpoint='{}')
    db.add(p);db.commit()
    return {**proj_json(p),'reused':False}

@app.get('/api/projects/{pid}')
def get_project(pid:int,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    p=owned_project(db,user,pid)
    sec=db.scalars(select(Section).where(Section.project_id==pid).order_by(Section.position,Section.id)).all()
    sec_versions={s.id:s.version for s in sec}
    return {'project':proj_json(p),'sections':[sec_json(s) for s in sec], 'facts':[fact_json(f,sec_versions) for f in db.scalars(select(Fact).where(Fact.project_id==pid).order_by(Fact.id))]}

class UpdateProject(BaseModel):
    version:int=Field(ge=1,le=9223372036854775806)
    title:str=Field(min_length=1,max_length=240)
    premise:str=Field(max_length=12000)
    structure:dict=Field(default_factory=dict)
    scratchpad:str=Field(max_length=200000)
    checkpoint:dict=Field(default_factory=dict)

@app.put('/api/projects/{pid}')
def update_project(pid:int,data:UpdateProject,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    current=owned_project(db,user,pid)
    if not data.title.strip(): raise HTTPException(422,'اسم العمل لا يمكن أن يكون فارغًا')
    if normalized_title(data.title)!=normalized_title(current.title):
        if db.bind.dialect.name=='postgresql':
            db.execute(text('SELECT pg_advisory_xact_lock(:lock_id)'),{'lock_id':int(user.id)+913570000})
        matches=db.execute(select(Project.id,Project.title).where(Project.user_id==user.id,Project.kind==current.kind,Project.id!=pid)).all()
        if any(normalized_title(item.title)==normalized_title(data.title) for item in matches):
            raise HTTPException(409,'لديك مشروع آخر بهذا الاسم والنوع')
    if len(json.dumps(data.structure,ensure_ascii=False))>50000 or len(json.dumps(data.checkpoint,ensure_ascii=False))>16000: raise HTTPException(413,'البيانات المنظمة طويلة')
    other_bytes=sum(len(s.body.encode('utf-8'))+len(s.blocks.encode('utf-8')) for s in db.scalars(select(Section).where(Section.project_id==pid)))
    if other_bytes+len(data.scratchpad.encode('utf-8'))>25_000_000: raise HTTPException(413,'العمل يتجاوز سعة الاختبار، صدّر نسخة احتياطية')
    result=db.execute(update(Project).where(Project.id==pid,Project.user_id==user.id,Project.version==data.version).values(title=data.title.strip(),premise=data.premise,structure=json.dumps(data.structure,ensure_ascii=False),scratchpad=data.scratchpad,checkpoint=json.dumps(data.checkpoint,ensure_ascii=False),version=Project.version+1,updated_at=now()))
    if result.rowcount!=1: db.rollback(); raise HTTPException(409,'تعديل أحدث موجود. احتفظ بنصك وأعد تحميل المشروع')
    db.commit(); return proj_json(db.get(Project,pid))

@app.delete('/api/projects/{pid}')
def delete_project(pid:int,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    p=owned_project(db,user,pid); db.delete(p); db.commit(); return {'ok':True}

class SectionCreate(BaseModel):
    title:str=Field(min_length=1,max_length=240)

@app.post('/api/projects/{pid}/sections')
def create_section(pid:int,data:SectionCreate,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    owned_project(db,user,pid)
    count=db.scalar(select(func.count(Section.id)).where(Section.project_id==pid))
    if count>=400: raise HTTPException(422,'وصلت إلى الحد المسموح للمقاطع')
    if not data.title.strip(): raise HTTPException(422,'اسم المقطع لا يمكن أن يكون فارغًا')
    s=Section(project_id=pid,title=data.title.strip(),position=count,blocks='[]'); db.add(s); db.commit(); return sec_json(s)

class SectionUpdate(BaseModel):
    version:int=Field(ge=1)
    title:str=Field(min_length=1,max_length=240)
    body:str=Field(max_length=450000)
    blocks:list=Field(default_factory=list,max_length=900)

def validate_blocks(blocks):
    if len(blocks)>900: raise HTTPException(422,'عدد عناصر المشهد يتجاوز الحد المسموح')
    for b in blocks:
        if not isinstance(b,dict) or b.get('type') not in BLOCK_TYPES or not isinstance(b.get('text'),str) or len(b['text'])>15000: raise HTTPException(422,'عنصر السيناريو غير صالح')

@app.put('/api/projects/{pid}/sections/{sid}')
def update_section(pid:int,sid:int,data:SectionUpdate,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    old=owned_section(db,user,pid,sid); validate_blocks(data.blocks)
    if not data.title.strip(): raise HTTPException(422,'اسم المقطع لا يمكن أن يكون فارغًا')
    if old.version!=data.version: raise HTTPException(409,'تعديل أحدث موجود؛ لن نكتب فوقه')
    other_bytes=sum(len(s.body.encode('utf-8'))+len(s.blocks.encode('utf-8')) for s in db.scalars(select(Section).where(Section.project_id==pid,Section.id!=sid)))
    project=db.get(Project,pid)
    incoming_bytes=len(data.body.encode('utf-8'))+len(json.dumps(data.blocks,ensure_ascii=False).encode('utf-8'))
    if other_bytes+incoming_bytes+len(project.scratchpad.encode('utf-8'))>25_000_000: raise HTTPException(413,'العمل يتجاوز سعة النسخة التجريبية')
    snapshot=Revision(section_id=sid,version=old.version,title=old.title,body=old.body,blocks=old.blocks)
    result=db.execute(update(Section).where(Section.id==sid,Section.project_id==pid,Section.version==data.version).values(title=data.title.strip(),body=data.body,blocks=json.dumps(data.blocks,ensure_ascii=False),version=Section.version+1,updated_at=now()))
    if result.rowcount!=1: db.rollback(); raise HTTPException(409,'تعديل أحدث موجود')
    db.add(snapshot)
    db.flush()
    # Retain exactly the latest three preceding revisions; existing history is
    # pruned only when that section next receives a successful new revision.
    latest_ids=select(Revision.id).where(Revision.section_id==sid).order_by(Revision.version.desc()).limit(3)
    db.execute(delete(Revision).where(Revision.section_id==sid,Revision.id.not_in(latest_ids)))
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409,'تعارض تحديث. أعد تحميل المشروع')
    return sec_json(db.get(Section,sid))

@app.get('/api/projects/{pid}/sections/{sid}/revisions')
def revisions(pid:int,sid:int,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    owned_section(db,user,pid,sid)
    return [{'version':r.version,'title':r.title,'created_at':r.created_at.isoformat()} for r in db.scalars(select(Revision).where(Revision.section_id==sid).order_by(Revision.version.desc()).limit(3))]

class Restore(BaseModel):
    current_version:int=Field(ge=1,le=9223372036854775806)
    target_version:int=Field(ge=1,le=9223372036854775806)

@app.post('/api/projects/{pid}/sections/{sid}/restore')
def restore(pid:int,sid:int,data:Restore,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    old=owned_section(db,user,pid,sid)
    if old.version!=data.current_version: raise HTTPException(409,'تعديل أحدث موجود')
    available=db.scalars(select(Revision).where(Revision.section_id==sid).order_by(Revision.version.desc()).limit(3)).all()
    target=next((rev for rev in available if rev.version==data.target_version),None)
    if not target: raise HTTPException(404,'النسخة المطلوبة غير موجودة')
    snap=Revision(section_id=sid,version=old.version,title=old.title,body=old.body,blocks=old.blocks)
    res=db.execute(update(Section).where(Section.id==sid,Section.version==data.current_version).values(title=target.title,body=target.body,blocks=target.blocks,version=Section.version+1,updated_at=now()))
    if res.rowcount!=1: db.rollback(); raise HTTPException(409,'تعارض استعادة')
    db.add(snap);db.flush()
    latest_ids=select(Revision.id).where(Revision.section_id==sid).order_by(Revision.version.desc()).limit(3)
    db.execute(delete(Revision).where(Revision.section_id==sid,Revision.id.not_in(latest_ids)))
    db.commit(); return sec_json(db.get(Section,sid))

@app.delete('/api/projects/{pid}/sections/{sid}')
def delete_section(pid:int,sid:int,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    s=owned_section(db,user,pid,sid); db.delete(s); db.commit(); return {'ok':True}

class FactCreate(BaseModel):
    subject:str=Field(min_length=1,max_length=200)
    predicate:str=Field(min_length=1,max_length=200)
    value:str=Field(min_length=1,max_length=500)
    evidence:str=Field(default='',max_length=2000)
    section_id:int|None=None

@app.post('/api/projects/{pid}/facts')
def add_fact(pid:int,data:FactCreate,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    owned_project(db,user,pid)
    if data.section_id is not None: owned_section(db,user,pid,data.section_id)
    status='manual'; source_version=None
    if data.evidence:
        if data.section_id is None: raise HTTPException(422,'حدد المقطع الداعم للشاهد')
        s=owned_section(db,user,pid,data.section_id)
        source=s.body+'\n'+'\n'.join(b.get('text','') for b in _json(s.blocks,[]))
        if data.evidence not in source: raise HTTPException(422,'الشاهد الحرفي غير موجود في النص')
        status='literal_unverified_meaning'; source_version=s.version
    f=Fact(project_id=pid,subject=data.subject,predicate=data.predicate,value=data.value,evidence=data.evidence,section_id=data.section_id,evidence_status=status,source_version=source_version); db.add(f); db.commit(); return fact_json(f)

@app.delete('/api/projects/{pid}/facts/{fid}')
def del_fact(pid:int,fid:int,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    owned_project(db,user,pid)
    if not 1<=fid<=9223372036854775806: raise HTTPException(404,'الواقعة غير موجودة')
    f=db.get(Fact,fid)
    if not f or f.project_id!=pid: raise HTTPException(404,'الواقعة غير موجودة')
    db.delete(f); db.commit(); return {'ok':True}

class ChatRequest(BaseModel):
    message:str=Field(min_length=2,max_length=4000)
    share_scratchpad:bool=False
    share_structure:bool=False
    section_ids:list[int]=Field(default_factory=list,max_length=3)
    share_history:bool=False

@app.get('/api/projects/{pid}/chat')
def chat_history(pid:int,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    owned_project(db,user,pid)
    out=db.scalars(select(Chat).where(Chat.project_id==pid).order_by(Chat.id.desc()).limit(40)).all()[::-1]
    return [{'id':v.id,'role':v.role,'text':v.text,'proposals':_json(v.proposals,[])} for v in out]

@app.delete('/api/projects/{pid}/chat')
def clear_chat(pid:int,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    owned_project(db,user,pid)
    db.execute(delete(Chat).where(Chat.project_id==pid)); db.commit(); return {'ok':True}

@app.post('/api/projects/{pid}/chat')
async def chat(pid:int,data:ChatRequest,request:Request,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    p=owned_project(db,user,pid)
    throttle('ai:'+str(user.id),limit=15,window=3600)
    ctx=[]
    if data.share_scratchpad: ctx.append('أفكار حرّة:\n'+p.scratchpad[:4000])
    if data.share_structure: ctx.append('بيانات منظمة:\n'+p.structure[:3000])
    for sid in set(data.section_ids):
        s=owned_section(db,user,pid,sid)
        ctx.append('مقطع '+s.title+':\n'+ (s.body or '\n'.join(x.get('text','') for x in _json(s.blocks,[])))[:2400])
    history=db.scalars(select(Chat).where(Chat.project_id==pid).order_by(Chat.id.desc()).limit(8)).all()[::-1] if data.share_history else []
    result=await analyze(p.kind,data.message,'\n---\n'.join(ctx),[{'role':x.role,'text':x.text} for x in history])
    db.add(Chat(project_id=pid,role='user',text=data.message))
    db.add(Chat(project_id=pid,role='assistant',text=result['reply'],proposals=json.dumps(result['suggestions'],ensure_ascii=False)))
    db.commit(); return result

@app.get('/api/projects/{pid}/export')
def export_project(pid:int,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    p=owned_project(db,user,pid)
    from .writer_intelligence import SectionSynopsis, progress_json
    from .literary_core import LiteraryFinding, FindingContextSnapshot
    from .writing_coach import PracticeEntry
    from .manuscript_tools import WriterMilestone
    sections=db.scalars(select(Section).where(Section.project_id==pid).order_by(Section.position,Section.id)).all()
    synopses=db.scalars(select(SectionSynopsis).where(SectionSynopsis.project_id==pid)).all()
    literary=db.scalars(select(LiteraryFinding).where(LiteraryFinding.project_id==pid)).all()
    context_rows=db.scalars(select(FindingContextSnapshot).where(FindingContextSnapshot.project_id==pid)).all()
    contexts={row.finding_id:_json(row.sources_json,[]) for row in context_rows}
    coaching=db.scalars(select(PracticeEntry).where(PracticeEntry.project_id==pid)).all()
    milestones=db.scalars(select(WriterMilestone).where(WriterMilestone.project_id==pid)).all()
    return {'format':'writer-cloud-v2','project':{**proj_json(p),'kind':p.kind},
            'sections':[sec_json(x) for x in sections],
            'facts':[fact_json(x,{s.id:s.version for s in sections}) for x in db.scalars(select(Fact).where(Fact.project_id==pid))],
            'revisions':[{'section_id':r.section_id,'version':r.version,'title':r.title,'body':r.body,'blocks':_json(r.blocks,[])}
                         for r in db.scalars(select(Revision).where(Revision.section_id.in_([a.id for a in sections])).order_by(Revision.section_id,Revision.version))],
            'chats':[{'role':x.role,'text':x.text,'proposals':_json(x.proposals,[])} for x in db.scalars(select(Chat).where(Chat.project_id==pid).order_by(Chat.id))],
            'synopses':[{'section_id':x.section_id,'summary':x.summary,'central_event':x.central_event,
                         'character_change':x.character_change,'open_question':x.open_question,
                         'source_hash':x.source_hash,'origin':x.origin} for x in synopses],
            'progress':progress_json(db,pid),
            'literary_findings':[{'section_id':x.section_id,'source_version':x.source_version,
                'source_hash':x.source_hash,'observation':x.observation,'evidence':x.evidence,
                'impact':x.impact,'action':x.action,'category':x.category,'state':x.state,
                'context_sources':contexts.get(x.id,[])}
                for x in literary],
            'coaching_sessions':[{'practice_code':x.practice_code,'skill':x.skill,
                'state':x.state,'before_rating':x.before_rating,
                'after_rating':x.after_rating,'author_notes':x.author_notes,
                'author_reflection':x.author_reflection}
                for x in coaching],
            'pinned_milestones':[{'section_id':x.section_id,'version':x.version,
                'label':x.label,'title':x.title,'body':x.body,
                'blocks':_json(x.blocks,[])} for x in milestones]}

class ImportData(BaseModel):
    model_config=ConfigDict(extra='forbid')
    data:dict

@app.post('/api/import')
def import_project(request:ImportData,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    raw=request.data
    fmt=raw.get('format')
    if fmt not in ('writer-cloud-v1','writer-cloud-v2') or not isinstance(raw.get('project'),dict) or not isinstance(raw.get('sections'),list) or not isinstance(raw.get('facts'),list): raise HTTPException(422,'صيغة النسخة الاحتياطية غير صالحة')
    revs=raw.get('revisions',[]) if fmt=='writer-cloud-v2' else []
    chats=raw.get('chats',[]) if fmt=='writer-cloud-v2' else []
    synopses=raw.get('synopses',[]) if fmt=='writer-cloud-v2' else []
    progress=raw.get('progress',None) if fmt=='writer-cloud-v2' else None
    literary_findings=raw.get('literary_findings',[]) if fmt=='writer-cloud-v2' else []
    coaching_sessions=raw.get('coaching_sessions',[]) if fmt=='writer-cloud-v2' else []
    pinned_milestones=raw.get('pinned_milestones',[]) if fmt=='writer-cloud-v2' else []
    if not isinstance(revs,list) or len(revs)>10000 or not isinstance(chats,list) or len(chats)>3000 or not isinstance(synopses,list) or len(synopses)>400 or not isinstance(literary_findings,list) or len(literary_findings)>1000 or not isinstance(coaching_sessions,list) or len(coaching_sessions)>2000 or not isinstance(pinned_milestones,list) or len(pinned_milestones)>20: raise HTTPException(422,'عدد سجلات النسخة الاحتياطية غير صالح')
    if len(json.dumps(raw,ensure_ascii=False).encode('utf-8'))>30_000_000: raise HTTPException(413,'النسخة الاحتياطية كبيرة جدًا')
    proj=raw['project']; kind=proj.get('kind')
    if kind not in KINDS or not isinstance(proj.get('title'),str) or not (1<=len(proj['title'])<=240) or not proj['title'].strip() or len(raw['sections'])>400 or len(raw['facts'])>3000: raise HTTPException(422,'بيانات المشروع غير صالحة')
    if (not isinstance(proj.get('premise',''),str) or len(proj.get('premise',''))>12000 or
        not isinstance(proj.get('scratchpad',''),str) or len(proj.get('scratchpad',''))>200000 or
        not isinstance(proj.get('structure',{}),dict) or not isinstance(proj.get('checkpoint',{}),dict)):
        raise HTTPException(422,'الملف يحتوي بيانات عمل غير صالحة')
    if len(json.dumps(proj.get('structure',{}),ensure_ascii=False))>50000 or len(json.dumps(proj.get('checkpoint',{}),ensure_ascii=False))>16000:
        raise HTTPException(422,'البيانات المنظمة تتجاوز الحد')
    try:
        validated=[]
        for sec in raw['sections']:
            if not isinstance(sec,dict) or not isinstance(sec.get('title'),str) or not (1<=len(sec['title'])<=240) or not sec['title'].strip() or not isinstance(sec.get('body'),str) or len(sec['body'])>450000 or not isinstance(sec.get('blocks'),list): raise ValueError()
            validate_blocks(sec['blocks'])
            if fmt=='writer-cloud-v2' and (type(sec.get('version')) is not int or not 1<=sec['version']<=9223372036854775806): raise ValueError('section version')
            validated.append(sec)
        source_ids=[sec.get('id') for sec in validated]
        if any(((not isinstance(x,(int,str))) or isinstance(x,bool) or (isinstance(x,int) and x<1) or (isinstance(x,str) and (not x.strip() or len(x)>120))) for x in source_ids) or len(source_ids)!=len(set((type(x).__name__,x) for x in source_ids)):
            raise ValueError('duplicate/invalid section identifiers')
        version_map={sec['id']:sec['version'] if fmt=='writer-cloud-v2' else 1 for sec in validated}
        checked_revisions=set()
        for rev in revs:
            if not isinstance(rev,dict) or rev.get('section_id') not in version_map or type(rev.get('version')) is not int or not 1<=rev['version']<version_map[rev['section_id']]: raise ValueError('revision reference')
            identity=(rev['section_id'],rev['version'])
            if identity in checked_revisions: raise ValueError('duplicate revision')
            checked_revisions.add(identity)
            if not isinstance(rev.get('title'),str) or not 1<=len(rev['title'])<=240 or not rev['title'].strip() or not isinstance(rev.get('body'),str) or len(rev['body'])>450000 or not isinstance(rev.get('blocks'),list): raise ValueError('revision')
            validate_blocks(rev['blocks'])
        synopsis_ids=set()
        for synopsis in synopses:
            if not isinstance(synopsis,dict) or synopsis.get('section_id') not in version_map:
                raise ValueError('synopsis source')
            if synopsis['section_id'] in synopsis_ids: raise ValueError('duplicate synopsis')
            synopsis_ids.add(synopsis['section_id'])
            for key,limit in [('summary',1200),('central_event',600),('character_change',600),('open_question',600)]:
                if not isinstance(synopsis.get(key,''),str) or len(synopsis.get(key,''))>limit:
                    raise ValueError('synopsis length')
            if not isinstance(synopsis.get('source_hash',''),str) or len(synopsis.get('source_hash',''))>64:
                raise ValueError('synopsis fingerprint')
        if progress is not None:
            if (not isinstance(progress,dict) or progress.get('tab') not in {'free','manuscript','structure','overview','checkpoint'} or
               progress.get('section_id') is not None and progress['section_id'] not in version_map or
               type(progress.get('cursor_offset',0)) is not int or not 0<=progress.get('cursor_offset',0)<=450000):
                raise ValueError('progress')
        for item in literary_findings:
            if not isinstance(item,dict) or item.get('section_id') not in version_map:
                raise ValueError('literary finding source')
            if type(item.get('source_version')) is not int or not 1<=item['source_version']<=version_map[item['section_id']]:
                raise ValueError('literary finding version')
            for key,limit in [('source_hash',64),('observation',1200),('evidence',650),('impact',1200),('action',1200),('category',32),('state',20)]:
                if not isinstance(item.get(key),str) or len(item[key])>limit:
                    raise ValueError('literary finding field')
            if item['state'] not in ('open','discussed','accepted','dismissed','resolved'):
                raise ValueError('literary finding state')
            references=item.get('context_sources',[])
            if not isinstance(references,list) or len(references)>12:
                raise ValueError('literary context size')
            for reference in references:
                if (not isinstance(reference,dict) or type(reference.get('section_id')) is not int or
                    type(reference.get('version')) is not int or reference['version']<1 or
                    not isinstance(reference.get('source_hash'),str) or len(reference['source_hash'])!=64):
                    raise ValueError('literary context reference')
                quotes=reference.get('quotes',[])
                if (not isinstance(quotes,list) or len(quotes)>2 or
                    any(not isinstance(q,str) or len(q)>650 for q in quotes)):
                    raise ValueError('literary context quotations')
        total_pinned_bytes=0
        for pinned in pinned_milestones:
            if (not isinstance(pinned,dict) or pinned.get('section_id') not in version_map or
                type(pinned.get('version')) is not int or
                not 1<=pinned['version']<=version_map[pinned['section_id']]):
                raise ValueError('pinned version')
            if (not isinstance(pinned.get('label'),str) or not 2<=len(pinned['label'])<=120 or
                not isinstance(pinned.get('title'),str) or not 1<=len(pinned['title'])<=240 or
                not isinstance(pinned.get('body'),str) or len(pinned['body'])>450000 or
                not isinstance(pinned.get('blocks'),list)):
                raise ValueError('pinned content')
            validate_blocks(pinned['blocks'])
            total_pinned_bytes+=len(pinned['body'].encode())+len(json.dumps(pinned['blocks'],ensure_ascii=False).encode())
        if total_pinned_bytes>8_000_000:
            raise ValueError('pinned storage limit')
        for item in coaching_sessions:
            if not isinstance(item,dict) or item.get('state') not in ('in_progress','completed'):
                raise ValueError('coaching session state')
            if not isinstance(item.get('practice_code'),str) or len(item['practice_code'])>40 or not isinstance(item.get('skill'),str) or len(item['skill'])>120:
                raise ValueError('coaching session identity')
            if type(item.get('before_rating')) is not int or not 1<=item['before_rating']<=5:
                raise ValueError('coaching session rating')
            after=item.get('after_rating')
            if after is not None and (type(after) is not int or not 1<=after<=5):
                raise ValueError('coaching session result')
            if item['state']=='completed' and after is None:
                raise ValueError('completed session without rating')
            for field in ('author_notes','author_reflection'):
                if not isinstance(item.get(field,''),str) or len(item.get(field,''))>3000:
                    raise ValueError('coaching text')
        for msg in chats:
            if not isinstance(msg,dict) or msg.get('role') not in ('user','assistant') or not isinstance(msg.get('text'),str) or len(msg['text'])>6000 or not isinstance(msg.get('proposals'),list) or len(json.dumps(msg['proposals'],ensure_ascii=False))>12000: raise ValueError('chat')
        for f in raw['facts']:
            if not isinstance(f,dict) or not all(isinstance(f.get(k),str) for k in ['subject','predicate','value','evidence']): raise ValueError()
            if not (1<=len(f['subject'])<=200 and 1<=len(f['predicate'])<=200 and 1<=len(f['value'])<=500 and len(f['evidence'])<=2000): raise ValueError()
        for fact in raw['facts']:
            if fact.get('section_id') is not None and fact['section_id'] not in source_ids:
                raise ValueError('dangling evidence source')
        cp_sid=proj.get('checkpoint',{}).get('section_id')
        if cp_sid is not None and cp_sid not in source_ids:
            raise ValueError('dangling checkpoint source')
        total_bytes=len(proj.get('scratchpad','').encode())+sum(len(s['body'].encode())+len(json.dumps(s['blocks'],ensure_ascii=False).encode()) for s in validated)
        total_bytes+=sum(len(r['body'].encode())+len(json.dumps(r['blocks'],ensure_ascii=False).encode()) for r in revs)
        total_bytes+=sum(len(m['text'].encode())+len(json.dumps(m['proposals'],ensure_ascii=False).encode()) for m in chats)
        if total_bytes>25_000_000: raise ValueError()
        pp=Project(user_id=user.id,kind=kind,title=proj['title'],premise=proj.get('premise',''),scratchpad=proj.get('scratchpad',''),structure=json.dumps(proj.get('structure',{}),ensure_ascii=False),checkpoint=json.dumps(proj.get('checkpoint',{}),ensure_ascii=False))
        db.add(pp); db.flush(); old_map={}
        for i,sec in enumerate(validated):
            new=Section(project_id=pp.id,title=sec['title'].strip(),body=sec['body'],blocks=json.dumps(sec['blocks'],ensure_ascii=False),position=i,version=version_map[sec['id']])
            db.add(new); db.flush(); old_map[sec.get('id')]=new.id
        # Restore section references in checkpoint after remapping imported IDs.
        cp=proj.get('checkpoint',{}).copy()
        old_checkpoint_sid=cp.get('section_id')
        if old_checkpoint_sid is not None: cp['section_id']=old_map.get(old_checkpoint_sid)
        pp.checkpoint=json.dumps(cp,ensure_ascii=False)
        for rev in revs:
            db.add(Revision(section_id=old_map[rev['section_id']],version=rev['version'],title=rev['title'].strip(),body=rev['body'],blocks=json.dumps(rev['blocks'],ensure_ascii=False)))
        from .writer_intelligence import SectionSynopsis, WriterProgress, section_text, fingerprint
        for summary in synopses:
            original=summary['section_id'];new_id=old_map[original]
            new_section=db.get(Section,new_id)
            source_hash=summary.get('source_hash','') or fingerprint(section_text(new_section))
            db.add(SectionSynopsis(
                section_id=new_id,project_id=pp.id,
                summary=summary.get('summary',''),
                central_event=summary.get('central_event',''),
                character_change=summary.get('character_change',''),
                open_question=summary.get('open_question',''),
                source_hash=source_hash,
                origin='writer' if summary.get('origin')=='writer' else 'ai_reviewed'))
        if progress:
            db.add(WriterProgress(project_id=pp.id,user_id=user.id,
                section_id=old_map.get(progress.get('section_id')),
                tab=progress['tab'],cursor_offset=progress.get('cursor_offset',0)))
        from .literary_core import LiteraryFinding, FindingContextSnapshot
        for finding in literary_findings:
            row=LiteraryFinding(project_id=pp.id,section_id=old_map[finding['section_id']],
                source_version=finding['source_version'],source_hash=finding['source_hash'],
                observation=finding['observation'],evidence=finding['evidence'],
                impact=finding['impact'],action=finding['action'],category=finding['category'],
                state=finding['state'])
            db.add(row);db.flush()
            references=[{'section_id':old_map.get(ref['section_id'],-1),
                'version':ref['version'],'source_hash':ref['source_hash'],
                'quotes':ref.get('quotes',[])}
                for ref in finding.get('context_sources',[])]
            if references:
                db.add(FindingContextSnapshot(finding_id=row.id,project_id=pp.id,
                    sources_json=json.dumps(references,ensure_ascii=False)))
        from .manuscript_tools import WriterMilestone
        for pinned in pinned_milestones:
            db.add(WriterMilestone(project_id=pp.id,section_id=old_map[pinned['section_id']],
                version=pinned['version'],label=pinned['label'].strip(),
                title=pinned['title'],body=pinned['body'],
                blocks=json.dumps(pinned['blocks'],ensure_ascii=False)))
        from .writing_coach import PracticeEntry
        for exercise in coaching_sessions:
            db.add(PracticeEntry(project_id=pp.id,practice_code=exercise['practice_code'],
                skill=exercise['skill'],state=exercise['state'],
                before_rating=exercise['before_rating'],after_rating=exercise.get('after_rating'),
                author_notes=exercise.get('author_notes',''),
                author_reflection=exercise.get('author_reflection','')))
        for msg in chats:
            db.add(Chat(project_id=pp.id,role=msg['role'],text=msg['text'],proposals=json.dumps(msg['proposals'],ensure_ascii=False)))
        for f in raw['facts']:
            sid=old_map.get(f.get('section_id'))
            ev=f['evidence'][:2000]; status='manual'
            if ev and sid:
                source=next((s for s in validated if old_map.get(s.get('id'))==sid),None)
                if source and ev in (source['body']+'\n'+'\n'.join(x.get('text','') for x in source['blocks'])): status='literal_unverified_meaning'
                else: ev=''
            else: ev=''
            db.add(Fact(project_id=pp.id,subject=f['subject'],predicate=f['predicate'],value=f['value'],evidence=ev,section_id=sid,evidence_status=status,source_version=version_map.get(f.get('section_id')) if status=='literal_unverified_meaning' else None))
        db.commit(); return {'id':pp.id}
    except (ValueError,TypeError,AttributeError):
        db.rollback(); raise HTTPException(422,'النسخة تحتوي بيانات غير سليمة')

class FountainUpload(BaseModel):
    text:str=Field(min_length=1,max_length=500000)

@app.post('/api/projects/{pid}/fountain/import')
def import_fountain(pid:int,data:FountainUpload,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    p=owned_project(db,user,pid)
    if p.kind!='screenplay': raise HTTPException(422,'استيراد Fountain مخصص للسيناريو')
    try: scenes=parse_fountain(data.text)
    except FountainError as e: raise HTTPException(422,str(e))
    existing=db.scalars(select(Section).where(Section.project_id==pid)).all()
    if len(existing)+len(scenes)>400: raise HTTPException(422,'لا توجد سعة كافية للمشاهد')
    total=sum(len(v.body.encode())+len(v.blocks.encode()) for v in existing)+len(p.scratchpad.encode())
    total+=sum(len(json.dumps(s['blocks'],ensure_ascii=False).encode()) for s in scenes)
    if total>25_000_000: raise HTTPException(413,'السيناريو يتجاوز حد الحجم')
    for scene in scenes:
        if not scene['title'].strip(): raise HTTPException(422,'عنوان المشهد غير صالح')
        validate_blocks(scene['blocks'])
    position=max([v.position for v in existing]+[-1])+1
    for i,sc in enumerate(scenes):
        db.add(Section(project_id=pid,title=sc['title'],body='',blocks=json.dumps(sc['blocks'],ensure_ascii=False),position=position+i))
    db.commit()
    return {'added_scenes':len(scenes)}

@app.get('/api/projects/{pid}/fountain')
def fountain(pid:int,user:User=Depends(auth),db:OrmSession=Depends(get_db)):
    p=owned_project(db,user,pid)
    if p.kind!='screenplay': raise HTTPException(422,'التصدير مخصص للسيناريو')
    items=db.scalars(select(Section).where(Section.project_id==pid).order_by(Section.position,Section.id)).all()
    lines=['Title: '+p.title,'','']
    for s in items:
        blocks=_json(s.blocks,[])
        if not blocks: lines.extend(['.'+s.title]+(['!'+s.body] if s.body else [])+['']); continue
        if not any(b.get('type')=='heading' for b in blocks): lines.extend(['.'+s.title,''])
        for block in blocks:
            t=block.get('type'); v=block.get('text','')
            if not v.strip(): continue
            if t=='heading': lines.append('.'+v)
            elif t=='character': lines.append('@'+v)
            elif t=='transition': lines.append('>'+v)
            elif t=='parenthetical': lines.append('('+v.strip('()')+')')
            elif t=='note': raise HTTPException(422,'يحتوي السيناريو على ملاحظة لا يمكن نقلها إلى Fountain بأمان')
            elif t=='action': lines.extend('!'+part for part in v.split('\n'))
            else: lines.extend(v.split('\n'))
            if t not in ('character','parenthetical','dialogue'): lines.append('')
        lines.append('')
    return PlainTextResponse('\n'.join(lines),media_type='text/plain; charset=utf-8',headers={'Content-Disposition':'attachment; filename="screenplay.fountain"'})

class DeleteAccount(BaseModel):
    password:str

@app.post('/api/account/delete')
def delete_account(data:DeleteAccount,user:User=Depends(auth),db:OrmSession=Depends(get_db),response:Response=None):
    if os.getenv('PILOT_INVITE_MODE')=='1': raise HTTPException(403,'المدير يتحكم في الدعوات خلال التجربة')
    if not verify(data.password,user.password_hash): raise HTTPException(403,'كلمة المرور غير صحيحة')
    db.delete(user); db.commit();
    if response is not None: response.delete_cookie(COOKIE_NAME,path='/')
    return {'ok':True}

from .pilot import router as pilot_router
app.include_router(pilot_router)
from .writer_intelligence import router as intelligence_router
app.include_router(intelligence_router)
from .literary_core import router as literary_router
app.include_router(literary_router)
from .manuscript_interchange import router as manuscript_router
app.include_router(manuscript_router)
from .writing_coach import router as coach_router
app.include_router(coach_router)
from .epub_export import router as epub_router
app.include_router(epub_router)
from .manuscript_tools import router as manuscript_tools_router
app.include_router(manuscript_tools_router)
from .reading_map import router as reading_map_router
app.include_router(reading_map_router)
