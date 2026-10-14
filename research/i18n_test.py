"""Расширение 1.1: панель на en/ru/uk, «Проверить» на адресе модели и на адресе стенда, карточка товара по-английски."""
import sys, os, time, tempfile, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright
import ali
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extension")
# копия с доступом к адресам заранее: окно «разрешить адрес» в безголовом браузере некому нажать (иначе проверка висит)
import shutil, json
EXT = os.path.join(tempfile.mkdtemp(), "ext"); shutil.copytree(SRC, EXT)
_m = json.load(open(EXT + "/manifest.json")); _m["host_permissions"] += ["http://*/*"]; json.dump(_m, open(EXT + "/manifest.json", "w"))
PID = sys.argv[1] if len(sys.argv) > 1 else None
errs = []
CYR = re.compile("[А-Яа-яЁёІіЇїЄєҐґ]")
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(tempfile.mkdtemp(), headless=False, executable_path=ali.CHROME,
        viewport={"width": 420, "height": 1100}, args=["--headless=new", "--lang=en-US", f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
    for _ in range(30):
        if ctx.service_workers: break
        time.sleep(1)
    sw = ctx.service_workers[0]; eid = sw.url.split("/")[2]
    print("имя расширения:", sw.evaluate("chrome.i18n.getMessage('ext_name')"), "| версия:", sw.evaluate("chrome.runtime.getManifest().version"))
    panel = ctx.new_page()
    panel.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
    panel.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    panel.goto(f"chrome-extension://{eid}/panel.html")
    panel.wait_for_timeout(1500)
    body = panel.inner_text("body")
    print("язык по умолчанию:", panel.eval_on_selector("#langsel", "e=>e.value"), "| кириллица на странице:", CYR.findall(body)[:5] or "нет")
    print("кнопка:", panel.inner_text("#go"), "|", panel.inner_text("#noproduct"))
    for base in ["http://192.168.1.107:8931", "http://192.168.1.104:8920"]:
        panel.fill("#base", base); panel.evaluate("document.getElementById('probeout').textContent=''"); panel.click("#probe")
        for _ in range(60):
            out = panel.inner_text("#probeout")
            if out and not out.endswith("…"): break
            time.sleep(0.5)
        for _ in range(0):
            if not panel.inner_text("#probeout").endswith("…"): break
            time.sleep(0.5)
        print("проверка", base, "->", panel.inner_text("#probeout").replace("\n", " / "), "| модели:", panel.eval_on_selector_all("#modelsel option", "o=>o.map(x=>x.value)"))
    panel.click("#savecfg")
    for lang in ["uk", "ru", "en"]:
        panel.click("#gear"); panel.select_option("#langsel", lang); panel.wait_for_timeout(300)
        print(lang, "->", panel.inner_text("header").replace("\n", " "), "|", panel.inner_text("#go"), "|", panel.inner_text("#setup h2"))
        panel.screenshot(path=f"imgs/i18n_{lang}.png", full_page=True)
        panel.click("#gear")
    print("язык сохранён:", sw.evaluate("chrome.storage.local.get('lang').then(s=>s.lang)"))
    if PID:
        ctx.add_cookies([{"name": "aep_usuc_f", "value": ali.region_cookie("UA", "USD"), "domain": ".aliexpress.com", "path": "/"}])
        prod = ctx.new_page(); prod.goto(f"https://www.aliexpress.com/item/{PID}.html", wait_until="domcontentloaded", timeout=60000)
        tabs = []
        for _ in range(30):
            tabs = sw.evaluate("chrome.tabs.query({url:'*://*.aliexpress.com/item/*'}).then(t=>t.map(x=>x.id))")
            if sw.evaluate("chrome.storage.session.get().then(s=>Object.keys(s).length)"): break
            time.sleep(1)
        panel.goto(f"chrome-extension://{eid}/panel.html?tab={tabs[0]}")
        for _ in range(180):
            if panel.is_visible("#pcard") or "reading" not in panel.inner_text("#noproduct"): break
            time.sleep(0.5)
        panel.wait_for_timeout(1000)
        print("товар:", panel.inner_text("#ptitle")[:60] if panel.is_visible("#pcard") else panel.inner_text("#noproduct"))
        print("цена:", panel.inner_text("#pprice") if panel.is_visible("#pcard") else "-", "| кнопка:", panel.inner_text("#go"))
        for w in ["50W", "100W", "150W", "200W"]:
            panel.locator(".chip", has_text=re.compile("^" + w + "$")).first.click(); panel.wait_for_timeout(200)
            print("  кнопка", w, "->", panel.inner_text("#pprice"), "| выбрано:", [c.inner_text() for c in panel.locator(".chip.on").all()])
        ph = panel.locator("#photos img")
        print("фото в ленте:", ph.count(), "| подсвечено:", [i for i in range(ph.count()) if "on" in (ph.nth(i).get_attribute("class") or "")])
        panel.locator(".chip", has_text="50W").first.click(); panel.wait_for_timeout(300)
        print("после 50W подсвечено:", [i for i in range(ph.count()) if "on" in (ph.nth(i).get_attribute("class") or "")], "| главное фото = фото 50W:", panel.get_attribute("#pimg", "src") == ph.nth(0).get_attribute("src"))
        ph.nth(2).click(); panel.wait_for_timeout(300)
        print("клик по №3: подсвечено", [i for i in range(ph.count()) if "on" in (ph.nth(i).get_attribute("class") or "")], "| главное фото сменилось:", panel.get_attribute("#pimg", "src") == ph.nth(2).get_attribute("src"))
        panel.screenshot(path="imgs/i18n_product_en.png", full_page=True)
    ctx.close()
print("ошибки панели:", errs or "нет")
