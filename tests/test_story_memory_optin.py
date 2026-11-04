"""Ensure story memory is never silently disclosed to the model.
Exercise actual FastAPI chat endpoint with a synthetic model spy.
"""
import secrets
from fastapi.testclient import TestClient
from app import main as core
from app.main import app
from app.db import SessionLocal
from app.models import Invite
from app.security import digest

def call(c,csrf,method,path,data):
    return c.request(method,path,json=data,headers={"X-CSRF-Token":csrf})

def test_story_memory_requires_per_request_opt_in_and_ignores_outdated_summaries(monkeypatch):
    core._attempts.clear()
    with TestClient(app) as c:
        invite=secrets.token_urlsafe(36)
        with SessionLocal() as db:
            db.add(Invite(token_hash=digest(invite)));db.commit()
        r=c.post('/api/auth/register',json={
            'email':secrets.token_hex(12)+'@optin.example',
            'password':'OnlySyntheticPassword_2026!!','invite':invite})
        assert r.status_code==200,r.text
        csrf=r.json()['csrf']
        p=call(c,csrf,'POST','/api/projects',{
            'title':'نص اختبار ذاكرة '+secrets.token_hex(3),'kind':'novel'})
        assert p.status_code==200
        pid=p.json()['id']
        s=call(c,csrf,'POST',f'/api/projects/{pid}/sections',{'title':'الفصل الأول'})
        sid=s.json()['id']
        assert call(c,csrf,'PUT',f'/api/projects/{pid}/sections/{sid}',{
            'version':1,'title':'الفصل الأول','body':'أعطت سلمى مفتاح البيت إلى مها.',
            'blocks':[]}).status_code==200
        assert call(c,csrf,'POST',f'/api/projects/{pid}/facts',{
            'subject':'سلمى','predicate':'أعطت','value':'مفتاح البيت',
            'section_id':sid,'evidence':'أعطت سلمى مفتاح البيت إلى مها.'}).status_code==200
        assert call(c,csrf,'PUT',f'/api/projects/{pid}/intelligence/sections/{sid}/summary',{
            'section_version':2,'summary':'سلمى أعطت المفتاح إلى مها.',
            'central_event':'تسليم المفتاح','character_change':'',
            'open_question':'أين ستضع مها المفتاح؟'}).status_code==200
        observations=[]
        async def spy(kind,message,context,history):
            observations.append(context)
            return {'reply':'راجع مصدر المعلومة قبل الحكم','questions':[],
                    'suggestions':[]}
        monkeypatch.setattr(core,'analyze',spy)
        url=f'/api/projects/{pid}/chat'
        assert call(c,csrf,'POST',url,{'message':'كيف أراجع الفصل؟'}).status_code==200
        assert observations[-1]==''
        assert call(c,csrf,'POST',url,{'message':'ما حدث في الفصل؟',
                    'share_memory':True}).status_code==200
        assert 'مفتاح البيت' in observations[-1]
        assert 'تسليم المفتاح' in observations[-1]
        # The old summary and quoted fact cease to be supplied when the
        # manuscript changes: the AI must not inherit outdated world facts.
        assert call(c,csrf,'PUT',f'/api/projects/{pid}/sections/{sid}',{
            'version':2,'title':'الفصل الأول','body':'لم تسلم سلمى المفتاح إلى أحد.',
            'blocks':[]}).status_code==200
        assert call(c,csrf,'POST',url,{'message':'ماذا تغير في النص؟',
                    'share_memory':True}).status_code==200
        assert 'تسليم المفتاح' not in observations[-1]
        assert 'أعطت' not in observations[-1]
        assert call(c,csrf,'POST',url,{'message':'هل تتذكر النص؟'}).status_code==200
        assert observations[-1]==''
