"""gemma4:31b-cloud (Ollama на gpu104) против MiniCPM-V 4.7: (А) 49 фото вариантов, (Б) «тот же товар, что образец»."""
import base64, json, re, sys, time, glob, os, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = sys.argv[1] if len(sys.argv) > 1 else "gemma4:31b-cloud"
OLL = "http://192.168.1.104:11434/v1/chat/completions"
MCP = "http://192.168.1.104:8920/v1/chat/completions"

def img_b64(url):
    url = url if url.startswith("http") else "https:" + url
    if not re.search(r"_\d+x\d+", url): url += "_350x350.jpg"
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
    from PIL import Image; import io
    im = Image.open(io.BytesIO(raw)).convert("RGB"); im.thumbnail((1024, 1024)); b = io.BytesIO(); im.save(b, "JPEG", quality=90)
    return base64.b64encode(b.getvalue()).decode()

def chat(url, model, text, imgs, max_tokens, extra=None):
    content = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b}} for b in imgs] + [{"type": "text", "text": text}]
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}], **(extra or {})}
    if url == MCP: body["chat_template_kwargs"] = {"enable_thinking": False}
    else: body["reasoning_effort"] = "none"
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=300))

def yes(url, model, text, imgs):
    r = chat(url, model, text, imgs, 1, {"logprobs": True, "top_logprobs": 10})
    lp = (((r["choices"][0].get("logprobs") or {}).get("content") or [{}])[0]).get("top_logprobs")
    if lp:
        y = sum(2.718281828 ** t["logprob"] for t in lp if t["token"].strip().lower() == "yes")
        n = sum(2.718281828 ** t["logprob"] for t in lp if t["token"].strip().lower() == "no")
        return round(y / (y + n), 3) if y + n else None, "logprobs"
    w = (r["choices"][0]["message"].get("content") or "").strip().lower()
    return (1.0 if w.startswith("yes") else 0.0 if w.startswith("no") else None), "text:" + w[:10]

# ---------- А: 49 фото вариантов ----------
PROMPT = ("You check marketplace listings. Look at the image only.\n"
          "What is the product shown? Answer with exactly one label from: "
          "WALL_CHARGER (power brick only), CABLE (cable only), CHARGER_AND_CABLE, CAR_CHARGER, ADAPTER_CONNECTOR, OTHER.\n"
          "Then on a second line, the wattage printed on the product if visible, else NONE.")
lab = lambda s: (re.search(r"WALL_CHARGER|CHARGER_AND_CABLE|CAR_CHARGER|ADAPTER_CONNECTOR|CABLE|OTHER", s) or [None])[0]
ref = json.load(open(ROOT + "/data/vis_minicpm_ok.json"))
ok = 0; miss = []; secs = []
for c in ref:
    t = time.time()
    try: a = chat(OLL, MODEL, PROMPT, [img_b64(c["img"])], 40)["choices"][0]["message"]["content"]
    except Exception as e: a = f"ERR {e}"
    secs.append(time.time() - t)
    want, got = lab(c["model"]), lab(a)
    if want == got: ok += 1
    else: miss.append((c["variant"], c["price"], want, got, a.replace("\n", " | ")[:60]))
print(f"А) фото вариантов: {ok}/{len(ref)} совпало с эталоном, {sum(secs)/len(secs):.1f} с/фото", flush=True)
for m in miss: print("   промах:", m, flush=True)

# ---------- Б: тот же товар, что образец ----------
SAME = ("Image 1 is the product the shopper wants. Image 2 is a marketplace offer. "
        "Is the product in image 2 the same type as in image 1 — same form factor/shape, same kind of board or body, "
        "same connection type (ignore background, text labels, colour of light, and which size/power is shown)? Answer Yes or No.")
items = {os.path.basename(f).split("_")[0]: json.load(open(f)) for f in glob.glob(ROOT + "/data/cache/*.json")}
refs = {"COB 220V": "1005007439009437"}
esp = [i for i, d in items.items() if re.search(r"ESP-?01", d.get("title", ""), re.I)]
if esp: refs["ESP-01 adapter"] = esp[0]
mode = set()
for name, rid in refs.items():
    rimg = img_b64(items[rid]["main_images"][0])
    kw = "COB" if "COB" in name else "ESP"
    cands = [i for i, d in items.items() if i != rid and kw in d.get("title", "").upper() and d.get("main_images")][:25]
    agree = n = 0; rows = []
    for cid in cands:
        try:
            ci = img_b64(items[cid]["main_images"][0])
            pm, _ = yes(MCP, "minicpm-v4.7", SAME, [rimg, ci])
            pg, how = yes(OLL, MODEL, SAME, [rimg, ci]); mode.add(how.split(":")[0])
        except Exception as e:
            print("   ошибка", cid, e); continue
        if pm is None or pg is None: continue
        if 0.3 <= pm < 0.7: continue          # MiniCPM сама не уверена — не судим
        n += 1; agree += (pm >= 0.7) == (pg >= 0.5)
        rows.append((cid, pm, pg, items[cid]["title"][:55]))
    print(f"Б) {name}: согласие с MiniCPM {agree}/{n} (MiniCPM «точно такой» {sum(r[1] >= 0.7 for r in rows)}, Gemma «да» {sum(r[2] >= 0.5 for r in rows)})", flush=True)
    for r in rows:
        if (r[1] >= 0.7) != (r[2] >= 0.5): print("   расхождение:", r, flush=True)
print("Gemma отдаёт:", mode)
