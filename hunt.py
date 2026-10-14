"""Агент поиска лучшей настоящей цены.

Настоящая цена = цена НУЖНОГО варианта (не кабеля вместо зарядки) + самая дешёвая доставка в выбранную страну.
Глубина поиска по правилу helgard: первые 3 уровня свободны; дальше каждый уровень без находки дешевле = +1
к утомлению; находка дешевле сбрасывает утомление в 0; утомление FATIGUE_LIMIT = стоп.
Проценты — вероятность ответа «Yes» у MiniCPM-V (как у моделей класса Jev), а не число, написанное текстом.
"""
import math
import re
import time

import ali
import models

FREE_LEVELS = 3
FATIGUE_LIMIT = 3
MAX_LEVELS = 9
PER_LEVEL = 6          # сколько новых кандидатов открывать на уровне
TIME_BUDGET = 15 * 60  # секунд


PLUG = {"GB": "UK", "US": "US", "CA": "US", "AU": "AU"}  # остальным странам списка нужна вилка EU
PLUG_RE = re.compile(r"\b(EU|US|UK|AU|KR)\b", re.I)


def plug_of(attrs):
    m = PLUG_RE.search(" ".join(attrs))
    return m.group(1).upper() if m else None


class Hunt:
    def __init__(self, ship_to="UA", query=None, image=None, log=print, model=None, fetcher=None):
        self.ship_to = ship_to
        self.query = (query or "").strip()
        self.image = image          # bytes или None
        self.log = log
        self.seen = {}              # id -> строка выдачи (всё, что хоть раз видели)
        self.checked = {}           # id -> оценённый кандидат
        self.levels = []            # история уровней
        self.fatigue = 0
        self.best = None
        self.intent = None
        self.done = False
        self.blocked = False
        self.confidence = None
        self.t0 = time.time()
        self.model = models.Model(model, log)
        self.fetcher_factory = fetcher   # None = робот-браузер на сервере; иначе функция -> объект с .item(pid)

    # ---------- понимание запроса ----------
    def understand(self):
        prompt = ("A shopper wants to buy something on AliExpress. "
                  + (f'Their words: "{self.query}". ' if self.query else "")
                  + ("The photo shows the product they want. " if self.image else "")
                  + "Describe the exact product in English and plan searches. JSON fields: "
                    '"what" (short exact product description, e.g. "65W USB-C wall charger (power brick)"), '
                    '"must" (list of 1-5 key features the item must have), '
                    '"not" (list of things that look similar but are wrong, e.g. "cable only", "car charger"), '
                    '"queries" (list of 4 short English search queries, different wording, most likely first).')
        imgs = [self.image] if self.image else []
        it = self.model.ask_json(prompt, imgs, 500, default={}) or {}
        if not it.get("what"):
            it = {"what": self.query or "the product in the photo", "must": [], "not": [], "queries": [self.query]}
        it["queries"] = [q for q in it.get("queries", []) if q][:6] or [self.query]
        self.intent = it
        self.log(f"понял так: {it['what']} | обязательно: {', '.join(it.get('must', []))} | "
                 f"не путать с: {', '.join(it.get('not', []))}")
        return it

    # ---------- уровни поиска ----------
    def level_plan(self, n):
        """Что делаем на уровне n (1..). Возвращает [(описание, функция-поиск)]."""
        q = self.intent["queries"]
        plan = []
        if n == 1:
            if self.query:
                plan.append((f'запрос как есть «{self.query}», по цене', lambda: ali.search(self.query, self.ship_to, sort="price_asc")))
                plan.append((f'запрос как есть «{self.query}», лучшие совпадения', lambda: ali.search(self.query, self.ship_to, sort="default")))
            if self.image:
                plan.append(("поиск по твоему фото", self._photo_search_user))
            if not plan:
                plan.append((f'«{q[0]}»', lambda: ali.search(q[0], self.ship_to, sort="price_asc")))
        elif n == 2:
            for qq in q[:3]:
                if qq.lower() != self.query.lower():
                    plan.append((f'переформулировка «{qq}», по цене', lambda qq=qq: ali.search(qq, self.ship_to, sort="price_asc")))
        elif n == 3:
            if self.best:
                plan.append(("похожие по фото лучшего найденного", self._photo_search_best))
            for qq in q[3:5]:
                plan.append((f'переформулировка «{qq}»', lambda qq=qq: ali.search(qq, self.ship_to, sort="price_asc")))
        else:
            k = n - 3
            src = [self.query] + q if self.query else q
            qq = src[(k - 1) % len(src)]
            page = 2 + (k - 1) // len(src)
            plan.append((f'«{qq}», страница {page}', lambda qq=qq, page=page: ali.search(qq, self.ship_to, sort="price_asc", page=page)))
            if self.best and self.best.get("img") and k % 2 == 0:
                plan.append(("похожие по фото нового лучшего", self._photo_search_best))
        return plan

    def _photo_search_user(self):
        path = f"/tmp/pricehunt_user_{int(self.t0)}.jpg"
        open(path, "wb").write(self.image)
        return ali.image_search(path, self.ship_to)[1]

    def _photo_search_best(self):
        import urllib.request
        url = self.best["img"]
        data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
        path = f"/tmp/pricehunt_best_{int(time.time())}.jpg"
        open(path, "wb").write(data)
        return ali.image_search(path, self.ship_to)[1]

    # ---------- отбор по названиям ----------
    def prefilter(self, hits):
        """MiniCPM по списку названий: какие похожи на нужный товар. Возвращает отфильтрованный список."""
        if not hits:
            return []
        lines = "\n".join(f"{i}. ${h['list_price']:.2f} {h['title'][:110]}" for i, h in enumerate(hits))
        prompt = (f"Wanted product: {self.intent['what']}. Must have: {', '.join(self.intent.get('must', []))}. "
                  f"Wrong items: {', '.join(self.intent.get('not', []))}.\n"
                  f"Marketplace listings (number. price title):\n{lines}\n\n"
                  "Which listings could sell the wanted product (possibly as one of several variants)? "
                  "Return a JSON list of their numbers.")
        idx = self.model.ask_json(prompt, [], 400, default=None)
        if not isinstance(idx, list):
            return hits
        keep = [hits[i] for i in idx if isinstance(i, int) and 0 <= i < len(hits)]
        return keep or hits

    # ---------- проверка кандидата ----------
    def evaluate(self, it, source="agent"):
        """it = результат ali.item. Выбирает нужный вариант, считает настоящую цену, смотрит фото."""
        variants = [v for v in it["variants"] if v.get("salable", True) and v.get("price")]
        if not variants:
            return None
        ships = [s for s in it["shipping"] if s.get("fee") is not None]
        ship = min(ships, key=lambda s: s["fee"]) if ships else None
        lines = "\n".join(f"{i}. {'; '.join(v['attrs']) or 'default'} — ${v['price']:.2f}" for i, v in enumerate(variants))
        prompt = (f"Wanted product: {self.intent['what']}. Must have: {', '.join(self.intent.get('must', []))}. "
                  f"Wrong items: {', '.join(self.intent.get('not', []))}.\n"
                  f"Listing title: {it['title']}\nVariants:\n{lines}\n\n"
                  "Which variant numbers are exactly the wanted product (not an accessory, cable only, or a different item)? "
                  'If the shopper must ship to ' + self.ship_to + ', prefer a plug/version usable there when it matters. '
                  'JSON: {"match": [numbers], "note": "one short sentence"}')
        ans = self.model.ask_json(prompt, [], 200, default={}) or {}
        match = [variants[i] for i in ans.get("match", []) if isinstance(i, int) and 0 <= i < len(variants)]
        flags = []
        if not match:
            return {"id": it["id"], "title": it["title"], "rejected": True, "note": ans.get("note", "нет подходящего варианта"),
                    "source": source, "url": f"https://www.aliexpress.com/item/{it['id']}.html"}
        want_plug = PLUG.get(self.ship_to, "EU")
        plugs = {plug_of(v["attrs"]) for v in match} - {None}
        if plugs:
            mine = [v for v in match if plug_of(v["attrs"]) in (want_plug, None)]
            if mine:
                match = mine
            else:
                flags.append(f"нет вилки {want_plug} — только {', '.join(sorted(plugs))} (нужен переходник)")
        def real(v):
            # цена для новичка недоступна старому покупателю: считаем по обычной (осторожно, честно)
            return (v["original"] or v["price"]) if v["welcome_deal"] else v["price"]
        v = min(match, key=real)
        cheapest_any = min(variants, key=lambda x: x["price"])
        if cheapest_any["price"] < v["price"] - 0.01 and cheapest_any not in match:
            flags.append(f"цена в выдаче ${cheapest_any['price']:.2f} — это «{'; '.join(cheapest_any['attrs'])}», не нужный товар")
        if v["welcome_deal"]:
            flags.append(f"${v['price']:.2f} — только для новых покупателей (1 шт.); считаю по обычной ${real(v):.2f}")
        # глаза: что на фото выбранного варианта
        img = v.get("img") or (it["main_images"][0] if it.get("main_images") else None)
        look = None
        if img:
            try:
                look = self.model.ask(f"Look at the photo. Does it show this product: {self.intent['what']}? "
                                  "A product that exceeds a minimum requirement (e.g. more watts, more ports) still counts as YES. "
                                  "Answer YES or NO, then a dash and what is actually shown (max 12 words). "
                                  "If wattage, model or chip names are printed, quote them.", [img], 60)
                if look.upper().startswith("NO"):
                    flags.append("фото не совпадает: " + look.split("-", 1)[-1].strip())
            except Exception as e:
                look = f"ERR {e}"
        fee = ship["fee"] if ship else None
        total = real(v) + (fee or 0)
        return {"id": it["id"], "title": it["title"], "source": source,
                "url": f"https://www.aliexpress.com/item/{it['id']}.html",
                "variant": "; ".join(v["attrs"]) or "default", "price": real(v), "shown_price": v["price"],
                "shipping": fee, "ship_company": ship["company"] if ship else None,
                "ship_days": ship["days"] if ship else None, "total": round(total, 2),
                "img": ("https:" + img) if img and img.startswith("//") else img,
                "look": look, "flags": flags, "note": ans.get("note", ""), "rejected": False,
                "currency": it.get("currency") or "USD",
                "n_variants": len(variants)}

    def _fetcher(self):
        import threading
        tid = threading.get_ident()
        if getattr(self, "_f_tid", None) != tid:
            self._f = self.fetcher_factory(self.ship_to, self.log) if self.fetcher_factory else ali.Fetcher(self.ship_to)
            self._f_tid = tid
        return self._f

    def open_items(self, ids, source="agent"):
        """Открывает товары по одному. Возвращает (оценки, сколько реально открыто)."""
        res, opened = [], 0
        for pid in ids:
            if self.blocked:
                break
            try:
                it = self._fetcher().item(pid)
            except ali.Captcha:
                self.blocked = True
                self.log("  ⛔ AliExpress попросил капчу — товары больше не открываю (обходить не буду). "
                         "Показываю то, что успел проверить; повтори поиск позже — открытое запомнено.")
                break
            except Exception as e:
                self.log(f"  не открылся {pid}: {e}"); continue
            if not it:
                self.log(f"  не открылся {pid}"); continue
            opened += 1
            ev = self.evaluate(it, source)
            if ev:
                self.checked[it["id"]] = ev
                res.append(ev)
                if ev["rejected"]:
                    self.log(f"  ✗ {it['title'][:60]} — {ev['note']}")
                else:
                    self.log(f"  ✓ ${ev['total']:.2f} = ${ev['price']:.2f} + доставка ${ev['shipping']} | {ev['variant'][:40]} | {it['title'][:50]}"
                             + (" ⚠" if ev["flags"] else ""))
        return res, opened

    # ---------- главный цикл ----------
    def run(self):
        self.log("модель: " + self.model.label())
        self.model.prepare()
        self.understand()
        n = 0
        while n < MAX_LEVELS and time.time() - self.t0 < TIME_BUDGET:
            n += 1
            self.log(f"— уровень {n} (утомление {self.fatigue}/{FATIGUE_LIMIT})")
            hits = []
            for desc, fn in self.level_plan(n):
                try:
                    h = fn()
                except Exception as e:
                    self.log(f"  {desc}: ошибка {e}"); continue
                new = [x for x in h if x["id"] not in self.seen]
                for x in h: self.seen.setdefault(x["id"], x)
                self.log(f"  {desc}: {len(h)} товаров, новых {len(new)}")
                hits += new
            cand = self.prefilter(hits)
            cand = [c for c in cand if c["id"] not in self.checked]
            cand.sort(key=lambda c: c["list_price"])
            pick = cand[:PER_LEVEL]
            self.log(f"  подходят по названию {len(cand)}, открываю {len(pick)} самых дешёвых")
            before = self.best["total"] if self.best else math.inf
            _, opened = self.open_items([c["id"] for c in pick])
            self._update_best()
            improved = self.best and self.best["total"] < before - 0.005
            self.levels.append({"n": n, "found": len(hits), "opened": opened,
                                "best": self.best["total"] if self.best else None, "improved": bool(improved)})
            if improved:
                self.log(f"  ★ новый лучший: ${self.best['total']:.2f} — утомление сброшено")
                self.fatigue = 0
            elif n >= FREE_LEVELS and (opened or not pick):
                self.fatigue += 1   # уровень, где ничего не смогли открыть, «пустым» не считается
            if self.blocked:
                break
            if self.fatigue >= FATIGUE_LIMIT:
                self.log("утомление на пределе — останавливаюсь"); break
            if not hits and n > FREE_LEVELS + 2:
                break
        if getattr(self, "_f", None):
            self._f.close(); self._f_tid = None
        self.score()
        self.done = True
        self.log(f"готово за {time.time() - self.t0:.0f} с: уровней {len(self.levels)}, видел {len(self.seen)}, открыл {len(self.checked)}")

    def _update_best(self):
        ok = [c for c in self.checked.values() if not c["rejected"] and not any(f.startswith("фото не совпадает") for f in c["flags"])]
        self.best = min(ok, key=lambda c: c["total"]) if ok else None

    # ---------- проценты ----------
    def depth_text(self):
        quiet = 0
        for lv in reversed(self.levels):
            if lv["improved"]: break
            quiet += 1
        return (f"Search depth: {len(self.levels)} levels, {len(self.seen)} listings seen, "
                f"{len(self.checked)} opened and checked variant by variant; "
                f"the last {quiet} levels found nothing cheaper."
                + (" The search was cut short: the marketplace showed a captcha, so fewer offers were opened than planned." if self.blocked else ""))

    def table_text(self, rows):
        out = []
        for i, c in enumerate(rows, 1):
            out.append(f"#{i} ${c['total']:.2f} total (item ${c['price']:.2f} + shipping ${c['shipping']}, "
                       f"{(c['ship_days'] or ['?','?'])[0]}-{(c['ship_days'] or ['?','?'])[1]} days) — variant «{c['variant']}» — "
                       f"{c['title'][:90]}" + (f" — warnings: {'; '.join(c['flags'])}" if c["flags"] else ""))
        return "\n".join(out)

    def score(self):
        self._update_best()
        rows = sorted([c for c in self.checked.values() if not c["rejected"]], key=lambda c: c["total"])[:10]
        if not rows:
            self.top = []; self.confidence = None; return
        head = (f"A shopper in {self.ship_to} wants: {self.intent['what']}. Must have: {', '.join(self.intent.get('must', []))}.\n"
                f"Checked offers, cheapest real total first:\n{self.table_text(rows)}\n{self.depth_text()}\n")
        for i, c in enumerate(rows, 1):
            c["p_good"] = self.model.yes_prob(head + f"\nIs offer #{i} the right product at a good real price for this shopper? Answer Yes or No.")
        self.confidence = self.model.yes_prob(head + "\nConsidering how deep the search went, is offer #1 really the cheapest correct "
                                                 "offer on the whole marketplace? Answer Yes or No.")
        for c in rows:
            c["why"] = self._why(c, rows[0])
        self.top = rows

    def _why(self, c, best):
        parts = [f"вариант «{c['variant']}» ${c['price']:.2f}",
                 f"доставка ${c['shipping']} ({c['ship_company']}, {c['ship_days'][0]}–{c['ship_days'][1]} дн.)" if c["ship_days"] else "доставка неизвестна"]
        if c is not best:
            parts.append(f"дороже лучшего на ${c['total'] - best['total']:.2f}")
        if c.get("look"):
            parts.append("фото: " + c["look"][:80])
        return parts

    # ---------- «я против агента» ----------
    def add_human(self, urls):
        ids = []
        for u in urls:
            m = re.search(r"/item/(\d+)", u) or re.search(r"(\d{10,})", u)
            if m: ids.append(m.group(1))
        self.log(f"проверяю твои находки: {len(ids)}")
        self.blocked = False
        self.open_items(ids, source="human")
        self.score()
        return ids

    def state(self):
        return {"intent": self.intent, "done": self.done, "blocked": self.blocked, "fatigue": self.fatigue, "levels": self.levels,
                "seen": len(self.seen), "checked": len(self.checked), "confidence": self.confidence,
                "top": getattr(self, "top", []),
                "rejected": [c for c in self.checked.values() if c["rejected"]][:30],
                "human": [c for c in self.checked.values() if c["source"] == "human"],
                "elapsed": round(time.time() - self.t0)}
