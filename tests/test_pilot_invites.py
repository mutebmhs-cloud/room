"""Invite-only access regression with synthetic content, role checks, and review consent."""
import os, secrets
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import pilot
from app.db import SessionLocal

@pytest.fixture
def pilot_setup(monkeypatch):
    monkeypatch.setattr(pilot,'PILOT_MODE',True)
    monkeypatch.setenv('PILOT_INVITE_MODE','1')
    monkeypatch.setenv('PILOT_ADMIN_USERNAME','test-admin')
    code='pilot-synthetic-admin-credential-for-testing-0000001'
    monkeypatch.setenv('PILOT_ADMIN_CODE',code)
    pilot.bootstrap_pilot()
    return code

def api_post(c,url,csrf,body):
    return c.post(url,json=body,headers={'X-CSRF-Token':csrf})

def test_invitation_registration_consent_and_admin_review(pilot_setup):
    with TestClient(app) as a, TestClient(app) as w, TestClient(app) as stranger:
        r=a.post('/api/pilot/login',json={'username':'test-admin','access_code':pilot_setup})
        assert r.status_code==200,r.text
        acsrf=r.json()['csrf']
        r=api_post(a,'/api/pilot/admin/writers',acsrf,{'username':'pilotwriter11','display_name':'مؤلف اختباري'})
        assert r.status_code==200,r.text
        code=r.json()['access_code']
        listing=a.get('/api/pilot/admin/writers').json()
        assert len(code)>=32 and code not in str(listing)
        eid=next(x['id'] for x in listing if x['username']=='pilotwriter11')
        assert a.get(f'/api/pilot/admin/writers/{eid}/projects').status_code==403
        assert w.post('/api/pilot/login',json={'username':'pilotwriter11','access_code':code}).status_code==422
        assert w.post('/api/pilot/login',json={'username':'pilotwriter11','access_code':'X'*50,'consent':True}).status_code==401
        r=w.post('/api/pilot/login',json={'username':'pilotwriter11','access_code':code,'consent':True})
        assert r.status_code==200
        assert w.get('/api/auth/me').json()['role']=='writer'
        csrf=r.json()['csrf']
        p=api_post(w,'/api/projects',csrf,{'title':'نص مصطنع','kind':'novel'})
        assert p.status_code==200
        pid=p.json()['id']
        s=api_post(w,f'/api/projects/{pid}/sections',csrf,{'title':'مقطع مصطنع'})
        sid=s.json()['id']
        saved=w.put(f'/api/projects/{pid}/sections/{sid}',json={'version':1,'title':'مقطع مصطنع','body':'نص تجريبي لا يعود إلى مؤلف حقيقي','blocks':[]},headers={'X-CSRF-Token':csrf})
        assert saved.status_code==200
        assert stranger.get('/api/pilot/admin/writers').status_code==401
        assert w.get('/api/pilot/admin/writers').status_code==403
        assert w.get(f'/api/pilot/admin/writers/{eid}/projects').status_code==403
        assert a.get(f'/api/pilot/admin/writers/{eid}/projects').status_code==200
        viewed=a.get(f'/api/pilot/admin/writers/{eid}/projects/{pid}')
        assert viewed.status_code==200 and viewed.json()['read_only']
        assert 'نص تجريبي' in viewed.json()['sections'][0]['body']
        assert [x['action'] for x in w.get('/api/pilot/my-review-log').json()][:2]==['read_project','list_projects']
        feedback=api_post(w,'/api/pilot/feedback',csrf,{'subject':'تعذر الحفظ','detail':'رسالة اختبارية مصطنعة لتوضيح مشكلة بالحفظ','category':'bug'})
        assert feedback.status_code==200
        assert 'تعذر الحفظ' in str(a.get('/api/pilot/admin/feedback').json())
        assert w.get('/api/pilot/admin/feedback').status_code==403
        rotated=api_post(a,f'/api/pilot/admin/writers/{eid}/rotate',acsrf,{})
        new_code=rotated.json()['access_code']
        assert new_code!=code
        assert w.get('/api/projects').status_code==401
        assert w.post('/api/pilot/login',json={'username':'pilotwriter11','access_code':code,'consent':True}).status_code==401
        assert w.post('/api/pilot/login',json={'username':'pilotwriter11','access_code':new_code,'consent':True}).status_code==200
        assert api_post(a,f'/api/pilot/admin/writers/{eid}/toggle',acsrf,{}) .json()['enabled'] is False
        assert w.get('/api/projects').status_code==401

def test_username_validation_and_legacy_auth_disabled(pilot_setup):
    with TestClient(app) as admin:
        auth=admin.post('/api/pilot/login',json={'username':'test-admin','access_code':pilot_setup})
        csrf=auth.json()['csrf']
        r=api_post(admin,'/api/pilot/admin/writers',csrf,{'username':'testwriter99','display_name':'كاتب 99'})
        assert r.status_code==200
        assert api_post(admin,'/api/pilot/admin/writers',csrf,{'username':'testwriter99','display_name':'مكرر'}).status_code==409
        assert api_post(admin,'/api/pilot/admin/writers',csrf,{'username':'bad name','display_name':'اسم'}).status_code==422
        assert admin.post('/api/auth/register',json={'email':'test@example.com','password':'LongTestPassword2026','invite':'A'*40}).status_code==403
