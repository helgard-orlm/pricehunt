import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright
import ali
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, executable_path=ali.CHROME)
    ctx = b.new_context(locale="en-US", user_agent=ali.UA, viewport={"width": 1400, "height": 900})
    pg = ctx.new_page(); pg.goto("https://www.aliexpress.com/", wait_until="domcontentloaded"); pg.wait_for_timeout(4000)
    el = pg.evaluate('''() => { const e = document.elementFromPoint(685, 38); const out=[]; let x=e; for (let i=0;i<4&&x;i++){ out.push(x.tagName+"."+(x.className&&x.className.baseVal!==undefined?x.className.baseVal:x.className)); x=x.parentElement;} return out; }''')
    print(el)
    b.close()
