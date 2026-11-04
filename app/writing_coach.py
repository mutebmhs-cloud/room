"""Author-controlled Arabic literary coaching and longitudinal practice.

These measurements are SELF-REPORTED and must not be presented as verified
literary improvement. No generation or rewriting of the author's manuscript.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, select
from sqlalchemy.orm import Session
from .db import Base, get_db
from .models import User, Project, now
from . import main as core

router=APIRouter(prefix='/api/projects/{pid}/coach',tags=['literary-coach'])

PRACTICES={
    'character_motive':{
        'title':'اختبار دافع الشخصية',
        'skill':'الشخصيات والدوافع',
        'instructions':'اختر قرارًا حاسمًا لشخصية، وحدد ماذا تريد ولماذا، وما الذي تخشى خسارته. ابحث في النص عن فعل يكشف هذا الدافع دون شرحه المباشر.',
        'assessment':'هل يستطيع قارئ النص تفسير القرار من الأحداث التي سبقتْه، مع إمكان اختلاف القراء في التأويل؟',
        'kinds':('novel','short','flash','children','screenplay')
    },
    'causal_chain':{
        'title':'ترابط السبب والنتيجة',
        'skill':'البناء السردي',
        'instructions':'اختر حدثين متتابعين. حدّد الفعل الذي تسبب في انتقال القصة من الأول إلى الثاني، وابحث عن أي انتقال يحتاج تمهيدًا إضافيًا.',
        'assessment':'هل توجد علاقة سببية مفهومة أم مجرد تتابع زمني مقصود؟',
        'kinds':('novel','short','flash','children','screenplay')
    },
    'point_of_view':{
        'title':'حدود معرفة الراوي',
        'skill':'التبئير والمنظور',
        'instructions':'راجع مشهدًا واحدًا، وحدد ما يعرفه الراوي وما يعرفه كل شخص، ثم راجع جملة قد تكشف معلومة لا يملك مصدرها.',
        'assessment':'هل يظل التبئير متسقًا مع اختيار الكاتب، بما في ذلك الراوي غير الموثوق؟',
        'kinds':('novel','short','flash','children')
    },
    'dialogue_subtext':{
        'title':'وظيفة الحوار وما وراءه',
        'skill':'الحوار',
        'instructions':'اختر محادثة من عملك، وحدد ما تريده كل شخصية وما تتجنب قوله صراحة، ثم افحص ضرورة كل تبادل.',
        'assessment':'هل يتغير الموقف الدرامي خلال الحوار؟',
        'kinds':('novel','short','children','screenplay')
    },
    'short_story_focus':{
        'title':'وحدة أثر القصة القصيرة',
        'skill':'التكثيف ووحدة الأثر',
        'instructions':'حدد التحول المركزي في القصة، ثم راجع مشهدًا: ماذا يضيف إلى هذا التحول أو يعقّده؟',
        'assessment':'هل يخدم المشهد التجربة المقصودة دون فرض قالب سردي واحد؟',
        'kinds':('short','flash')
    },
    'screen_action':{
        'title':'الفعل المرئي في المشهد',
        'skill':'السيناريو والفعل',
        'instructions':'اختر وصفًا داخليًا في مشهد واكتب لنفسك ما يمكن للمشاهد ملاحظته فعلًا. حافظ على التأليف بيدك.',
        'assessment':'هل يستطيع فريق التصوير فهم الفعل المقصود دون تفسير ذهني غير مرئي؟',
        'kinds':('screenplay',)
    },
    'child_audience':{
        'title':'ملاءمة عمر القارئ',
        'skill':'قصة الطفل',
        'instructions':'حدد العمر المقصود وقارئًا تجريبيًا مناسبًا، ثم راجع وضوح موقف واحد ومستوى المفردات والخبرة المفترضة.',
        'assessment':'هل تحتاج النتيجة إلى اختبار قراءة مع جمهور العمر المقصود؟',
        'kinds':('children',)
    }
}
class PracticeEntry(Base):
    __tablename__='writer_coaching_practice'
    id=Column(Integer,primary_key=True)
    project_id=Column(Integer,ForeignKey('projects.id',ondelete='CASCADE'),nullable=False,index=True)
    practice_code=Column(String(40),nullable=False)
    skill=Column(String(120),nullable=False)
    state=Column(String(20),nullable=False,default='in_progress')
    before_rating=Column(Integer)
    after_rating=Column(Integer)
    author_notes=Column(Text,nullable=False,default='')
    author_reflection=Column(Text,nullable=False,default='')
    created_at=Column(DateTime(timezone=True),default=now,nullable=False)
    updated_at=Column(DateTime(timezone=True),default=now,nullable=False)

class BeginPractice(BaseModel):
    practice_code:str=Field(min_length=3,max_length=40)
    before_rating:int=Field(ge=1,le=5)

class CompletePractice(BaseModel):
    after_rating:int=Field(ge=1,le=5)
    author_reflection:str=Field(min_length=3,max_length=3000)
    author_notes:str=Field(default='',max_length=3000)

def entry_json(row):
    return {'id':row.id,'practice_code':row.practice_code,'skill':row.skill,
            'state':row.state,'before_rating':row.before_rating,
            'after_rating':row.after_rating,'author_notes':row.author_notes,
            'author_reflection':row.author_reflection,
            'created_at':row.created_at.isoformat() if row.created_at else None,
            'updated_at':row.updated_at.isoformat() if row.updated_at else None}

@router.get('')
def coach_dashboard(pid:int,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    p=core.owned_project(db,user,pid)
    practices=[{'code':code,**{k:v for k,v in item.items() if k!='kinds'}}
               for code,item in PRACTICES.items() if p.kind in item['kinds']]
    entries=db.scalars(select(PracticeEntry).where(PracticeEntry.project_id==pid)
                       .order_by(PracticeEntry.id.desc()).limit(70)).all()
    completed=[r for r in entries if r.state=='completed']
    return {'practices':practices,'sessions':[entry_json(r) for r in entries],
            'completed_count':len(completed),
            'self_rating_change':[{'skill':r.skill,'before':r.before_rating,
                                   'after':r.after_rating} for r in completed],
            'measurement_note':'هذه تقييمات ذاتية يحددها الكاتب، ولا تثبت تحسن الجودة الأدبية دون مراجعة مستقلة.'}

@router.post('/begin')
def begin_practice(pid:int,data:BeginPractice,user:User=Depends(core.auth),db:Session=Depends(get_db)):
    p=core.owned_project(db,user,pid)
    practice=PRACTICES.get(data.practice_code)
    if not practice or p.kind not in practice['kinds']:
        raise HTTPException(422,'التمرين غير مناسب لهذا النوع')
    ongoing=db.scalar(select(PracticeEntry).where(PracticeEntry.project_id==pid,
        PracticeEntry.practice_code==data.practice_code,
        PracticeEntry.state=='in_progress').order_by(PracticeEntry.id.desc()))
    if ongoing:return entry_json(ongoing)
    row=PracticeEntry(project_id=pid,practice_code=data.practice_code,
                      skill=practice['skill'],before_rating=data.before_rating)
    db.add(row);db.commit();db.refresh(row)
    return entry_json(row)

@router.put('/sessions/{sid}/complete')
def complete_practice(pid:int,sid:int,data:CompletePractice,
                      user:User=Depends(core.auth),db:Session=Depends(get_db)):
    core.owned_project(db,user,pid)
    entry=db.scalar(select(PracticeEntry).where(
        PracticeEntry.id==sid,PracticeEntry.project_id==pid))
    if not entry:raise HTTPException(404,'جلسة التدريب غير موجودة')
    if entry.state!='in_progress':
        raise HTTPException(409,'أُغلقت هذه الجلسة بالفعل')
    entry.after_rating=data.after_rating
    entry.author_reflection=data.author_reflection.strip()
    entry.author_notes=data.author_notes.strip()
    entry.state='completed';entry.updated_at=now()
    db.commit()
    return entry_json(entry)
