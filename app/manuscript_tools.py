"""Author-controlled manuscript search and pinned milestone snapshots.

Pinned snapshots are separate from the rolling last-three ordinary revisions.
No model calls; project authorization and optimistic locking are mandatory.
"""
import re
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, select, update, delete
from sqlalchemy.orm import Session
from .db import Base, get_db
from .models import User, Section, Project, Revision, now
from . import main as core

router=APIRouter(prefix='/api/projects/{pid}/manuscript-tools',tags=['manuscript-tools'])

class WriterMilestone(Base):
    __tablename__='writer_milestone_snapshots'
    id=Column(Integer,primary_key=True)
    project_id=Column(Integer,ForeignKey('projects.id',ondelete='CASCADE'),nullable=False,index=True)
    section_id=Column(Integer,ForeignKey('sections.id',ondelete='CASCADE'),nullable=False,index=True)
    version=Column(Integer,nullable=False)
    label=Column(String(120),nullable=False)
    title=Column(String(240),nullable=False)
    body=Column(Text,nullable=False)
    blocks=Column(Text,nullable=False)
    created_at=Column(DateTime(timezone=True),default=now,nullable=False)

class PinRequest(BaseModel):
    section_id:int=Field(gt=0)
    section_version:int=Field(ge=1)
    label:str=Field(min_length=2,max_length=120)

class RestoreRequest(BaseModel):
    current_version:int=Field(ge=1)

def brief(x):
    return {'id':x.id,'section_id':x.section_id,'version':x.version,'label':x.label,
            'title':x.title,'created_at':x.created_at.isoformat() if x.created_at else None}

@router.get('/search')
def search_manuscript(pid:int,q:str,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    core.owned_project(db,user,pid)
    needle=q.strip()
    if len(needle)<2 or len(needle)>120:
        raise HTTPException(422,'عبارة البحث يجب أن تتكون من حرفين إلى 120 حرفًا')
    pattern=re.compile(re.escape(needle),re.IGNORECASE)
    sections=db.scalars(select(Section).where(Section.project_id==pid)
                        .order_by(Section.position,Section.id)).all()
    found=[];total=0
    for sec in sections:
        raw=sec.body+'\n'+'\n'.join(str(b.get('text','')) for b in core._json(sec.blocks,[]))
        hits=list(pattern.finditer(raw))
        total+=len(hits)
        for hit in hits[:10]:
            start=max(0,hit.start()-60);end=min(len(raw),hit.end()+65)
            if len(found)>=120:break
            found.append({'section_id':sec.id,'title':sec.title,'version':sec.version,
                          'offset':hit.start(),'excerpt':raw[start:end],
                          'excerpt_offset':start})
    return {'query':needle,'hits':found,'total_matched':total,
            'results_truncated':total>len(found),
            'scope':'all_current_sections',
            'note':'البحث الحرفي داخل المخطوط الحالي فقط؛ لا يقارن كتبًا خارجية.'}

@router.get('/milestones')
def list_milestones(pid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    core.owned_project(db,user,pid)
    items=db.scalars(select(WriterMilestone).where(WriterMilestone.project_id==pid)
                     .order_by(WriterMilestone.id.desc())).all()
    return [brief(row) for row in items]

@router.post('/milestones')
def pin_milestone(pid:int,data:PinRequest,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    section=core.owned_section(db,user,pid,data.section_id)
    if section.version!=data.section_version:
        raise HTTPException(409,'تغير الفصل؛ افتحه مجددًا قبل تثبيت نسخته')
    if not data.label.strip():
        raise HTTPException(422,'أدخل اسمًا واضحًا للنسخة المرجعية')
    existing=db.scalars(select(WriterMilestone).where(
        WriterMilestone.project_id==pid)).all()
    if len(existing)>=20:
        raise HTTPException(422,'بلغت عشرين نسخة مرجعية، احذف غير اللازمة قبل إضافة أخرى')
    existing_bytes=sum(len(x.body.encode('utf8'))+len(x.blocks.encode('utf8')) for x in existing)
    incoming=len(section.body.encode('utf8'))+len(section.blocks.encode('utf8'))
    if existing_bytes+incoming>8_000_000:
        raise HTTPException(413,'تجاوزت النسخ المرجعية السعة التجريبية؛ احفظ نسخة خارجية قبل المتابعة')
    record=WriterMilestone(project_id=pid,section_id=section.id,version=section.version,
        label=data.label.strip(),title=section.title,body=section.body,blocks=section.blocks)
    db.add(record);db.commit();db.refresh(record)
    return brief(record)

@router.post('/milestones/{mid}/restore')
def restore_milestone(pid:int,mid:int,data:RestoreRequest,
                      user:User=Depends(core.auth),db:Session=Depends(get_db)):
    core.owned_project(db,user,pid)
    row=db.scalar(select(WriterMilestone).where(
        WriterMilestone.id==mid,WriterMilestone.project_id==pid))
    if row is None:raise HTTPException(404,'النسخة المرجعية غير موجودة')
    current=core.owned_section(db,user,pid,row.section_id)
    if current.version!=data.current_version:
        raise HTTPException(409,'تغير الفصل؛ لا يجوز استعادة نسخة فوق تعديل أحدث')
    snapshot=Revision(section_id=current.id,version=current.version,title=current.title,
        body=current.body,blocks=current.blocks)
    changed=db.execute(update(Section).where(Section.id==current.id,
        Section.project_id==pid,Section.version==data.current_version).values(
        title=row.title,body=row.body,blocks=row.blocks,
        version=Section.version+1,updated_at=now()))
    if changed.rowcount!=1:
        db.rollback();raise HTTPException(409,'تعارض أثناء الاستعادة')
    db.add(snapshot);db.flush()
    recent=select(Revision.id).where(Revision.section_id==current.id).order_by(
        Revision.version.desc()).limit(3)
    db.execute(delete(Revision).where(
        Revision.section_id==current.id,Revision.id.not_in(recent)))
    db.commit()
    return core.sec_json(db.get(Section,current.id))

@router.delete('/milestones/{mid}')
def delete_milestone(pid:int,mid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    core.owned_project(db,user,pid)
    row=db.scalar(select(WriterMilestone).where(
        WriterMilestone.id==mid,WriterMilestone.project_id==pid))
    if row is None:raise HTTPException(404,'النسخة المرجعية غير موجودة')
    db.delete(row);db.commit()
    return {'ok':True}
