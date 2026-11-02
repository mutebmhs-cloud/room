"""Real headless Chromium writer journeys against an isolated local FastAPI server.
Run as a standalone script in GitHub Actions. No real author data is accessed.
"""
import os,tempfile,subprocess,sys,time,secrets,socket
from pathlib import Path
from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

ROOT=Path(__file__).resolve().parents[1]
fd,dbpath=tempfile.mkstemp(prefix="writer-browser-all-genres-",suffix=".sqlite")
os.close(fd)
os.environ["DATABASE_URL"]="sqlite:///"+dbpath
os.environ.pop("PILOT_INVITE_MODE",None)
from app.db import Base,engine,SessionLocal
from app.models import Invite
from app.security import digest
from app.main import app
Base.metadata.create_all(bind=engine)
invitation="browser-"+secrets.token_urlsafe(24)
with SessionLocal() as db:
    db.add(Invite(token_hash=digest(invitation)));db.commit()
port=9876
env=os.environ.copy()
p=subprocess.Popen([sys.executable,"-m","uvicorn","app.main:app","--host","127.0.0.1","--port",str(port)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
try:
    ready=False
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1",port),timeout=1):ready=True;break
        except OSError:time.sleep(.2)
    assert ready,"Server did not boot"
    steps=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True,args=["--no-sandbox"])
        page=browser.new_page(viewport={"width":1440,"height":900},locale="ar-SA",accept_downloads=True)
        errors=[]
        page.on("pageerror",lambda exc:errors.append(str(exc)))
        page.goto(f"http://127.0.0.1:{port}/",wait_until="domcontentloaded")
        page.locator("#toggleAuth").click()
        page.locator("#email").fill("synthetic-browser-"+secrets.token_hex(5)+"@writer.test")
        page.locator("#password").fill("LongSyntheticPassword_2026")
        page.locator("#invite").fill(invitation)
        page.locator("#authSubmit").click()
        page.locator("#newProject").wait_for(timeout=20000)
        steps.append("real-browser-registration")
        cases=[
            ("novel","رواية اختبار متصفح","فصل البداية","تصل البطلة إلى المدينة القديمة."),
            ("short","قصة قصيرة اختبار متصفح","بداية القصة","يجد التلميذ رسالة تحت باب البيت."),
            ("flash","قصة خاطفة اختبار متصفح","النص","أغلق الباب؛ لكنه ترك المفتاح في الخارج."),
            ("children","قصة أطفال اختبار متصفح","الصفحة الأولى","زرع الأرنب بذرة قرب النهر."),
            ("screenplay","سيناريو اختبار متصفح","مشهد افتتاحي","")
        ]
        for kind,title,section,body in cases:
            page.locator("#newProject").click()
            form=page.locator("#createProjectForm")
            form.wait_for()
            form.locator('input[name="title"]').fill(title)
            form.locator('select[name="kind"]').select_option(kind)
            form.locator("button.primary").click()
            page.locator("#scratch").wait_for()
            page.locator("#scratch").fill("ملاحظات تجريبية خاصة بنوع "+kind)
            page.locator('[data-action="save-project"]').first.click()
            page.locator('[data-tab="manuscript"]').click()
            page.once("dialog",lambda dialog:dialog.accept(section))
            page.locator('[data-action="new-section"]').first.click()
            if kind!="screenplay":
                page.locator("#editorBody").wait_for()
                page.locator("#editorBody").fill(body)
            else:
                page.locator('[data-action="add-block"]').click()
                page.locator('[data-block-type="0"]').select_option("action")
                page.locator('[data-block-text="0"]').fill("تقترب مريم من الباب وتقرأ رسالة.")
            page.locator('[data-action="save-section"]').first.click()
            page.locator('[data-tab="growth"]').click()
            page.locator("#growthForm").wait_for(timeout=15000)
            assert page.locator("#growthForm select[name=dimension] option").count()>=5
            page.locator('#growthForm textarea[name="observation"]').fill("أحتاج إلى مراجعة معيار نوع الكتابة.")
            page.locator('#growthForm textarea[name="next_action"]').fill("مراجعة النص وفق الأدلة.")
            page.locator('#growthForm button.primary').click()
            page.locator("#growthForm").wait_for()
            assert page.locator("text=سجل تطورك الذاتي").count()>0
            with page.expect_download(timeout=20000) as dl:
                page.locator('a[href*="/api/pro-export/"]').click()
            d=dl.value
            assert d.suggested_filename.endswith(".docx")
            steps.append(kind+":write-save-progress-export")
            page.locator('[data-action="home"]').first.click() if page.locator('[data-action="home"]').count() else page.locator('.nav-link[data-view="home"]').first.click()
            page.locator("#newProject").wait_for()
        assert not errors,"Javascript page errors: "+str(errors)
        browser.close()
    print("REAL_CHROMIUM_GENRE_RESULT",steps)
finally:
    p.terminate()
    try:p.wait(timeout=8)
    except subprocess.TimeoutExpired:p.kill()
    Path(dbpath).unlink(missing_ok=True)
