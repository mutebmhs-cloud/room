import os,sys,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
fd,path=tempfile.mkstemp(suffix='.db');os.close(fd)
os.environ['DATABASE_URL']='sqlite:///'+path
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Invite
from app.security import digest
import app.main as main
from scripts.convert_v6_export import convert_one

def post(c,csrf,path,data,method='POST'):
    return c.request(method,path,json=data,headers={'X-CSRF-Token':csrf})

def test_extended(monkeypatch):
  with TestClient(app) as client:
    with SessionLocal() as db: db.add(Invite(token_hash=digest('exclusive-invite-123'))); db.commit()
    auth=client.post('/api/auth/register',json={'email':'extended@writer.test','password':'LongPassword!!!!!2026','invite':'exclusive-invite-123'})
    assert auth.status_code==200,auth.text
    csrf=auth.json()['csrf']
    assert client.post('/api/auth/register',json={'email':'second@writer.test','password':'LongPassword!!!!!2026','invite':'exclusive-invite-123'}).status_code==403
    pid=post(client,csrf,'/api/projects',{'title':'سيناريو الاختبار','kind':'screenplay'}).json()['id']
    sid=post(client,csrf,f'/api/projects/{pid}/sections',{'title':'مشهد عربي'}).json()['id']
    text='لم أفهم لماذا توقّف الكاتب عن هذا المشهد. 🎬'
    blocks=[{'type':'heading','text':'داخلي - محطة - ليل'},{'type':'action','text':text},{'type':'character','text':'مريم'},{'type':'dialogue','text':'سأعود غدًا.'}]
    saved=post(client,csrf,f'/api/projects/{pid}/sections/{sid}',{'title':'مشهد عربي','body':'','blocks':blocks,'version':1},'PUT')
    assert saved.status_code==200,saved.text
    f=post(client,csrf,f'/api/projects/{pid}/facts',{'subject':'مريم','predicate':'تقرر','value':'العودة','evidence':text,'section_id':sid})
    assert f.status_code==200,f.text
    assert client.get(f'/api/projects/{pid}').json()['facts'][0]['evidence_status']=='literal_unverified_meaning'
    revised=post(client,csrf,f'/api/projects/{pid}/sections/{sid}',{'title':'مشهد عربي','body':'','blocks':[{'type':'action','text':'نص جديد'}],'version':2},'PUT')
    assert revised.status_code==200
    assert client.get(f'/api/projects/{pid}').json()['facts'][0]['evidence_status']=='source_changed'
    # Mock service: guarantee no text is sent unless checkbox/flag was chosen
    calls=[]
    async def fake(kind,message,context,history):
        calls.append({'kind':kind,'msg':message,'context':context,'history':history})
        return {'reply':'ما هدف الشخصية في هذا المشهد؟','questions':['ما الذي يتغيّر؟'],'suggestions':[{'field':'goal','value':'العودة','reason':'ورد في سؤال الكاتب'}]}
    monkeypatch.setattr(main,'analyze',fake)
    r=post(client,csrf,f'/api/projects/{pid}/chat',{'message':'لديّ مشكلة في الصراع.'})
    assert r.status_code==200,r.text
    assert calls[-1]['context']=='' and calls[-1]['history']==[]
    p=post(client,csrf,f'/api/projects/{pid}',{'version':1,'title':'سيناريو الاختبار','premise':'','structure':{'goal':'النجاة'},'scratchpad':'سرّ عائلي','checkpoint':{'summary':'بلغت منتصف الفصل'}},'PUT')
    assert p.status_code==200
    r=post(client,csrf,f'/api/projects/{pid}/chat',{'message':'كيف أرتّب الأحداث؟','share_scratchpad':True,'share_structure':True,'share_history':True,'section_ids':[sid]})
    assert r.status_code==200,r.text
    assert 'سرّ عائلي' in calls[-1]['context'] and 'النجاة' in calls[-1]['context'] and len(calls[-1]['history'])==2
    assert len(client.get(f'/api/projects/{pid}/chat').json())==4
    assert post(client,csrf,f'/api/projects/{pid}/chat',{},'DELETE').status_code==200
    assert client.get(f'/api/projects/{pid}/chat').json()==[]
    # backup and import preserve Arabic + metadata; account deletion cleans sessions
    snapshot=client.get(f'/api/projects/{pid}/export').json()
    imported=post(client,csrf,'/api/import',{'data':snapshot})
    assert imported.status_code==200,imported.text
    newp=client.get(f'/api/projects/{imported.json()["id"]}').json()
    assert '🎬' not in newp['sections'][0]['blocks'][0]['text']  # saved newest content, not stale history
    assert newp['project']['scratchpad']=='سرّ عائلي'
    result=post(client,csrf,'/api/account/delete',{'password':'LongPassword!!!!!2026'})
    assert result.status_code==200,result.text
    assert client.get('/api/projects').status_code==401
    assert client.post('/api/auth/login',json={'email':'extended@writer.test','password':'LongPassword!!!!!2026'}).status_code==401
  try: os.remove(path)
  except OSError: pass

def test_v6_converter():
    p={'genre':'screenplay','title':'فيلم اختبار','intent':'رحلة','docs':[{'id':'sec1','title':'م1','kind':'screenplay','body':'','scene':{'interior':'INT','location':'بيت','time':'ليل'},'blocks':[{'type':'action','text':'ذهب إلى البيت.'}]}],'facts':[],'assistantState':{'freeInput':'نقطة البداية','checkpoint':{'docId':'sec1','done':'أنجزت المشهد','next':'التالي','question':'كيف؟'}},'structure':{},'tasks':[],'notes':[]}
    result=convert_one(p)
    assert result['format']=='writer-cloud-v1' and result['sections'][0]['blocks'][0]['type']=='heading'
    assert result['project']['scratchpad']=='نقطة البداية'
    assert result['project']['checkpoint']['summary']=='أنجزت المشهد'

def test_fountain_roundtrip_parser():
    from app.fountain import parse, FountainError
    source='Title: فيلم\n\n.داخلي - غرفة - ليل\n\n!تجلس مريم قرب النافذة.\n\n@مريم\nهل وصلت الرسالة؟\n(بهمس)\nأخبرني.\n>قطع إلى\n\n.خارجي - شارع - فجر\n!تظهر السيارة.\n'
    scenes=parse(source)
    assert len(scenes)==2
    assert [v['type'] for v in scenes[0]['blocks']]==['heading','action','character','dialogue','parenthetical','dialogue','transition']
    assert scenes[0]['blocks'][3]['text']=='هل وصلت الرسالة؟'
    try: parse('Title: عنوان\n\nهذا النص خارج المشاهد')
    except FountainError: pass
    else: assert False,'Must reject content outside scenes'
    try: parse('.مشهد\n[[ملاحظة متقدمة]]')
    except FountainError: pass
    else: assert False,'Must reject unsupported syntax'
