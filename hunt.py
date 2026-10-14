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

SAME_MIN = 0.3          # ниже — «другой», чем на фото пользователя
EXACT_MIN = 0.7         # от этого — «точно такой»; лучшим считается только он (ступени: точно / похожий / другой)
MATCH_MIN = 0.7         # выше — «точное совпадение»: его название идёт в поисковые запросы
THUMBS_PER_LEVEL = 6    # сравнение миниатюры с образцом ~7 с (замер 14.10), карточка ~20–35 с
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


SPEC_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(w|mah|mm|cm|inch|in|gb|tb|ah)\b", re.I)


def spec_tokens(text):
    """«100W», «200-240V», «2.8 inch» -> {('100','w'), ...}; диапазоны напряжения не дробим (их проверяет модель)."""
    out = set()
    for num, unit in SPEC_RE.findall(text or ""):
        u = unit.lower()
        u = "inch" if u in ("in", "inch") else u
        out.add((num.replace(",", "."), u))
    return out


def has_spec(text, tok):
    num, unit = tok
    alt = "(?:inch|in|\"|'')" if unit == "inch" else re.escape(unit)
    return re.search(rf"(?<![\d.]){re.escape(num)}\s*{alt}\b", text or "", re.I) is not None


class Hunt:
    def __init__(self, ship_to="UA", query=None, image=None, log=print, model=None, fetcher=None, ref_url=None, ref_sku=None):
        self.ship_to = ship_to
        self.query = (query or "").strip()
        self.image = models.to_jpeg(image) if image else None   # образец (JPEG); AliExpress отдаёт AVIF/WebP
        self.ref_url = (ref_url or "").strip()
        self.ref_sku = (ref_sku or "").strip()   # вариант, который пользователь выбрал кнопками
        self.ref = None             # товар по ссылке пользователя — образец и цена, которую надо побить
        self.log = log
        self.seen = {}              # id -> строка выдачи (всё, что хоть раз видели)
        self.checked = {}           # id -> оценённый кандидат
        self.levels = []            # история уровней
        self.fatigue = 0
        self.best = None
        self.intent = None
        self.done = False
        self.blocked = False
        self.cancelled = False
        self.thumb_same = {}        # id -> похожесть миниатюры выдачи на образец
        self.title_queries = []     # запросы из названий точных совпадений (слова продавцов)
        self.used_queries = set()
        self.confidence = None
        self.t0 = time.time()
        self.model = models.Model(model, log)
        self.fetcher_factory = fetcher   # None = робот-браузер на сервере; иначе функция -> объект с .item(pid)

    ref_raw = None
    ref_variant = None
    user_text = ""

    def hard_specs(self):
        """Обязательные числа: из текста пользователя и из варианта по ссылке (100W, 220V, 2.8 inch…)."""
        if self.ref_variant:
            return spec_tokens(" ".join(self.ref_variant["attrs"]))   # выбрано кнопками — главнее всего
        return spec_tokens((self.user_text or self.query) if (self.user_text or not self.ref_raw) else "")

    def load_reference(self):
        """Ссылка на товар -> название (как запрос, если его нет), главное фото (как образец), сам товар (как планка цены)."""
        m = re.search(r"/item/(\d+)", self.ref_url) or re.search(r"(\d{10,})", self.ref_url)
        if not m:
            self.log("ссылка не похожа на товар AliExpress — пропускаю"); return
        pid = m.group(1)
        self.log(f"открываю твою ссылку-образец {pid}")
        try:
            it = self._fetcher().item(pid)
        except ali.Captcha:
            self.blocked = True; self.log("  ⛔ капча на ссылке-образце"); return
        if not it:
            self.log("  ссылка не открылась"); return
        self.ref_raw = it
        self.ref_variant = None
        if self.ref_sku:
            self.ref_variant = next((v for v in it["variants"] if v["sku"] == self.ref_sku), None)
        if self.ref_variant:
            self.log(f"  ты выбрал вариант: «{'; '.join(self.ref_variant['attrs'])}» — это требование, ищу такой же")
            if self.ref_variant.get("img"):
                self.ref_variant_img = self.ref_variant["img"]
        if len(self.query.split()) < 3:
            short = " ".join(re.sub(r"\s+", " ", it["title"] or "").split()[:8])
            self.log(f"  запрос из названия образца: «{short}»" + (f" (твой текст «{self.query}» учту при отборе)" if self.query else ""))
            self.user_text = self.query
            self.query = short
        if not self.image and (it.get("main_images") or getattr(self, "ref_variant_img", None)):
            import urllib.request
            u = getattr(self, "ref_variant_img", None) or it["main_images"][0]
            u = ("https:" + u) if u.startswith("//") else u
            try:
                self.image = models.to_jpeg(urllib.request.urlopen(
                    urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())
                self.log("  фото-образец взято с карточки")
            except Exception as e:
                self.log(f"  фото не скачалось: {e}")

    # ---------- понимание запроса ----------
    def understand(self):
        prompt = ("A shopper wants to buy something on AliExpress. "
                  + (f'Their words: "{self.query}". ' if self.query else "")
                  + ("The photo shows EXACTLY the product they want: base the description, must-haves and wrong items on what the photo shows "
                     "(type, shape/form factor, how it is connected or powered, built-in parts). " if self.image else "")
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
                plan.append((f'запрос как есть «{self.query}», по цене', lambda: self._search(self.query, sort="price_asc")))
                plan.append((f'запрос как есть «{self.query}», лучшие совпадения', lambda: self._search(self.query, sort="default")))
            if self.image:
                plan.append(("поиск по твоему фото", self._photo_search_user))
            if not plan:
                plan.append((f'«{q[0]}»', lambda: self._search(q[0], sort="price_asc")))
        elif n == 2:
            for qq in self._fresh(self.title_queries)[:2]:
                plan.append((f'из названий совпадений «{qq}», лучшие совпадения', lambda qq=qq: self._search(qq, sort="default")))
            for qq in self._fresh(q)[:3 - min(2, len(plan))]:
                plan.append((f'переформулировка «{qq}», по цене', lambda qq=qq: self._search(qq, sort="price_asc")))
        elif n == 3:
            if self.best:
                plan.append(("похожие по фото лучшего найденного", self._photo_search_best))
            for qq in self._fresh(self.title_queries)[:1]:
                plan.append((f'из названий совпадений «{qq}», лучшие совпадения', lambda qq=qq: self._search(qq, sort="default")))
            for qq in self._fresh(q)[:2]:
                plan.append((f'переформулировка «{qq}»', lambda qq=qq: self._search(qq, sort="price_asc")))
        else:
            fresh = self._fresh(self.title_queries)
            if fresh:
                qq = fresh[0]
                plan.append((f'из названий совпадений «{qq}», лучшие совпадения', lambda qq=qq: self._search(qq, sort="default")))
            k = n - 3
            src = ([self.query] if self.query else []) + self.title_queries + q
            qq = src[(k - 1) % len(src)]
            page = 2 + (k - 1) // len(src)
            plan.append((f'«{qq}», страница {page}', lambda qq=qq, page=page: self._search(qq, sort="price_asc", page=page)))
            if self.best and self.best.get("img") and k % 2 == 0:
                plan.append(("похожие по фото нового лучшего", self._photo_search_best))
        return plan

    def _fresh(self, qs):
        return [x for x in qs if x and x.lower() not in self.used_queries and x.lower() != self.query.lower()]

    def _search(self, q, sort="price_asc", page=1):
        """Поиск идёт тем же путём, что и товары: расширение (браузер пользователя) или робот."""
        if page == 1:
            self.used_queries.add(q.lower())
        f = self._fetcher()
        if hasattr(f, "search"):
            return f.search(q, self.ship_to, sort=sort, page=page)
        return ali.search(q, self.ship_to, sort=sort, page=page)

    def _photo_search(self, jpeg):
        f = self._fetcher()
        if hasattr(f, "image_search"):
            return f.image_search(jpeg)[1]
        path = f"/tmp/pricehunt_photo_{int(time.time() * 1000)}.jpg"
        open(path, "wb").write(jpeg)
        return ali.image_search(path, self.ship_to)[1]

    def _photo_search_user(self):
        return self._photo_search(self.image)

    def _photo_search_best(self):
        import urllib.request
        url = self.best["img"]
        data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
        return self._photo_search(models.to_jpeg(data))

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
        if source == "ref" and self.ref_variant:
            it = dict(it, variants=[self.ref_variant])
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
        if source == "ref" and self.ref_variant:
            ans = {"match": [0], "note": "твой выбранный вариант"}
        else:
            ans = self.model.ask_json(prompt, [], 200, default={}) or {}
        match = [variants[i] for i in ans.get("match", []) if isinstance(i, int) and 0 <= i < len(variants)]
        flags = []
        specs = self.hard_specs() if source != "ref" else set()
        for tok in specs:
            # требование действует, если у товара вообще есть варианты с этой единицей (иначе число может быть только в названии)
            if any(SPEC_RE.search(" ".join(v["attrs"])) and tok[1] in {u.lower() for _, u in SPEC_RE.findall(" ".join(v["attrs"]))} for v in variants):
                keep = [v for v in match if has_spec(" ".join(v["attrs"]), tok)]
                if not keep and match:
                    ans["note"] = f"нет варианта {tok[0]}{tok[1].upper()} (обязательно по твоему запросу/образцу)"
                match = keep
            elif not has_spec(it["title"], tok) and match:
                flags.append(f"в названии нет {tok[0]}{tok[1].upper()} — проверь вручную")
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
                if look.upper().startswith("NO") and not self.image:
                    flags.append("фото не совпадает: " + look.split("-", 1)[-1].strip())
            except Exception as e:
                look = f"ERR {e}"
        same = None
        if self.image and img and source != "ref":
            same = self.same_as_reference(img)
            if same is not None and same < SAME_MIN:
                try:
                    diff = self.model.ask("Image 1 is what the shopper wants, image 2 is an offer. "
                                          "In max 15 words: the main difference between the products?", [self.image, img], 50)
                except Exception:
                    diff = "отличается от образца"
                flags.append(f"не такой, как на твоём фото ({round(same*100)}%): {diff}")
        fee = ship["fee"] if ship else None
        total = real(v) + (fee or 0)
        return {"id": it["id"], "title": it["title"], "source": source,
                "url": f"https://www.aliexpress.com/item/{it['id']}.html",
                "variant": "; ".join(v["attrs"]) or "default", "price": real(v), "shown_price": v["price"],
                "shipping": fee, "ship_company": ship["company"] if ship else None,
                "ship_days": ship["days"] if ship else None, "total": round(total, 2),
                "img": ("https:" + img) if img and img.startswith("//") else img,
                "look": look, "flags": flags, "note": ans.get("note", ""), "rejected": False,
                "currency": it.get("currency") or "USD", "same": same,
                "n_variants": len(variants)}

    def score_thumbs(self, hits):
        """Сравнить миниатюры выдачи с образцом (без открытия карточек)."""
        todo = [h for h in hits if h.get("img") and h["id"] not in self.thumb_same][:THUMBS_PER_LEVEL]
        for h in todo:
            if self.cancelled:
                break
            p = self.same_as_reference(h["img"])
            if p is not None:
                self.thumb_same[h["id"]] = p
        good = [h for h in todo if self.thumb_same.get(h["id"], 0) >= MATCH_MIN]
        if todo:
            self.log(f"  миниатюры: сравнил с твоим фото {len(todo)}, точных совпадений {len(good)}")
        return good

    def queries_from_matches(self):
        """Слова, которыми продавцы называют именно этот товар -> новые запросы."""
        titles = [self.seen[i]["title"] for i, p in self.thumb_same.items() if p >= MATCH_MIN and i in self.seen]
        titles += [c["title"] for c in self.checked.values() if (c.get("same") or 0) >= MATCH_MIN and c.get("title")]
        if self.ref_raw and self.ref_raw.get("title"):
            titles.insert(0, self.ref_raw["title"])
        titles = list(dict.fromkeys(titles))[:12]
        if not titles or (len(titles) < 2 and not self.ref_raw) or len(titles) == getattr(self, "_tq_from", 0):
            return
        self._tq_from = len(titles)
        lines = "\n".join(f"- {t[:140]}" for t in titles)
        qs = self.model.ask_json(
            "These marketplace listing titles are confirmed (by photo) to be EXACTLY the product the shopper wants:\n"
            f"{lines}\n\nWrite 3 short English search queries (3-7 words each) built from the words these sellers use most "
            "often for this product, most likely to find more of the same item first. JSON list of strings.", [], 200, default=[])
        new = [q.strip() for q in qs if isinstance(q, str) and q.strip()] if isinstance(qs, list) else []
        new = [q for q in new if q.lower() not in {x.lower() for x in self.title_queries}]
        if new:
            self.title_queries += new
            self.log("  запросы из названий точных совпадений: " + " | ".join(f"«{q}»" for q in new))

    def same_as_reference(self, img):
        """Оценка «тот же тип товара, что на фото пользователя» — две картинки рядом, вероятность Yes."""
        try:
            return self.model.yes_prob(
                "Image 1 is the product the shopper wants. Image 2 is a marketplace offer. "
                "Is the product in image 2 the same type as in image 1 — same form factor/shape, same kind of board or body, "
                "same connection type (ignore background, text labels, colour of light, and which size/power is shown)? "
                "Answer Yes or No.", [self.image, img])
        except Exception:
            return None

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
            if self.blocked or self.cancelled:
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
        if self.ref_url:
            self.load_reference()
        self.understand()
        if self.ref_variant:
            self.intent.setdefault("must", []).append("exactly this variant: " + "; ".join(
                a.split(":", 1)[-1].strip() for a in self.ref_variant["attrs"]))
        elif self.user_text:
            self.intent.setdefault("must", []).append(f"shopper also said: {self.user_text}")
        if self.ref_raw:
            self.queries_from_matches()
        if self.ref_raw:
            self.ref = self.evaluate(self.ref_raw, source="ref")
            if self.ref:
                self.checked[self.ref["id"]] = self.ref
                if not self.ref.get("rejected"):
                    self.log(f"  образец: ${self.ref['total']:.2f} = ${self.ref['price']:.2f} + доставка ${self.ref['shipping']} — это надо побить")
        n = 0
        while n < MAX_LEVELS and time.time() - self.t0 < TIME_BUDGET:
            if self.cancelled:
                break
            n += 1
            self.log(f"— уровень {n} (утомление {self.fatigue}/{FATIGUE_LIMIT})")
            hits = []
            for desc, fn in self.level_plan(n):
                if self.cancelled:
                    break
                try:
                    h = fn()
                except Exception as e:
                    self.log(f"  {desc}: ошибка {e}"); continue
                if "фото" in desc:
                    for x in h: x["_photo"] = True
                new = [x for x in h if x["id"] not in self.seen]
                for x in h: self.seen.setdefault(x["id"], x)
                self.log(f"  {desc}: {len(h)} товаров, новых {len(new)}")
                hits += new
            cand = self.prefilter(hits)
            cand = [c for c in cand if c["id"] not in self.checked]
            cand.sort(key=lambda c: c["list_price"])
            if self.image and not self.cancelled:
                photo_hits = [h for h in hits if h.get("_photo")][:4]
                self.score_thumbs(photo_hits + [c for c in cand if not c.get("_photo")])
                self.queries_from_matches()
                exact = [h for h in (photo_hits + hits) if self.thumb_same.get(h["id"], 0) >= EXACT_MIN
                         and h["id"] not in self.checked]
                ids = {c["id"] for c in cand}
                cand += [h for h in dict((h["id"], h) for h in exact).values() if h["id"] not in ids]
                cand.sort(key=lambda c: (-(self.thumb_same.get(c["id"], 0.5) >= EXACT_MIN),
                                         self.thumb_same.get(c["id"], 0.5) < SAME_MIN, c["list_price"]))
            pick = cand[:PER_LEVEL]
            self.log(f"  подходят по названию {len(cand)}, открываю {len(pick)}"
                     + (" (сначала похожие на твоё фото, потом дешёвые)" if self.image else " самых дешёвых"))
            before = self.best["total"] if self.best else math.inf
            _, opened = self.open_items([c["id"] for c in pick])
            if self.image:
                self.queries_from_matches()
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

    def tier(self, c):
        """0 — точно такой, 1 — похожий / без образца, 2 — другой."""
        if any(f.startswith("фото не совпадает") for f in c["flags"]):
            return 2
        sm = c.get("same")
        if sm is None:
            return 0 if c["source"] == "ref" or not self.image else 1
        return 0 if sm >= EXACT_MIN else (1 if sm >= SAME_MIN else 2)

    def _fits(self, c):
        return self.tier(c) < 2

    def _update_best(self):
        ok = [c for c in self.checked.values() if not c["rejected"] and c["source"] != "ref" and self._fits(c)]
        top_tier = min((self.tier(c) for c in ok), default=None)
        ok = [c for c in ok if self.tier(c) == top_tier]
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
            same = f" — looks like the shopper's photo: {round(c['same']*100)}%" if c.get("same") is not None else ""
            out.append(f"#{i} ${c['total']:.2f} total (item ${c['price']:.2f} + shipping ${c['shipping']}, "
                       f"{(c['ship_days'] or ['?','?'])[0]}-{(c['ship_days'] or ['?','?'])[1]} days) — variant «{c['variant']}» — "
                       f"{c['title'][:90]}" + same + (" — this is the shopper's own reference link" if c["source"] == "ref" else "")
                       + (f" — warnings: {'; '.join(c['flags'])}" if c["flags"] else ""))
        return "\n".join(out)

    def score(self):
        self._update_best()
        rows = sorted([c for c in self.checked.values() if not c["rejected"] and c["source"] != "ref"],
                      key=lambda c: (self.tier(c), c["total"]))[:10]
        if self.ref and not self.ref.get("rejected"):
            rows.append(self.ref)
            rows.sort(key=lambda c: (self.tier(c), c["total"]))
        for c in rows:
            c["tier"] = self.tier(c)
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
        return {"intent": self.intent, "done": self.done, "blocked": self.blocked, "ref": self.ref, "fatigue": self.fatigue, "levels": self.levels,
                "seen": len(self.seen), "checked": len(self.checked), "confidence": self.confidence,
                "top": getattr(self, "top", []),
                "rejected": [c for c in self.checked.values() if c["rejected"]][:30],
                "human": [c for c in self.checked.values() if c["source"] == "human"],
                "elapsed": round(time.time() - self.t0)}
