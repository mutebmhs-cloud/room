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
from .narrative_retrieval import salient_terms, select_passage, rank_chapters

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
    """Passage retrieval across the complete chapter, with exact offsets and
    coverage disclosure. Not semantic search or complete-book analysis.
    """
    sections,synopses=sources(db,pid)
    selected=next((section for section in sections if section.id==section_id),None)
    if selected is None:
        raise HTTPException(404,'الفصل غير موجود')
    raw_selected=section_text(selected)
    search_terms=salient_terms(query or raw_selected[:1500])
    valid_summaries={}
    for section in sections:
        synopsis=synopses.get(section.id)
        if synopsis and synopsis.source_hash==fingerprint(section_text(section)):
            valid_summaries[section.id]=' '.join((synopsis.summary,
                synopsis.central_event,synopsis.character_change))
    ranked=rank_chapters(sections,section_id,query or raw_selected[:1500],valid_summaries)
    candidates=[(selected,raw_selected,True)]+[
        (section,section_text(section),False) for section,_,score in ranked if score>0][:7]
    if len(candidates)==1 and len(sections)>1:
        candidates.extend((section,section_text(section),False)
                          for section,_,_ in ranked[:2])
    blocks=[]
    remaining=max_chars
    for section,full_text,is_selected in candidates:
        if remaining<200:break
        max_window=7500 if is_selected else 1700
        span,offset=select_passage(full_text,search_terms,min(max_window,remaining))
        if not span.strip():continue
        blocks.append({'section_id':section.id,'section_title':section.title,
                       'version':section.version,'excerpt':span,
                       'excerpt_offset':offset,'truncated':len(span)<len(full_text),
                       'source_hash':fingerprint(full_text),'selected':is_selected})
        remaining-=len(span)
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

@router.get('/memory')
def narrative_memory(pid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    p=core.owned_project(db,user,pid)
    sections,synopses=sources(db,pid)
    facts=db.scalars(select(Fact).where(Fact.project_id==pid).order_by(Fact.id)).all()
    by_id={x.id:x for x in sections}
    nodes={}
    for f in facts:
        key=normalize(f.subject).strip()
        if key not in nodes:
            nodes[key]={'name':f.subject,'facts':[]}
        source=by_id.get(f.section_id)
        nodes[key]['facts'].append({'predicate':f.predicate,'value':f.value,
            'section_id':f.section_id,'evidence':f.evidence,
            'source_current':bool(source and f.source_version==source.version)
                if f.evidence else f.evidence_status=='manual',
            'status':f.evidence_status})
    timeline=[]
    for sec in sections:
        item=synopses.get(sec.id)
        current=bool(item and item.source_hash==fingerprint(section_text(sec)))
        timeline.append({'section_id':sec.id,'title':sec.title,'position':sec.position,
                         'summary':item.summary if current else '',
                         'summary_current':current})
    return {'entities':list(nodes.values()),'timeline':timeline,
            'approved_structure':core._json(p.structure,{}),
            'note':'الذاكرة تجمع ما أدخله الكاتب وما اعتمده. عدم وجود معلومة لا يثبت أنها غير موجودة في المخطوط.'}

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
    approved=core._json(p.structure,{})
    approved_excerpt=json.dumps(approved,ensure_ascii=False)[:1800]
    facts=db.scalars(select(Fact).where(Fact.project_id==pid).order_by(Fact.id).limit(25)).all()
    documented='\n'.join((f.subject+' — '+f.predicate+': '+f.value)[:220] for f in facts)
    pieces=['راجع من منظور أدبي عربي. تحقق من تناقضات عبر الشواهد المتاحة فقط؛ لا تفترض قراءة بقية العمل.',
            'قرارات المشروع المعتمدة من الكاتب: '+approved_excerpt,
            'وقائع سجلها الكاتب أو كانت موجودة سابقًا وتحتاج التحقق من المصدر: '+documented[:2600]]
    for item in context:
        pieces.append('الفصل '+item['section_title']+' [رقم '+str(item['section_id'])+', إصدار '+str(item['version'])+']:\n'+item['excerpt'])
    text='\n\n'.join(pieces)
    if len(text)>16000:raise HTTPException(413,'السياق طويل عن الحد الحالي')
    result=await generate_analysis(p.kind,'critique',text)
    created=[]
    for f in result.get('feedback',[])[:6]:
        evidence=f.get('evidence','')
        matching=[item for item in context if evidence and evidence in item['excerpt']]
        # An identical quotation in multiple chapters is ambiguous: do not assign
        # a possibly incorrect source automatically.
        if len(matching)!=1:continue
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
