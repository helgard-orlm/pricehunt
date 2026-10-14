"""Образец в двух ракурсах (фото варианта сбоку + фронтальное из галереи) в одном вопросе — против одного образца."""
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(ROOT + "/research/cloud_test.py").read().split("# ---------- А")[0]
ns = {"__file__": ROOT + "/research/cloud_test.py"}; exec(src, ns)
R1 = "https://ae-pic-a1.aliexpress-media.com/kf/S351af3223e5848e3940146771265b8ffr.jpg"   # фото варианта (сбоку)
R2 = "https://ae-pic-a1.aliexpress-media.com/kf/S1910f37718c0438297cbf1684c7cb1f9i.jpg"   # галерея (спереди)
SAME_MODEL = {0, 2, 3, 4, 13, 16}
TWO = ("Images 1 and 2 show the exact product the shopper wants (the same item, two views). Image 3 is a marketplace offer (it may show several items or colours). "
       "Look only at the connectors, ports, sockets, buttons and the number of them. Does the product in image 3 have exactly the same ports/connectors "
       "(same count and same types, e.g. USB-C vs USB-A) as the wanted product? Ignore colour and plug type. Answer Yes or No.")
TWO0 = ("Images 1 and 2 show the exact product the shopper wants (the same item, two views). Image 3 is a marketplace offer (it may show several items, colours or plug types). "
       "Is the product in image 3 the SAME MODEL as in images 1-2 — same body shape and design details, same ports and their layout, "
       "same display or lights, same printed power rating — not just a similar product of the same kind or another model of the same brand? "
       "Ignore colour, background, advertising text and plug type. Answer Yes or No.")
c = json.load(open(ROOT + "/data/bundle/model_cands.json"))
c.append({"img": "https://ae-pic-a1.aliexpress-media.com/kf/S182464d1daaa48b4bf43494cc634c3c3g.jpg_960x960.jpg", "title": "КОЛЛАЖ белая+чёрная 1005008033832703"})
r1, r2 = ns["img_b64"](R1), ns["img_b64"](R2); res = []
for i, x in enumerate(c):
    p, _ = ns["yes"](ns["MCP"], "minicpm-v4.7", TWO, [r1, r2, ns["img_b64"](x["img"])]); res.append(p)
    print(f"{i:2} {'ТА ЖЕ' if i in SAME_MODEL else 'другая':6} порты={p:<6} {x['title'][:50]}", flush=True)
for thr in (0.5, 0.7):
    tp = sum(1 for i, p in enumerate(res) if p is not None and p >= thr and i in SAME_MODEL)
    fp = sum(1 for i, p in enumerate(res) if p is not None and p >= thr and i not in SAME_MODEL)
    print(f"порты порог {thr}: верно {tp}/{len(SAME_MODEL)}, ложно {fp}/{len(c) - len(SAME_MODEL)}")
