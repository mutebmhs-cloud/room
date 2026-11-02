"""Objective author progress journal. Self-assessments are opinions, not quality scores."""
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import Column,Integer,String,Text,ForeignKey,DateTime,select,func
from sqlalchemy.orm import Session
from .db import Base,get_db
from .models import User,Project,Section,now
from . import main as core
from .genre_catalog import GENRES,catalog
router=APIRouter(prefix="/api/writer-growth",tags=["writer-growth"])
class GrowthEntry(Base):
 __tablename__="writer_growth_entries"
 id=Column(Integer,primary_key=True)
 project_id=Column(Integer,ForeignKey("projects.id",ondelete="CASCADE"),nullable=False,index=True)
 user_id=Column(Integer,ForeignKey("users.id",ondelete="CASCADE"),nullable=False)
 dimension=Column(String(40),nullable=False)
 stage=Column(String(40),nullable=False)
 confidence=Column(Integer,nullable=False)
 observation=Column(Text,nullable=False)
 next_action=Column(Text,nullable=False)
 created_at=Column(DateTime(timezone=True),default=now,nullable=False)
class Entry(BaseModel):
 dimension:str
 stage:str
 confidence:int=Field(ge=1,le=5)
 observation:str=Field(min_length=5,max_length=1500)
 next_action:str=Field(min_length=5,max_length=1000)
@router.get("/genres")
def genres(user:User=Depends(core.auth)):return catalog()
@router.get("/projects/{pid}")
def progress(pid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
 p=core.owned_project(db,user,pid)
 sec=db.scalars(select(Section).where(Section.project_id==pid)).all()
 items=db.scalars(select(GrowthEntry).where(GrowthEntry.project_id==pid,GrowthEntry.user_id==user.id).order_by(GrowthEntry.id)).all()
 return {"genre":catalog(p.kind)[0],"section_count":len(sec),
   "word_count":sum(len((s.body or " ".join(x.get("text","") for x in core._json(s.blocks,[]))).split()) for s in sec),
   "checkins":[{"id":x.id,"dimension":x.dimension,"stage":x.stage,"confidence":x.confidence,
     "observation":x.observation,"next_action":x.next_action,"created_at":x.created_at.isoformat()} for x in items],
   "disclaimer":"الثقة تقييم ذاتي لا تقيس جودة المخطوط، وعدد الكلمات مؤشر إنجاز لا جودة"}
@router.post("/projects/{pid}/checkins")
def checkin(pid:int,data:Entry,user:User=Depends(core.auth),db:Session=Depends(get_db)):
 p=core.owned_project(db,user,pid);spec=GENRES[p.kind]
 if data.dimension not in [x[0] for x in spec["dimensions"]] or data.stage not in [x[0] for x in spec["stages"]]:raise HTTPException(422,"هذا المعيار أو المرحلة غير صالح لنوع الكتابة")
 x=GrowthEntry(project_id=pid,user_id=user.id,dimension=data.dimension,stage=data.stage,confidence=data.confidence,observation=data.observation.strip(),next_action=data.next_action.strip())
 db.add(x);db.commit()
 return {"id":x.id,"message":"سُجلت المراجعة الذاتية، لا تمثل حكمًا آليًا على الجودة"}
