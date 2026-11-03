"""Real Chromium E2E against the current FastAPI source, plus the public deployed URL.
Synthetic-only data. No credentials or private writing materials are printed.
"""
import os, pathlib, subprocess, sys, tempfile, time, urllib.request
from playwright.sync_api import sync_playwright, expect

OUT=pathlib.Path('/tmp/writer-browser-artifacts')
OUT.mkdir(exist_ok=True)
PORT=9187
BASE=f'http://127.0.0.1:{PORT}'
PUBLIC='https://writer-space-pilot-room.onrender.com'
ADMIN_CODE=os.environ['TEST_ADMIN_CODE']
REPO=pathlib.Path(__file__).resolve().parents[1]
steps=[]
errors=[]

def record(name):
    steps.append(name);print('E2E PASS:',name,flush=True)

def poll_health():
    for _ in range(65):
        try:
            with urllib.request.urlopen(BASE+'/health',timeout=3) as r:
                if r.status==200:return
        except Exception:pass
        time.sleep(.4)
    raise AssertionError('Local server did not reach health')

def check_errors(label, page):
    page.on('pageerror',lambda e:errors.append(label+': '+str(e)))

def login_admin(page):
    page.goto(BASE+'/',wait_until='domcontentloaded')
    expect(page.locator('#pilotConsentWrap')).to_be_visible(timeout=10000)
    expect(page.locator('#email')).to_be_hidden()
    page.locator('#password').fill(ADMIN_CODE)
    page.locator('#authSubmit').click()
    expect(page).to_have_url(BASE+'/admin',timeout=15000)
    expect(page.locator('#newWriter')).to_be_visible()
    record('manager login and dashboard navigation')

def make_writer(manager,username):
    assert manager.locator('#newWriter input').count()==1
    manager.locator('#newWriter input[name=display_name]').fill('كاتب تجريبي')
    manager.locator('#newWriter button.primary').click()
    expect(manager.locator('#issued')).to_be_visible()
    code=manager.locator('#issued code').inner_text().strip()
    assert len(code)==10 and code.isalnum()
    expect(manager.get_by_text('كاتب تجريبي',exact=True).first).to_be_visible()
    record('manager creates individualized invite')
    return code

def login_writer(page,username,access):
    page.goto(BASE+'/',wait_until='domcontentloaded')
    expect(page.locator('#pilotConsentWrap')).to_be_visible(timeout=10000)
    expect(page.locator('#email')).to_be_hidden()
    page.locator('#password').fill(access)
    page.locator('#reviewConsent').check()
    page.locator('#authSubmit').click()
    expect(page.locator('#newProject')).to_be_visible(timeout=15000)
    expect(page.get_by_text('دليل الكاتب في مساحة الكاتب')).to_be_visible(timeout=10000)
    page.locator('[data-action=close-modal]').last.click()
    record('writer invitation sign-in, consent and first-login guide')

def create_work(page,kind,label):
    page.locator('#newProject').click()
    expect(page.locator('#createProjectForm')).to_be_visible()
    page.locator('#createProjectForm input[name=title]').fill(label)
    page.locator('#createProjectForm select[name=kind]').select_option(kind)
    page.locator('#createProjectForm button.primary').click()
    expect(page.locator('#scratch')).to_be_visible(timeout=12000)
    page.locator('#scratch').fill('تجربة مصطنعة للنوع '+label)
    page.locator('[data-action=save-project]').first.click()
    page.wait_for_timeout(350)
    expect(page.locator('#scratch')).to_have_value('تجربة مصطنعة للنوع '+label)
    # Reopen the writer's persisted project after a full browser reload.
    page.reload(wait_until='domcontentloaded')
    expect(page.locator('#newProject')).to_be_visible(timeout=12000)
    page.locator('#projectNav .project-link').filter(has_text=label).first.click()
    page.locator('[data-tab=free]').first.click()
    expect(page.locator('#scratch')).to_have_value('تجربة مصطنعة للنوع '+label)
    page.locator('[data-tab=manuscript]').first.click()
    page.once('dialog',lambda d:d.accept('مقطع تجريبي'))
    page.locator('[data-action=new-section]').first.click()
    if kind=='screenplay':
        expect(page.locator('#blockList')).to_be_visible()
        page.locator('[data-action=add-block]').first.click()
        page.locator('[data-block-type="0"]').select_option('dialogue')
        page.locator('[data-block-text="0"]').fill('حوار مصطنع للفحص.')
    else:
        expect(page.locator('#editorBody')).to_be_visible()
        page.locator('#editorBody').fill('نص مصطنع يخص اختبار '+label)
    page.locator('[data-action=save-section]').first.click()
    page.wait_for_timeout(350)
    page.locator('[data-tab=structure]').first.click()
    page.locator('[data-structure-field=protagonist]').fill('شخصية تجريبية')
    page.locator('[data-action=save-project]').first.click()
    page.locator('[data-tab=coach]').first.click()
    expect(page.get_by_text('مدربك الشخصي').first).to_be_visible()
    record('complete writing/editing path: '+kind)
    page.locator('[data-action=view][data-view=home]').first.click()
    expect(page.locator('#newProject')).to_be_visible()

def run():
    with tempfile.TemporaryDirectory(prefix='writer-real-browser-') as td:
        env=os.environ.copy()
        env['DATABASE_URL']='sqlite:///'+td+'/writer.db'
        env['APP_ENV']='development'
        env['PILOT_INVITE_MODE']='1'
        env['PILOT_ADMIN_USERNAME']='test-admin'
        env['PILOT_ADMIN_CODE']=ADMIN_CODE
        env['PILOT_EPHEMERAL']='0'
        env.pop('OPENAI_API_KEY',None)
        server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--port',str(PORT),'--host','127.0.0.1'],cwd=REPO,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
        try:
            poll_health()
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
                manager=browser.new_context(viewport={'width':1400,'height':950},locale='ar-SA')
                writer=browser.new_context(viewport={'width':1280,'height':920},locale='ar-SA')
                m=manager.new_page();w=writer.new_page()
                check_errors('manager',m);check_errors('writer',w)
                login_admin(m)
                access=make_writer(m,'writertrial01')
                m.screenshot(path=str(OUT/'manager.png'),full_page=True)
                login_writer(w,'writertrial01',access)
                w.screenshot(path=str(OUT/'writer-guide-closed.png'),full_page=True)
                for kind,name in [('novel','رواية تجريبية'),('short','قصة قصيرة تجريبية'),('flash','قصة خاطفة تجريبية'),('children','قصة أطفال تجريبية'),('screenplay','سيناريو تجريبي')]:
                    create_work(w,kind,name)
                w.locator('[data-action=view][data-view=report]').first.click()
                expect(w.locator('#feedbackForm')).to_be_visible()
                w.locator('#feedbackForm input[name=subject]').fill('ملاحظة تجربة المتصفح')
                w.locator('#feedbackForm textarea[name=detail]').fill('بلاغ مصطنع للتأكد من ظهور الملاحظات في لوحة الإدارة.')
                w.locator('#feedbackForm button.primary').click()
                record('writer feedback submission')
                m.locator('#refreshFeedback').click()
                expect(m.get_by_text('ملاحظة تجربة المتصفح')).to_be_visible(timeout=8000)
                record('manager review of writer feedback')
                m.locator('#refresh').click()
                m.locator('[data-action=view]').first.click()
                expect(m.locator('#inspector [data-project]').first).to_be_visible(timeout=8000)
                m.locator('#inspector [data-project]').first.click()
                expect(m.get_by_text('قراءة فقط؛ تم تسجيل عملية الاطلاع.',exact=False)).to_be_visible()
                record('manager read-only project review')
                w.locator('#userBtn').click()
                w.locator('[data-action=my-review-log]').click()
                expect(w.get_by_text('read_project',exact=False)).to_be_visible(timeout=8000)
                record('writer can inspect manager access log')
                w.locator('[data-action=close-modal]').last.click()
                w.screenshot(path=str(OUT/'writer-dashboard.png'),full_page=True)
                mobile=browser.new_context(viewport={'width':390,'height':844},locale='ar-SA',storage_state=writer.storage_state())
                mb=mobile.new_page();check_errors('mobile',mb)
                mb.goto(BASE+'/')
                expect(mb.locator('#newProject')).to_be_visible(timeout=10000)
                mb.screenshot(path=str(OUT/'mobile.png'),full_page=True)
                assert mb.evaluate('document.documentElement.scrollWidth<=window.innerWidth+2'),'horizontal overflow mobile'
                record('mobile authenticated RTL layout without overflow')
                with browser.new_context() as unauth:
                    pub=unauth.new_page()
                    check_errors('live-public',pub)
                    pub.goto(PUBLIC+'/')
                    expect(pub.get_by_text('مساحة الكاتب',exact=False).first).to_be_visible(timeout=80000)
                    expect(pub.locator('#authForm')).to_be_visible()
                    record('public deployed URL loaded in Chromium')
                browser.close()
        finally:
            server.terminate()
            try:server.wait(timeout=6)
            except subprocess.TimeoutExpired:server.kill()
    print('BROWSER TOTAL:',len(steps),'JS_ERRORS:',errors,flush=True)
    if errors:raise AssertionError(str(errors))
if __name__=='__main__':run()
