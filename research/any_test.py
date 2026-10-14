"""Промах на коллаже двух расцветок: строгий «та же модель» против «есть ли среди товаров на фото та же модель» — 16 Essager + коллаж 1005008033832703."""
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(ROOT + "/research/cloud_test.py").read().split("# ---------- А")[0]
ns = {"__file__": ROOT + "/research/cloud_test.py"}; exec(src, ns)
mt = open(ROOT + "/research/model_test.py").read()
REF = os.environ.get("REF", "https://ae-pic-a1.aliexpress-media.com/kf/S1910f37718c0438297cbf1684c7cb1f9i.jpg")
SAME_MODEL = {0, 2, 3, 4, 13}
MODEL = eval(mt.split("\nMODEL = ")[1].split("\nc = ")[0])
ANY = ("Image 1 is the exact product the shopper wants. Image 2 is a marketplace offer; it may show several units, e.g. the same charger in different colours. "
       "Is at least one product in image 2 the SAME MODEL as in image 1 — same body shape and design details, same ports and their layout, "
       "same display or lights, same printed power rating — not just a similar product of the same kind or another model of the same brand? "
       "Ignore colour, background, advertising text and plug type. Answer Yes or No.")
c = json.load(open(ROOT + "/data/bundle/model_cands.json"))
c.append({"img": "https://ae-pic-a1.aliexpress-media.com/kf/S182464d1daaa48b4bf43494cc634c3c3g.jpg_960x960.jpg", "title": "КОЛЛАЖ белая+чёрная 1005008033832703"})
SAME_MODEL.add(len(c) - 1)
r = ns["img_b64"](REF); res = {"model": [], "any": []}
for i, x in enumerate(c):
    im = ns["img_b64"](x["img"])
    pm, _ = ns["yes"](ns["MCP"], "minicpm-v4.7", MODEL, [r, im]); pa, _ = ns["yes"](ns["MCP"], "minicpm-v4.7", ANY, [r, im])
    res["model"].append(pm); res["any"].append(pa)
    print(f"{i:2} {'ТА ЖЕ' if i in SAME_MODEL else 'другая':6} модель={pm:<6} любая={pa:<6} {x['title'][:50]}", flush=True)
for k in res:
    for thr in (0.5, 0.7):
        tp = sum(1 for i, p in enumerate(res[k]) if p is not None and p >= thr and i in SAME_MODEL)
        fp = sum(1 for i, p in enumerate(res[k]) if p is not None and p >= thr and i not in SAME_MODEL)
        print(f"{k} порог {thr}: верно {tp}/{len(SAME_MODEL)}, ложно {fp}/{len(c) - len(SAME_MODEL)}")
