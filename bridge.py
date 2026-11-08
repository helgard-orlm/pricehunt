"""Мост: OpenAI-формат /v1/chat/completions -> подписочные CLI (Хайку через claude, Луна через codex).

Только для личного стенда helgard. Каждый вызов = отдельный запуск CLI.
Доступ: сам Parrot без ключа (сайт :8931), домашняя сеть 192.168.1.x с ключом (расширение), остальные отказ.
Инструментов у моделей нет: в промт попадают названия товаров с AliExpress, то есть чужой текст.
logprobs здесь нет: клиенты в этом случае берут сам ответ Yes/No (1 или 0).
"""
import base64
import datetime
import hmac
import ipaddress
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("BRIDGE_PORT", "8932"))
STATE = os.path.expanduser("~/.local/state/pricehunt-bridge")
CODEX_HOME = os.path.join(STATE, "codexhome")
INSTR = os.path.join(STATE, "instr.md")
WORK = os.path.join(STATE, "cwd")
TIMEOUT = 180
HAIKU, LUNA = "haiku", "gpt-5.6-luna"
SYSTEM = "Answer the question directly and briefly, in exactly the format it asks for. You have no tools."
HOME_NET = ipaddress.ip_network("192.168.1.0/24")
with open(os.path.expanduser("~/.config/pricehunt-bridge/key")) as _f:
    KEY = _f.read().strip()
if len(KEY) < 24:
    raise SystemExit("ключ моста пуст или слишком короткий")
MAX_BODY = 64 * 1024 * 1024
_slots = threading.Semaphore(3)
_stats_lock = threading.Lock()
STATS = {}


def setup():
    os.makedirs(CODEX_HOME, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    auth = os.path.join(CODEX_HOME, "auth.json")
    if not os.path.lexists(auth):
        os.symlink(os.path.expanduser("~/.codex/auth.json"), auth)
    with open(INSTR, "w") as f:
        f.write(SYSTEM + "\n")


def system_prompt():
    return f"Today is {datetime.date.today().isoformat()}. {SYSTEM}"


def split_message(messages):
    """Текст и картинки (байты) из сообщений OpenAI-формата."""
    texts, images = [], []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            texts.append(c)
            continue
        for part in c or []:
            if part.get("type") == "text":
                texts.append(part["text"])
            elif part.get("type") == "image_url":
                url = part["image_url"]["url"]
                found = re.match(r"data:[^;]+;base64,(.*)", url, re.S)
                if not found:
                    raise ValueError("мост принимает только картинки data:base64")
                images.append(base64.b64decode(found.group(1)))
    return "\n".join(texts), images


def run_haiku(text, images):
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(i).decode()}} for i in images]
    content.append({"type": "text", "text": text})
    stdin = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
    cmd = ["claude", "-p", "--model", HAIKU, "--tools", "", "--strict-mcp-config", "--setting-sources", "",
           "--settings", '{"disableAllHooks":true}', "--no-session-persistence",
           "--system-prompt", system_prompt(), "--input-format", "stream-json",
           "--output-format", "stream-json", "--verbose"]
    env = dict(os.environ, MAX_THINKING_TOKENS="0")
    p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=TIMEOUT, cwd=WORK, env=env)
    result = None
    for line in p.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "result":
            result = d
    if not result or result.get("is_error"):
        raise RuntimeError(str(result.get("result") if result else p.stderr or p.stdout)[:400])
    u = result.get("usage", {})
    tokens = sum(u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return result.get("result") or "", tokens, u.get("output_tokens", 0)


def run_luna(text, images):
    with tempfile.TemporaryDirectory() as tmp:
        cmd = ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only", "--json",
               "-m", LUNA, "-c", f"model_instructions_file={INSTR}", "-c", "features.shell_tool=false",
               "-c", "web_search=disabled"]
        for n, data in enumerate(images):
            path = os.path.join(tmp, f"{n}.jpg")
            with open(path, "wb") as f:
                f.write(data)
            cmd += ["-i", path]
        cmd += ["--", f"Today is {datetime.date.today().isoformat()}.\n{text}"]
        env = dict(os.environ, CODEX_HOME=CODEX_HOME)
        # stdin закрыт: иначе codex ждёт дополнительный ввод и висит
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=TIMEOUT, cwd=WORK, env=env)
    answer, used, error = "", {}, None
    for line in p.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        kind = d.get("type")
        if kind == "item.completed" and d["item"].get("type") == "agent_message":
            answer = d["item"]["text"]
        elif kind == "turn.completed":
            used = d.get("usage", {})
        elif kind in ("error", "turn.failed"):
            error = str(d.get("message") or d.get("error") or d)
    if error or not used:
        raise RuntimeError((error or p.stderr or p.stdout or "codex не ответил")[:400])
    return answer, used.get("input_tokens", 0), used.get("output_tokens", 0)


RUN = {HAIKU: run_haiku, LUNA: run_luna}


def note(model, seconds, tokens_in, tokens_out, failed=False):
    with _stats_lock:
        s = STATS.setdefault(model, {"calls": 0, "failed": 0, "seconds": 0.0, "in": 0, "out": 0})
        s["calls"] += 1
        s["failed"] += int(failed)
        s["seconds"] = round(s["seconds"] + seconds, 1)
        s["in"] += tokens_in
        s["out"] += tokens_out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        print(f"{self.client_address[0]} {self.command} {self.path} -> {code} "
              f"origin={self.headers.get('Origin')} auth={'да' if self.headers.get('Authorization') else 'нет'}", flush=True)
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self):
        """Отвечает отказом сам. True = запрос можно обрабатывать."""
        ip = ipaddress.ip_address(self.client_address[0])
        if ip.is_loopback:
            return True
        if ip not in HOME_NET:
            self._send(403, {"error": {"message": "только домашняя сеть"}})
            return False
        given = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given.encode(), KEY.encode()):
            self._send(401, {"error": {"message": "неверный ключ моста"}})
            return False
        return True

    def do_OPTIONS(self):
        self._send(403, {"error": {"message": "CORS не поддерживается"}})

    def do_GET(self):
        if not self._allowed():
            return
        if self.path == "/v1/models":
            return self._send(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in RUN]})
        if self.path == "/stats":
            with _stats_lock:
                return self._send(200, STATS)
        self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if not self._allowed():
            return
        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": {"message": "not found"}})
        size = int(self.headers.get("Content-Length", 0))
        if size > MAX_BODY:
            return self._send(413, {"error": {"message": "запрос слишком большой"}})
        body = json.loads(self.rfile.read(size))
        model = body.get("model")
        if model not in RUN:
            return self._send(400, {"error": {"message": f"неизвестная модель {model}"}})
        t0 = time.time()
        try:
            text, images = split_message(body.get("messages", []))
            with _slots:
                answer, tokens_in, tokens_out = RUN[model](text, images)
        except Exception as e:
            note(model, time.time() - t0, 0, 0, failed=True)
            print(f"{model} ОШИБКА: {e}", flush=True)
            return self._send(502, {"error": {"message": f"{model}: {e}"}})
        seconds = time.time() - t0
        note(model, seconds, tokens_in, tokens_out)
        print(f"{model} {seconds:.1f}s in={tokens_in} out={tokens_out} img={len(images)}", flush=True)
        self._send(200, {"id": "bridge", "object": "chat.completion", "model": model,
                         "choices": [{"index": 0, "finish_reason": "stop",
                                      "message": {"role": "assistant", "content": answer}}],
                         "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out}})


if __name__ == "__main__":
    setup()
    print(f"мост на порту {PORT}: Parrot без ключа, 192.168.1.x с ключом", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
