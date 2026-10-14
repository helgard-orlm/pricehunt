"""AliExpress: поиск (простой HTTP) и карточка товара (безголовый Chromium, ответ pdp API)."""
import glob, json, re, urllib.parse, urllib.request

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
    out = []
    for m in re.finditer(r'"productId":"(\d+)"', html):
        chunk = html[m.start():m.start() + 6000]
        title = re.search(r'"displayTitle":"((?:[^"\\]|\\.)*)"', chunk)
        price = re.search(r'"minPrice":([\d.]+)', chunk)
        img = re.search(r'"imgUrl":"([^"]+)"', chunk)
        if title and price:
            out.append({"id": m.group(1), "title": json.loads('"%s"' % title.group(1)),
                        "list_price": float(price.group(1)),
                        "img": "https:" + img.group(1) if img and img.group(1).startswith("//") else (img.group(1) if img else None)})
    seen, uniq = set(), []
    for o in out:
        if o["id"] not in seen:
            seen.add(o["id"]); uniq.append(o)
    return uniq


def _pdp_result(text):
    return json.loads(re.sub(r'^[^{]*\(|\)\s*$', '', text.strip()))["data"]["result"]


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
        sale = re.search(r"[\d.]+", (pi.get("salePriceString") or "").replace(",", ""))
        variants.append({"sku": sid, "attrs": attrs, "stock": p.get("skuStock"), "salable": p.get("salable"),
                         "price": float(sale.group()) if sale else None,
                         "original": (pi.get("originalPrice") or {}).get("value"),
                         "welcome_deal": "welcome" in (banner.get(sid) or ""),
                         "img": vimg or (imgs.get(sid) or [None])[0]})
    ship = []
    for li in (r.get("SHIPPING") or {}).get("deliveryLayoutInfo", []):
        b = li.get("bizData", {})
        ship.append({"company": b.get("company"), "fee": b.get("displayAmount") if b.get("shippingFee") != "free" else 0.0,
                     "fee_kind": b.get("shippingFee"), "days": [b.get("deliveryDayMin"), b.get("deliveryDayMax")],
                     "ship_to": b.get("shipToCode"), "from": b.get("shipFrom")})
    title = (r.get("PRODUCT_TITLE") or {}).get("text")
    main = ((r.get("HEADER_IMAGE_PC") or {}).get("imagePathList") or [None])
    return {"title": title, "main_images": main[:6], "variants": variants, "shipping": ship}


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
