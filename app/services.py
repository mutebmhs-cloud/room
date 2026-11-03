"""Service marketplace pilot: explicit owner-scoped requests and opt-in snapshots.
No payments, unverified professionals or automatic AI processing in this release.
"""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, select
from sqlalchemy.orm import Session
from .db import Base, get_db
from .models import Project, Section, User, now
from . import main as core

router = APIRouter(prefix="/api/services", tags=["services"])
CATALOG = [
 ("proofread","التدقيق اللغوي","تصحيح الأخطاء الإملائية والنحوية دون تبديل أسلوب الكاتب",["human","ai","hybrid"],["novel","short","flash","children","screenplay"]),
 ("editorial","المراجعة التحريرية","تحليل البناء والشخصيات وتقديم ملاحظات قابلة للمراجعة",["human","ai","hybrid"],["novel","short","flash","children","screenplay"]),
 ("illustration","رسوم قصص الأطفال","تجهيز موجز بصري ورسوم متسقة مع متطلبات القصة",["human","ai","hybrid"],["children"]),
 ("cover","تصميم الغلاف","تجهيز غلاف أو تصورات بصرية لكتاب",["human","ai","hybrid"],["novel","short","flash","children"]),
 ("publishing","التقديم لدار نشر","تجهيز طلب نشر وتبادل الملاحظات مع جهة توافق على المشاركة",["human"],["novel","short","flash","children"]),
 ("screenplay","مراجعة السيناريو","تحليل المشاهد وبناء ملف تقديم لمنتج",["human","ai","hybrid"],["screenplay"]),
 ("production","عرض المشروع على جهة إنتاج","تنظيم ملف السيناريو وطلب التعاون مع جهة إنتاج",["human"],["screenplay"]),
 ("formatting","تنسيق المخطوط","تجهيز ملف قابل لمراجعة الإخراج والطباعة",["human","ai","hybrid"],["novel","short","flash","children"])
]
CATALOG_MAP={v[0]:v for v in CATALOG}
STATES={"requested","in_review","in_progress","delivered","revision_requested","accepted","cancelled"}
TRANSITIONS={"requested":{"in_review","cancelled"},"in_review":{"in_progress","cancelled"},"in_progress":{"delivered","cancelled"},"delivered":{"revision_requested","accepted"},"revision_requested":{"in_progress","cancelled"},"accepted":set(),"cancelled":set()}

class ServiceRequest(Base):
    __tablename__="cultural_service_requests"
    id=Column(Integer,primary_key=True)
    owner_id=Column(Integer,ForeignKey("users.id",ondelete="CASCADE"),nullable=False,index=True)
    project_id=Column(Integer,ForeignKey("projects.id",ondelete="CASCADE"),nullable=False,index=True)
    service_key=Column(String(40),nullable=False)
    route=Column(String(12),nullable=False)
    title=Column(String(180),nullable=False)
    brief=Column(Text,nullable=False)
    shared_snapshot=Column(Text,nullable=False,default="[]")
    status=Column(String(32),nullable=False,default="requested")
    provider_id=Column(Integer,ForeignKey("users.id",ondelete="SET NULL"),nullable=True)
    ai_consent=Column(String(12),nullable=False,default="no")
    created_at=Column(DateTime(timezone=True),default=now,nullable=False)
    updated_at=Column(DateTime(timezone=True),default=now,nullable=False)

class ServiceMessage(Base):
    __tablename__="cultural_service_messages"
    id=Column(Integer,primary_key=True)
    request_id=Column(Integer,ForeignKey("cultural_service_requests.id",ondelete="CASCADE"),nullable=False,index=True)
    author_id=Column(Integer,ForeignKey("users.id",ondelete="SET NULL"),nullable=True)
    body=Column(Text,nullable=False)
    created_at=Column(DateTime(timezone=True),default=now,nullable=False)

class CreateRequest(BaseModel):
    project_id:int=Field(gt=0)
    service_key:str
    route:str
    title:str=Field(min_length=3,max_length=180)
    brief:str=Field(min_length=12,max_length=4000)
    section_ids:list[int]=Field(default_factory=list,max_length=25)
    allow_ai_processing:bool=False

class Note(BaseModel):
    body:str=Field(min_length=2,max_length=3000)
class ChangeState(BaseModel):
    status:str

def serialize(r,include_snapshot=False):
    out={"id":r.id,"project_id":r.project_id,"service_key":r.service_key,
    "route":r.route,"title":r.title,"brief":r.brief,"status":r.status,
    "shared_section_count":len(json.loads(r.shared_snapshot)),"provider_assigned":r.provider_id is not None,
    "ai_processing_authorized":r.ai_consent=="yes",
    "created_at":r.created_at.isoformat() if r.created_at else None}
    if include_snapshot:out["shared_sections"]=json.loads(r.shared_snapshot)
    return out

def owner_request(db,user,rid):
    r=db.get(ServiceRequest,rid)
    if not r or r.owner_id!=user.id:raise HTTPException(404,"الطلب غير موجود")
    return r

@router.get("/catalog")
def catalog(user:User=Depends(core.auth)):
    return [{"key":key,"name":name,"problem":problem,"routes":routes,"kinds":kinds} for key,name,problem,routes,kinds in CATALOG]

@router.get("/requests")
def requests(project_id:int|None=None,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    q=select(ServiceRequest).where(ServiceRequest.owner_id==user.id)
    if project_id is not None:
        core.owned_project(db,user,project_id)
        q=q.where(ServiceRequest.project_id==project_id)
    return [serialize(r) for r in db.scalars(q.order_by(ServiceRequest.id.desc())).all()]

@router.post("/requests")
def create_request(data:CreateRequest,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    p=core.owned_project(db,user,data.project_id)
    spec=CATALOG_MAP.get(data.service_key)
    if not spec or p.kind not in spec[4] or data.route not in spec[3]:
        raise HTTPException(422,"الخدمة أو نوع التنفيذ غير ملائم لهذا العمل")
    if data.route in ("ai","hybrid") and not data.allow_ai_processing:
        raise HTTPException(422,"يلزم الإذن المستقل قبل طلب معالجة بالذكاء الاصطناعي")
    if len(set(data.section_ids))!=len(data.section_ids):raise HTTPException(422,"المقاطع مكررة")
    selected=db.scalars(select(Section).where(Section.project_id==p.id,Section.id.in_(data.section_ids))).all() if data.section_ids else []
    if len(selected)!=len(data.section_ids):raise HTTPException(422,"مقطع غير تابع للعمل")
    snapshot=[{"section_id":s.id,"version":s.version,"title":s.title,"body":s.body,"blocks":json.loads(s.blocks)} for s in selected]
    r=ServiceRequest(owner_id=user.id,project_id=p.id,service_key=spec[0],route=data.route,
                     title=data.title.strip(),brief=data.brief.strip(),shared_snapshot=json.dumps(snapshot,ensure_ascii=False),
                     ai_consent="yes" if data.allow_ai_processing and data.route in ("ai","hybrid") else "no")
    db.add(r);db.commit();db.refresh(r)
    return serialize(r)

@router.get("/requests/{rid}")
def get_request(rid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    r=owner_request(db,user,rid)
    return {**serialize(r,True),"messages":[{"id":n.id,"body":n.body,"created_at":n.created_at.isoformat()} for n in db.scalars(select(ServiceMessage).where(ServiceMessage.request_id==rid).order_by(ServiceMessage.id)).all()],
        "execution_state":"not_connected","notice":"لا يُرسل المخطوط إلى أي جهة أو نموذج خارجي في هذه النسخة"}

@router.post("/requests/{rid}/messages")
def add_message(rid:int,data:Note,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    r=owner_request(db,user,rid)
    if r.status in ("cancelled","accepted"):raise HTTPException(409,"الطلب مغلق")
    n=ServiceMessage(request_id=rid,author_id=user.id,body=data.body.strip())
    db.add(n);db.commit();return {"id":n.id,"body":n.body}

@router.post("/requests/{rid}/state")
def change_state(rid:int,data:ChangeState,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    r=owner_request(db,user,rid)
    # Only cancellation and acceptance are user transitions; internal statuses need a verified provider workflow.
    if data.status not in ("cancelled","accepted") or data.status not in TRANSITIONS[r.status]:
        raise HTTPException(409,"هذا الانتقال غير مسموح للمستخدم في التجربة")
    r.status=data.status;r.updated_at=now();db.commit()
    return serialize(r)
