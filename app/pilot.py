import os, re, secrets
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, select, delete
from sqlalchemy.orm import Session
from .db import Base, SessionLocal, get_db
from .models import User, Project, Section, Chat, Session as LoginSession, now
from .security import digest, hash_password
from . import main as core

PILOT_MODE = os.getenv('PILOT_INVITE_MODE') == '1'
router = APIRouter(prefix='/api/pilot')
USERNAME_RE = re.compile(r'^[a-z][a-z0-9_-]{2,31}$')

class PilotAccess(Base):
    __tablename__='pilot_access'
    id=Column(Integer,primary_key=True)
    user_id=Column(Integer,ForeignKey('users.id',ondelete='CASCADE'),nullable=False,unique=True,index=True)
    username=Column(String(32),nullable=False,unique=True,index=True)
    display_name=Column(String(80),nullable=False)
    code_hash=Column(String(64),nullable=False)
    role=Column(String(12),nullable=False,default='writer')
    enabled=Column(Boolean,nullable=False,default=True)
    review_consent_at=Column(DateTime(timezone=True),nullable=True)
    created_at=Column(DateTime(timezone=True),default=now,nullable=False)

class AdminAccessLog(Base):
    __tablename__='pilot_admin_access_log'
    id=Column(Integer,primary_key=True)
    admin_user_id=Column(Integer,ForeignKey('users.id',ondelete='SET NULL'),nullable=True)
    writer_user_id=Column(Integer,ForeignKey('users.id',ondelete='CASCADE'),nullable=False,index=True)
    project_id=Column(Integer,nullable=True)
    action=Column(String(32),nullable=False)
    viewed_at=Column(DateTime(timezone=True),default=now,nullable=False)

class PilotLogin(BaseModel):
    username:str=Field(min_length=3,max_length=32)
    access_code:str=Field(min_length=32,max_length=160)
    consent:bool=False

class CreateWriter(BaseModel):
    username:str=Field(min_length=3,max_length=32)
    display_name:str=Field(min_length=2,max_length=80)

def require_mode():
    if not PILOT_MODE: raise HTTPException(404,'المسار غير متاح')

def pilot_entry(db,user):
    return db.scalar(select(PilotAccess).where(PilotAccess.user_id==user.id))

def require_admin(db,user):
    require_mode()
    entry=pilot_entry(db,user)
    if not entry or entry.role!='admin' or not entry.enabled: raise HTTPException(403,'للمدير فقط')
    return entry

def bootstrap_pilot():
    if not PILOT_MODE: return
    with SessionLocal() as db:
        if db.scalar(select(PilotAccess).where(PilotAccess.role=='admin')): return
        name=os.getenv('PILOT_ADMIN_USERNAME','pilot-admin').strip().lower()
        if not USERNAME_RE.fullmatch(name): raise RuntimeError('Invalid pilot admin username')
        code=os.getenv('PILOT_ADMIN_CODE') or secrets.token_urlsafe(36)
        if len(code)<32:raise RuntimeError('Pilot admin code too short')
        account=User(email=f'pilot-admin-{secrets.token_hex(12)}@pilot.invalid',password_hash=hash_password.hash(secrets.token_urlsafe(48)))
        db.add(account);db.flush()
        db.add(PilotAccess(user_id=account.id,username=name,display_name='إدارة الاختبار',code_hash=digest(code),role='admin',enabled=True))
        db.commit()
        if not os.getenv('PILOT_ADMIN_CODE'):
            print('PILOT_ADMIN_FIRST_RUN_ACCESS='+name+':'+code,flush=True)

@router.get('/status')
def pilot_status():
    return {'invite_mode':PILOT_MODE,'ai_ready':bool(os.getenv('OPENAI_API_KEY')) and os.getenv('PILOT_EPHEMERAL')!='1','durable_storage':core.engine.dialect.name=='postgresql','admin_review_disclosure':True}

@router.post('/login')
def login_pilot(data:PilotLogin,request:Request,response:Response,db:Session=Depends(get_db)):
    require_mode()
    username=data.username.strip().lower()
    core.throttle('pilot-login:'+request.client.host+':'+username,limit=7,window=900)
    entry=db.scalar(select(PilotAccess).where(PilotAccess.username==username)) if USERNAME_RE.fullmatch(username) else None
    if not entry or not entry.enabled or not secrets.compare_digest(entry.code_hash,digest(data.access_code)):
        raise HTTPException(401,'اسم المستخدم أو رمز الدعوة غير صحيح')
    if entry.role=='writer' and not data.consent:
        raise HTTPException(422,'يجب الموافقة على إشعار مراجعة الإدارة للأعمال التجريبية')
    if entry.role=='writer' and entry.review_consent_at is None:
        entry.review_consent_at=now();db.commit()
    result=core.login_session(db,db.get(User,entry.user_id),response)
    return {**result,'username':entry.username,'role':entry.role,'pilot':True}

@router.post('/admin/writers')
def create_writer(data:CreateWriter,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    require_admin(db,user)
    name=data.username.strip().lower()
    if not USERNAME_RE.fullmatch(name): raise HTTPException(422,'اسم المستخدم غير صالح')
    if not data.display_name.strip(): raise HTTPException(422,'الاسم المعروض فارغ')
    if db.scalar(select(PilotAccess).where(PilotAccess.username==name)):raise HTTPException(409,'اسم المستخدم محجوز')
    code=secrets.token_urlsafe(36)
    account=User(email=f'pilot-writer-{secrets.token_hex(12)}@pilot.invalid',password_hash=hash_password.hash(secrets.token_urlsafe(48)))
    db.add(account);db.flush()
    db.add(PilotAccess(user_id=account.id,username=name,display_name=data.display_name.strip(),code_hash=digest(code),role='writer',enabled=True))
    db.commit()
    return {'username':name,'access_code':code,'note':'احفظ الرمز الآن؛ لن يعرض مجددًا'}

@router.get('/admin/writers')
def list_writers(user:User=Depends(core.auth),db:Session=Depends(get_db)):
    require_admin(db,user)
    entries=db.scalars(select(PilotAccess).where(PilotAccess.role=='writer').order_by(PilotAccess.created_at.desc())).all()
    result=[]
    for e in entries:
        projects=db.scalars(select(Project).where(Project.user_id==e.user_id)).all()
        result.append({'id':e.id,'username':e.username,'display_name':e.display_name,'enabled':e.enabled,'review_consented':e.review_consent_at is not None,'project_count':len(projects),'last_updated':max((p.updated_at for p in projects),default=None).isoformat() if projects else None,'created_at':e.created_at.isoformat() if e.created_at else None})
    return result

@router.post('/admin/writers/{eid}/rotate')
def rotate(eid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    require_admin(db,user)
    entry=db.get(PilotAccess,eid)
    if not entry or entry.role!='writer':raise HTTPException(404,'الكاتب غير موجود')
    code=secrets.token_urlsafe(36)
    entry.code_hash=digest(code)
    db.execute(delete(LoginSession).where(LoginSession.user_id==entry.user_id))
    db.commit()
    return {'username':entry.username,'access_code':code}

@router.post('/admin/writers/{eid}/toggle')
def toggle(eid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    require_admin(db,user)
    entry=db.get(PilotAccess,eid)
    if not entry or entry.role!='writer':raise HTTPException(404,'الكاتب غير موجود')
    entry.enabled=not entry.enabled
    if not entry.enabled:db.execute(delete(LoginSession).where(LoginSession.user_id==entry.user_id))
    db.commit()
    return {'enabled':entry.enabled}

def author_for_review(db,eid):
    entry=db.get(PilotAccess,eid)
    if not entry or entry.role!='writer':raise HTTPException(404,'الكاتب غير موجود')
    if not entry.review_consent_at:raise HTTPException(403,'الكاتب لم يوافق على مراجعة أعماله')
    return entry

@router.get('/admin/writers/{eid}/projects')
def author_projects(eid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    require_admin(db,user)
    e=author_for_review(db,eid)
    projects=db.scalars(select(Project).where(Project.user_id==e.user_id).order_by(Project.updated_at.desc())).all()
    db.add(AdminAccessLog(admin_user_id=user.id,writer_user_id=e.user_id,action='list_projects'));db.commit()
    return [core.proj_json(p) for p in projects]

@router.get('/admin/writers/{eid}/projects/{pid}')
def inspect_project(eid:int,pid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    require_admin(db,user)
    e=author_for_review(db,eid)
    p=db.scalar(select(Project).where(Project.id==pid,Project.user_id==e.user_id))
    if not p:raise HTTPException(404,'العمل غير موجود')
    sections=db.scalars(select(Section).where(Section.project_id==p.id).order_by(Section.position,Section.id)).all()
    messages=db.scalars(select(Chat).where(Chat.project_id==p.id).order_by(Chat.id.desc()).limit(40)).all()
    db.add(AdminAccessLog(admin_user_id=user.id,writer_user_id=e.user_id,project_id=pid,action='read_project'));db.commit()
    return {'project':core.proj_json(p),'sections':[core.sec_json(s) for s in sections],'messages':[{'role':m.role,'text':m.text} for m in messages[::-1]],'read_only':True}

@router.get('/my-review-log')
def my_review_log(user:User=Depends(core.auth),db:Session=Depends(get_db)):
    require_mode()
    results=db.scalars(select(AdminAccessLog).where(AdminAccessLog.writer_user_id==user.id).order_by(AdminAccessLog.id.desc()).limit(40)).all()
    return [{'action':v.action,'project_id':v.project_id,'viewed_at':v.viewed_at.isoformat()} for v in results]
