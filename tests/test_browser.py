"""UI test: browser interactions backed by an isolated FastAPI TestClient.
Browser navigation is blocked in this test environment, so API calls are bridged.
"""
import os,time,tempfile,atexit
fd,test_db=tempfile.mkstemp(prefix='writer_browser_',suffix='.db');os.close(fd)
os.environ['DATABASE_URL']='sqlite:///'+test_db
atexit.register(lambda: os.path.exists(test_db) and os.unlink(test_db))
from playwright.sync_api import sync_playwright
from fastapi.testclient import TestClient
from app.main import app
from pathlib import Path
STATIC=Path(__file__).resolve().parents[1]/'app'/'static'
url='https://writer.test'
from app.db import SessionLocal
from app.models import Invite
from app.db import Base,engine
Base.metadata.create_all(bind=engine)
from app.security import digest
import secrets
invite=secrets.token_urlsafe(24)
with SessionLocal() as d:
    d.add(Invite(token_hash=digest(invite))); d.commit()
email='pilot_'+secrets.token_hex(4)+'@writer.test'
errors=[]
class Report(list):
  def append(self,x): print("STEP",x,flush=True); super().append(x)
steps=Report()
with TestClient(app) as client, sync_playwright() as p:
  def backend(path,method='GET',body=None,headers=None):
    response=client.request(method,path,content=body,headers=headers or {})
    return {'status':response.status_code,'body':response.text,'type':response.headers.get('content-type','application/json')}
  def attach(page):
    page.expose_function('backend',backend)
    markup=(STATIC/'index.html').read_text()
    import re
    markup=re.sub(r'<script[^>]*src="/static/app.js"[^>]*></script>','',markup)
    markup=re.sub(r'<link[^>]*href="/static/style.css"[^>]*>','',markup)
    page.set_content(markup,wait_until='domcontentloaded')
    page.add_style_tag(content=(STATIC/'style.css').read_text())
    page.evaluate("""() => {window.fetch=async (path,opts={})=>{const r=await window.backend(path,opts.method||'GET',opts.body||null,opts.headers||{});return new Response(r.body,{status:r.status,headers:{'content-type':r.type}})}}""")
    page.add_script_tag(content=(STATIC/'app.js').read_text())
  browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
  page=browser.new_page(viewport={'width':1420,'height':900},locale='ar-SA')
  attach(page)
  page.set_default_timeout(7000)
  page.on('pageerror',lambda e:errors.append(str(e)))
  # HTML loaded by attach()
  page.locator('#toggleAuth').click();page.locator('#email').fill(email);page.locator('#password').fill('LongPassword!2026!!');page.locator('#invite').fill(invite);page.locator('#authSubmit').click()
  page.locator('#newProject').wait_for(timeout=15000);steps.append('register/login')
  page.screenshot(path='/mnt/data/منصة_مساحة_الكاتب_السحابية/docs/screenshot_home.png',full_page=True)
  page.locator('#newProject').click(); page.locator('#createProjectForm input[name=title]').fill('رواية ذاكرة المدن');page.locator('#createProjectForm button.primary').click()
  page.locator('#scratch').wait_for(timeout=10000);steps.append('project create')
  page.locator('#scratch').fill('بدأت بطلة الرواية البحث عن رسالة قديمة تركها جدها.');page.locator('[data-action=save-project]').first.click()
  page.wait_for_timeout(1100);steps.append('free writing and save')
  page.locator('[data-tab=manuscript]').click();page.once('dialog',lambda dialog:dialog.accept('الفصل الأول'));page.locator('[data-action=new-section]').first.click()
  page.locator('#editorBody').wait_for(timeout=10000)
  page.locator('#editorBody').fill('وصلت مريم إلى المنزل ثم قرأت الرسالة التي كانت تخشاها.')
  page.locator('[data-action=save-section]').first.click();page.wait_for_timeout(600);steps.append('manuscript save')
  page.locator('[data-tab=checkpoint]').click();page.locator('[data-checkpoint-field=summary]').fill('كتبت المشهد الافتتاحي واستقر قرار مريم')
  page.locator('[data-checkpoint-field=next]').fill('توضيح رد فعل الأخ على الرسالة');page.locator('[data-action=save-project]').first.click()
  page.wait_for_timeout(600);steps.append('checkpoint')
  page.locator('[data-tab=structure]').click();page.locator('[data-structure-field=protagonist]').fill('مريم');page.locator('[data-action=save-project]').first.click();steps.append('structure')
  page.locator('[data-tab=facts]').click();page.locator('input[name=subject]').fill('مريم');page.locator('input[name=predicate]').fill('تقرأ');page.locator('input[name=value]').fill('الرسالة');page.locator('#factForm button.primary').click()
  page.locator('.list-item').filter(has_text='الرسالة').first.wait_for(timeout=8000);steps.append('facts')
  page.locator('[data-tab=coach]').click();page.get_by_text('السببية',exact=True).wait_for();steps.append('coach')
  page.locator('[data-tab=chat]').first.click();page.locator('#chatWindow').wait_for();steps.append('chat UI')
  page.locator('[data-tab=overview]').click();page.screenshot(path='/mnt/data/منصة_مساحة_الكاتب_السحابية/docs/screenshot_project.png',full_page=True)
  page.locator('#exportBtn').click();steps.append('export click')
  page.evaluate('initialize()');page.locator('#newProject').wait_for(timeout=10000);page.locator('.project-link').first.click();page.locator('[data-tab=free]').first.click()
  assert 'بدأت بطلة الرواية' in page.locator('#scratch').input_value();steps.append('persistence after reload')
  # screenplay separate path
  page.locator('#newProject').click();page.locator('#createProjectForm input[name=title]').fill('سيناريو القطار');page.locator('#createProjectForm select[name=kind]').select_option('screenplay');page.locator('#createProjectForm button.primary').click();page.locator('#scratch').wait_for();page.locator('[data-tab=manuscript]').click()
  page.once('dialog',lambda dialog:dialog.accept('داخلي - قطار - مساء'));page.locator('[data-action=new-section]').first.click();page.locator('#blockList').wait_for(state='attached')
  page.locator('[data-action=add-block]').click();page.locator('[data-block-type="0"]').select_option('dialogue');page.locator('[data-block-text="0"]').fill('لن أغادر قبل أن أعرف الحقيقة.');page.locator('[data-action=save-section]').first.click()
  page.screenshot(path='/mnt/data/منصة_مساحة_الكاتب_السحابية/docs/screenshot_screenplay.png',full_page=True)
  steps.append('screenplay block editor')
  mobile=browser.new_page(viewport={'width':390,'height':844},locale='ar-SA')
  attach(mobile)
  mobile.locator('#newProject').wait_for(timeout=8000);mobile.screenshot(path='/mnt/data/منصة_مساحة_الكاتب_السحابية/docs/screenshot_mobile.png',full_page=True)
  assert mobile.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1')
  steps.append('mobile width')
  browser.close()
print('PASS',len(steps),'steps:',', '.join(steps));print('JS ERRORS:',errors)
assert not errors,errors
