"""Isolated PostgreSQL integration smoke. Never target a production DATABASE_URL."""
import os,secrets
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.db import engine,SessionLocal
from app.models import Invite
from app.security import digest

def main():
    db_url=os.environ.get('DATABASE_URL','')
    assert 'localhost:5432/writer_space_ci' in db_url, 'Refusing non-CI database'
    with TestClient(app) as c:
        with engine.connect() as conn:
            tables={row[0] for row in conn.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'")).all()}
        assert {'projects','sections','revisions','writer_analysis_drafts',
                'writer_section_summaries','writer_progress'}<=tables
        code='ci-'+secrets.token_urlsafe(25)
        with SessionLocal() as db:
            db.add(Invite(token_hash=digest(code)));db.commit()
        login=c.post('/api/auth/register',json={
            'email':'pg-ci-'+secrets.token_hex(8)+'@writer.test',
            'password':'Only_for_CI_pilot_2026!!','invite':code})
        assert login.status_code==200,login.text
        csrf=login.json()['csrf']
        def send(method,path,body):
            return c.request(method,path,json=body,headers={'X-CSRF-Token':csrf})
        first=send('POST','/api/projects',{'title':'تجربة PostgreSQL','kind':'novel'})
        assert first.status_code==200,first.text
        pid=first.json()['id']
        duplicate=send('POST','/api/projects',{'title':' تجربة  PostgreSQL ','kind':'novel'})
        assert duplicate.status_code==200 and duplicate.json()['id']==pid
        section=send('POST',f'/api/projects/{pid}/sections',{'title':'فصل تجريبي'})
        assert section.status_code==200,section.text
        sid=section.json()['id']
        for version in range(1,6):
            out=send('PUT',f'/api/projects/{pid}/sections/{sid}',{
                'version':version,'title':'فصل تجريبي',
                'body':'نص اختبار PostgreSQL '+str(version),'blocks':[]})
            assert out.status_code==200,out.text
        versions=c.get(f'/api/projects/{pid}/sections/{sid}/revisions')
        assert [x['version'] for x in versions.json()]==[5,4,3]
        summary=send('PUT',f'/api/projects/{pid}/intelligence/sections/{sid}/summary',
                     {'section_version':6,'summary':'عودة الشخصية','central_event':'قرار العودة'})
        assert summary.status_code==200,summary.text
        progress=send('PUT',f'/api/projects/{pid}/intelligence/progress',
                      {'tab':'manuscript','section_id':sid,'cursor_offset':7})
        assert progress.status_code==200,progress.text
        export=c.get(f'/api/projects/{pid}/export')
        assert export.status_code==200,export.text
        restored=send('POST','/api/import',{'data':export.json()})
        assert restored.status_code==200,restored.text
        intel=c.get(f"/api/projects/{restored.json()['id']}/intelligence")
        assert intel.status_code==200,intel.text
        assert len(intel.json()['summaries'])==1
        assert intel.json()['progress']['cursor_offset']==7
        with engine.connect() as conn:
            assert conn.execute(text('SELECT count(*) FROM writer_section_summaries')).scalar()>=2
        print('POSTGRESQL_INTEGRATION_OK: schema, invite, idempotency, revisions, summaries, cursor, export/import')

if __name__=='__main__':
    main()
