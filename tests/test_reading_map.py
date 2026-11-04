"""Writer v5 reading map privacy, facts and exact-source tests."""
import secrets
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.db import SessionLocal
from app.models import Invite
from app.security import digest

def account(client):
    invite=secrets.token_urlsafe(36)
    with SessionLocal() as db:
        db.add(Invite(token_hash=digest(invite)))
        db.commit()
    resp=client.post('/api/auth/register',json={
        'email':secrets.token_hex(13)+'@synthetic.example',
        'password':'SyntheticWriterTest2026!','invite':invite})
    assert resp.status_code==200,resp.text
    return resp.json()['csrf']

def mutate(client,csrf,method,path,data):
    return client.request(method,path,
        headers={'X-CSRF-Token':csrf},json=data)

def create(client,csrf,title):
    r=mutate(client,csrf,'POST','/api/projects',{'title':title,'kind':'novel'})
    assert r.status_code==200,r.text
    return r.json()['id']

def chapter(client,csrf,pid,title,body):
    r=mutate(client,csrf,'POST',f'/api/projects/{pid}/sections',{'title':title})
    assert r.status_code==200,r.text
    sid=r.json()['id']
    updated=mutate(client,csrf,'PUT',f'/api/projects/{pid}/sections/{sid}',{
        'title':title,'body':body,'version':1,'blocks':[]})
    assert updated.status_code==200,updated.text
    return sid

def test_reading_map_only_saved_author_owned_text():
    with TestClient(app) as writer,TestClient(app) as intruder:
        csrf=account(writer)
        other=account(intruder)
        pid=create(writer,csrf,'حكاية القراءة '+secrets.token_hex(3))
        sid1=chapter(writer,csrf,pid,'الفصل الأول','في الصباح قابلت ليان سامر قرب النهر.\n«غدًا نلتقي» قالت ليان.')
        sid2=chapter(writer,csrf,pid,'الفصل الثاني','أمس عادت ليان إلى النهر.')
        fact=mutate(writer,csrf,'POST',f'/api/projects/{pid}/facts',{
            'subject':'ليان','predicate':'الشخصية الأساسية','value':'تسكن قرب النهر',
            'evidence':'','section_id':None})
        assert fact.status_code==200,fact.text
        result=writer.get(f'/api/projects/{pid}/reading-map')
        assert result.status_code==200,result.text
        data=result.json()
        assert data['method']=='deterministic_text_inspection'
        assert data['scope']=='current_owned_manuscript'
        assert len(data['chapters'])==2
        assert data['total_words']>5
        assert data['chapters'][0]['section_id']==sid1
        assert data['chapters'][1]['section_id']==sid2
        cues=[t['cue'] for ch in data['chapters'] for t in ch['time_cues']]
        assert 'الصباح' in ''.join(cues) or 'في الصباح' in ''.join(cues)
        assert any('غدًا' in c for c in cues)
        mentions=data['documented_subject_mentions']
        assert len(mentions)==1 and mentions[0]['subject']=='ليان'
        assert {x['section_id'] for x in mentions[0]['chapters']}=={sid1,sid2}
        assert all(x['offsets'][0]>=0 for x in mentions[0]['chapters'])
        assert intruder.get(f'/api/projects/{pid}/reading-map').status_code==404
    with TestClient(app) as anonymous:
        assert anonymous.get(f'/api/projects/{pid}/reading-map').status_code==401

def test_reading_map_does_not_invent_characters_or_times():
    from app.reading_map import manuscript_map
    from types import SimpleNamespace
    a=SimpleNamespace(id=1,title='نص تجريبي',position=0,version=1,
                      body='جلس رجل خلف النافذة. لا توجد شخصيات معروفة.',
                      blocks='[]')
    result=manuscript_map([a],[])
    assert result['documented_subject_mentions']==[]
    assert result['chapters'][0]['time_cues']==[]
    assert result['chapters'][0]['dialogue_lines']==0
