"""Opt-in pilot partner collaboration. Profiles are self-declared and never verified."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint, select
from sqlalchemy.orm import Session
from .db import Base, get_db
from .models import User
from . import main as core
from .services import ServiceRequest, ServiceMessage, CATALOG_MAP, serialize

router=APIRouter(prefix="/api/partners",tags=["partners"])
class ProviderProfile(Base):
    __tablename__="cultural_provider_profiles"
    user_id=Column(Integer,ForeignKey("users.id",ondelete="CASCADE"),primary_key=True)
    display_name=Column(String(100),nullable=False)
    bio=Column(Text,nullable=False)
    specialties=Column(Text,nullable=False)
    verified=Column(String(10),nullable=False,default="no")

class ServiceInvitation(Base):
    __tablename__="cultural_service_invitations"
    id=Column(Integer,primary_key=True)
    request_id=Column(Integer,ForeignKey("cultural_service_requests.id",ondelete="CASCADE"),nullable=False,index=True)
    provider_id=Column(Integer,ForeignKey("users.id",ondelete="CASCADE"),nullable=False,index=True)
    status=Column(String(12),nullable=False,default="pending")
    __table_args__=(UniqueConstraint("request_id","provider_id",name="uq_service_provider_invite"),)

class ProfileData(BaseModel):
    display_name:str=Field(min_length=2,max_length=100)
    bio:str=Field(min_length=12,max_length=1200)
    specialties:list[str]=Field(min_length=1,max_length=8)

class InviteData(BaseModel):
    provider_id:int=Field(gt=0)

class InvitationDecision(BaseModel):
    decision:str

class PartnerNote(BaseModel):
    body:str=Field(min_length=2,max_length=3000)

def profile_json(p):
    return {"user_id":p.user_id,"display_name":p.display_name,"bio":p.bio,
      "specialties":__import__("json").loads(p.specialties),"verified":False}

@router.post("/profile")
def upsert_profile(data:ProfileData,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    kinds=set(CATALOG_MAP)
    if any(x not in kinds for x in data.specialties) or len(set(data.specialties))!=len(data.specialties):
        raise HTTPException(422,"تخصصات غير معروفة أو مكررة")
    import json
    p=db.get(ProviderProfile,user.id)
    if not p:
        p=ProviderProfile(user_id=user.id,display_name=data.display_name.strip(),bio=data.bio.strip(),specialties=json.dumps(data.specialties),verified="no")
        db.add(p)
    else:
        p.display_name=data.display_name.strip();p.bio=data.bio.strip();p.specialties=json.dumps(data.specialties)
    db.commit();return profile_json(p)

@router.get("/directory")
def directory(service_key:str|None=None,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    if service_key and service_key not in CATALOG_MAP:raise HTTPException(422,"خدمة غير معروفة")
    q=select(ProviderProfile).where(ProviderProfile.user_id!=user.id).order_by(ProviderProfile.user_id.desc()).limit(100)
    rows=[profile_json(p) for p in db.scalars(q)]
    return [p for p in rows if not service_key or service_key in p["specialties"]]

@router.post("/requests/{rid}/invite")
def invite(rid:int,data:InviteData,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    r=core.owned_project(db,user,db.get(ServiceRequest,rid).project_id) if db.get(ServiceRequest,rid) and db.get(ServiceRequest,rid).owner_id==user.id else None
    if r is None:raise HTTPException(404,"الطلب غير موجود")
    job=db.get(ServiceRequest,rid)
    if job.route not in ("human","hybrid") or job.status in ("cancelled","accepted"):
        raise HTTPException(409,"الطلب لا يدعم دعوة متخصص")
    provider=db.get(ProviderProfile,data.provider_id)
    if not provider or job.service_key not in __import__("json").loads(provider.specialties) or data.provider_id==user.id:
        raise HTTPException(422,"مقدم الخدمة غير متاح لهذا التخصص")
    existing=db.scalar(select(ServiceInvitation).where(ServiceInvitation.request_id==rid,ServiceInvitation.provider_id==data.provider_id))
    if existing:raise HTTPException(409,"سبق إرسال الدعوة")
    link=ServiceInvitation(request_id=rid,provider_id=data.provider_id,status="pending")
    db.add(link);db.commit();return {"invitation_id":link.id,"status":link.status}

@router.get("/invitations")
def invitations(user:User=Depends(core.auth),db:Session=Depends(get_db)):
    rows=db.scalars(select(ServiceInvitation).where(ServiceInvitation.provider_id==user.id).order_by(ServiceInvitation.id.desc())).all()
    result=[]
    for invitation in rows:
        r=db.get(ServiceRequest,invitation.request_id)
        if r:
            result.append({"id":invitation.id,"status":invitation.status,"request_id":r.id,
             "title":r.title,"service_key":r.service_key,"brief":r.brief if invitation.status=="accepted" else None})
    return result

@router.post("/invitations/{iid}/decision")
def decision(iid:int,data:InvitationDecision,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    inv=db.get(ServiceInvitation,iid)
    if not inv or inv.provider_id!=user.id:raise HTTPException(404,"الدعوة غير موجودة")
    if inv.status!="pending" or data.decision not in ("accepted","declined"):
        raise HTTPException(409,"القرار غير متاح")
    inv.status=data.decision;db.commit();return {"status":inv.status}

@router.get("/work/{rid}")
def provider_work(rid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    inv=db.scalar(select(ServiceInvitation).where(ServiceInvitation.request_id==rid,ServiceInvitation.provider_id==user.id,ServiceInvitation.status=="accepted"))
    if not inv:raise HTTPException(404,"لا يوجد تفويض لهذا الطلب")
    r=db.get(ServiceRequest,rid)
    if not r or r.status in ("cancelled","accepted"):raise HTTPException(404,"الطلب مغلق")
    import json
    messages=db.scalars(select(ServiceMessage).where(ServiceMessage.request_id==rid).order_by(ServiceMessage.id)).all()
    return {**serialize(r,True),"messages":[{"body":m.body,"author_id":m.author_id} for m in messages],
      "notice":"اطلاع محدود على النسخ المختارة في الدعوة فقط. ليست إذنًا باستخدامها خارج هذا الطلب."}

@router.post("/work/{rid}/messages")
def provider_note(rid:int,data:PartnerNote,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    inv=db.scalar(select(ServiceInvitation).where(ServiceInvitation.request_id==rid,ServiceInvitation.provider_id==user.id,ServiceInvitation.status=="accepted"))
    if not inv:raise HTTPException(404,"لا يوجد تفويض")
    r=db.get(ServiceRequest,rid)
    if not r or r.status in ("accepted","cancelled"):raise HTTPException(409,"الطلب مغلق")
    n=ServiceMessage(request_id=rid,author_id=user.id,body=data.body.strip())
    db.add(n);db.commit();return {"id":n.id,"body":n.body}
