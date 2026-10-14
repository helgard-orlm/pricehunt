"""Идея helgard: продавцы копируют фото -> общие фото галереи = тот же товар. dHash всех фото (галерея + фото вариантов)
образца и 15 Essager-кандидатов (разметка глазами из model_test.py), сколько общих с образцом у «той же» и у «другой»."""
import json, os, re, time, io, urllib.request, sys
from PIL import Image
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C = json.load(open(ROOT + "/data/bundle/model_cands.json"))
SAME = {0, 2, 3, 4, 13}; REF = 2
CACHE = ROOT + "/data/second/gal.json"
gal = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/141 Safari/537.36", "Accept-Language": "en"}

def page_imgs(pid):
    h = urllib.request.urlopen(urllib.request.Request(f"https://www.aliexpress.com/item/{pid}.html", headers=UA), timeout=30).read().decode("utf8", "ignore")
    if "punish" in h or "_____tmd_____" in h: return None
    m = re.search(r'"imagePathList":\[([^\]]*)\]', h)
    g = re.findall(r'"(https?://[^"]+)"', m.group(1)) if m else []
    v = re.findall(r'"skuPropertyImagePath":"(https?://[^"]+)"', h)
    return {"gallery": g, "variants": list(dict.fromkeys(v))}

def dhash(url, n=8):
    raw = urllib.request.urlopen(urllib.request.Request(url + ("_220x220.jpg" if not re.search(r"_\d+x\d+", url) else ""), headers=UA), timeout=30).read()
    im = Image.open(io.BytesIO(raw)).convert("L").resize((n + 1, n), Image.LANCZOS)
    px = list(im.getdata()); bits = 0
    for y in range(n):
        for x in range(n): bits = bits << 1 | (px[y * (n + 1) + x] > px[y * (n + 1) + x + 1])
    return bits

for x in C:
    if x["id"] in gal: continue
    r = page_imgs(x["id"]); time.sleep(2)
    if r is None: print("КАПЧА на", x["id"]); sys.exit(1)
    r["hash"] = {}
    for u in r["gallery"] + r["variants"]:
        try: r["hash"][u] = dhash(u)
        except Exception as e: pass
    gal[x["id"]] = r; json.dump(gal, open(CACHE, "w"))
    print("собрано", x["id"], len(r["gallery"]), "галерея,", len(r["variants"]), "вариантов", flush=True)

ref = gal[C[REF]["id"]]
for thr in (4, 8, 12):
    print(f"\nпорог Хэмминга ≤{thr}:")
    for i, x in enumerate(C):
        if i == REF: continue
        g = gal[x["id"]]
        shared = [(a, b) for a, ha in ref["hash"].items() for b, hb in g["hash"].items() if bin(ha ^ hb).count("1") <= thr]
        ga = sum(1 for a, b in shared if a in ref["gallery"]); 
        print(f"  {i:2} {'ТА ЖЕ' if i in SAME else 'другая':6} общих фото {len(set(b for a,b in shared)):2} (из {len(g['hash'])})  {x['title'][:55]}")
