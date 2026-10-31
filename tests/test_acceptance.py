import os, sys, json, secrets, tempfile, hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
# isolated DB must be selected before importing the app
fd,path=tempfile.mkstemp(prefix='writer_acceptance_',suffix='.db'); os.close(fd)
os.environ['DATABASE_URL']='sqlite:///'+path
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Invite
from app.security import digest
import pytest

@pytest.fixture(scope='module')
def clients():
    with TestClient(app) as c, TestClient(app) as d:
        with SessionLocal() as db:
            for code in ('invite-abcdef-01','invite-abcdef-02'):
                db.add(Invite(token_hash=digest(code)))
            db.commit()
        yield c,d
    # keep test database until process exit so other modules using cached app can finish
    import atexit
    atexit.register(lambda: Path(path).unlink(missing_ok=True))

def register(c,email,invite):
    r=c.post('/api/auth/register',json={'email':email,'password':'VeryStrongPassword_123','invite':invite})
    assert r.status_code==200, r.text
    return r.json()['csrf']

def req(c,method,url,csrf,data={}):
    return c.request(method,url,json=data,headers={'X-CSRF-Token':csrf})

def test_auth_csrf_and_data_isolation(clients):
    a,b=clients; token_a=register(a,'one@writer.test','invite-abcdef-01'); token_b=register(b,'two@writer.test','invite-abcdef-02')
    assert a.get('/api/auth/me').status_code==200
    # /me rotates csrf intentionally
    token_a=a.get('/api/auth/me').json()['csrf']; token_b=b.get('/api/auth/me').json()['csrf']
    assert a.post('/api/projects',json={'title':'رواية','kind':'novel'}).status_code==403
    assert req(a,'POST','/api/projects',token_a,{'title':'رواية','kind':'novel'}).status_code==200
    p=a.get('/api/projects').json()[0]
    assert b.get('/api/projects').json()==[]
    assert b.get(f'/api/projects/{p["id"]}').status_code==404
    assert req(b,'PUT',f'/api/projects/{p["id"]}',token_b,{'title':'اختراق','version':1,'premise':'','scratchpad':'','structure':{},'checkpoint':{}}).status_code==404
    r=req(a,'PUT',f'/api/projects/{p["id"]}',token_a,{'title':'رواية','version':1,'premise':'فكرة','scratchpad':'فكرة حرّة','structure':{'goal':'النجاة'},'checkpoint':{'summary':'انتهيت من المشهد','next':'العودة'}})
    assert r.status_code==200, r.text
    assert r.json()['version']==2
    assert req(a,'PUT',f'/api/projects/{p["id"]}',token_a,{'title':'رواية','version':1,'premise':'خاطئ','scratchpad':'','structure':{},'checkpoint':{}}).status_code==409
    assert a.get(f'/api/projects/{p["id"]}').json()['project']['scratchpad']=='فكرة حرّة'
    r=req(a,'POST',f'/api/projects/{p["id"]}/sections',token_a,{'title':'الفصل الأول'})
    assert r.status_code==200
    sid=r.json()['id']; body='كتبت مريم رسالتها ثم غادرت.'
    updated=req(a,'PUT',f'/api/projects/{p["id"]}/sections/{sid}',token_a,{'version':1,'title':'الفصل الأول','body':body,'blocks':[]})
    assert updated.status_code==200,updated.text
    assert req(a,'PUT',f'/api/projects/{p["id"]}/sections/{sid}',token_a,{'version':1,'title':'خاطئ','body':'نص بديل','blocks':[]}).status_code==409
    assert a.get(f'/api/projects/{p["id"]}/sections/{sid}/revisions').json()[0]['version']==1
    restored=req(a,'POST',f'/api/projects/{p["id"]}/sections/{sid}/restore',token_a,{'current_version':2,'target_version':1})
    assert restored.status_code==200
    assert restored.json()['body']==''
    assert a.get(f'/api/projects/{p["id"]}/sections/{sid}/revisions').json()[0]['version']==2
    fake=req(a,'POST',f'/api/projects/{p["id"]}/facts',token_a,{'subject':'مريم','predicate':'تكتب','value':'نعم','section_id':sid,'evidence':'اقتباس مختلق'})
    assert fake.status_code==422
    assert req(a,'POST',f'/api/projects/{p["id"]}/facts',token_a,{'subject':'مريم','predicate':'تكتب','value':'نعم'}).status_code==200
    exported=a.get(f'/api/projects/{p["id"]}/export').json()
    assert exported['project']['scratchpad']=='فكرة حرّة'
    imported=req(a,'POST','/api/import',token_a,{'data':exported})
    assert imported.status_code==200,imported.text
    bad={**exported,'sections':[{'title':'مخرب','body':11,'blocks':[]}]}
    assert req(a,'POST','/api/import',token_a,{'data':bad}).status_code==422
    assert req(a,'POST',f'/api/projects/{p["id"]}/chat',token_a,{'message':'أين الصراع؟'}).status_code==503
    assert req(a,'POST','/api/auth/logout',token_a).status_code==200
    assert a.get('/api/projects').status_code==401
    assert b.get('/api/projects').status_code==200

def test_screenplay_and_blocks(clients):
    c,_=clients; csrf=c.post('/api/auth/login',json={'email':'one@writer.test','password':'VeryStrongPassword_123'}).json()['csrf']
    pid=req(c,'POST','/api/projects',csrf,{'title':'فيلم تحت المطر','kind':'screenplay'}).json()['id']
    sid=req(c,'POST',f'/api/projects/{pid}/sections',csrf,{'title':'داخلي - بيت - ليل'}).json()['id']
    blocks=[{'type':'heading','text':'داخلي - بيت - ليل'},{'type':'action','text':'يدخل سامي الغرفة.'},{'type':'character','text':'سامي'},{'type':'dialogue','text':'لم أتوقع عودتك.'}]
    r=req(c,'PUT',f'/api/projects/{pid}/sections/{sid}',csrf,{'version':1,'title':'المشهد 1','body':'','blocks':blocks})
    assert r.status_code==200,r.text
    assert 'لم أتوقع عودتك.' in c.get(f'/api/projects/{pid}/fountain').text
    assert req(c,'PUT',f'/api/projects/{pid}/sections/{sid}',csrf,{'version':2,'title':'المشهد','body':'','blocks':[{'type':'not-valid','text':'x'}]}).status_code==422
    assert req(c,'POST',f'/api/projects/{pid}/facts',csrf,{'subject':'سامي','predicate':'يقول','value':'شيء','evidence':'لم أتوقع عودتك.','section_id':sid}).status_code==200
    assert req(c,'POST',f'/api/projects/{pid}/facts',csrf,{'subject':'سامي','predicate':'يقول','value':'شيء','evidence':'نص مختلق','section_id':sid}).status_code==422
    assert c.get(f'/api/projects/{pid}').json()['facts'][0]['evidence_status']=='literal_unverified_meaning'

def test_security(clients):
    a,_=clients
    assert a.post('/api/projects',data='{}',headers={'content-type':'text/plain'}).status_code==415
    assert a.post('/api/projects',json={},headers={'origin':'https://attacker.example'}).status_code==403
    assert a.get('/').headers['x-frame-options']=='DENY'
    assert a.get('/api/projects').headers['cache-control']=='no-store'
    assert a.get('/robots.txt').status_code==200

def test_reset_me_token(clients):
    a,_=clients
    old=a.get('/api/auth/me').json()['csrf']
    new=a.get('/api/auth/me').json()['csrf']
    assert old==new
    assert req(a,'POST','/api/projects',old,{'title':'x','kind':'novel'}).status_code==200
    assert req(a,'POST','/api/projects',new,{'title':'x','kind':'novel'}).status_code==200
