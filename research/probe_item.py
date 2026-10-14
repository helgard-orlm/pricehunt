import sys, json, re
from playwright.sync_api import sync_playwright
pid = sys.argv[1]
caps = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, executable_path=__import__("glob").glob("/home/helgard/.cache/ms-playwright/chromium-1243/chrome-linux*/chrome")[0])
    ctx = b.new_context(locale="en-US", user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36")
    ctx.add_cookies([{"name":"aep_usuc_f","value":"site=glo&province=&city=&c_tp=USD&region=UA&b_locale=en_US","domain":".aliexpress.com","path":"/"}])
    pg = ctx.new_page()
    def on_resp(r):
        if "mtop" in r.url and ("pdp" in r.url or "detail" in r.url or "freight" in r.url.lower()):
            try: caps.append((r.url.split("?")[0], r.text()))
            except Exception: pass
    pg.on("response", on_resp)
    pg.goto(f"https://www.aliexpress.com/item/{pid}.html", wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(8000)
    print("TITLE:", pg.title()[:100])
    body = pg.inner_text("body")
    for line in body.splitlines():
        l=line.strip()
        if re.search(r"(US ?\$|\$\d|Shipping|Delivery|Color|Plug|Ships)", l) and len(l)<120: print("  |", l)
    for u,t in caps: print("API:", u, len(t))
    open("item_api.json","w").write(json.dumps([{"u":u,"t":t} for u,t in caps]))
    b.close()
