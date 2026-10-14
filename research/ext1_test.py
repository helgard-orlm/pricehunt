"""Проверка расширения 1.0 в Chromium: товар с вкладки -> панель -> (по желанию) поиск агента."""
import sys, os, time, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright
import ali
EXT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extension")
PID = sys.argv[1]; RUN_SECS = int(sys.argv[2]) if len(sys.argv) > 2 else 0
errs = []
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(tempfile.mkdtemp(), headless=False, executable_path=ali.CHROME,
        viewport={"width": 420, "height": 1100}, args=["--headless=new", f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
    for _ in range(30):
        if ctx.service_workers: break
        time.sleep(1)
    sw = ctx.service_workers[0]
    eid = sw.url.split("/")[2]
    sw.evaluate("""chrome.storage.local.set({model:{base:'http://192.168.1.104:8920',kind:'openai',model:'minicpm-v4.7',key:'',vision:true}})""")
    ctx.add_cookies([{"name": "aep_usuc_f", "value": ali.region_cookie("UA", "USD"), "domain": ".aliexpress.com", "path": "/"}])
    prod = ctx.new_page()
    prod.goto(f"https://www.aliexpress.com/item/{PID}.html", wait_until="domcontentloaded", timeout=60000)
    for _ in range(30):
        tabs = sw.evaluate("chrome.tabs.query({url:'*://*.aliexpress.com/item/*'}).then(t=>t.map(x=>x.id))")
        stored = sw.evaluate(f"chrome.storage.session.get().then(s=>Object.keys(s))")
        if stored: break
        time.sleep(1)
    print("вкладки товара:", tabs, "| данные страницы в памяти:", stored)
    panel = ctx.new_page()
    panel.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
    panel.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    panel.goto(f"chrome-extension://{eid}/panel.html?tab={tabs[0]}")
    panel.wait_for_function("!document.getElementById('pcard').hidden || !document.getElementById('noproduct').textContent.startsWith('читаю')", timeout=90000)
    panel.wait_for_timeout(1500)
    print("товар:", panel.inner_text("#ptitle")[:70] if panel.is_visible("#pcard") else panel.inner_text("#noproduct"))
    print("группы:", [g.inner_text() for g in panel.locator(".gname").all()], "| кнопок:", panel.locator(".chip").count())
    print("цена:", panel.inner_text("#pprice") if panel.is_visible("#pcard") else "-")
    print("кнопка:", panel.inner_text("#go"), "| активна:", panel.is_enabled("#go"))
    panel.screenshot(path="imgs/ext1_panel.png", full_page=True)
    if RUN_SECS and panel.is_enabled("#go"):
        panel.click("#go"); t = time.time(); shown = 0
        while time.time() - t < RUN_SECS:
            time.sleep(5)
            lines = panel.inner_text("#log").splitlines() if panel.locator("#log").count() else []
            for l in lines[shown:]: print("  ", l[:160], flush=True)
            shown = len(lines)
            if "готово за" in panel.inner_text("#log"): break
        print("ВЕРДИКТ:", panel.inner_text("#verdict"))
        for it in panel.locator("#list .item").all()[:6]: print(" •", it.inner_text().replace("\n", " | ")[:200])
        panel.screenshot(path="imgs/ext1_result.png", full_page=True)
    ctx.close()
print("ошибки панели:", errs or "нет")
