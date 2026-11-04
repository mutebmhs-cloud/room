"""Arabic literary core: grounded cross-chapter context, review workflow and source lookup.

No unlicensed full-text library, no automatic disclosure of manuscripts, and no
unattested claims of literary quality. All project endpoints require auth.
"""
from datetime import datetime
import hashlib
import json
import re
import unicodedata
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, select
from sqlalchemy.orm import Session
from .db import Base, get_db
from .models import User, Project, Section, Fact, now
from . import main as core
from .writer_intelligence import SectionSynopsis, section_text, generate_analysis, fingerprint

router=APIRouter(prefix='/api/projects/{pid}/literary',tags=['literary-core'])
ARABIC_TATWEEL='ـ'
ARABIC_DIACRITICS=re.compile('[\u064b-\u065f\u0670]')
WORD_RE=re.compile(r'[\w\u0600-\u06ff]+',re.UNICODE)
STOP={'الذي','التي','على','كان','كانت','هذا','هذه','ذلك','تلك','عند','بعد','قبل','الى','إلى','من','في','عن','هو','هي','كما','مع','أو','ثم','لقد','لكن','وقد','حتى','ليس','هناك','بعض','بين','وهو'}

class LiteraryFinding(Base):
    __tablename__='literary_findings'
    id=Column(Integer,primary_key=True)
    project_id=Column(Integer,ForeignKey('projects.id',ondelete='CASCADE'),nullable=False,index=True)
    section_id=Column(Integer,ForeignKey('sections.id',ondelete='CASCADE'),nullable=False)
    source_version=Column(Integer,nullable=False)
    source_hash=Column(String(64),nullable=False)
    observation=Column(Text,nullable=False)
    evidence=Column(Text,nullable=False)
    impact=Column(Text,nullable=False)
    action=Column(Text,nullable=False)
    category=Column(String(32),nullable=False,default='needs_review')
    state=Column(String(20),nullable=False,default='open')
    created_at=Column(DateTime(timezone=True),default=now,nullable=False)
    updated_at=Column(DateTime(timezone=True),default=now,nullable=False)

class ReviewRequest(BaseModel):
    section_id:int=Field(gt=0)
    allow_ai_processing:bool=False

class FindingUpdate(BaseModel):
    state:str=Field(pattern='^(open|discussed|accepted|dismissed|resolved)$')

class ResearchRequest(BaseModel):
    query:str=Field(min_length=3,max_length=180)
    consent_external_lookup:bool=False

def normalize(s):
    s=unicodedata.normalize('NFKC',str(s or '')).replace(ARABIC_TATWEEL,'')
    s=ARABIC_DIACRITICS.sub('',s)
    return s.casefold()

def keywords(s):
    return {x for x in WORD_RE.findall(normalize(s)) if len(x)>=3 and x not in STOP}

def sources(db,pid):
    sections=db.scalars(select(Section).where(Section.project_id==pid).order_by(Section.position,Section.id)).all()
    synopses={v.section_id:v for v in db.scalars(select(SectionSynopsis).where(SectionSynopsis.project_id==pid))}
    return sections,synopses

def contextual_sources(db,pid,section_id,query='',max_chars=11500):
    """Context is exact, cited text. It is NOT a fully semantic retrieval engine."""
    sections,synopses=sources(db,pid)
    selected=next((s for s in sections if s.id==section_id),None)
    if selected is None:raise HTTPException(404,'الفصل غير موجود')
    search=keywords(query or section_text(selected)[:500])
    scored=[]
    for s in sections:
        if s.id==section_id:continue
        original=section_text(s)
        synopsis=synopses.get(s.id)
        auxiliary=(synopsis.summary+' '+synopsis.central_event+' '+synopsis.character_change) if synopsis and synopsis.source_hash==fingerprint(original) else ''
        terms=keywords(s.title+' '+original[:2500]+' '+auxiliary)
        score=len(search&terms)
        scored.append((score,s.position,s,original,auxiliary))
    scored.sort(key=lambda x:(-x[0],x[1]))
    selected_text=section_text(selected)
    blocks=[]
    budget=max_chars
    # Always include current text first, never silently claim to have read omitted text.
    for s,raw in [(selected,selected_text)]+[(x[2],x[3]) for x in scored if x[0]>0][:7]:
        if budget<200:break
        cap=7500 if s.id==selected.id else 1500
        portion=raw[:min(cap,budget)]
        blocks.append({'section_id':s.id,'section_title':s.title,'version':s.version,
                       'excerpt':portion,'excerpt_offset':0,'truncated':len(portion)<len(raw),
                       'source_hash':fingerprint(raw),'selected':s.id==selected.id})
        budget-=len(portion)
    if len(blocks)==1 and len(sections)>1:
        for score,position,s,raw,_ in scored[:2]:
            if budget<200:break
            portion=raw[:min(900,budget)]
            blocks.append({'section_id':s.id,'section_title':s.title,'version':s.version,
                           'excerpt':portion,'excerpt_offset':0,'truncated':len(portion)<len(raw),
                           'source_hash':fingerprint(raw),'selected':False})
            budget-=len(portion)
    return blocks,len(sections)

def finding_json(row,current_version=None,current_hash=None):
    return {'id':row.id,'section_id':row.section_id,'source_version':row.source_version,
            'observation':row.observation,'evidence':row.evidence,'impact':row.impact,
            'action':row.action,'category':row.category,'state':row.state,
            'stale':bool(current_version is not None and
                (current_version!=row.source_version or current_hash!=row.source_hash))}

@router.get('/context')
def get_context(pid:int,section_id:int,query:str='',user:User=Depends(core.auth),db:Session=Depends(get_db)):
    core.owned_section(db,user,pid,section_id)
    if len(query)>600:raise HTTPException(422,'السؤال أطول من الحد')
    blocks,total=contextual_sources(db,pid,section_id,query)
    return {'sections':blocks,'total_sections':total,'retrieved_sections':len(blocks),
            'coverage':'partial','warning':'الاسترجاع محدود وليس فحصًا شاملًا لجميع الرواية'}

@router.get('/findings')
def findings(pid:int,section_id:int|None=None,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    core.owned_project(db,user,pid)
    sections,_=sources(db,pid)
    current={s.id:(s.version,fingerprint(section_text(s))) for s in sections}
    stmt=select(LiteraryFinding).where(LiteraryFinding.project_id==pid)
    if section_id is not None:
        core.owned_section(db,user,pid,section_id)
        stmt=stmt.where(LiteraryFinding.section_id==section_id)
    rows=db.scalars(stmt.order_by(LiteraryFinding.id.desc()).limit(100)).all()
    return [finding_json(r,*(current.get(r.section_id) or (None,None))) for r in rows]

@router.post('/review')
async def review(pid:int,data:ReviewRequest,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    if not data.allow_ai_processing:
        raise HTTPException(422,'يجب الموافقة على إرسال النصوص ذات الصلة إلى مزود التحليل')
    p=core.owned_project(db,user,pid)
    sec=core.owned_section(db,user,pid,data.section_id)
    core.throttle('literary-review:'+str(user.id),limit=8,window=3600)
    context,total=contextual_sources(db,pid,sec.id)
    # Only exact retrieved excerpts are provided. Do not claim full-manuscript review.
    pieces=['راجع من منظور أدبي عربي. تحقق من تناقضات عبر الشواهد المتاحة فقط؛ لا تفترض قراءة بقية العمل.']
    for item in context:
        pieces.append('الفصل '+item['section_title']+' [رقم '+str(item['section_id'])+', إصدار '+str(item['version'])+']:\n'+item['excerpt'])
    text='\n\n'.join(pieces)
    if len(text)>16000:raise HTTPException(413,'السياق طويل عن الحد الحالي')
    result=await generate_analysis(p.kind,'critique',text)
    created=[]
    for f in result.get('feedback',[])[:6]:
        evidence=f.get('evidence','')
        matching=[item for item in context if evidence and evidence in item['excerpt']]
        if not matching:continue
        source=matching[0]
        s=core.owned_section(db,user,pid,source['section_id'])
        current=section_text(s)
        if s.version!=source['version'] or fingerprint(current)!=source['source_hash']:
            raise HTTPException(409,'تغير نص أحد الفصول أثناء المراجعة، أعد المحاولة')
        obs=f.get('observation','').strip()
        if not obs:continue
        duplicate=db.scalar(select(LiteraryFinding).where(
            LiteraryFinding.project_id==pid,LiteraryFinding.section_id==s.id,
            LiteraryFinding.source_hash==source['source_hash'],
            LiteraryFinding.observation==obs))
        if duplicate:created.append(duplicate);continue
        row=LiteraryFinding(project_id=pid,section_id=s.id,source_version=s.version,
                           source_hash=source['source_hash'],observation=obs[:1200],
                           evidence=evidence[:650],impact=f.get('impact','')[:1200],
                           action=f.get('action','')[:1200],category='needs_review')
        db.add(row);created.append(row)
    db.commit()
    return {'findings':[finding_json(r) for r in created],
            'coverage':'partial','sections_examined':len(context),'total_sections':total,
            'warning':'هذه ملاحظات مرشحة لا أحكامًا نهائية؛ لم تُفحص الرواية كلها بالضرورة'}

@router.put('/findings/{fid}')
def update_finding(pid:int,fid:int,data:FindingUpdate,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    core.owned_project(db,user,pid)
    row=db.scalar(select(LiteraryFinding).where(
        LiteraryFinding.id==fid,LiteraryFinding.project_id==pid))
    if row is None:raise HTTPException(404,'الملاحظة غير موجودة')
    sec=db.get(Section,row.section_id)
    if data.state=='resolved' and sec and sec.version==row.source_version:
        raise HTTPException(409,'لم يتغير الفصل منذ اكتشاف الملاحظة؛ راجع المعالجة قبل إغلاقها')
    row.state=data.state;row.updated_at=now();db.commit()
    return finding_json(row,sec.version if sec else None,
                        fingerprint(section_text(sec)) if sec else None)

@router.post('/research')
async def research(pid:int,data:ResearchRequest,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    core.owned_project(db,user,pid)
    if not data.consent_external_lookup:
        raise HTTPException(422,'يجب الموافقة على إرسال عبارة البحث المحددة إلى فهرس خارجي')
    core.throttle('book-lookup:'+str(user.id),limit=8,window=3600)
    # The query is explicitly supplied by the writer; NEVER send the manuscript.
    try:
        async with httpx.AsyncClient(timeout=12,follow_redirects=False) as client:
            r=await client.get('https://openlibrary.org/search.json',
                               params={'q':data.query,'limit':8,'fields':'key,title,author_name,first_publish_year,edition_key'})
        if r.status_code!=200:raise HTTPException(502,'فهرس الكتب غير متاح الآن')
        results=[]
        for row in r.json().get('docs',[])[:8]:
            key=row.get('key','')
            if not isinstance(key,str) or not re.fullmatch(r'/works/OL[0-9]+W',key):
                continue
            authors=row.get('author_name') or []
            results.append({'title':str(row.get('title',''))[:240],
                            'authors':[str(x)[:120] for x in authors[:3]],
                            'first_publish_year':row.get('first_publish_year'),
                            'source':'Open Library','url':'https://openlibrary.org'+key,
                            'comparison_scope':'بيانات فهرسية فقط؛ لم تتم مقارنة النص الكامل'})
        return {'query':data.query,'results':results,'coverage':'catalog_metadata_only',
                'warning':'عدم العثور على نتائج لا يثبت أصالة الفكرة أو غياب أعمال مشابهة'}
    except HTTPException:raise
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        raise HTTPException(502,'تعذر التحقق من نتائج البحث الخارجي')
