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

import queue

import ali
import hunt
import models

PORT = int(os.environ.get("PORT", "8931"))
HERE = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(HERE, "data", "jobs")
os.makedirs(JOBS_DIR, exist_ok=True)
JOBS = {}


# ---------- расширение браузера: очередь заданий ----------
class TaskList:
    """Очередь заданий: расширение берёт только то, что умеет его версия (0.1 — только товары)."""
    def __init__(self):
        self.items, self.cv = [], threading.Condition()

    def put(self, t):
        with self.cv:
            self.items.append(t); self.cv.notify_all()

    def get(self, can, timeout):
        end = time.time() + timeout
        with self.cv:
            while True:
                for i, t in enumerate(self.items):
                    if t["type"] in can:
                        return self.items.pop(i)
                left = end - time.time()
                if left <= 0:
                    raise queue.Empty
                self.cv.wait(left)

    def qsize(self):
        return len(self.items)


def ext_can(version):
    try:
        v = tuple(int(x) for x in (version or "0.1.0").split("."))
    except ValueError:
        v = (0, 1, 0)
    return {"item"} if v < (0, 2, 0) else {"item", "fetch_html", "image_search"}


class Ext:
    tasks = TaskList()
    waiting = {}            # task id -> {"ev": Event, "res": dict}
    last_seen = 0.0
    info = {}

    @classmethod
    def connected(cls):
        return time.time() - cls.last_seen < 30


class ExtFetcher:
    """Товары открывает расширение в браузере пользователя: его адрес, его вход, его капча."""
    def __init__(self, ship_to, log):
        self.ship_to, self.log = ship_to, log

    def _task(self, task, timeout=90):
        """Отдать задание расширению и дождаться ответа; капча -> ждём человека до 5 минут."""
        if not Ext.connected():
            raise RuntimeError("расширение не на связи")
        tid = uuid.uuid4().hex[:10]
        task["id"] = tid
        slot = {"ev": threading.Event(), "res": None}
        Ext.waiting[tid] = slot
        Ext.tasks.put(task)
        told = False
        deadline = time.time() + timeout
        while time.time() < deadline:
            if slot["ev"].wait(2):
                r = slot["res"]
                if r.get("captcha"):
                    if not told:
                        self.log("  🧩 AliExpress показал капчу в твоём браузере — сдвинь ползунок во вкладке, агент подождёт (до 5 мин)")
                        told = True
                    deadline = time.time() + 300
                    slot["ev"].clear()
                    continue
                break
        Ext.waiting.pop(tid, None)
        return slot["res"] or {}

    def search(self, query, ship_to=None, sort="price_asc", page=1):
        import urllib.parse
        q = urllib.parse.quote(query.replace(" ", "-"))
        r = self._task({"type": "fetch_html", "url": f"https://www.aliexpress.com/w/wholesale-{q}.html?SortType={sort}&page={page}"})
        return ali._parse_search(r.get("html") or "")

    def image_search(self, jpeg):
        import base64
        r = self._task({"type": "image_search", "image": base64.b64encode(jpeg).decode()}, 120)
        return r.get("url"), ali._parse_search(r.get("html") or "")

    def item(self, pid):
        c = ali.cached_item(pid, "EXT", "EXT")
        if c:
            return c
        r = self._task({"type": "item", "pid": pid, "url": f"https://www.aliexpress.com/item/{pid}.html"})
        if not r.get("raw"):
            return None
        it = ali.parse_item(ali._pdp_result(r["raw"]))
        it["id"] = pid
        to = {s.get("ship_to") for s in it["shipping"]} - {None}
        if to and self.ship_to not in to:
            self.log(f"  ⚠ твой AliExpress считает доставку в {', '.join(to)}, а выбрано {self.ship_to} — цены по настройкам сайта")
        os.makedirs(ali.CACHE_DIR, exist_ok=True)
        json.dump(it, open(ali._cache_path(pid, "EXT", "EXT"), "w"), ensure_ascii=False)
        return it

    def close(self):
        pass


class Job:
    def __init__(self, ship_to, query, image, model=None, fetch="server", ref_url=None, ref_sku=None):
        self.id = time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.lines = []
        self.error = None
        self.busy = True
        self.created = time.time()
        self.query = query
        self.has_image = bool(image)
        self.ref_url = ref_url
        self.fetch = fetch
        self.h = hunt.Hunt(ship_to=ship_to, query=query, image=image, log=self.log, model=model,
                           fetcher=(lambda st, lg: ExtFetcher(st, lg)) if fetch == "extension" else None,
                           ref_url=ref_url, ref_sku=ref_sku)
        if image:
            try:
                open(os.path.join(JOBS_DIR, self.id + "_photo.jpg"), "wb").write(self.h.image)
            except Exception:
                pass

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
                   "query": self.query, "has_image": self.has_image, "ship_to": self.h.ship_to,
                   "model": self.h.model.label(), "fetch": self.fetch, "ref_url": self.ref_url})
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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def log_message(self, *a):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

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
        if p == "/api/models":
            return self._send(200, models.available())
        if p == "/api/ext/status":
            return self._send(200, {"connected": Ext.connected(), "info": Ext.info,
                                    "queued": Ext.tasks.qsize(), "waiting": len(Ext.waiting)})
        if p == "/api/ext/next":
            Ext.last_seen = time.time()
            ver = (self.path.split("v=")[1].split("&")[0]) if "v=" in self.path else "0.1.0"
            try:
                t = Ext.tasks.get(ext_can(ver), timeout=20)
            except queue.Empty:
                t = {}
            Ext.last_seen = time.time()
            return self._send(200, t)
        if p == "/api/history":
            out = []
            for name in sorted(os.listdir(JOBS_DIR), reverse=True)[:40]:
                try:
                    v = json.load(open(os.path.join(JOBS_DIR, name)))
                    top = v.get("top") or []
                    hum = [c for c in top if c.get("source") == "human"]
                    out.append({"id": v["id"], "query": v.get("query") or ("(фото)" if v.get("has_image") else (v.get("ref_url") or "")[:60]),
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
            ref_url = (b.get("ref_url") or "").strip()
            if not q and not img and not ref_url:
                return self._send(400, {"error": "нужно название, фото или ссылка на товар"})
            fetch = b.get("fetch") or "server"
            if fetch == "extension" and not Ext.connected():
                return self._send(400, {"error": "расширение не на связи — открой браузер с расширением"})
            j = Job(b.get("ship_to") or "UA", q, img, b.get("model"), fetch, ref_url, b.get("ref_sku"))
            JOBS[j.id] = j
            j.start()
            return self._send(200, {"id": j.id})
        if p == "/api/preview":
            import re as _re
            url = (b.get("url") or "").strip()
            m = _re.search(r"/item/(\d+)", url) or _re.search(r"(\d{10,})", url)
            if not m:
                return self._send(400, {"error": "это не похоже на ссылку на товар AliExpress"})
            pid = m.group(1)
            try:
                if b.get("fetch") == "extension":
                    if not Ext.connected():
                        return self._send(400, {"error": "расширение не на связи"})
                    it = ExtFetcher(b.get("ship_to") or "UA", lambda s: None).item(pid)
                else:
                    f = ali.Fetcher(b.get("ship_to") or "UA")
                    try:
                        it = f.item(pid)
                    finally:
                        f.close()
            except ali.Captcha:
                return self._send(409, {"error": "AliExpress просит капчу — попробуй режим «мой браузер»"})
            except Exception as e:
                return self._send(500, {"error": f"не открылся: {e}"})
            if not it:
                return self._send(404, {"error": "товар не открылся"})
            sku = _re.search(r"(?:skuId=|%21)(12\d{12,})", url)
            ships = [x for x in it["shipping"] if x.get("fee") is not None]
            return self._send(200, {"id": pid, "title": it["title"], "img": (it.get("main_images") or [None])[0],
                                    "currency": it.get("currency"), "groups": ali.variant_groups(it),
                                    "variants": [{k: v[k] for k in ("sku", "attrs", "price", "original", "welcome_deal", "img", "salable")}
                                                 for v in it["variants"]],
                                    "shipping": min((x["fee"] for x in ships), default=None),
                                    "url_sku": sku.group(1) if sku else None})
        if p == "/api/ext/result":
            Ext.last_seen = time.time()
            slot = Ext.waiting.get(b.get("id"))
            if slot:
                slot["res"] = b
                slot["ev"].set()
            return self._send(200, {"ok": bool(slot)})
        if p == "/api/ext/hello":
            Ext.last_seen = time.time()
            Ext.info = {k: b.get(k) for k in ("browser", "version", "ua")}
            return self._send(200, {"ok": True})
        if p.startswith("/api/hunt/") and p.endswith("/stop"):
            j = JOBS.get(p.split("/")[3])
            if not j:
                return self._send(404, {"error": "нет такого поиска"})
            j.h.cancelled = True
            j.log("остановлено по кнопке «Стоп» — показываю, что успел")
            return self._send(200, {"ok": True})
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
