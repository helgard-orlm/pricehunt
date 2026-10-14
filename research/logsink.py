"""Приёмник журналов расширения pricehunt (для разработчика): POST /log -> data/logs/<id>.json.
Тот же поиск присылает журнал после каждого уровня и в конце — файл перезаписывается (по id)."""
import json, os, re, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "logs")
os.makedirs(DIR, exist_ok=True)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8932


class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        files = sorted(os.listdir(DIR))[-20:]
        body = json.dumps({"ok": True, "logs": files}, ensure_ascii=False).encode()
        self.send_response(200); self._cors(); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 30_000_000:
            self.send_response(413); self.end_headers(); return
        try:
            d = json.loads(self.rfile.read(n))
            name = re.sub(r"[^\w.-]", "_", str(d.get("id") or time.strftime("%Y%m%d-%H%M%S")))[:120] + ".json"
            d["received"] = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(os.path.join(DIR, name), "w") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            self.send_response(200); self._cors(); self.end_headers(); self.wfile.write(b'{"ok":true}')
        except Exception as e:
            self.send_response(400); self._cors(); self.end_headers(); self.wfile.write(str(e).encode()[:300])

    def log_message(self, fmt, *a):
        # каждая попытка (и OPTIONS) — в журнал службы: видно, доходит ли браузер вообще
        print(time.strftime("%H:%M:%S"), self.client_address[0], fmt % a, flush=True)


ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
