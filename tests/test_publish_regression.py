import json, secrets, tempfile, os, sys
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models import Invite
from app.security import digest
from app.main import app
from scripts.convert_v6_export import convert_one

def test_import_legacy_string_id_and_block_bad_references():
    with TestClient(app) as client:
        code=secrets.token_urlsafe(24)
        with SessionLocal() as db:
            db.add(Invite(token_hash=digest(code)));db.commit()
        login=client.post('/api/auth/register',json={'email':f'{secrets.token_hex(10)}@example.org','password':'A_secure_password_45678','invite':code})
        assert login.status_code==200,login.text
        csrf=login.json()['csrf'];h={'X-CSRF-Token':csrf}
        p={'genre':'screenplay','title':'فيلم اختبار','intent':'رحلة','docs':[{'id':'sec1','title':'م1','kind':'screenplay','body':'','scene':{'interior':'INT','location':'بيت','time':'ليل'},'blocks':[{'type':'action','text':'دخلت إلى البيت.'}]}], 'facts':[], 'assistantState':{'checkpoint':{'docId':'sec1','done':'أنجزت المشهد'}}}
        converted=convert_one(p)
        r=client.post('/api/import',json={'data':converted},headers=h)
        assert r.status_code==200,r.text
        obj=client.get('/api/projects/'+str(r.json()['id'])).json()
        assert obj['project']['checkpoint']['section_id']==obj['sections'][0]['id']
        bad=json.loads(json.dumps(converted));bad['sections'].append(dict(bad['sections'][0]));bad['sections'][1]['title']='مشهد مكرر'
        r=client.post('/api/import',json={'data':bad},headers=h)
        assert r.status_code==422
        bad=json.loads(json.dumps(converted));bad['project']['checkpoint']['section_id']='does-not-exist'
        r=client.post('/api/import',json={'data':bad},headers=h)
        assert r.status_code==422

def test_export_then_import_exact_text():
    with TestClient(app) as client:
        code=secrets.token_urlsafe(24)
        with SessionLocal() as db:db.add(Invite(token_hash=digest(code)));db.commit()
        login=client.post('/api/auth/register',json={'email':f'{secrets.token_hex(10)}@example.org','password':'A_secure_password_45678','invite':code})
        assert login.status_code==200,login.text
        h={'X-CSRF-Token':login.json()['csrf']}
        a=client.post('/api/projects',json={'title':'عمل اختبار الرجوع','kind':'novel'},headers=h).json()['id']
        b=client.post(f'/api/projects/{a}/sections',json={'title':'الفصل الأول'},headers=h).json()['id']
        content='أهلاً بالشخصيات 🎬\n'+('عِبارة مشكّلة ثابتة.\n'*200)
        save=client.put(f'/api/projects/{a}/sections/{b}',json={'version':1,'title':'الفصل الأول','body':content,'blocks':[]},headers=h)
        assert save.status_code==200,save.text
        snapshot=client.get(f'/api/projects/{a}/export').json()
        restore=client.post('/api/import',json={'data':snapshot},headers=h)
        assert restore.status_code==200,restore.text
        payload=client.get('/api/projects/'+str(restore.json()['id'])).json()
        assert payload['sections'][0]['body']==content
