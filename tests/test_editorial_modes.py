"""Professional editorial-review mode contracts on synthetic Arabic manuscripts."""
import secrets
import asyncio
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Invite
from app.security import digest
from app.editorial_rubrics import specialized_instruction, GENRE_RUBRICS, REVIEW_MODES
from app import writer_intelligence as wi
from app import literary_core as lc

@pytest.mark.parametrize("kind",list(GENRE_RUBRICS))
@pytest.mark.parametrize("mode",list(REVIEW_MODES))
def test_all_thirty_genre_role_combinations(kind,mode):
    instruction=specialized_instruction(kind,mode)
    assert GENRE_RUBRICS[kind][0] in instruction
    assert REVIEW_MODES[mode][0] in instruction
    assert 'لا تنشئ حوارًا أو مشهدًا' in instruction
    assert 'الشاهد' in instruction
    assert len(instruction)>350

def test_invalid_genre_and_mode_fail_closed():
    for kind,mode in [('poetry','style'),('novel','freeform'),('screenplay','admin')]:
        with pytest.raises(ValueError):
            specialized_instruction(kind,mode)

@pytest.mark.parametrize("mode",list(REVIEW_MODES))
def test_selected_mode_reaches_real_gateway_adapter_without_external_model(monkeypatch,mode):
    calls=[]
    monkeypatch.setattr(wi,'ai_configured',lambda:True)
    monkeypatch.setattr(wi,'ai_selection',lambda:('groq','synthetic-model','synthetic-key'))
    async def fake_gateway(instructions,messages,schema,max_tokens=1800):
        calls.append((instructions,messages,schema))
        return {'fields':[],'summary':'','central_event':'','character_change':'',
                'open_question':'','feedback':[{
                    'observation':'تحتاج حيازة المفتاح إلى مراجعة أدلة',
                    'evidence':'أعطت سلمى المفتاح إلى هند.',
                    'corroborating_evidence':'',
                    'impact':'قد يلتبس تسلسل الأحداث',
                    'action':'تحقق من موضع المفتاح في الفصل اللاحق',
                    'classification':'narrative_hypothesis'}]}
    monkeypatch.setattr(wi,'json_completion',fake_gateway)
    result=asyncio.run(wi.generate_analysis(
        'screenplay','critique','أعطت سلمى المفتاح إلى هند.',review_mode=mode))
    assert len(result['feedback'])==1
    assert result['review_mode']==mode
    assert REVIEW_MODES[mode][0] in calls[0][0]
    assert 'السيناريو' in calls[0][0]
    assert calls[0][1][0]['role']=='user'
    assert calls[0][2]['required']==['feedback']
    assert list(calls[0][2]['properties'])==['feedback']

def author(client):
    code=secrets.token_urlsafe(35)
    with SessionLocal() as db:
        db.add(Invite(token_hash=digest(code)))
        db.commit()
    r=client.post('/api/auth/register',json={
        'email':secrets.token_hex(10)+'@independent.test',
        'password':'OnlySyntheticWriter2026!!',
        'invite':code})
    assert r.status_code==200,r.text
    return r.json()['csrf']

def post(client,csrf,path,data,method='POST'):
    return client.request(method,path,json=data,headers={'X-CSRF-Token':csrf})

@pytest.mark.parametrize("mode",list(REVIEW_MODES))
def test_authenticated_editorial_mode_is_consented_and_persisted(monkeypatch,mode):
    from app import main as core
    core._attempts.clear()
    with TestClient(app) as writer:
        csrf=author(writer)
        p=post(writer,csrf,'/api/projects',{'title':'اختبار نقد '+secrets.token_hex(3),'kind':'novel'})
        assert p.status_code==200,p.text
        pid=p.json()['id']
        section=post(writer,csrf,f'/api/projects/{pid}/sections',{'title':'الفصل الأول'})
        sid=section.json()['id']
        saved=post(writer,csrf,f'/api/projects/{pid}/sections/{sid}',{
            'version':1,'title':'الفصل الأول','body':'أعطت سلمى المفتاح إلى هند.',
            'blocks':[]},'PUT')
        assert saved.status_code==200,saved.text
        received=[]
        async def mocked(kind,scope,text,review_mode='comprehensive'):
            received.append((kind,scope,text,review_mode))
            return {'feedback':[]}
        monkeypatch.setattr(lc,'generate_analysis',mocked)
        url=f'/api/projects/{pid}/literary/review'
        no_consent=post(writer,csrf,url,{'section_id':sid,'mode':mode,'allow_ai_processing':False})
        assert no_consent.status_code==422
        ok=post(writer,csrf,url,{'section_id':sid,'mode':mode,'allow_ai_processing':True})
        assert ok.status_code==200,ok.text
        assert ok.json()['review_mode']==mode
        assert received[0][0:2]==('novel','critique')
        assert received[0][3]==mode
        assert ok.json()['coverage']=='partial'
        assert post(writer,csrf,url,{'section_id':sid,'mode':'unknown','allow_ai_processing':True}).status_code==422
