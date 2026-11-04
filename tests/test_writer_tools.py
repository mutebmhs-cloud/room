"""Regression tests for secure literal search and pinned author milestone recovery."""
import secrets
import pytest
from fastapi.testclient import TestClient
from app import main as core
from app.main import app
from app.models import Invite
from app.db import SessionLocal
from app.security import digest

@pytest.fixture(autouse=True)
def reset_test_throttles():
    core._attempts.clear()
    yield
    core._attempts.clear()

def auth(client):
    invite=secrets.token_urlsafe(40)
    with SessionLocal() as db:
        db.add(Invite(token_hash=digest(invite)));db.commit()
    res=client.post('/api/auth/register',json={'email':secrets.token_hex(12)+'@example.test',
        'password':'SyntheticPassword12345!!','invite':invite})
    assert res.status_code==200,res.text
    return res.json()['csrf']

def write(client,csrf,method,path,data):
    return client.request(method,path,json=data,headers={'X-CSRF-Token':csrf})

def setup(client,csrf,body):
    p=write(client,csrf,'POST','/api/projects',
        {'title':'مسودة تجريبية '+secrets.token_hex(4),'kind':'novel'})
    assert p.status_code==200,p.text
    pid=p.json()['id']
    r=write(client,csrf,'POST',f'/api/projects/{pid}/sections',{'title':'البداية'})
    assert r.status_code==200,r.text
    sid=r.json()['id']
    updated=write(client,csrf,'PUT',f'/api/projects/{pid}/sections/{sid}',
        {'version':1,'title':'البداية','body':body,'blocks':[]})
    assert updated.status_code==200,updated.text
    return pid,sid

def test_search_is_private_and_returns_literal_original_offsets():
    with TestClient(app) as owner,TestClient(app) as stranger:
        csrf=auth(owner);other=auth(stranger)
        text=('البيت بعيد. '*350)+'أعطت هند المفتاح الفضي إلى سلمى.'
        pid,sid=setup(owner,csrf,text)
        path=f'/api/projects/{pid}/manuscript-tools/search'
        result=owner.get(path,params={'q':'المفتاح الفضي'})
        assert result.status_code==200,result.text
        assert result.json()['scope']=='all_current_sections'
        entry=result.json()['hits'][0]
        assert entry['section_id']==sid
        assert entry['offset']>2000
        assert 'المفتاح الفضي' in entry['excerpt']
        assert stranger.get(path,params={'q':'المفتاح الفضي'}).status_code==404
        assert owner.get(path,params={'q':'x'}).status_code==422

def test_pinned_versions_survive_three_revision_pruning_and_portable_backup():
    with TestClient(app) as owner,TestClient(app) as stranger:
        csrf=auth(owner);other=auth(stranger)
        pid,sid=setup(owner,csrf,'النص المرجعي الذي سيحفظه الكاتب.')
        base=f'/api/projects/{pid}/manuscript-tools'
        created=write(owner,csrf,'POST',base+'/milestones',
            {'section_id':sid,'section_version':2,'label':'قبل المراجعة'})
        assert created.status_code==200,created.text
        mid=created.json()['id']
        assert stranger.get(base+'/milestones').status_code==404
        assert write(stranger,other,'POST',base+'/milestones/'+str(mid)+'/restore',
            {'current_version':2}).status_code==404
        version=2
        for i in range(6):
            res=write(owner,csrf,'PUT',f'/api/projects/{pid}/sections/{sid}',
                {'version':version,'title':'البداية','body':'نص منقح رقم '+str(i),
                 'blocks':[]})
            assert res.status_code==200,res.text
            version=res.json()['version']
        revs=owner.get(f'/api/projects/{pid}/sections/{sid}/revisions').json()
        assert len(revs)==3
        assert all(x['version']!=2 for x in revs)
        conflict=write(owner,csrf,'POST',base+'/milestones/'+str(mid)+'/restore',
            {'current_version':2})
        assert conflict.status_code==409
        snapshot=owner.get(f'/api/projects/{pid}/export').json()
        assert len(snapshot['pinned_milestones'])==1
        restored_project=write(owner,csrf,'POST','/api/import',{'data':snapshot})
        assert restored_project.status_code==200,restored_project.text
        new_pid=restored_project.json()['id']
        migrated=owner.get(f'/api/projects/{new_pid}/manuscript-tools/milestones').json()
        assert len(migrated)==1 and migrated[0]['label']=='قبل المراجعة'
        restored=write(owner,csrf,'POST',base+'/milestones/'+str(mid)+'/restore',
            {'current_version':version})
        assert restored.status_code==200,restored.text
        assert restored.json()['body']=='النص المرجعي الذي سيحفظه الكاتب.'
        latest=owner.get(f'/api/projects/{pid}/sections/{sid}/revisions').json()
        assert any(x['version']==version for x in latest)
        assert len(latest)==3
        assert len(owner.get(base+'/milestones').json())==1
