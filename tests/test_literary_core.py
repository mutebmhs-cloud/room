"""Integration checks for reader evidence, access controls, consent and Arabic DOCX."""
from io import BytesIO
import base64
import secrets
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.db import SessionLocal
from app.models import Invite
from app.security import digest
from app import literary_core as lit

def author(client):
    invite=secrets.token_urlsafe(32)
    with SessionLocal() as db:
        db.add(Invite(token_hash=digest(invite)));db.commit()
    response=client.post('/api/auth/register',json={
        'email':secrets.token_hex(12)+'@writer.example',
        'password':'SyntheticTestPassword26!!','invite':invite})
    assert response.status_code==200,response.text
    return response.json()['csrf']

def request(client,csrf,method,path,data):
    return client.request(method,path,json=data,headers={'X-CSRF-Token':csrf})

def make_project(client,csrf,kind='novel'):
    created=request(client,csrf,'POST','/api/projects',{'title':'تجربة الأدب '+secrets.token_hex(3),'kind':kind})
    assert created.status_code==200,created.text
    return created.json()['id']

def section(client,csrf,pid,title,body):
    r=request(client,csrf,'POST',f'/api/projects/{pid}/sections',{'title':title})
    assert r.status_code==200,r.text
    sid=r.json()['id']
    changed=request(client,csrf,'PUT',f'/api/projects/{pid}/sections/{sid}',
                    {'title':title,'version':1,'body':body,'blocks':[]})
    assert changed.status_code==200,changed.text
    return sid

def test_context_is_from_real_owned_chapters_and_discloses_coverage():
    with TestClient(app) as writer,TestClient(app) as stranger:
        csrf=author(writer);other=author(stranger)
        pid=make_project(writer,csrf)
        first=section(writer,csrf,pid,'الفصل الأول','أعطت سلمى المفتاح الذهبي إلى ليلى قرب المحطة.')
        second=section(writer,csrf,pid,'الفصل الثاني','بحثت ليلى عن المفتاح الذهبي داخل البيت.')
        result=writer.get(f'/api/projects/{pid}/literary/context',
                          params={'section_id':second,'query':'المفتاح سلمى'})
        assert result.status_code==200,result.text
        data=result.json()
        assert data['coverage']=='partial' and data['total_sections']==2
        assert data['sections'][0]['section_id']==second
        assert any(x['section_id']==first and 'سلمى' in x['excerpt'] for x in data['sections'])
        assert all(x['source_hash'] and x['version']==2 for x in data['sections'])
        assert stranger.get(f'/api/projects/{pid}/literary/context',params={'section_id':second}).status_code==404
        assert writer.get(f'/api/projects/{pid}/literary/context',params={'section_id':second,'query':'أ'*601}).status_code==422

def test_review_consent_provider_unavailable_and_findings(monkeypatch):
    from fastapi import HTTPException
    with TestClient(app) as w:
        csrf=author(w);pid=make_project(w,csrf)
        sid=section(w,csrf,pid,'بداية','أعطت سلمى المفتاح إلى ليلى ثم عادت.')
        path=f'/api/projects/{pid}/literary/review'
        assert request(w,csrf,'POST',path,{'section_id':sid,'allow_ai_processing':False}).status_code==422
        async def mocked(kind,scope,text):
            assert 'سلمى' in text and scope=='critique'
            return {'feedback':[{'observation':'تحقق من انتقال المفتاح','evidence':'أعطت سلمى المفتاح إلى ليلى',
                 'impact':'قد يضيع تتبع الشيء','action':'راجع الفصل التالي'},
                {'observation':'شاهد مختلق','evidence':'هذه عبارة غير موجودة',
                 'impact':'غير صحيح','action':'غير صحيح'}]}
        monkeypatch.setattr(lit,'generate_analysis',mocked)
        result=request(w,csrf,'POST',path,{'section_id':sid,'allow_ai_processing':True})
        assert result.status_code==200,result.text
        assert len(result.json()['findings'])==1
        finding=result.json()['findings'][0]
        assert finding['evidence']=='أعطت سلمى المفتاح إلى ليلى'
        fid=finding['id']
        assert request(w,csrf,'PUT',f'/api/projects/{pid}/literary/findings/{fid}',
                       {'state':'resolved'}).status_code==409
        assert request(w,csrf,'PUT',f'/api/projects/{pid}/literary/findings/{fid}',
                       {'state':'dismissed'}).status_code==200
        assert len(w.get(f'/api/projects/{pid}/literary/findings').json())==1
        # Re-running cannot multiply an identical observation on unchanged text.
        assert len(request(w,csrf,'POST',path,{'section_id':sid,'allow_ai_processing':True}).json()['findings'])==1
        assert len(w.get(f'/api/projects/{pid}/literary/findings').json())==1
        # Existing author text is untouched by review.
        assert w.get(f'/api/projects/{pid}').json()['sections'][0]['body']=='أعطت سلمى المفتاح إلى ليلى ثم عادت.'

def test_metadata_only_research_requires_writer_optin(monkeypatch):
    class FakeResp:
        status_code=200
        def json(self):
            return {'docs':[{'key':'/works/OL12345W','title':'رواية قديمة',
                             'author_name':['كاتب افتراضي'],'first_publish_year':1950},
                            {'key':'https://evil.example/path','title':'مزور'}]}
    class Client:
        def __init__(self,**kw):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):return False
        async def get(self,url,params=None):
            assert url=='https://openlibrary.org/search.json'
            assert params['q']=='محطة قطار'
            return FakeResp()
    monkeypatch.setattr(lit.httpx,'AsyncClient',Client)
    with TestClient(app) as w:
        csrf=author(w);pid=make_project(w,csrf)
        path=f'/api/projects/{pid}/literary/research'
        assert request(w,csrf,'POST',path,{'query':'محطة قطار'}).status_code==422
        result=request(w,csrf,'POST',path,{'query':'محطة قطار','consent_external_lookup':True})
        assert result.status_code==200,result.text
        data=result.json()
        assert data['coverage']=='catalog_metadata_only' and len(data['results'])==1
        assert data['results'][0]['url']=='https://openlibrary.org/works/OL12345W'

def test_word_export_and_nondestructive_import():
    with TestClient(app) as w:
        csrf=author(w);pid=make_project(w,csrf)
        section(w,csrf,pid,'فصل البداية','أحب سامر القصص العربية.\nهذا السطر الثاني.')
        exported=w.get(f'/api/projects/{pid}/manuscript/docx')
        assert exported.status_code==200,exported.text[:150]
        doc=Document(BytesIO(exported.content))
        whole='\n'.join(x.text for x in doc.paragraphs)
        assert 'فصل البداية' in whole and 'أحب سامر' in whole
        result=request(w,csrf,'POST',f'/api/projects/{pid}/manuscript/docx/import',{
            'filename':'story.docx','content_base64':base64.b64encode(exported.content).decode()})
        assert result.status_code==200,result.text
        assert result.json()['added_sections']>=1
        all_sections=w.get(f'/api/projects/{pid}').json()['sections']
        assert len(all_sections)>=2 and any('أحب سامر' in s['body'] for s in all_sections)
        assert request(w,csrf,'POST',f'/api/projects/{pid}/manuscript/docx/import',{
            'filename':'other.docx','content_base64':base64.b64encode(b'not a docx').decode()}).status_code==422

def test_review_findings_roundtrip_in_portable_backup(monkeypatch):
    with TestClient(app) as writer:
        csrf=author(writer);pid=make_project(writer,csrf)
        sid=section(writer,csrf,pid,'الفصل الأول','احتفظت هند بالرسالة عند النافذة.')
        async def model(kind,scope,text):
            return {'feedback':[{'observation':'تأكد من موضع الرسالة',
                 'evidence':'احتفظت هند بالرسالة','impact':'تؤثر في الاستمرارية',
                 'action':'قارن المشهد التالي'}]}
        monkeypatch.setattr(lit,'generate_analysis',model)
        assert request(writer,csrf,'POST',f'/api/projects/{pid}/literary/review',
                {'section_id':sid,'allow_ai_processing':True}).status_code==200
        export=writer.get(f'/api/projects/{pid}/export')
        assert export.status_code==200,export.text
        assert len(export.json()['literary_findings'])==1
        restored=request(writer,csrf,'POST','/api/import',{'data':export.json()})
        assert restored.status_code==200,restored.text
        new_pid=restored.json()['id']
        notes=writer.get(f'/api/projects/{new_pid}/literary/findings')
        assert notes.status_code==200
        assert len(notes.json())==1
        assert notes.json()[0]['observation']=='تأكد من موضع الرسالة'
        assert notes.json()[0]['section_id']!=sid
