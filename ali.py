"""AliExpress: поиск (простой HTTP) и карточка товара (безголовый Chromium, ответ pdp API)."""
import glob, json, os, re, time, urllib.parse, urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
CHROME = (glob.glob("/home/helgard/.cache/ms-playwright/chromium-1243/chrome-linux*/chrome") or [None])[0]


def region_cookie(ship_to="UA", currency="USD"):
    return f"site=glo&province=&city=&c_tp={currency}&region={ship_to}&b_locale=en_US"


def search(query, ship_to="UA", currency="USD", sort="price_asc", page=1):
    q = urllib.parse.quote(query.replace(" ", "-"))
    url = f"https://www.aliexpress.com/w/wholesale-{q}.html?SortType={sort}&page={page}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US",
                                               "Cookie": "aep_usuc_f=" + region_cookie(ship_to, currency)})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf8", "replace")
    return _parse_search(html)


def _pdp_result(text):
    return json.loads(re.sub(r'^[^{]*\(|\)\s*$', '', text.strip()))["data"]["result"]


def money(text):
    """«US $1,234.56», «1 234,56 грн.», «€ 35,69» -> float."""
    m = re.search(r"\d[\d\s\u00a0\u202f.,]*\d|\d", str(text or ""))
    if not m:
        return None
    t = re.sub(r"[\s\u00a0\u202f]", "", m.group())
    if "," in t and "." in t:
        t = t.replace(",", "") if t.rfind(".") > t.rfind(",") else t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".") if len(t.split(",")[-1]) <= 2 else t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def parse_item(r):
    sku = r["SKU"]
    names = {}
    for prop in sku.get("skuProperties", []):
        for v in prop["skuPropertyValues"]:
            names[str(v["propertyValueIdLong"])] = (prop.get("skuPropertyName"), v.get("propertyValueDisplayName"),
                                                     v.get("skuPropertyImagePath"))
    prices = r["PRICE"].get("skuIdStrPriceInfoMap", {})
    banner = (r.get("PRICE_BANNER") or {}).get("atmosphereCodeMap", {})
    imgs = (r.get("HEADER_IMAGE_PC") or {}).get("skuImagesMap", {})
    variants = []
    for p in sku.get("skuPaths", []):
        sid = p["skuIdStr"]
        attrs, vimg = [], None
        for part in p["path"].split(";"):
            if ":" in part:
                n = names.get(part.split(":")[1])
                if n:
                    attrs.append(f"{n[0]}: {n[1]}")
                    vimg = vimg or n[2]
        pi = prices.get(sid, {})
        sale = money(pi.get("salePriceString"))
        variants.append({"sku": sid, "attrs": attrs, "stock": p.get("skuStock"), "salable": p.get("salable"),
                         "price": sale,
                         "original": (pi.get("originalPrice") or {}).get("value"),
                         "welcome_deal": "welcome" in (banner.get(sid) or ""),
                         "img": vimg or (imgs.get(sid) or [None])[0]})
    ship = []
    for li in (r.get("SHIPPING") or {}).get("deliveryLayoutInfo", []):
        b = li.get("bizData", {})
        ship.append({"company": b.get("company"), "fee": b.get("displayAmount") if b.get("shippingFee") != "free" else 0.0,
                     "fee_kind": b.get("shippingFee"), "days": [b.get("deliveryDayMin"), b.get("deliveryDayMax")],
                     "ship_to": b.get("shipToCode"), "from": b.get("shipFrom")})
    cur = None
    for pi in prices.values():
        cur = (pi.get("originalPrice") or {}).get("currency")
        if cur: break
    cur = cur or next((li.get("bizData", {}).get("displayCurrency") for li in (r.get("SHIPPING") or {}).get("deliveryLayoutInfo", [])), None)
    title = (r.get("PRODUCT_TITLE") or {}).get("text")
    main = ((r.get("HEADER_IMAGE_PC") or {}).get("imagePathList") or [None])
    return {"title": title, "main_images": main[:6], "variants": variants, "shipping": ship, "currency": cur}


class Captcha(Exception):
    """AliExpress попросил капчу (страница punish) — дальше открывать товары нельзя, ждать."""


CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cache")
CACHE_TTL = 6 * 3600


def _cache_path(pid, ship_to, currency):
    return os.path.join(CACHE_DIR, f"{pid}_{ship_to}_{currency}.json")


def cached_item(pid, ship_to="UA", currency="USD"):
    p = _cache_path(pid, ship_to, currency)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < CACHE_TTL:
        return json.load(open(p))
    return None


class Fetcher:
    """Один браузер на поток, товары по одному с паузой (вежливый темп — иначе капча через ~25 страниц)."""
    PAUSE = 1.5

    def __init__(self, ship_to="UA", currency="USD"):
        from playwright.sync_api import sync_playwright
        self.ship_to, self.currency = ship_to, currency
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=True, executable_path=CHROME)
        self.ctx = self.browser.new_context(locale="en-US", user_agent=UA)
        self.ctx.add_cookies([{"name": "aep_usuc_f", "value": region_cookie(ship_to, currency),
                               "domain": ".aliexpress.com", "path": "/"}])
        self.last = 0.0

    def item(self, pid):
        c = cached_item(pid, self.ship_to, self.currency)
        if c:
            return c
        wait = self.PAUSE - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        page = self.ctx.new_page()
        got, punished = [], []
        def on_resp(r):
            if "punish" in r.url:
                punished.append(r.url)
            elif "mtop.aliexpress.pdp.pc.query" in r.url:
                got.append(r)
        page.on("response", on_resp)
        try:
            page.goto(f"https://www.aliexpress.com/item/{pid}.html", wait_until="domcontentloaded", timeout=45000)
            res = None
            for _ in range(30):
                if punished:
                    raise Captcha(pid)
                for r in got:
                    try:
                        t = r.text()
                        if len(t) > 5000:
                            res = parse_item(_pdp_result(t)); break
                    except Captcha:
                        raise
                    except Exception:
                        pass
                if res: break
                page.wait_for_timeout(500)
            if punished:
                raise Captcha(pid)
        finally:
            self.last = time.time()
            page.close()
        if res:
            res["id"] = pid
            os.makedirs(CACHE_DIR, exist_ok=True)
            json.dump(res, open(_cache_path(pid, self.ship_to, self.currency), "w"), ensure_ascii=False)
        return res

    def close(self):
        try:
            self.browser.close(); self.pw.stop()
        except Exception:
            pass


def item(pid, ship_to="UA", currency="USD", browser=None):
    from playwright.sync_api import sync_playwright
    own = browser is None
    if own:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True, executable_path=CHROME)
    ctx = browser.new_context(locale="en-US", user_agent=UA)
    ctx.add_cookies([{"name": "aep_usuc_f", "value": region_cookie(ship_to, currency),
                      "domain": ".aliexpress.com", "path": "/"}])
    page = ctx.new_page()
    got = []
    page.on("response", lambda resp: got.append(resp) if "mtop.aliexpress.pdp.pc.query" in resp.url else None)
    page.goto(f"https://www.aliexpress.com/item/{pid}.html", wait_until="domcontentloaded", timeout=45000)
    for _ in range(30):
        if got: break
        page.wait_for_timeout(500)
    page.wait_for_timeout(1500)
    res = None
    for resp in got:
        try:
            t = resp.text()
            if len(t) > 5000:
                res = parse_item(_pdp_result(t)); break
        except Exception:
            pass
    ctx.close()
    if own:
        browser.close(); pw.stop()
    if res: res["id"] = pid
    return res


def search_url(url, ship_to="UA", currency="USD"):
    """Читает готовую страницу выдачи (например, результат поиска по фото) простым HTTP."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US",
                                               "Cookie": "aep_usuc_f=" + region_cookie(ship_to, currency)})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf8", "replace")
    return _parse_search(html)


def _parse_search(html):
    out, seen = [], set()
    starts = [m for m in re.finditer(r'"productId":"(\d+)"', html)]
    for k, m in enumerate(starts):
        if m.group(1) in seen:
            continue
        end = starts[k + 1].start() if k + 1 < len(starts) else m.start() + 8000
        chunk = html[m.start():min(end, m.start() + 8000)]
        title = re.search(r'"displayTitle":"((?:[^"\\]|\\.)*)"', chunk)
        price = re.search(r'"minPrice":([\d.]+)', chunk)
        img = re.search(r'"imgUrl":"([^"]+)"', chunk)
        if title and price:
            seen.add(m.group(1))
            src = img.group(1) if img else None
            out.append({"id": m.group(1), "title": json.loads('"%s"' % title.group(1)),
                        "list_price": float(price.group(1)),
                        "img": ("https:" + src) if src and src.startswith("//") else src,
                        # метки карточки: бесплатная доставка / цена для новичков / «лучшая цена такого же» по версии сайта
                        "free_ship": "Free_Shipping" in chunk or "platformFreeShipping" in chunk,
                        "welcome": "welcomedeal" in chunk,
                        "same_style_best": "SAME_STYLE_PRICE_BEST" in chunk})
    return out


def image_search(path, ship_to="UA", currency="USD"):
    """Поиск по фото, как кнопка-камера на сайте: загрузка картинки в браузере -> адрес выдачи -> товары."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, executable_path=CHROME)
        ctx = b.new_context(locale="en-US", user_agent=UA, viewport={"width": 1400, "height": 900})
        ctx.add_cookies([{"name": "aep_usuc_f", "value": region_cookie(ship_to, currency),
                          "domain": ".aliexpress.com", "path": "/"}])
        pg = ctx.new_page()
        pg.goto("https://www.aliexpress.com/", wait_until="domcontentloaded", timeout=45000)
        btn = pg.wait_for_selector('[class*="picture-search-btn"]', timeout=20000)
        for sel in ["text=Accept cookies", "text=Don't allow"]:
            try: pg.click(sel, timeout=1500)
            except Exception: pass
        try: pg.keyboard.press("Escape")
        except Exception: pass
        btn.click(force=True)
        inp = pg.wait_for_selector("input[type=file]", state="attached", timeout=10000)
        inp.set_input_files(path)
        pg.wait_for_url(re.compile(r"isNewImageSearch"), timeout=40000)
        pg.wait_for_timeout(2500)
        url, html = pg.url, pg.content()
        b.close()
    hits = _parse_search(html)
    if len(hits) < 10:
        hits = search_url(url, ship_to, currency)
    return url, hits


def variant_groups(it):
    """{"Колір": [{"value": "100W", "img": ...}, ...], ...} из attrs вида «Имя: значение»."""
    groups = {}
    for v in it["variants"]:
        for a in v["attrs"]:
            name, _, val = a.partition(":")
            g = groups.setdefault(name.strip(), [])
            if val.strip() and val.strip() not in [x["value"] for x in g]:
                g.append({"value": val.strip(), "img": v.get("img")})
    return [{"name": k, "values": v} for k, v in groups.items()]
