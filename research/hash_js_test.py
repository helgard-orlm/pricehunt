"""JS-отпечаток из model.js в настоящем Chromium: расстояния между фото образца и кандидатов (порог PHOTO_D)."""
import json, os, re, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright
import ali
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(ROOT + "/extension/lib/model.js").read()
code = src[src.index("// ---------- отпечаток фото"):src.index("export class Model")].replace("export ", "")
g = json.load(open(ROOT + "/data/second/gal.json")); C = json.load(open(ROOT + "/data/bundle/model_cands.json"))
SAME = {0, 3, 4, 13}
ref = g["1005008033224158"]["gallery"]
with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=ali.CHROME, args=["--disable-web-security", "--headless=new"])
    pg = b.new_page()
    pg.evaluate(code + "\nwindow.H = async (u) => { const h = await imgHash(u); return h ? Array.from(h) : null; }; window.D = (a, b) => (!a || !b) ? 999 : hamming(Uint8Array.from(a), Uint8Array.from(b));")
    R = [pg.evaluate("u => H(u)", u) for u in ref]
    for i, x in enumerate(C):
        if i == 2: continue
        ds = []
        for u in g[x["id"]]["gallery"]:
            h = pg.evaluate("u => H(u)", u)
            ds.append(min((pg.evaluate("([a,b]) => D(a,b)", [h, r]), k + 1) for k, r in enumerate(R)))
        close = sorted(d for d in ds if d[0] <= 12)
        print(f"{i:2} {'ТА ЖЕ' if i in SAME else 'другая':6} близкие (бит, фото образца): {close}", flush=True)
    b.close()
