"""Модели на gpu104: MiniCPM-V (глаза и мозг, llama-server :8920) и tev1 (решатель с процентами, Ollama /v1/systemone).
На карте 8 ГБ обе сразу не помещаются (4.1 + 4.5 ГБ), поэтому держим одну и переключаем."""
import base64, json, os, re, subprocess, threading, time, urllib.request

GPU_HOST = os.environ.get("GPU_HOST", "192.168.1.104")
MINICPM = f"http://{GPU_HOST}:8920"
OLLAMA = f"http://{GPU_HOST}:11434"
JUDGE = os.environ.get("JUDGE_MODEL", "tev1:4b-q8_0")
_lock = threading.Lock()
_current = None


def _post(url, body, timeout=300):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _ssh(cmd):
    return subprocess.run(["ssh", "-o", "ConnectTimeout=8", f"helgard@{GPU_HOST}", cmd],
                          capture_output=True, text=True, timeout=120)


def _minicpm_up():
    try:
        urllib.request.urlopen(MINICPM + "/v1/models", timeout=3); return True
    except Exception:
        return False


def _unload_ollama():
    try:
        ps = json.load(urllib.request.urlopen(OLLAMA + "/api/ps", timeout=5)).get("models", [])
    except Exception:
        return
    for m in ps:
        try: _post(OLLAMA + "/api/generate", {"model": m["name"], "keep_alive": 0}, 60)
        except Exception: pass


def use(which, log=print):
    """which = 'eyes' (MiniCPM) или 'judge' (tev1)."""
    global _current
    if which == _current and (which != "eyes" or _minicpm_up()):
        return
    if which == "eyes":
        log("видеокарта: выгружаю решатель, поднимаю MiniCPM-V")
        _unload_ollama()
        if not _minicpm_up():
            _ssh("systemctl --user start minicpm-v")
            for _ in range(60):
                if _minicpm_up(): break
                time.sleep(2)
    else:
        log("видеокарта: останавливаю MiniCPM-V, загружаю решатель " + JUDGE)
        _ssh("systemctl --user stop minicpm-v")
    _current = which


def img_b64(src):
    if isinstance(src, (bytes, bytearray)):
        return base64.b64encode(src).decode()
    url = src if src.startswith("http") else "https:" + src
    if "alicdn" in url or "aliexpress-media" in url:
        if not re.search(r"_\d+x\d+", url): url += "_350x350.jpg"
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
    return base64.b64encode(data).decode()


def ask(text, images=(), max_tokens=400):
    """MiniCPM-V без «размышлений» (иначе при коротком лимите ответ пустой — замер 14.10)."""
    content = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + img_b64(i)}} for i in images]
    content.append({"type": "text", "text": text})
    with _lock:
        r = _post(MINICPM + "/v1/chat/completions", {
            "model": "minicpm-v4.7", "temperature": 0, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": content}]})
    return r["choices"][0]["message"]["content"].strip()


def ask_json(text, images=(), max_tokens=600, default=None):
    out = ask(text + "\nAnswer with JSON only, no comments.", images, max_tokens)
    m = re.search(r"[\[{].*[\]}]", out, re.S)
    try:
        return json.loads(m.group()) if m else default
    except Exception:
        return default


def judge(state, questions):
    """Ollama /v1/systemone: questions = {name: {type, instructions, criteria}} -> answers."""
    return _post(OLLAMA + "/v1/systemone", {"model": JUDGE, "state": state, "questions": questions}, 600)["answers"]


def yes_prob(text):
    """Вероятность ответа Yes (по вероятностям первого токена), как у моделей класса Jev."""
    with _lock:
        r = _post(MINICPM + "/v1/chat/completions", {
            "model": "minicpm-v4.7", "temperature": 0, "max_tokens": 1, "logprobs": True, "top_logprobs": 10,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": text}]})
    yes = no = 0.0
    for t in r["choices"][0]["logprobs"]["content"][0]["top_logprobs"]:
        w = t["token"].strip().lower()
        p = 2.718281828459045 ** t["logprob"]
        if w == "yes": yes += p
        elif w == "no": no += p
    return round(yes / (yes + no), 3) if yes + no > 0 else None
