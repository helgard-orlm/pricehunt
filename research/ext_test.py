"""Chromium с расширением ext/ -> агент открывает товары через расширение. Печатает журнал агента."""
import sys, os, time, json, urllib.request, tempfile; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright
import ali
EXT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ext")
def get(p): return json.load(urllib.request.urlopen("http://localhost:8931" + p, timeout=30))
def post(p, b): return json.load(urllib.request.urlopen(urllib.request.Request("http://localhost:8931" + p, json.dumps(b).encode(), {"Content-Type": "application/json"}), timeout=30))
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(tempfile.mkdtemp(), headless=False, executable_path=ali.CHROME,
        args=["--headless=new", f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
    for _ in range(20):
        if get("/api/ext/status")["connected"]: break
        time.sleep(1)
    print("ext status:", get("/api/ext/status"))
    print("sw:", [w.url for w in ctx.service_workers])
    import base64
    body = {"ship_to": "UA", "query": sys.argv[1], "fetch": "extension"}
    if len(sys.argv) > 3:
        body["image_b64"] = base64.b64encode(open(sys.argv[3], "rb").read()).decode()
    j = post("/api/hunt", body)
    print("job", j)
    t = time.time(); seen = 0
    while time.time() - t < float(sys.argv[2]):
        time.sleep(3)
        v = get("/api/hunt/" + j["id"])
        for l in v["log"][seen:]: print(l, flush=True)
        seen = len(v["log"])
        if not v["busy"]: break
    print("tabs:", [p.url[:80] for p in ctx.pages])
    ctx.close()
