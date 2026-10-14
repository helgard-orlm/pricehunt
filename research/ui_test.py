import sys, os, time; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright
import ali
errs = []
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, executable_path=ali.CHROME)
    pg = b.new_page(viewport={"width": 1200, "height": 1600})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto("http://localhost:8931/")
    print("ship default:", pg.input_value("#ship"))
    pg.fill("#q", sys.argv[1])
    pg.click("#go")
    t = time.time()
    while time.time() - t < 600:
        pg.wait_for_timeout(3000)
        if pg.is_enabled("#go") and "готово" in pg.inner_text("#status") or "ошибка" in pg.inner_text("#status"):
            break
    print("status:", pg.inner_text("#status"))
    print("conf:", pg.inner_text("#conf"), "| depth:", pg.inner_text("#depth").replace("\n", " "))
    print("score:", pg.inner_text("#score"))
    print("items:", pg.locator("#top .item").count())
    pg.screenshot(path="imgs/ui.png", full_page=True)
    b.close()
print("JS errors:", errs or "нет")
