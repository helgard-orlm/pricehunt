"""pricehunt — сайт: агент ищет лучшую настоящую цену, человек может соревноваться своими ссылками.

GET  /                      страница
POST /api/hunt              {ship_to, query, image_b64} -> {id}
GET  /api/hunt/<id>         состояние + журнал
POST /api/hunt/<id>/mine    {urls: [...]} — мои находки в ту же таблицу
GET  /api/history           прошлые поиски
"""
import base64
import json
import os
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import hunt

PORT = int(os.environ.get("PORT", "8931"))
HERE = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(HERE, "data", "jobs")
os.makedirs(JOBS_DIR, exist_ok=True)
JOBS = {}


class Job:
    def __init__(self, ship_to, query, image):
        self.id = time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.lines = []
        self.error = None
        self.busy = True
        self.created = time.time()
        self.query = query
        self.has_image = bool(image)
        self.h = hunt.Hunt(ship_to=ship_to, query=query, image=image, log=self.log)

    def log(self, s):
        self.lines.append(time.strftime("%H:%M:%S ") + s)

    def _wrap(self, fn, *a):
        self.busy = True
        try:
            fn(*a)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            self.log("ОШИБКА: " + self.error)
            traceback.print_exc()
        finally:
            self.busy = False
            self.save()

    def start(self):
        threading.Thread(target=self._wrap, args=(self.h.run,), daemon=True).start()

    def add_mine(self, urls):
        threading.Thread(target=self._wrap, args=(self.h.add_human, urls), daemon=True).start()

    def view(self):
        st = self.h.state()
        st.update({"id": self.id, "busy": self.busy, "error": self.error, "log": self.lines[-400:],
                   "query": self.query, "has_image": self.has_image, "ship_to": self.h.ship_to})
        return st

    def save(self):
        try:
            v = self.view()
            with open(os.path.join(JOBS_DIR, self.id + ".json"), "w") as f:
                json.dump(v, f, ensure_ascii=False, indent=1)
        except Exception:
            traceback.print_exc()


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "json" in ctype or "html" in ctype else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self._send(200, open(os.path.join(HERE, "web", "index.html"), "rb").read(), "text/html")
        if p.startswith("/api/hunt/"):
            jid = p.split("/")[3]
            j = JOBS.get(jid)
            if j:
                return self._send(200, j.view())
            f = os.path.join(JOBS_DIR, os.path.basename(jid) + ".json")
            if os.path.exists(f):
                return self._send(200, json.load(open(f)))
            return self._send(404, {"error": "нет такого поиска"})
        if p == "/api/history":
            out = []
            for name in sorted(os.listdir(JOBS_DIR), reverse=True)[:40]:
                try:
                    v = json.load(open(os.path.join(JOBS_DIR, name)))
                    top = v.get("top") or []
                    hum = [c for c in top if c.get("source") == "human"]
                    out.append({"id": v["id"], "query": v.get("query") or ("(фото)" if v.get("has_image") else ""),
                                "ship_to": v.get("ship_to"), "best": top[0]["total"] if top else None,
                                "winner": top[0].get("source") if top else None, "human": len(hum),
                                "conf": v.get("confidence")})
                except Exception:
                    pass
            return self._send(200, out)
        self._send(404, {"error": "not found"})

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            b = self._body()
        except Exception:
            return self._send(400, {"error": "плохой JSON"})
        if p == "/api/hunt":
            q = (b.get("query") or "").strip()
            img = base64.b64decode(b["image_b64"].split(",")[-1]) if b.get("image_b64") else None
            if not q and not img:
                return self._send(400, {"error": "нужно название или фото"})
            j = Job(b.get("ship_to") or "UA", q, img)
            JOBS[j.id] = j
            j.start()
            return self._send(200, {"id": j.id})
        if p.startswith("/api/hunt/") and p.endswith("/mine"):
            j = JOBS.get(p.split("/")[3])
            if not j:
                return self._send(404, {"error": "поиск не в памяти сервера (перезапускался?)"})
            if j.busy:
                return self._send(409, {"error": "агент ещё работает — подожди конца"})
            urls = [u for u in b.get("urls", []) if u.strip()]
            j.add_mine(urls)
            return self._send(200, {"ok": True, "n": len(urls)})
        self._send(404, {"error": "not found"})


if __name__ == "__main__":
    print(f"pricehunt на http://0.0.0.0:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
