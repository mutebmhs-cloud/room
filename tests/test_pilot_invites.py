"""Invite-only access regression with synthetic content, role checks, and review consent."""
import os, secrets
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import pilot
from app.db import SessionLocal

@pytest.fixture
def pilot_setup(monkeypatch):
    from app.main import _attempts
    _attempts.clear()
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
        r=a.post('/api/pilot/login',json={'access_code':pilot_setup})
        assert r.status_code==200,r.text
        acsrf=r.json()['csrf']
        r=api_post(a,'/api/pilot/admin/writers',acsrf,{'display_name':'مؤلف اختباري'})
        assert r.status_code==200,r.text
        code=r.json()['access_code']
        listing=a.get('/api/pilot/admin/writers').json()
        assert len(code)==10 and code.isalnum() and any(c.isdigit() for c in code) and any(c.isalpha() for c in code)
        assert code not in str(listing)
        eid=next(x['id'] for x in listing if x['display_name']=='مؤلف اختباري')
        assert a.get(f'/api/pilot/admin/writers/{eid}/projects').status_code==403
        assert w.post('/api/pilot/login',json={'access_code':code}).status_code==422
        assert w.post('/api/pilot/login',json={'access_code':'X'*50,'consent':True}).status_code==401
        r=w.post('/api/pilot/login',json={'access_code':code,'consent':True})
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
        assert w.post('/api/pilot/login',json={'access_code':code,'consent':True}).status_code==401
        assert w.post('/api/pilot/login',json={'access_code':new_code,'consent':True}).status_code==200
        assert api_post(a,f'/api/pilot/admin/writers/{eid}/toggle',acsrf,{}) .json()['enabled'] is False
        assert w.get('/api/projects').status_code==401

def test_name_only_invitations_and_legacy_auth_disabled(pilot_setup):
    with TestClient(app) as admin:
        auth=admin.post('/api/pilot/login',json={'access_code':pilot_setup})
        csrf=auth.json()['csrf']
        r=api_post(admin,'/api/pilot/admin/writers',csrf,{'display_name':'كاتب 99'})
        assert r.status_code==200
        assert api_post(admin,'/api/pilot/admin/writers',csrf,{'display_name':'كاتب 99'}).status_code==200
        assert api_post(admin,'/api/pilot/admin/writers',csrf,{'display_name':'  '}).status_code==422
        assert admin.post('/api/auth/register',json={'email':'test@example.com','password':'LongTestPassword2026','invite':'A'*40}).status_code==403

def test_admin_code_only_session_reload_and_rate_limit(pilot_setup):
    from app.main import _attempts
    with TestClient(app) as admin, TestClient(app) as attacker:
        login=admin.post('/api/pilot/login',json={'access_code':' '+pilot_setup+' '})
        assert login.status_code==200
        assert login.json()['role']=='admin'
        for _ in range(3):
            assert admin.get('/api/auth/me').json()['role']=='admin'
            assert admin.get('/api/pilot/admin/writers').status_code==200
        _attempts.clear()
        for _ in range(7):
            assert attacker.post('/api/pilot/login',json={'access_code':'Invalid123','consent':True}).status_code==401
        assert attacker.post('/api/pilot/login',json={'access_code':'Invalid123','consent':True}).status_code==429
        assert admin.get('/api/pilot/admin/writers').status_code==200


def test_issued_codes_are_alphanumeric_and_contain_both_types(pilot_setup):
    with TestClient(app):
        with SessionLocal() as db:
            codes=[pilot.new_access_code(db) for _ in range(200)]
        assert len(set(codes))==200
        assert all(len(c)==10 and c.isascii() and c.isalnum() and any(x.isdigit() for x in c) and any(x.isalpha() for x in c) for c in codes)
