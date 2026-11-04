"""v4 regression: full-text Arabic retrieval, coaching, EPUB and portable recovery."""
import base64
import secrets
from io import BytesIO
from zipfile import ZipFile,ZIP_STORED
from xml.etree import ElementTree as ET
from fastapi.testclient import TestClient
import pytest
from app.main import app
from app import main as core

@pytest.fixture(autouse=True)
def isolate_throttle_between_tests():
    # Earlier suite cases share the same in-memory rate limiter: tests must not
    # generate false 429 failures or weaken rate limits in application code.
    core._attempts.clear()
    yield
    core._attempts.clear()
from app.db import SessionLocal
from app.models import Invite
from app.security import digest
from app.narrative_retrieval import select_passage,salient_terms

def signup(client):
    invite=secrets.token_urlsafe(35)
    with SessionLocal() as db:
        db.add(Invite(token_hash=digest(invite)));db.commit()
    r=client.post('/api/auth/register',json={
        'email':secrets.token_hex(12)+'@example.test',
        'password':'SyntheticTestPassword123!!','invite':invite})
    assert r.status_code==200,r.text
    return r.json()['csrf']

def post(c,csrf,path,obj,method='POST'):
    return c.request(method,path,json=obj,headers={'X-CSRF-Token':csrf})

def create(c,csrf,kind='novel'):
    r=post(c,csrf,'/api/projects',{'title':'نص اختبار '+secrets.token_hex(4),'kind':kind})
    assert r.status_code==200,r.text
    return r.json()['id']

def chapter(c,csrf,pid,title,body):
    r=post(c,csrf,f'/api/projects/{pid}/sections',{'title':title})
    assert r.status_code==200,r.text
    sid=r.json()['id']
    res=post(c,csrf,f'/api/projects/{pid}/sections/{sid}',
             {'title':title,'version':1,'body':body,'blocks':[]},'PUT')
    assert res.status_code==200,res.text
    return sid

def test_retrieval_uses_ending_passage_not_only_chapter_opening():
    text=('مرت ساعات طويلة ولم يحدث شيء. '*250)+'أعطت هند المفتاح الأزرق إلى سليم قرب البرج.'
    terms=salient_terms('هند المفتاح الأزرق سليم')
    excerpt,offset=select_passage(text,terms,limit=400)
    assert offset>1500 and text[offset:offset+len(excerpt)]==excerpt
    assert 'أعطت هند المفتاح الأزرق' in excerpt
    with TestClient(app) as writer:
        csrf=signup(writer);pid=create(writer,csrf)
        prior=chapter(writer,csrf,pid,'الفصل المبكر',text)
        later=chapter(writer,csrf,pid,'الفصل التالي','قال سليم إن المفتاح الأزرق ضاع من هند.')
        res=writer.get(f'/api/projects/{pid}/literary/context',
            params={'section_id':later,'query':'هند المفتاح الأزرق سليم'})
        assert res.status_code==200,res.text
        evidence=[x for x in res.json()['sections'] if x['section_id']==prior]
        assert evidence and evidence[0]['excerpt_offset']>0
        assert 'أعطت هند المفتاح الأزرق' in evidence[0]['excerpt']

def test_coach_is_author_scoped_genre_specific_and_recovers_from_backup():
    with TestClient(app) as writer,TestClient(app) as other:
        csrf=signup(writer);other_csrf=signup(other)
        pid=create(writer,csrf,'short')
        catalog=writer.get(f'/api/projects/{pid}/coach')
        assert catalog.status_code==200,catalog.text
        codes={x['code'] for x in catalog.json()['practices']}
        assert 'short_story_focus' in codes
        assert 'screen_action' not in codes
        assert other.get(f'/api/projects/{pid}/coach').status_code==404
        assert post(writer,csrf,f'/api/projects/{pid}/coach/begin',
                    {'practice_code':'screen_action','before_rating':2}).status_code==422
        res=post(writer,csrf,f'/api/projects/{pid}/coach/begin',
                 {'practice_code':'short_story_focus','before_rating':2})
        assert res.status_code==200,res.text
        sid=res.json()['id']
        again=post(writer,csrf,f'/api/projects/{pid}/coach/begin',
                   {'practice_code':'short_story_focus','before_rating':1})
        assert again.json()['id']==sid
        assert post(other,other_csrf,f'/api/projects/{pid}/coach/sessions/{sid}/complete',
            {'after_rating':4,'author_reflection':'لاحظت تحولا في البناء'},'PUT').status_code==404
        done=post(writer,csrf,f'/api/projects/{pid}/coach/sessions/{sid}/complete',
            {'after_rating':4,'author_reflection':'لاحظت أن التحول كان يحتاج تمهيدا إضافيا'},
            'PUT')
        assert done.status_code==200,done.text
        assert done.json()['state']=='completed'
        assert post(writer,csrf,f'/api/projects/{pid}/coach/sessions/{sid}/complete',
            {'after_rating':5,'author_reflection':'إعادة اختبار'},'PUT').status_code==409
        summary=writer.get(f'/api/projects/{pid}/coach').json()
        assert summary['completed_count']==1 and summary['self_rating_change'][0]['before']==2
        backup=writer.get(f'/api/projects/{pid}/export')
        assert backup.status_code==200
        assert len(backup.json()['coaching_sessions'])==1
        restored=post(writer,csrf,'/api/import',{'data':backup.json()})
        assert restored.status_code==200,restored.text
        new_pid=restored.json()['id']
        progress=writer.get(f'/api/projects/{new_pid}/coach').json()
        assert progress['completed_count']==1
        assert progress['sessions'][0]['author_reflection']==done.json()['author_reflection']

def test_epub_is_valid_arabic_rtl_package_and_escapes_manuscript():
    with TestClient(app) as writer,TestClient(app) as stranger:
        csrf=signup(writer);other=signup(stranger)
        pid=create(writer,csrf,'novel')
        chapter(writer,csrf,pid,'بداية <المغامرة>','مخطوط عربي يتضمن <علامة> و & حرفا خاصا.')
        chapter(writer,csrf,pid,'النهاية','ثم انتهت الحكاية.')
        assert stranger.get(f'/api/projects/{pid}/manuscript/epub').status_code==404
        response=writer.get(f'/api/projects/{pid}/manuscript/epub')
        assert response.status_code==200,response.text[:100]
        assert response.headers['content-type'].startswith('application/epub+zip')
        with ZipFile(BytesIO(response.content)) as z:
            assert z.namelist()[0]=='mimetype'
            assert z.getinfo('mimetype').compress_type==ZIP_STORED
            assert z.read('mimetype')==b'application/epub+zip'
            opf=ET.fromstring(z.read('OEBPS/content.opf'))
            assert opf.attrib['version']=='3.0'
            nav=ET.fromstring(z.read('OEBPS/nav.xhtml'))
            first=ET.fromstring(z.read('OEBPS/chapters/chapter-1.xhtml'))
            assert first.attrib['dir']=='rtl'
            html=z.read('OEBPS/chapters/chapter-1.xhtml').decode('utf-8')
            assert '&lt;علامة&gt;' in html and '&amp;' in html
            assert '<علامة>' not in html
            assert 'بداية &lt;المغامرة&gt;' in html
            assert ET.fromstring(z.read('OEBPS/chapters/chapter-2.xhtml')) is not None

def test_cross_chapter_review_becomes_stale_when_another_chapter_changes(monkeypatch):
    from app import literary_core as lit
    with TestClient(app) as writer:
        csrf=signup(writer);pid=create(writer,csrf)
        earlier=chapter(writer,csrf,pid,'الحادثة','تحدثت هند عن المفتاح الفضي مع سليم.')
        later=chapter(writer,csrf,pid,'النتيجة','قال سليم إن المفتاح الفضي لا يزال عند هند.')
        async def model(kind,scope,text):
            assert 'المفتاح الفضي' in text
            return {'feedback':[{'observation':'راجع تسلسل انتقال المفتاح',
                'evidence':'قال سليم إن المفتاح الفضي لا يزال عند هند.',
                'impact':'قد يتعارض انتقال الشيء بين الفصلين',
                'action':'قارن ما يعرفه الطرفان',
                'corroborating_evidence':'تحدثت هند عن المفتاح الفضي مع سليم.',
                'classification':'objective_candidate'}]}
        monkeypatch.setattr(lit,'generate_analysis',model)
        result=post(writer,csrf,f'/api/projects/{pid}/literary/review',
            {'section_id':later,'allow_ai_processing':True})
        assert result.status_code==200,result.text
        fid=result.json()['findings'][0]['id']
        current=writer.get(f'/api/projects/{pid}/literary/findings').json()
        assert current[0]['context_status']=='current'
        assert current[0]['category']=='objective_candidate'
        assert len(current[0]['citations'])==2
        assert {quote['section_id'] for quote in current[0]['citations']}=={earlier,later}
        assert current[0]['stale'] is False
        # An earlier source changes while the quoted chapter stays untouched.
        updated=post(writer,csrf,f'/api/projects/{pid}/sections/{earlier}',
            {'title':'الحادثة','version':2,'body':'تحدثت هند عن رسالة جديدة.', 'blocks':[]},'PUT')
        assert updated.status_code==200,updated.text
        stale=writer.get(f'/api/projects/{pid}/literary/findings').json()
        assert stale[0]['stale'] is True
        assert stale[0]['context_status']=='changed'
        recheck=writer.get(f'/api/projects/{pid}/literary/findings/{fid}/recheck')
        assert recheck.status_code==200
        assert recheck.json()['evidence_still_present'] is True
        assert recheck.json()['requires_literary_review'] is True
        exported=writer.get(f'/api/projects/{pid}/export').json()
        assert len(exported['literary_findings'][0]['context_sources'])==2
        restored=post(writer,csrf,'/api/import',{'data':exported})
        assert restored.status_code==200,restored.text
        new_id=restored.json()['id']
        restored_findings=writer.get(f'/api/projects/{new_id}/literary/findings').json()
        assert restored_findings[0]['context_status']=='changed'
