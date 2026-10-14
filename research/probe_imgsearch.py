import sys, re
from playwright.sync_api import sync_playwright
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ali
img = sys.argv[1]
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, executable_path=ali.CHROME)
    ctx = b.new_context(locale="en-US", user_agent=ali.UA, viewport={"width": 1400, "height": 900})
    ctx.add_cookies([{"name": "aep_usuc_f", "value": ali.region_cookie("UA", "USD"), "domain": ".aliexpress.com", "path": "/"}])
    pg = ctx.new_page()
    reqs = []
    pg.on("request", lambda r: reqs.append(r.url) if re.search(r"upload|image|imgsearch|picsearch", r.url, re.I) and not re.search(r"\.(jpg|png|webp|gif|svg|avif)", r.url) else None)
    pg.goto("https://www.aliexpress.com/", wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(5000)
    for sel in ["text=Accept cookies", "text=Don't allow"]:
        try: pg.click(sel, timeout=2000)
        except Exception: pass
    try: pg.mouse.click(985, 244)
    except Exception: pass
    pg.wait_for_timeout(800)
    try:
        with pg.expect_file_chooser(timeout=6000) as fc:
            pg.mouse.click(685, 38)
        fc.value.set_files(img); print("file chooser used")
    except Exception as e:
        print("no chooser:", str(e)[:80]); pg.wait_for_timeout(1500)
    inputs = pg.query_selector_all("input[type=file]")
    print("file inputs:", len(inputs), [i.get_attribute("accept") for i in inputs])
    if inputs and "file chooser used" not in str(locals().get("_x","")):
        try: inputs[0].set_input_files(img)
        except Exception as e: print("set_input_files:", str(e)[:80])
        pg.wait_for_timeout(12000)
    print("URL:", pg.url[:300])
    for u in reqs[:15]: print("REQ:", u[:200])
    pg.screenshot(path="imgs/imgsearch.png")
    html = pg.content()
    print("productIds:", len(set(re.findall(r'"productId":"(\d+)"', html))), "item links:", len(set(re.findall(r'/item/(\d+)\.html', html))))
    b.close()
