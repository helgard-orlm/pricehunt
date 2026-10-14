"""Модели для агента: любая с OpenAI-совместимым /v1/chat/completions.

kind:
  minicpm — MiniCPM-V 4.7 на gpu104 (llama-server :8920), по умолчанию
  ollama  — любая модель Ollama (для фото нужна со зрением)
  openai  — любой другой адрес OpenAI-формата (base_url + model + api_key)
Проценты («как у Jev») — вероятность первого токена Yes/No из logprobs; их отдают и llama-server, и Ollama.
На карте 8 ГБ две большие модели сразу не помещаются, поэтому для своих моделей gpu104 освобождаем память.
"""
import base64, json, os, re, subprocess, threading, time, urllib.request

GPU_HOST = os.environ.get("GPU_HOST", "192.168.1.104")
MINICPM = f"http://{GPU_HOST}:8920"
OLLAMA = f"http://{GPU_HOST}:11434"
_lock = threading.Lock()


def _post(url, body, timeout=300, headers=None):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, json.dumps(body).encode(), h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _ssh(cmd):
    return subprocess.run(["ssh", "-o", "ConnectTimeout=8", f"helgard@{GPU_HOST}", cmd],
                          capture_output=True, text=True, timeout=120)


def _up(url):
    try:
        urllib.request.urlopen(url, timeout=3); return True
    except Exception:
        return False


def _unload_ollama(keep=None):
    try:
        ps = json.load(urllib.request.urlopen(OLLAMA + "/api/ps", timeout=5)).get("models", [])
    except Exception:
        return
    for m in ps:
        if m["name"] != keep:
            try: _post(OLLAMA + "/api/generate", {"model": m["name"], "keep_alive": 0}, 60)
            except Exception: pass


def available():
    """Список для выпадающего меню: MiniCPM + модели Ollama (со зрением отмечены)."""
    out = [{"kind": "minicpm", "model": "minicpm-v4.7", "label": "MiniCPM-V 4.7 (gpu104, зрение)", "vision": True}]
    try:
        tags = json.load(urllib.request.urlopen(OLLAMA + "/api/tags", timeout=5)).get("models", [])
    except Exception:
        tags = []
    for t in tags:
        name = t["name"]
        if "embed" in name or "bge" in name:
            continue
        caps = []
        try:
            caps = _post(OLLAMA + "/api/show", {"model": name}, 10).get("capabilities", [])
        except Exception:
            pass
        if "completion" not in caps:
            continue
        cloud = name.endswith(":cloud") or "-cloud" in name
        out.append({"kind": "ollama", "model": name, "vision": "vision" in caps,
                    "label": f"{name} (Ollama{', облако' if cloud else ''}{', зрение' if 'vision' in caps else ''})"})
    return out


class Model:
    def __init__(self, cfg=None, log=print):
        cfg = cfg or {"kind": "minicpm"}
        self.kind = cfg.get("kind", "minicpm")
        self.name = cfg.get("model") or "minicpm-v4.7"
        self.log = log
        if self.kind == "minicpm":
            self.base = MINICPM
        elif self.kind == "ollama":
            self.base = OLLAMA
        else:
            self.base = (cfg.get("base_url") or "").rstrip("/")
            if self.base.endswith("/v1"):
                self.base = self.base[:-3]
        self.headers = {"Authorization": "Bearer " + cfg["api_key"]} if cfg.get("api_key") else {}
        self.vision = cfg.get("vision", self.kind == "minicpm")

    def label(self):
        return f"{self.name} ({self.kind})"

    def prepare(self):
        """Освободить видеокарту gpu104 под выбранную модель."""
        if self.kind == "minicpm":
            _unload_ollama()
            if not _up(MINICPM + "/v1/models"):
                self.log("видеокарта: поднимаю MiniCPM-V")
                _ssh("systemctl --user start minicpm-v")
                for _ in range(60):
                    if _up(MINICPM + "/v1/models"): break
                    time.sleep(2)
        elif self.kind == "ollama" and not self.name.endswith("cloud"):
            if _up(MINICPM + "/v1/models"):
                self.log("видеокарта: останавливаю MiniCPM-V, освобождаю место под " + self.name)
                _ssh("systemctl --user stop minicpm-v")
            _unload_ollama(keep=self.name)

    def _chat(self, content, max_tokens, extra=None):
        body = {"model": self.name, "temperature": 0, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": content}]}
        if self.kind == "minicpm":
            body["chat_template_kwargs"] = {"enable_thinking": False}  # иначе думает и отдаёт пустой ответ (замер 14.10)
        elif self.kind == "ollama":
            body["reasoning_effort"] = "none"
        body.update(extra or {})
        with _lock:
            return _post(self.base + "/v1/chat/completions", body, 300, self.headers)

    def ask(self, text, images=(), max_tokens=400):
        if images and not self.vision:
            images = ()
            text = "(No image available: answer from the text only.)\n" + text
        content = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + img_b64(i)}} for i in images]
        content.append({"type": "text", "text": text})
        r = self._chat(content, max_tokens)
        msg = r["choices"][0]["message"]
        return (msg.get("content") or "").strip()

    def ask_json(self, text, images=(), max_tokens=600, default=None):
        out = self.ask(text + "\nAnswer with JSON only, no comments.", images, max_tokens)
        m = re.search(r"[\[{].*[\]}]", out, re.S)
        try:
            return json.loads(m.group()) if m else default
        except Exception:
            return default

    def yes_prob(self, text):
        """Оценка «да» по вероятностям первого токена (logprobs). Если сервер их не отдаёт — None."""
        try:
            r = self._chat([{"type": "text", "text": text}], 1, {"logprobs": True, "top_logprobs": 10})
            lps = r["choices"][0]["logprobs"]["content"][0]["top_logprobs"]
        except Exception:
            return None
        yes = no = 0.0
        for t in lps:
            w = t["token"].strip().lower()
            p = 2.718281828459045 ** t["logprob"]
            if w == "yes": yes += p
            elif w == "no": no += p
        return round(yes / (yes + no), 3) if yes + no > 0 else None


def img_b64(src):
    if isinstance(src, (bytes, bytearray)):
        return base64.b64encode(src).decode()
    url = src if src.startswith("http") else "https:" + src
    if "alicdn" in url or "aliexpress-media" in url:
        if not re.search(r"_\d+x\d+", url): url += "_350x350.jpg"
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
    return base64.b64encode(data).decode()
