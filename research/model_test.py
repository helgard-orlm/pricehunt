"""«Тот же тип» (как сейчас) против «та же модель» — MiniCPM на 16 зарядках из выдачи, разметка глазами."""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(ROOT + "/research/cloud_test.py").read().split("# ---------- А")[0]
ns = {"__file__": ROOT + "/research/cloud_test.py"}; exec(src, ns)
REF = "https://ae-pic-a1.aliexpress-media.com/kf/S1910f37718c0438297cbf1684c7cb1f9i.jpg"
SAME_MODEL = {0, 2, 3, 4, 13}   # глазами: чёрная Essager 33W GaN с дисплеем, C+A (14.10)
TYPE = ("Image 1 is the product the shopper wants. Image 2 is a marketplace offer. "
        "Is the product in image 2 the same type as in image 1 — same form factor/shape, same kind of board or body, "
        "same connection type (ignore background, text labels, colour of light, and which size/power is shown)? Answer Yes or No.")
MODEL = ("Image 1 is the exact product the shopper wants. Image 2 is a marketplace offer (it may show several items or plug types). "
         "Is the product in image 2 the SAME MODEL as in image 1 — same body shape and design details, same ports and their layout, "
         "same display or lights, same printed power rating — not just a similar product of the same kind or another model of the same brand? "
         "Ignore background, advertising text and plug type. Answer Yes or No.")
c = json.load(open(ROOT + "/data/bundle/model_cands.json"))
r = ns["img_b64"](REF)
res = {"type": [], "model": []}
for i, x in enumerate(c):
    im = ns["img_b64"](x["img"])
    pt, _ = ns["yes"](ns["MCP"], "minicpm-v4.7", TYPE, [r, im])
    pm, _ = ns["yes"](ns["MCP"], "minicpm-v4.7", MODEL, [r, im])
    res["type"].append(pt); res["model"].append(pm)
    print(f"{i:2} {'ТА ЖЕ' if i in SAME_MODEL else 'другая':6} тип={pt:<6} модель={pm:<6} {x['title'][:50]}", flush=True)
for k in res:
    for thr in (0.5, 0.7):
        tp = sum(1 for i, p in enumerate(res[k]) if p is not None and p >= thr and i in SAME_MODEL)
        fp = sum(1 for i, p in enumerate(res[k]) if p is not None and p >= thr and i not in SAME_MODEL)
        print(f"{k} порог {thr}: верно «та же» {tp}/{len(SAME_MODEL)}, ложно «та же» {fp}/{len(c) - len(SAME_MODEL)}")
