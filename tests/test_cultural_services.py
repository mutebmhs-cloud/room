"""Regression checks for the cultural services pilot; all content is synthetic."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Invite
from app.security import digest

def post(c,csrf,path,data):
    return c.post(path,json=data,headers={"X-CSRF-Token":csrf})

def sign_up(c,email,token):
    with SessionLocal() as db:
        db.add(Invite(token_hash=digest(token)));db.commit()
    r=c.post("/api/auth/register",json={"email":email,"password":"SafeTestPassword2026","invite":token})
    assert r.status_code==200,r.text
    return r.json()["csrf"]

def test_service_isolation_and_explicit_attachments(monkeypatch):
    monkeypatch.delenv("PILOT_INVITE_MODE",raising=False)
    with TestClient(app) as writer, TestClient(app) as stranger:
        a=sign_up(writer,"services-owner@example.test","unique-service-invite-001")
        b=sign_up(stranger,"services-stranger@example.test","unique-service-invite-002")
        p=post(writer,a,"/api/projects",{"title":"قصة تجريبية","kind":"children"}).json()["id"]
        s=post(writer,a,f"/api/projects/{p}/sections",{"title":"سر محفوظ"}).json()["id"]
        req={"project_id":p,"service_key":"illustration","route":"human","title":"رسوم قصة","brief":"ارسم قصة تجريبية من اثنتي عشرة صفحة","section_ids":[s]}
        r=post(writer,a,"/api/services/requests",req)
        assert r.status_code==200,r.text
        rid=r.json()["id"]
        assert r.json()["shared_section_count"]==1
        assert stranger.get(f"/api/services/requests/{rid}").status_code==404
        assert stranger.get(f"/api/services/requests?project_id={p}").status_code==404
        assert post(stranger,b,f"/api/services/requests/{rid}/messages",{"body":"محاولة كشف"}).status_code==404
        assert post(writer,a,f"/api/services/requests/{rid}/state",{"status":"delivered"}).status_code==409
        assert post(writer,a,f"/api/services/requests/{rid}/messages",{"body":"أريد رسومات دافئة"}).status_code==200
        info=writer.get(f"/api/services/requests/{rid}").json()
        assert info["shared_sections"][0]["section_id"]==s
        assert info["execution_state"]=="not_connected"
        assert len(info["messages"])==1
        assert post(writer,a,f"/api/services/requests/{rid}/state",{"status":"cancelled"}).status_code==200
        assert post(writer,a,f"/api/services/requests/{rid}/messages",{"body":"بعد إغلاق"}).status_code==409

def test_ai_requires_consent_and_foreign_sections_are_rejected(monkeypatch):
    monkeypatch.delenv("PILOT_INVITE_MODE",raising=False)
    with TestClient(app) as client:
        csrf=sign_up(client,"services-consent@example.test","unique-service-invite-003")
        p=post(client,csrf,"/api/projects",{"title":"قصة أطفال اختبارية","kind":"children"}).json()["id"]
        other=post(client,csrf,"/api/projects",{"title":"عمل ثان","kind":"novel"}).json()["id"]
        section=post(client,csrf,f"/api/projects/{other}/sections",{"title":"مقطع خاص"}).json()["id"]
        data={"project_id":p,"service_key":"illustration","route":"ai","title":"رسم تجريبي","brief":"أريد رسومات إرشادية بصرية لكتاب أطفال"}
        assert post(client,csrf,"/api/services/requests",data).status_code==422
        assert post(client,csrf,"/api/services/requests",{**data,"allow_ai_processing":True,"section_ids":[section]}).status_code==422
        created=post(client,csrf,"/api/services/requests",{**data,"allow_ai_processing":True})
        assert created.status_code==200,created.text
        assert created.json()["ai_processing_authorized"] is True
        assert client.get("/api/services/catalog").status_code==200
        assert post(client,csrf,"/api/services/requests",{**data,"service_key":"publishing"}).status_code==422
