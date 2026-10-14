import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(ROOT + "/research/cloud_test.py").read().split("# ---------- А")[0]
ns = {"__file__": ROOT + "/research/cloud_test.py"}; exec(src, ns)
Q = ("Look at the main product in the photo (if several identical units in different colours are shown, describe one). "
     "List every connector, port, socket, pin header, terminal and button you can see on it, with how many of each. "
     "Answer only JSON like {\"USB-C\": 1, \"USB-A\": 1}; use {} if there are none.")
c = json.load(open(ROOT + "/data/bundle/model_cands.json"))
L = [("R1 вариант сбоку", "https://ae-pic-a1.aliexpress-media.com/kf/S351af3223e5848e3940146771265b8ffr.jpg"),
     ("R2 спереди", "https://ae-pic-a1.aliexpress-media.com/kf/S1910f37718c0438297cbf1684c7cb1f9i.jpg")]
L += [(f"{i} {x['title'][:40]}", x["img"]) for i, x in enumerate(c)]
L += [(k + " " + t[:38], u) for k, u, t in json.load(open(ROOT + "/data/fp_extra.json"))]
L.append(("16 КОЛЛАЖ", "https://ae-pic-a1.aliexpress-media.com/kf/S182464d1daaa48b4bf43494cc634c3c3g.jpg_960x960.jpg"))
for name, u in L:
    r = ns["chat"](ns["MCP"], "minicpm-v4.7", Q, [ns["img_b64"](u)], 30)
    print(f"{name:45} {r['choices'][0]['message']['content'][:120]}", flush=True)
