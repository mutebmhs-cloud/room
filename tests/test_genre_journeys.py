"""Synthetic writing journeys across all five enabled genres (not production).
Tests writer workflows independently of external AI model quality.
"""
import secrets
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Invite
from app.security import digest
import app.main as main
from app.ai import instruction

GENRES={
 "novel":{"title":"رواية مفاتيح المدينة","part":"الفصل الأول","body":"عادت ليلى إلى المدينة عند الفجر، ومعها مفتاح قديم ورثته عن أمها. لاحظت أن الباب المفتوح أمس أصبح مغلقًا.","theme":"الفقد والهوية","task":"هل هناك تعارض بين زمن العودة وزمن إغلاق الباب؟"},
 "short":{"title":"قصة ساعة المطر","part":"القصة","body":"كلما هطل المطر أخفى يوسف الساعة في درج مكتبه. في تلك الليلة لم يهطل المطر، لكنه فتح الدرج للمرة الأولى.","theme":"الذاكرة والتحول","task":"كيف أراجع وحدة الأثر ونقطة التحول؟"},
 "flash":{"title":"قصة خاطفة النافذة","part":"النص الوجيز","body":"ترك المصباح مضاءً كل ليلة. وحين عادت أخيرًا، اكتشف أنها كانت تخشى الضوء.","theme":"المفارقة","task":"هل يمكن الاستغناء عن جملة مع الحفاظ على المفارقة؟"},
 "children":{"title":"قصة أطفال قمر الأرنب","part":"الصفحة الأولى","body":"وجد الأرنب سامر بذرة زرقاء قرب الشجرة. زرعها وانتظر صباحًا ليعرف ماذا ستصبح.","theme":"الصبر","task":"هل اللغة مناسبة لعمر ست سنوات؟ وما الرسوم التي تحتاجها الصفحة؟"},
 "screenplay":{"title":"سيناريو آخر محطة","part":"المشهد الأول","body":"","theme":"الاختيار","task":"هل يمكن تصوير الصراع دون حوار شارح؟",
    "blocks":[{"type":"heading","text":"داخلي - محطة القطار - ليل"},
              {"type":"action","text":"تضع هدى التذكرة على المقعد وتنظر إلى الساعة."},
              {"type":"character","text":"هدى"},
              {"type":"dialogue","text":"لن أنتظر أكثر."}]}
}
def write(client,csrf,url,payload,method="POST"):
    return client.request(method,url,json=payload,headers={"X-CSRF-Token":csrf})
def account(client):
    email="genre-"+secrets.token_hex(7)+"@writer.test"
    token="synthetic-genre-"+secrets.token_urlsafe(16)
    with SessionLocal() as db:
        db.add(Invite(token_hash=digest(token)));db.commit()
    r=client.post("/api/auth/register",json={"email":email,"invite":token,"password":"StrongGenreTest-2026-Content"})
    assert r.status_code==200,r.text
    return r.json()["csrf"]

@pytest.mark.parametrize("genre",list(GENRES))
def test_full_writer_genre_journey(genre,monkeypatch):
    """Create, brainstorm, structure, save, evidence, detect conflict, restore, checkpoint, backup."""
    monkeypatch.delenv("PILOT_INVITE_MODE",raising=False)
    sample=GENRES[genre]
    with TestClient(app) as writer, TestClient(app) as intruder:
        csrf=account(writer); ic=account(intruder)
        p=write(writer,csrf,"/api/projects",{"title":sample["title"],"kind":genre})
        assert p.status_code==200,p.text
        pid=p.json()["id"]
        assert intruder.get(f"/api/projects/{pid}").status_code==404
        p=write(writer,csrf,f"/api/projects/{pid}",{"version":1,"title":sample["title"],
            "premise":"المشروع يبدأ بفكرة حرة، ولا يكتب الذكاء الاصطناعي بدلاً عن المؤلف.",
            "scratchpad":"أفكار خاصة حول "+sample["theme"],
            "structure":{"theme":sample["theme"],"audience":"القارئ العربي","goal":"تطوير نص أصيل"},
            "checkpoint":{"summary":"جهزت الفكرة الأولية","next":"كتابة أول مقطع","question":"كيف أبدأ؟"}},"PUT")
        assert p.status_code==200,p.text
        assert p.json()["version"]==2
        assert write(writer,csrf,f"/api/projects/{pid}",{"version":1,"title":"تعارض","premise":"","scratchpad":"","structure":{},"checkpoint":{}},"PUT").status_code==409
        s=write(writer,csrf,f"/api/projects/{pid}/sections",{"title":sample["part"]})
        assert s.status_code==200,s.text
        sid=s.json()["id"]
        blocks=sample.get("blocks",[])
        saved=write(writer,csrf,f"/api/projects/{pid}/sections/{sid}",
          {"version":1,"title":sample["part"],"body":sample["body"],"blocks":blocks},"PUT")
        assert saved.status_code==200,saved.text
        assert saved.json()["version"]==2
        assert write(writer,csrf,f"/api/projects/{pid}/sections/{sid}",
          {"version":1,"title":sample["part"],"body":"تعارض مرفوض","blocks":[]},"PUT").status_code==409
        witness=blocks[1]["text"] if blocks else sample["body"].split(".")[0]+"."
        fact=write(writer,csrf,f"/api/projects/{pid}/facts",
          {"subject":"عنصر داخل العمل","predicate":"ورد في النص","value":sample["theme"],"evidence":witness,"section_id":sid})
        assert fact.status_code==200,fact.text
        assert fact.json()["evidence_status"]=="literal_unverified_meaning"
        assert write(writer,csrf,f"/api/projects/{pid}/facts",
          {"subject":"ادعاء","predicate":"قيل","value":"شيء لم يحدث","evidence":"اقتباس مختلق لا وجود له","section_id":sid}).status_code==422
        changed=write(writer,csrf,f"/api/projects/{pid}/sections/{sid}",
          {"version":2,"title":sample["part"],"body":"نسخة بديلة مؤقتة","blocks":[]},"PUT")
        assert changed.status_code==200,changed.text
        assert writer.get(f"/api/projects/{pid}").json()["facts"][0]["evidence_status"]=="source_changed"
        revs=writer.get(f"/api/projects/{pid}/sections/{sid}/revisions")
        assert revs.status_code==200 and any(r["version"]==2 for r in revs.json())
        restore=write(writer,csrf,f"/api/projects/{pid}/sections/{sid}/restore",
          {"current_version":3,"target_version":2})
        assert restore.status_code==200,restore.text
        assert restore.json()["body"]==sample["body"]
        assert restore.json()["blocks"]==blocks
        assert restore.json()["version"]==4
        # Persist restart-like authentication: new TestClient with same database, real login credentials are not assumed available.
        record=writer.get(f"/api/projects/{pid}").json()
        assert record["project"]["scratchpad"]=="أفكار خاصة حول "+sample["theme"]
        assert record["project"]["checkpoint"]["next"]=="كتابة أول مقطع"
        assert record["sections"][0]["version"]==4
        assert intruder.get(f"/api/projects/{pid}").status_code==404
        export=writer.get(f"/api/projects/{pid}/export")
        assert export.status_code==200,export.text
        snapshot=export.json()
        assert snapshot["project"]["kind"]==genre
        assert any(r["section_id"]==sid for r in snapshot["revisions"])
        clone=write(writer,csrf,"/api/import",{"data":snapshot})
        assert clone.status_code==200,clone.text
        new=writer.get(f'/api/projects/{clone.json()["id"]}').json()
        assert new["project"]["kind"]==genre
        assert new["sections"][0]["body"]==sample["body"]
        assert new["sections"][0]["blocks"]==blocks
        assert intruder.get(f'/api/projects/{clone.json()["id"]}').status_code==404
        if genre=="screenplay":
            out=writer.get(f"/api/projects/{pid}/fountain")
            assert out.status_code==200 and "هدى" in out.text
            assert "تضع هدى التذكرة" in out.text
            imported=write(writer,csrf,f"/api/projects/{pid}/fountain/import",
              {"text":"Title: اختبار\n\n.داخلي - غرفة - صباح\n\n!تفتح سارة النافذة.\n\n@سارة\nوصلت الرسالة.\n"})
            assert imported.status_code==200,imported.text
            assert imported.json()["added_scenes"]==1
        else:
            assert writer.get(f"/api/projects/{pid}/fountain").status_code==422
        assert "الكاتب" in instruction(genre) and "لا تكتب" in instruction(genre)

@pytest.mark.parametrize("genre",list(GENRES))
def test_chat_shared_context_is_opt_in(genre,monkeypatch):
    """Confidentiality and genre routing; no real model call is made."""
    monkeypatch.delenv("PILOT_INVITE_MODE",raising=False)
    captured=[]
    async def fake_ai(kind,message,context,history):
        captured.append((kind,message,context,history))
        return {"reply":"ما الذي تريد توضيحه؟","questions":["ما الخطوة التالية؟"],"suggestions":[]}
    monkeypatch.setattr(main,"analyze",fake_ai)
    with TestClient(app) as writer:
        csrf=account(writer);p=write(writer,csrf,"/api/projects",{"title":"تجربة خصوصية "+genre,"kind":genre}).json()
        pid=p["id"]
        up=write(writer,csrf,f"/api/projects/{pid}",{"version":1,"title":p["title"],
            "premise":"","scratchpad":"معلومة خاصة لا ترسل دون إذن","structure":{"theme":"سر مبدع"},
            "checkpoint":{}},"PUT")
        assert up.status_code==200
        s=write(writer,csrf,f"/api/projects/{pid}/sections",{"title":"مشهد سري"}).json()
        sec=write(writer,csrf,f'/api/projects/{pid}/sections/{s["id"]}',
                  {"title":"مشهد سري","body":"المحتوى خاص","blocks":[],"version":1},"PUT")
        assert sec.status_code==200
        ask=write(writer,csrf,f"/api/projects/{pid}/chat",{"message":"ما الذي أراجعه؟"})
        assert ask.status_code==200,ask.text
        assert captured[-1][0]==genre and captured[-1][2]=="" and captured[-1][3]==[]
        shared=write(writer,csrf,f"/api/projects/{pid}/chat",
           {"message":"حلل المعلومات التي سمحت بمشاركتها","share_scratchpad":True,
            "share_structure":True,"section_ids":[s["id"]],"share_history":True})
        assert shared.status_code==200,shared.text
        assert all(z in captured[-1][2] for z in ("معلومة خاصة","سر مبدع","المحتوى خاص"))
        assert len(captured[-1][3])==2
        assert writer.get(f"/api/projects/{pid}/chat").status_code==200
        assert write(writer,csrf,f"/api/projects/{pid}/chat",{},"DELETE").status_code==200
        assert writer.get(f"/api/projects/{pid}/chat").json()==[]

def test_invalid_genres_and_unsafe_screenplay_blocks(monkeypatch):
    monkeypatch.delenv("PILOT_INVITE_MODE",raising=False)
    with TestClient(app) as writer:
        csrf=account(writer)
        assert write(writer,csrf,"/api/projects",{"title":"شعر","kind":"poetry"}).status_code==422
        p=write(writer,csrf,"/api/projects",{"title":"تجربة سيناريو","kind":"screenplay"}).json()
        s=write(writer,csrf,f'/api/projects/{p["id"]}/sections',{"title":"مشهد"}).json()
        assert write(writer,csrf,f'/api/projects/{p["id"]}/sections/{s["id"]}',
          {"version":1,"title":"مشهد","body":"","blocks":[{"type":"unsafe","text":"شيء"}]},"PUT").status_code==422
