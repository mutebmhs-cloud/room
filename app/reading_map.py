"""Privacy-preserving reading dashboard for Arabic manuscript drafts.

All measures are deterministic textual observations. Neither artistic judgments
nor verified character identities are inferred; no network or model is called.
"""
from collections import Counter
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_db
from .models import User, Section, Fact
from . import main as core
from .writer_intelligence import section_text
from .narrative_retrieval import terms

router=APIRouter(prefix="/api/projects/{pid}/reading-map",tags=["reading-map"])

TIME_CUES=re.compile(r"(?:\b(?:صباحًا|مساءً|ليلًا|ظهرًا|فجرًا|أمس|غدًا|اليوم|البارحة|لاحقًا|سابقًا|بعد|قبل|عندما|حين|خلال|منذ|ثم|أخيرًا)\b|(?:\bفي\b\s+(?:الصباح|المساء|الليل|الظهر|الفجر)))",re.UNICODE)

def word_count(value):
    return len(re.findall(r"[^\W_]+",value,flags=re.UNICODE))

def cue_samples(text,max_cues=8):
    results=[]
    for hit in TIME_CUES.finditer(text):
        if len(results)>=max_cues:break
        offset=hit.start()
        results.append({
            "quote":text[max(0,offset-55):min(len(text),hit.end()+85)],
            "offset":offset,"cue":hit.group(0)
        })
    return results

def mention_occurrences(text,term,max_offsets=5):
    # Exact non-subword character matches only, never guessed identities.
    if not term or len(term)<2 or len(term)>120:return []
    pattern=re.compile(r"(?<![\w])"+re.escape(term)+r"(?![\w])",re.UNICODE|re.IGNORECASE)
    return [m.start() for i,m in enumerate(pattern.finditer(text)) if i<max_offsets]

def manuscript_map(sections,facts):
    timeline=[]
    all_text=[]
    for section in sections:
        raw=section_text(section)
        all_text.append(raw)
        paragraphs=[x for x in raw.splitlines() if x.strip()]
        timeline.append({"section_id":section.id,"title":section.title,
            "version":section.version,"characters":len(raw),
            "words":word_count(raw),
            "paragraphs":len(paragraphs),
            "dialogue_lines":sum(1 for part in paragraphs if part.lstrip().startswith(("«","\"","–","—","-"))),
            "time_cues":cue_samples(raw)})
    unique={}
    for fact in facts:
        key=fact.subject.strip()
        if key and key not in unique and len(key)<=120 and len(unique)<50:
            unique[key]=fact.subject.strip()
    mentions=[]
    for name in unique.values():
        found=[]
        for section,raw in zip(sections,all_text):
            offsets=mention_occurrences(raw,name)
            if offsets:
                found.append({"section_id":section.id,"title":section.title,
                    "offsets":offsets,"at_least":len(offsets)})
        if found:mentions.append({"subject":name,"chapters":found})
    return {
        "scope":"current_owned_manuscript",
        "method":"deterministic_text_inspection",
        "chapters":timeline,
        "total_words":sum(x["words"] for x in timeline),
        "total_characters":sum(x["characters"] for x in timeline),
        "documented_subject_mentions":mentions,
        "limitations":[
            "عدد الكلمات والمؤشرات وصفية وليست تقييمًا للجودة الأدبية.",
            "ذكر الاسم ليس دليلًا على حضور الشخصية فعليًا أو معرفة الراوي بها.",
            "الإشارات الزمنية مقتطفات أولية للمراجعة وليست تسلسلًا زمنيًا مُثبتًا.",
            "الأسماء المعروضة مأخوذة من سجل الوقائع الذي أدخله الكاتب؛ لا نكتشف هويات جديدة آليًا."
        ]
    }

@router.get("")
def reading_map(pid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    core.owned_project(db,user,pid)
    sections=db.scalars(select(Section).where(Section.project_id==pid)
                        .order_by(Section.position,Section.id)).all()
    facts=db.scalars(select(Fact).where(Fact.project_id==pid)
                    .order_by(Fact.id)).all()
    return manuscript_map(sections,facts)
