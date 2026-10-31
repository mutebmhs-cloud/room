"""Synthetic end-to-end regression across all supported writing genres."""
import uuid, pytest
from fastapi.testclient import TestClient
from app.main import app
import app.main as main
from app.db import SessionLocal
from app.models import Invite
from app.security import digest

@pytest.fixture(autouse=True)
def clear_test_throttle():
    main._attempts.clear()

def writer(c):
    tag=uuid.uuid4().hex
    invite='test-'+tag
    with SessionLocal() as d:
        d.add(Invite(token_hash=digest(invite)));d.commit()
    email=tag+'@writer.test'
    res=c.post('/api/auth/register',json={'email':email,'password':'StrongPass_2026_!!','invite':invite})
    assert res.status_code==200,res.text
    return email,res.json()['csrf'],res.json()['recovery_code']

def call(c,method,url,csrf,body=None):
    return c.request(method,url,json={} if body is None else body,headers={'X-CSRF-Token':csrf})

@pytest.mark.parametrize('kind',['novel','short','flash','children','screenplay'])
def test_complete_writer_roundtrip(kind,monkeypatch):
    with TestClient(app) as c:
        _,token,_=writer(c)
        p=call(c,'POST','/api/projects',token,{'title':'عمل تجريبي '+kind,'kind':kind})
        assert p.status_code==200,p.text
        pid=p.json()['id']
        sid=call(c,'POST',f'/api/projects/{pid}/sections',token,{'title':'الفصل الأول'}).json()['id']
        blocks=[{'type':'heading','text':'داخلي - مكتبة - ليل'},{'type':'action','text':'تقرأ ندى رسالتها.'},{'type':'character','text':'ندى'},{'type':'dialogue','text':'وصلت الرسالة.'}] if kind=='screenplay' else []
        for version in (1,2):
            res=call(c,'PUT',f'/api/projects/{pid}/sections/{sid}',token,{'version':version,'title':'الفصل الثاني' if version==2 else 'الفصل الأول','body':'ملاحظة الكاتب المصطنعة '+str(version) if not blocks else '','blocks':blocks})
            assert res.status_code==200,res.text
        assert call(c,'POST',f'/api/projects/{pid}/facts',token,{'subject':'ندى','predicate':'تبحث عن','value':'جواب','section_id':sid}).status_code==200
        async def fake(k,message,context,history):
            assert k==kind
            return {'reply':'ما هدف الشخصية؟','questions':['ما العائق؟'],'suggestions':[]}
        monkeypatch.setattr(main,'analyze',fake)
        r=call(c,'POST',f'/api/projects/{pid}/chat',token,{'message':'حلل عملي دون كتابة نص بديل'})
        assert r.status_code==200,r.text
        backup=c.get(f'/api/projects/{pid}/export').json()
        assert backup['format']=='writer-cloud-v2'
        assert len(backup['revisions'])==2 and len(backup['chats'])==2
        new=call(c,'POST','/api/import',token,{'data':backup})
        assert new.status_code==200,new.text
        npid=new.json()['id']
        proj=c.get(f'/api/projects/{npid}').json()
        sec=proj['sections'][0]
        assert sec['version']==3 and sec['title']=='الفصل الثاني'
        assert proj['facts'][0]['section_id']==sec['id']
        revisions=c.get(f"/api/projects/{npid}/sections/{sec['id']}/revisions").json()
        assert {rev['version'] for rev in revisions}=={1,2}
        restored=call(c,'POST',f"/api/projects/{npid}/sections/{sec['id']}/restore",token,{'current_version':3,'target_version':1})
        assert restored.status_code==200
        assert len(c.get(f'/api/projects/{npid}/chat').json())==2
        if kind=='screenplay': assert c.get(f'/api/projects/{npid}/fountain').status_code==200
        old={k:v for k,v in backup.items() if k not in ('revisions','chats')}
        old['format']='writer-cloud-v1'
        assert call(c,'POST','/api/import',token,{'data':old}).status_code==200

def test_isolation_and_validation():
    with TestClient(app) as a, TestClient(app) as b:
        _,ta,_=writer(a);_,tb,_=writer(b)
        pa=call(a,'POST','/api/projects',ta,{'title':'مشروع أ','kind':'novel'}).json()['id']
        pb=call(b,'POST','/api/projects',tb,{'title':'مشروع ب','kind':'novel'}).json()['id']
        sb=call(b,'POST',f'/api/projects/{pb}/sections',tb,{'title':'خاص ب'}).json()['id']
        assert call(a,'POST',f'/api/projects/{pa}/facts',ta,{'subject':'س','predicate':'ف','value':'ع','section_id':sb}).status_code==404
        assert a.get(f'/api/projects/{pb}').status_code==404
        assert call(a,'POST','/api/projects',ta,{'title':'    ','kind':'novel'}).status_code==422
        assert call(a,'POST',f'/api/projects/{pa}/sections',ta,{'title':'    '}).status_code==422
        invalid={'version':2**100,'title':'x','premise':'','structure':{},'scratchpad':'','checkpoint':{}}
        assert call(a,'PUT',f'/api/projects/{pa}',ta,invalid).status_code==422
        before=a.get('/api/projects').json()
        backup={'format':'writer-cloud-v1','project':{'kind':'screenplay','title':'كاتب'},'sections':[{'id':1,'title':'مشهد','body':'','blocks':[{'type':'action','text':'x'}]*901}],'facts':[]}
        assert call(a,'POST','/api/import',ta,{'data':backup}).status_code==422
        assert a.get('/api/projects').json()==before
        assert call(a,'DELETE',f'/api/projects/{pa}',ta).status_code==200
        assert b.get(f'/api/projects/{pb}').status_code==200

def test_recovery_rotates_code_and_kills_sessions():
    with TestClient(app) as c:
        email,csrf,code=writer(c)
        assert c.post('/api/auth/recover',json={'email':email,'code':'A'*50,'new_password':'NewPass2026_!!'}).status_code==403
        response=c.post('/api/auth/recover',json={'email':email,'code':code,'new_password':'NewPass2026_!!'})
        assert response.status_code==200,response.text
        next_code=response.json()['recovery_code']
        assert next_code!=code
        assert c.get('/api/auth/me').status_code==401
        assert c.post('/api/auth/login',json={'email':email,'password':'StrongPass_2026_!!'}).status_code==401
        assert c.post('/api/auth/login',json={'email':email,'password':'NewPass2026_!!'}).status_code==200
        assert c.post('/api/auth/recover',json={'email':email,'code':code,'new_password':'ThirdPass_2026_!!'}).status_code==403
        assert c.post('/api/auth/recover',json={'email':email,'code':next_code,'new_password':'ThirdPass_2026_!!'}).status_code==200
