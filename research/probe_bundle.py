"""Где на AliExpress «Пропозиції комплектів» (Bundle deals): в данных карточки (pdp), в DOM карточки, в выдаче поиска."""
import sys, os, re, json, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright
import ali
PID = sys.argv[1] if len(sys.argv) > 1 else "1005007439009437"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bundle")
os.makedirs(OUT, exist_ok=True)
RX = re.compile(r"bundle|комплект", re.I)
bodies = []
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(tempfile.mkdtemp(), headless=False, executable_path=ali.CHROME,
        viewport={"width": 1400, "height": 900}, args=["--headless=new"], locale="uk-UA")
    ctx.add_cookies([{"name": "aep_usuc_f", "value": ali.region_cookie("UA", "USD"), "domain": ".aliexpress.com", "path": "/"}])
    page = ctx.new_page()
    def on_resp(r):
        if "mtop" in r.url or "bundle" in r.url.lower():
            try: bodies.append((r.url, r.text()))
            except Exception: pass
    page.on("response", on_resp)
    page.goto(f"https://www.aliexpress.com/item/{PID}.html", wait_until="domcontentloaded", timeout=60000)
    for y in range(0, 6000, 900):
        page.mouse.wheel(0, 900); page.wait_for_timeout(700)
    page.wait_for_timeout(2000)
    html = page.content(); open(OUT + "/item.html", "w").write(html)
    print("карточка: captcha" if "punish" in page.url or "_____tmd_____" in html else "карточка: ок")
    print("в DOM карточки:", sorted(set(m.group(0) for m in RX.finditer(page.inner_text("body"))))[:10])
    for m in re.finditer(r"[^<>\"]{0,80}(?:bundle|комплект)[^<>\"]{0,80}", page.inner_text("body"), re.I):
        print("   текст:", m.group(0).strip()[:160])
    links = page.eval_on_selector_all("a", "a=>a.map(x=>[x.innerText.trim().slice(0,60), x.href]).filter(p=>/bundle|комплект/i.test(p[0]+p[1]))")
    for l in links[:10]: print("   ссылка:", l)
    for url, body in bodies:
        if RX.search(body):
            keys = sorted(set(re.findall(r'"(\w*[Bb]undle\w*)"', body)))
            print("ответ:", url[:110], "| ключи:", keys[:15])
            json.dump({"url": url, "body": body}, open(OUT + f"/resp_{len(os.listdir(OUT))}.json", "w"))
    ctx.close()
