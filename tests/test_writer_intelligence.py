"""Synthetic regression tests for the writer intelligence release."""
import secrets
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Invite
from app.security import digest
from app import writer_intelligence as wi

def create_author(client):
    token=secrets.token_urlsafe(30)
    with SessionLocal() as db:
        db.add(Invite(token_hash=digest(token)));db.commit()
    email=secrets.token_hex(12)+'@writer.test'
    res=client.post('/api/auth/register',json={'email':email,'password':'SecureLongTestPassword_2026','invite':token})
    assert res.status_code==200,res.text
    return res.json()['csrf']

def request(client,method,path,csrf,data):
    return client.request(method,path,json=data,headers={'X-CSRF-Token':csrf})

def test_duplicate_project_and_compact_catalog():
    with TestClient(app) as c:
        csrf=create_author(c)
        one=request(c,'POST','/api/projects',csrf,{'title':'  رسالة   القطار  ','kind':'novel'})
        assert one.status_code==200,one.text
        same=request(c,'POST','/api/projects',csrf,{'title':'رسالة القطار','kind':'novel'})
        assert same.status_code==200,same.text
        assert same.json()['id']==one.json()['id'] and same.json()['reused'] is True
        other=request(c,'POST','/api/projects',csrf,{'title':'رسالة القطار','kind':'short'})
        assert other.status_code==200 and other.json()['id']!=one.json()['id']
        p=one.json()
        saved=request(c,'PUT',f"/api/projects/{p['id']}",csrf,
                      {'version':p['version'],'title':p['title'],'premise':'', 'scratchpad':'م'*12000,
                       'structure':{},'checkpoint':{}})
        assert saved.status_code==200,saved.text
        listing=c.get('/api/projects/catalog')
        assert listing.status_code==200
        assert len(listing.json())==2 and all('scratchpad' not in row for row in listing.json())

def test_summary_progress_and_three_revisions(monkeypatch):
    with TestClient(app) as c:
        csrf=create_author(c)
        project=request(c,'POST','/api/projects',csrf,{'title':'عمل للتحليل','kind':'novel'}).json()
        pid=project['id']
        assert c.get(f'/api/projects/{pid}/intelligence').status_code==200
        sec=request(c,'POST',f'/api/projects/{pid}/sections',csrf,{'title':'فصل تجريبي'}).json()
        sid=sec['id']
        for version in range(1,7):
            r=request(c,'PUT',f'/api/projects/{pid}/sections/{sid}',csrf,
                      {'version':version,'title':'فصل تجريبي','body':'ملاحظة مصطنعة رقم '+str(version),'blocks':[]})
            assert r.status_code==200,r.text
        versions=c.get(f'/api/projects/{pid}/sections/{sid}/revisions').json()
        assert [v['version'] for v in versions]==[5,4,3]
        summary=request(c,'PUT',f'/api/projects/{pid}/intelligence/sections/{sid}/summary',
                        csrf,{'section_version':7,'summary':'ملخص مستقل للفصل','central_event':'رسالة'})
        assert summary.status_code==200,summary.text
        assert summary.json()['stale'] is False
        progress=request(c,'PUT',f'/api/projects/{pid}/intelligence/progress',csrf,
                         {'tab':'manuscript','section_id':sid,'cursor_offset':13})
        assert progress.status_code==200,progress.text
        intel=c.get(f'/api/projects/{pid}/intelligence').json()
        assert intel['progress']['cursor_offset']==13
        assert intel['summaries'][str(sid)]['summary']=='ملخص مستقل للفصل'
        edited=request(c,'PUT',f'/api/projects/{pid}/sections/{sid}',csrf,
                       {'version':7,'title':'فصل تجريبي','body':'ملاحظة جديدة','blocks':[]})
        assert edited.status_code==200
        assert c.get(f'/api/projects/{pid}/intelligence').json()['summaries'][str(sid)]['stale'] is True
        assert request(c,'PUT',f'/api/projects/{pid}/intelligence/progress',csrf,
                       {'tab':'manuscript','section_id':sid+999999,'cursor_offset':2}).status_code==404

def test_consent_review_stale_and_ownership(monkeypatch):
    with TestClient(app) as a,TestClient(app) as b:
        ac=create_author(a);bc=create_author(b)
        p=request(a,'POST','/api/projects',ac,{'title':'مخطوط مصطنع','kind':'novel'}).json()
        pid=p['id']
        assert request(b,'POST',f'/api/projects/{pid}/intelligence/analyze',bc,
                       {'scope':'project','allow_ai_processing':True}).status_code==404
        updated=request(a,'PUT',f'/api/projects/{pid}',ac,
                        {'version':1,'title':p['title'],'premise':'','structure':{},'checkpoint':{},
                         'scratchpad':'سامر يعمل مهندسا ويخشى مواجهة ماضي أسرته.'})
        assert updated.status_code==200
        assert request(a,'POST',f'/api/projects/{pid}/intelligence/analyze',ac,
                       {'scope':'project','allow_ai_processing':False}).status_code==422
        async def mock(kind,scope,text):
            assert scope=='project'
            return {'fields':[{'key':'protagonist','value':'سامر','evidence':'سامر','certainty':'explicit'}],
                    'summary':'','central_event':'','character_change':'','open_question':'','feedback':[]}
        monkeypatch.setattr(wi,'generate_analysis',mock)
        analysis=request(a,'POST',f'/api/projects/{pid}/intelligence/analyze',ac,
                         {'scope':'project','allow_ai_processing':True})
        assert analysis.status_code==200,analysis.text
        aid=analysis.json()['id']
        bad=request(b,'POST',f'/api/projects/{pid}/intelligence/analyses/{aid}/apply',bc,
                    {'selected_fields':['protagonist']})
        assert bad.status_code==404
        accepted=request(a,'POST',f'/api/projects/{pid}/intelligence/analyses/{aid}/apply',ac,
                         {'selected_fields':['protagonist']})
        assert accepted.status_code==200,accepted.text
        assert accepted.json()['project']['structure']['protagonist']=='سامر'
        assert request(a,'POST',f'/api/projects/{pid}/intelligence/analyses/{aid}/apply',ac,
                       {'selected_fields':['protagonist']}).status_code==404
        second=request(a,'POST',f'/api/projects/{pid}/intelligence/analyze',ac,
                       {'scope':'project','allow_ai_processing':True}).json()
        q=accepted.json()['project']
        changed=request(a,'PUT',f'/api/projects/{pid}',ac,
                        {'version':q['version'],'title':q['title'],'premise':q['premise'],
                         'scratchpad':'نص جديد كليًا','structure':q['structure'],'checkpoint':{}})
        assert changed.status_code==200
        stale=request(a,'POST',f"/api/projects/{pid}/intelligence/analyses/{second['id']}/apply",ac,
                      {'selected_fields':['protagonist']})
        assert stale.status_code==409
