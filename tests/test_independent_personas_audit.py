"""Independent synthetic writer-persona acceptance audit.
Ten role journeys (beginner/professional x five currently exposed genres).
No real author data, no external LLM calls, no writes to production.
This proves workflow invariants, NOT literary quality.
"""
import secrets
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import main as core
from app.db import SessionLocal
from app.models import Invite
from app.security import digest

SAMPLES={
 "novel": ("في الرياض سلّمت سلمى المفتاح إلى ندى، ثم سافرت قبل الغروب.",
           "في اليوم التالي زعمت ندى أن سلمى لا تزال تحمل المفتاح."),
 "short": ("أعطت سلمى المفتاح إلى ندى في المحطة. لم يعد بينهما موعد.",
           "عادت ندى إلى الباب، وقالت إن المفتاح ما زال عند سلمى."),
 "flash": ("تركت سلمى المفتاح على النافذة وذهبت.",
           "أغلق الباب. قالت ندى إن المفتاح لم يغادر حقيبة سلمى."),
 "children": ("سلمى طفلة في السابعة. أعطت المفتاح إلى ندى، وطلبت منها حفظه.",
              "بعد دقائق تبحث ندى عن المفتاح؛ ثم تقول إن سلمى أخذته."),
 "screenplay": ("داخلي - مكتبة - نهار", "خارجي - شارع - ليل"),
}
def signup(client):
    token=secrets.token_urlsafe(32)
    with SessionLocal() as db:
        db.add(Invite(token_hash=digest(token)))
        db.commit()
    response=client.post('/api/auth/register',json={
        'email':secrets.token_hex(12)+'@synthetic.writer.test',
        'password':'PrivateSyntheticTestPassword2026!!','invite':token})
    assert response.status_code==200,response.text
    return response.json()['csrf']
def api(client,csrf,method,path,data):
    return client.request(method,path,json=data,headers={'X-CSRF-Token':csrf})
def make_sections(kind,experience):
    intro,second=SAMPLES[kind]
    if experience=='professional':
        intro+='\nتفحص ندى دافع الشخصية وذاكرتها قبل قرار المغادرة.'
        second+='\nيعود سؤال المعرفة إلى المشهد السابق ولا يجوز الجزم بتناقض.'
    if kind=='screenplay':
        one=[{'type':'heading','text':intro},
             {'type':'action','text':'تعطي سلمى المفتاح إلى ندى قبل انطفاء الضوء.'},
             {'type':'character','text':'ندى'},
             {'type':'dialogue','text':'سأحتفظ بالمفتاح.'}]
        two=[{'type':'heading','text':second},
             {'type':'action','text':'تقول ندى إن سلمى ما زالت تحمل المفتاح.'},
             {'type':'character','text':'سلمى'},
             {'type':'dialogue','text':'هل تتذكرين ما حدث؟'}]
        return ('',one),('',two)
    return (intro,[]),(second,[])
@pytest.fixture(autouse=True)
def clear_throttle():
    core._attempts.clear()
    yield
    core._attempts.clear()
@pytest.mark.parametrize('kind',['novel','short','flash','children','screenplay'])
@pytest.mark.parametrize('experience',['beginner','professional'])
def test_independent_writer_persona_lifecycle(kind,experience):
    with TestClient(app) as writer:
        csrf=signup(writer)
        prefix='/api/projects'
        title='تقييم مستقل '+kind+' '+experience+' '+secrets.token_hex(4)
        response=api(writer,csrf,'POST',prefix,{'title':title,'kind':kind})
        assert response.status_code==200,response.text
        pid=response.json()['id']
        project=writer.get(f'{prefix}/{pid}').json()['project']
        premise='كاتب '+('مبتدئ' if experience=='beginner' else 'محترف')+' يختبر الغموض دون توليد أدب.'
        update=api(writer,csrf,'PUT',f'{prefix}/{pid}',{
            'version':project['version'],'title':title,'premise':premise,
            'scratchpad':'أحتاج سؤالًا محددًا عن السببية في عملي.','structure':{
                'protagonist':'سلمى','audience':'قرّاء بالعربية'},
            'checkpoint':{'next_step':'مراجعة موضع المفتاح'}})
        assert update.status_code==200,update.text
        texts=make_sections(kind,experience)
        ids=[]
        for i,(body,blocks) in enumerate(texts,1):
            sid_resp=api(writer,csrf,'POST',f'{prefix}/{pid}/sections',{'title':f'المقطع {i}'})
            assert sid_resp.status_code==200,sid_resp.text
            sid=sid_resp.json()['id']
            saved=api(writer,csrf,'PUT',f'{prefix}/{pid}/sections/{sid}',{
                'version':1,'title':f'المقطع {i}','body':body,'blocks':blocks})
            assert saved.status_code==200,saved.text
            assert saved.json()['version']==2
            ids.append(sid)
        sid1,sid2=ids
        project=writer.get(f'{prefix}/{pid}').json()
        assert project['project']['scratchpad']=='أحتاج سؤالًا محددًا عن السببية في عملي.'
        assert len(project['sections'])==2 and project['project']['premise']==premise
        assert api(writer,csrf,'PUT',f'{prefix}/{pid}/sections/{sid1}',{
            'version':1,'title':'تعديل قديم','body':'لا يجب قبول هذه النسخة','blocks':[]}).status_code==409
        assert writer.get(f'{prefix}/{pid}').json()['sections'][0]['version']==2
        summary=api(writer,csrf,'PUT',
          f'{prefix}/{pid}/intelligence/sections/{sid1}/summary',{
            'section_version':2,'summary':'انتقل المفتاح، ويجب مراجعة العلم السابق',
            'central_event':'تسليم المفتاح','character_change':'تغير موقف ندى',
            'open_question':'هل تذكرت ندى التسليم؟'})
        assert summary.status_code==200,summary.text
        assert summary.json()['stale'] is False
        progress=api(writer,csrf,'PUT',f'{prefix}/{pid}/intelligence/progress',{
          'tab':'manuscript','section_id':sid2,'cursor_offset':7})
        assert progress.status_code==200,progress.text
        intelligence=writer.get(f'{prefix}/{pid}/intelligence').json()
        assert intelligence['progress']['section_id']==sid2
        assert intelligence['progress']['cursor_offset']==7
        # Literary intelligence, retrieval, and coaching must be reader-owned,
        # explicitly consented, and source-grounded even without an AI key.
        context=writer.get(f'{prefix}/{pid}/literary/context',params={
          'section_id':sid2,'query':'سلمى المفتاح'})
        assert context.status_code==200,context.text
        assert context.json()['coverage']=='partial'
        assert context.json()['total_sections']==2
        search=writer.get(f'{prefix}/{pid}/manuscript-tools/search',params={'q':'المفتاح'})
        assert search.status_code==200,search.text
        assert search.json()['total_matched']>=2
        assert all(h['offset']>=0 for h in search.json()['hits'])
        reading=writer.get(f'{prefix}/{pid}/reading-map')
        assert reading.status_code==200,reading.text
        assert len(reading.json()['chapters'])==2
        assert reading.json()['total_words']>0
        fact=api(writer,csrf,'POST',f'{prefix}/{pid}/facts',{
            'subject':'سلمى','predicate':'تناولت','value':'المفتاح',
            'evidence':'المفتاح','section_id':sid1})
        assert fact.status_code==200,fact.text
        memory=writer.get(f'{prefix}/{pid}/literary/memory').json()
        assert any(x['name']=='سلمى' for x in memory['entities'])
        forbidden=api(writer,csrf,'POST',f'{prefix}/{pid}/literary/review',{
            'section_id':sid2,'allow_ai_processing':False})
        assert forbidden.status_code==422,forbidden.text
        coach=writer.get(f'{prefix}/{pid}/coach')
        assert coach.status_code==200,coach.text
        practices=coach.json()['practices']
        assert len(practices)>=2
        codes={x['code'] for x in practices}
        if kind=='screenplay': assert 'screen_action' in codes
        elif kind=='children': assert 'child_audience' in codes
        elif kind=='flash': assert 'short_story_focus' in codes
        practice=api(writer,csrf,'POST',f'{prefix}/{pid}/coach/begin',{
            'practice_code':practices[0]['code'],
            'before_rating':1 if experience=='beginner' else 3})
        assert practice.status_code==200,practice.text
        completed=api(writer,csrf,'PUT',f'{prefix}/{pid}/coach/sessions/{practice.json()["id"]}/complete',{
            'after_rating':2 if experience=='beginner' else 4,
            'author_reflection':'راجعت السببية والأدلة ولم أستبدل نصي بنص آلي.'})
        assert completed.status_code==200,completed.text
        assert writer.get(f'{prefix}/{pid}/coach').json()['completed_count']==1
        pin=api(writer,csrf,'POST',f'{prefix}/{pid}/manuscript-tools/milestones',{
            'section_id':sid1,'section_version':2,'label':'قبل التعديل التحريري'})
        assert pin.status_code==200,pin.text
        assert len(writer.get(f'{prefix}/{pid}/manuscript-tools/milestones').json())==1
        assert writer.get(f'{prefix}/{pid}/manuscript/docx').status_code==200
        assert writer.get(f'{prefix}/{pid}/manuscript/epub').status_code==200
        if kind=='screenplay':
            fountain=writer.get(f'{prefix}/{pid}/fountain')
            assert fountain.status_code==200 and 'المفتاح' in fountain.text
        backup=writer.get(f'{prefix}/{pid}/export')
        assert backup.status_code==200,backup.text
        assert backup.json()['format']=='writer-cloud-v2'
        assert len(backup.json()['sections'])==2
        assert len(backup.json()['coaching_sessions'])==1
        imported=api(writer,csrf,'POST','/api/import',{'data':backup.json()})
        assert imported.status_code==200,imported.text
        new_id=imported.json()['id']
        recovered=writer.get(f'{prefix}/{new_id}').json()
        assert len(recovered['sections'])==2
        assert recovered['project']['scratchpad']==project['project']['scratchpad']
        assert writer.get(f'{prefix}/{new_id}/coach').json()['completed_count']==1
        assert writer.get(f'{prefix}/{new_id}/literary/memory').status_code==200

def test_private_export_boundaries_without_authorization():
    with TestClient(app) as writer,TestClient(app) as other:
        csrf=signup(writer)
        signup(other)
        response=api(writer,csrf,'POST','/api/projects',{'title':'خصوصية مصطنعة '+secrets.token_hex(3),'kind':'novel'})
        assert response.status_code==200
        pid=response.json()['id']
        for suffix in ('','/export','/manuscript/docx','/manuscript/epub','/literary/memory','/reading-map','/coach','/intelligence','/manuscript-tools/milestones'):
            assert other.get(f'/api/projects/{pid}{suffix}').status_code==404,suffix
        assert TestClient(app).get(f'/api/projects/{pid}/export').status_code==401
