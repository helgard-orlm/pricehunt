"""Сверка: что на картинке варианта (кабель / зарядка / зарядка+кабель / автомобильная) vs текст варианта."""
import base64, json, re, sys, time, urllib.request
model = sys.argv[1]  # minicpm | gemma
items = json.load(open("cheap.json"))
want = {"1005007500206559", "1005008278804721", "1005009579135810", "1005007177221241", "1005012142286732", "1005004683413179"}
cases = []
for it in items:
    if it["id"] not in want: continue
    seen = set()
    for v in it["variants"]:
        if not v["img"] or v["img"] in seen: continue
        seen.add(v["img"]); cases.append((it, v))
PROMPT = ("You check marketplace listings. Look at the image only.\n"
          "What is the product shown? Answer with exactly one label from: "
          "WALL_CHARGER (power brick only), CABLE (cable only), CHARGER_AND_CABLE, CAR_CHARGER, ADAPTER_CONNECTOR, OTHER.\n"
          "Then on a second line, the wattage printed on the product if visible, else NONE.")
def img_b64(url):
    url = url if url.startswith("http") else "https:" + url
    if not re.search(r"_\d+x\d+", url): url += "_350x350.jpg"
    return base64.b64encode(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()).decode()
def ask(b64):
    if model == "minicpm":
        body = {"model": "minicpm-v4.7", "temperature": 0, "max_tokens": 40, "chat_template_kwargs": {"enable_thinking": False}, "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}, {"type": "text", "text": PROMPT}]}]}
        req = urllib.request.Request("http://192.168.1.104:8920/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=180))["choices"][0]["message"]["content"]
    body = {"model": "gemma4:12b-it-qat", "stream": False, "think": False, "options": {"temperature": 0, "num_predict": 40},
            "messages": [{"role": "user", "content": PROMPT, "images": [b64]}]}
    req = urllib.request.Request("http://192.168.1.104:11434/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=300))["message"]["content"]
res = []
for it, v in cases:
    t = time.time()
    try: a = ask(img_b64(v["img"])).strip().replace("\n", " | ")
    except Exception as e: a = f"ERR {e}"
    res.append({"id": it["id"], "variant": "; ".join(v["attrs"]), "price": v["price"], "model": a, "s": round(time.time() - t, 1), "img": v["img"]})
    print(f"{res[-1]['s']:5}s  {it['id'][-6:]}  ${v['price']:<5} {res[-1]['variant'][:34]:34} -> {a[:60]}", flush=True)
json.dump(res, open(f"vis_{model}.json", "w"), ensure_ascii=False, indent=1)
