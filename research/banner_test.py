import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(ROOT + "/research/cloud_test.py").read().split("# ---------- А")[0]
ns = {"__file__": ROOT + "/research/cloud_test.py"}; exec(src, ns)
Q = ("Is a physical product the main subject of this photo, large and clearly visible — not an advertising banner, "
     "a chip/technology illustration, a diagram, a size chart or a text list? Answer Yes or No.")
g = json.load(open(ROOT + "/data/second/gal.json"))
for pid in ["1005008033224158", "1005010240619659", "1005008033832703"]:
    for k, u in enumerate(g[pid]["gallery"]):
        p, _ = ns["yes"](ns["MCP"], "minicpm-v4.7", Q, [ns["img_b64"](u)])
        print(pid[-4:], k + 1, p, flush=True)
