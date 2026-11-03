"""Regression tests for specialized genre rubrics, writer progress and DOCX export."""
import io,zipfile
import pytest
from fastapi.testclient import TestClient
from docx import Document
from app.main import app
from app.genre_catalog import GENRES
from app.db import SessionLocal
from app.models import Invite
from app.security import digest
import secrets
import app.main as main

def auth(client,monkeypatch):
 monkeypatch.setattr(main,"throttle",lambda *a,**k:None)
 invitation="growth-"+secrets.token_urlsafe(24)
 with SessionLocal() as db:
  db.add(Invite(token_hash=digest(invitation)));db.commit()
 r=client.post("/api/auth/register",json={"email":secrets.token_hex(10)+"@growth.test","password":"LongPasswordForTest2026","invite":invitation})
 assert r.status_code==200,r.text
 return r.json()["csrf"]
def post(c,csrf,url,body,method="POST"):
 return c.request(method,url,json=body,headers={"X-CSRF-Token":csrf})
@pytest.mark.parametrize("kind",list(GENRES))
def test_genre_progress_and_professional_export(kind,monkeypatch):
 monkeypatch.delenv("PILOT_INVITE_MODE",raising=False)
 with TestClient(app) as writer,TestClient(app) as other:
  csrf=auth(writer,monkeypatch);othercsrf=auth(other,monkeypatch)
  p=post(writer,csrf,"/api/projects",{"title":"تجربة نوع "+kind,"kind":kind}).json()["id"]
  section=post(writer,csrf,f"/api/projects/{p}/sections",{"title":"الفصل التجريبي"}).json()["id"]
  blocks=[{"type":"heading","text":"داخلي - غرفة - مساء"},{"type":"action","text":"تدخل سارة البيت."}] if kind=="screenplay" else []
  body="" if blocks else "النص العربي التجريبي لا يعود إلى مؤلف حقيقي."
  saved=post(writer,csrf,f"/api/projects/{p}/sections/{section}",
    {"version":1,"title":"الفصل التجريبي","body":body,"blocks":blocks},"PUT")
  assert saved.status_code==200,saved.text
  progress=writer.get(f"/api/writer-growth/projects/{p}")
  assert progress.status_code==200,progress.text
  data=progress.json()
  assert data["genre"]["key"]==kind
  assert len(data["genre"]["dimensions"])>=5
  assert data["section_count"]==1 and data["word_count"]>0
  dim=data["genre"]["dimensions"][0]["key"];stage=data["genre"]["stages"][0]["key"]
  checkin=post(writer,csrf,f"/api/writer-growth/projects/{p}/checkins",
    {"dimension":dim,"stage":stage,"confidence":3,"observation":"سرد تجريبي يحتاج إلى إعادة ضبط","next_action":"مراجعة المقطع الأول وفق معيار النوع"})
  assert checkin.status_code==200,checkin.text
  assert len(writer.get(f"/api/writer-growth/projects/{p}").json()["checkins"])==1
  assert post(writer,csrf,f"/api/writer-growth/projects/{p}/checkins",
    {"dimension":"unknown","stage":stage,"confidence":5,"observation":"مراجعة غير صالحة","next_action":"هذا لا ينطبق على النوع"}).status_code==422
  assert other.get(f"/api/writer-growth/projects/{p}").status_code==404
  assert other.get(f"/api/pro-export/projects/{p}/docx").status_code==404
  export=writer.get(f"/api/pro-export/projects/{p}/docx")
  assert export.status_code==200,export.text
  assert export.headers["content-type"].startswith("application/vnd.openxmlformats")
  assert zipfile.is_zipfile(io.BytesIO(export.content))
  doc=Document(io.BytesIO(export.content))
  texts=" ".join(z.text for z in doc.paragraphs)
  assert "تجربة نوع" in texts and ("تدخل سارة" if blocks else "النص العربي") in texts
  assert doc.paragraphs[0].alignment is not None
