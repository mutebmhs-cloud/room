"""Literal manuscript revision comparison is author scoped and non-destructive."""
import secrets
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Invite
from app.security import digest

def start(client):
    invite=secrets.token_urlsafe(36)
    with SessionLocal() as db:
        db.add(Invite(token_hash=digest(invite)));db.commit()
    response=client.post('/api/auth/register',json={
        'email':secrets.token_hex(10)+'@versions.example',
        'password':'OnlyForTestWriter2026!!','invite':invite})
    assert response.status_code==200,response.text
    return response.json()['csrf']

def change(client,csrf,method,url,payload):
    return client.request(method,url,json=payload,headers={'X-CSRF-Token':csrf})

def test_revision_comparison_and_access_isolation():
    with TestClient(app) as writer,TestClient(app) as stranger:
        csrf=start(writer)
        start(stranger)
        p=change(writer,csrf,'POST','/api/projects',{
            'title':'مقارنة اختبار '+secrets.token_hex(4),'kind':'novel'})
        pid=p.json()['id']
        section=change(writer,csrf,'POST',f'/api/projects/{pid}/sections',{
            'title':'مقطع'})
        sid=section.json()['id']
        url=f'/api/projects/{pid}/sections/{sid}'
        first=change(writer,csrf,'PUT',url,{
            'version':1,'title':'مقطع','body':'سلمى حملت المفتاح.\nانتظرت عند الباب.',
            'blocks':[]})
        assert first.status_code==200
        second=change(writer,csrf,'PUT',url,{
            'version':2,'title':'مقطع','body':'سلمى أعطت المفتاح إلى مها.\nانتظرت عند الباب.',
            'blocks':[]})
        assert second.status_code==200
        diff=writer.get(f'/api/projects/{pid}/manuscript-tools/compare',params={'section_id':sid})
        assert diff.status_code==200,diff.text
        result=diff.json()
        assert result['source_version']==2
        assert result['current_version']==3
        assert result['changes']
        assert any('مها' in x['after'] for x in result['changes'])
        assert result['note'].startswith('المقارنة حرفية')
        assert stranger.get(f'/api/projects/{pid}/manuscript-tools/compare',params={'section_id':sid}).status_code==404
        assert writer.get(f'/api/projects/{pid}/manuscript-tools/compare',params={
            'section_id':sid,'target_version':9999}).status_code==404
        assert writer.get(f'/api/projects/{pid}').json()['sections'][0]['body'].startswith('سلمى أعطت')
