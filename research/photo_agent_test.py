"""Настоящий код agent.js (buildPhotos -> photoHits) в Chromium на живой модели: образец 33W Black EU, кандидаты из gal.json."""
import json, os, sys, threading, functools, http.server
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright
import ali
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8977), functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT + "/extension"))
threading.Thread(target=srv.serve_forever, daemon=True).start()
g = json.load(open(ROOT + "/data/second/gal.json")); C = json.load(open(ROOT + "/data/bundle/model_cands.json"))
SAME = {0, 3, 4, 13}
ref = g["1005008033224158"]
REFIMG = "https://ae-pic-a1.aliexpress-media.com/kf/S351af3223e5848e3940146771265b8ffr.jpg"
with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=ali.CHROME, args=["--disable-web-security", "--headless=new"])
    pg = b.new_page(); pg.goto("http://127.0.0.1:8977/panel.html")
    pg.on("console", lambda m: print("console:", m.text) if "error" in m.type else None)
    out = pg.evaluate("""async ([gallery, refimg, cands]) => {
      globalThis.chrome = globalThis.chrome || { runtime: {}, storage: { local: { get: async () => ({}) } } };
      const { Hunt } = await import('/lib/agent.js'); const { Model } = await import('/lib/model.js');
      const h = Object.create(Hunt.prototype); const logs = [];
      h.model = new Model({ base: 'http://192.168.1.104:8920', model: 'minicpm-v4.7', kind: 'openai' });
      h.ref = { item: { main_images: gallery }, variant: { img: refimg } }; h.cancelled = false; h.log = (x) => logs.push(x);
      await h.buildPhotos(refimg);
      const res = {};
      const { imgHash } = await import('/lib/model.js');
      for (const [id, urls] of Object.entries(cands)) { res[id] = await h.photoHits(urls); let f = 0; for (const u of urls) if (!(await imgHash(u))) { f++; if (!res.err) { try { const k = u.split('?')[0]; const rr = await fetch(k + '_350x350.jpg'); const bb = await rr.blob(); res.err0 = [rr.status, bb.type, bb.size, String.fromCharCode(...new Uint8Array(await bb.slice(0, 40).arrayBuffer())).replace(/[^ -~]/g, '.'), [...rr.headers].slice(0, 12)]; const bmp = await createImageBitmap(bb); const mid = new OffscreenCanvas(64, 64); mid.getContext('2d').drawImage(bmp, 0, 0, 64, 64); res.err = 'manual ok ' + k; } catch (e) { res.err = String(e) + ' ' + u; } } } res[id + '_fail'] = f; }
      return { logs, pool: h.photos.map((p) => p.k.slice(-40)), res };
    }""", [ref["gallery"], REFIMG, {x["id"]: g[x["id"]]["gallery"] for i, x in enumerate(C) if i != 2}])
    print(out["logs"], out["res"].get("err"), out["res"].get("err0")); print("в образце:", out["pool"])
    for i, x in enumerate(C):
        if i == 2: continue
        print(f"{i:2} {'ТА ЖЕ' if i in SAME else 'другая':6} общих товарных фото: {out['res'][x['id']]} (не загрузилось {out['res'][x['id']+'_fail']})  {x['title'][:50]}")
    b.close()
srv.shutdown()
