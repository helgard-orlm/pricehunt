// Разбор данных AliExpress: карточка товара (ответ pdp), выдача поиска, цены.
// Перенос ali.py стенда; поведение то же, проверено на живых данных 14.10.

/** «US $1,234.56», «1 234,56 грн.», «€ 35,69» -> число. */
export function money(text) {
  const m = String(text ?? "").match(/\d[\d\s  .,]*\d|\d/);
  if (!m) return null;
  let t = m[0].replace(/[\s  ]/g, "");
  if (t.includes(",") && t.includes(".")) {
    t = t.lastIndexOf(".") > t.lastIndexOf(",") ? t.replace(/,/g, "") : t.replace(/\./g, "").replace(",", ".");
  } else if (t.includes(",")) {
    t = t.split(",").pop().length <= 2 ? t.replace(",", ".") : t.replace(/,/g, "");
  }
  const v = parseFloat(t);
  return Number.isFinite(v) ? v : null;
}

/** Текст ответа mtop.aliexpress.pdp.pc.query (JSON или JSONP) -> data.result. */
export function pdpResult(text) {
  const s = String(text).trim().replace(/^[^{]*\(/, "").replace(/\)\s*$/, "");
  const j = JSON.parse(s);
  return (j.data && j.data.result) || j.result || j;
}

const abs = (u) => (u && u.startsWith("//") ? "https:" + u : u);

/** data.result карточки -> {title, main_images, variants[], shipping[], currency}. */
export function parseItem(r) {
  const sku = r.SKU || {};
  const names = {};
  for (const prop of sku.skuProperties || []) {
    for (const v of prop.skuPropertyValues || []) {
      names[String(v.propertyValueIdLong)] = [prop.skuPropertyName, v.propertyValueDisplayName, v.skuPropertyImagePath];
    }
  }
  const prices = (r.PRICE || {}).skuIdStrPriceInfoMap || {};
  const banner = ((r.PRICE_BANNER || {}).atmosphereCodeMap) || {};
  const imgs = ((r.HEADER_IMAGE_PC || {}).skuImagesMap) || {};
  const variants = [];
  for (const p of sku.skuPaths || []) {
    const sid = p.skuIdStr;
    const attrs = [];
    let vimg = null;
    for (const part of String(p.path || "").split(";")) {
      if (!part.includes(":")) continue;
      const n = names[part.split(":")[1]];
      if (n) { attrs.push(`${n[0]}: ${n[1]}`); vimg = vimg || n[2]; }
    }
    const pi = prices[sid] || {};
    variants.push({
      sku: sid, attrs, stock: p.skuStock, salable: p.salable !== false,
      price: money(pi.salePriceString),
      original: (pi.originalPrice || {}).value ?? null,
      welcome_deal: String(banner[sid] || "").includes("welcome"),
      img: abs(vimg || (imgs[sid] || [null])[0]),
    });
  }
  const shipping = [];
  for (const li of ((r.SHIPPING || {}).deliveryLayoutInfo) || []) {
    const b = li.bizData || {};
    shipping.push({
      company: b.company, fee: b.shippingFee === "free" ? 0 : b.displayAmount, fee_kind: b.shippingFee,
      // Choice: сайт пишет «Free shipping», если shippingFee=free ИЛИ порог бесплатной доставки нулевой (thresholdOverZero=no),
      // хотя displayAmount=0.49 (правило из самих данных страницы: displayCondition "shippingFee=free||thresholdOverZero!=yes").
      // При пороге > 0 — бесплатно, если цена товара не ниже порога (logisticsComposeThreshold). Замер 14.10, зарядка helgard.
      free_now: b.shippingFee === "free" || b.thresholdOverZero === "no",
      threshold: b.thresholdOverZero === "yes" ? money(b.logisticsComposeThreshold) : null,
      days: [b.deliveryDayMin, b.deliveryDayMax], ship_to: b.shipToCode, from: b.shipFrom,
    });
  }
  let currency = null;
  for (const pi of Object.values(prices)) { currency = (pi.originalPrice || {}).currency; if (currency) break; }
  currency = currency || (((r.SHIPPING || {}).deliveryLayoutInfo || [])[0] || {}).bizData?.displayCurrency || null;
  return {
    title: (r.PRODUCT_TITLE || {}).text || "",
    main_images: (((r.HEADER_IMAGE_PC || {}).imagePathList) || []).slice(0, 6).map(abs),
    variants, shipping, currency,
  };
}

/** Варианты, сгруппированные по свойствам — для кнопок выбора. */
export function variantGroups(item) {
  const groups = new Map();
  for (const v of item.variants) {
    for (const a of v.attrs) {
      const i = a.indexOf(":");
      const name = a.slice(0, i).trim(), val = a.slice(i + 1).trim();
      if (!groups.has(name)) groups.set(name, []);
      const g = groups.get(name);
      if (val && !g.some((x) => x.value === val)) g.push({ value: val, img: v.img });
    }
  }
  return [...groups].map(([name, values]) => ({ name, values }));
}

/** Стоимость способа доставки для товара по цене price — как её покажет сайт. */
export function feeFor(s, price) {
  if (!s || s.fee == null) return null;
  if (s.free_now) return 0;
  if (s.threshold != null && price != null && price >= s.threshold) return 0;
  return s.fee;
}

/** Самый дешёвый способ доставки для цены price: {ship, fee}. */
export function cheapestShip(shipping, price) {
  let best = null;
  for (const s of shipping || []) {
    const f = feeFor(s, price);
    if (f != null && (!best || f < best.fee)) best = { ship: s, fee: f };
  }
  return best || { ship: null, fee: null };
}

/** HTML страницы выдачи (обычный поиск или поиск по фото) -> товары с метками карточки. */
export function parseSearch(html) {
  const out = [], seen = new Set();
  const re = /"productId":"(\d+)"/g;
  const starts = [];
  let m;
  while ((m = re.exec(html))) starts.push([m.index, m[1]]);
  for (let k = 0; k < starts.length; k++) {
    const [at, id] = starts[k];
    if (seen.has(id)) continue;
    const end = Math.min(k + 1 < starts.length ? starts[k + 1][0] : at + 8000, at + 8000);
    const chunk = html.slice(at, end);
    const title = chunk.match(/"displayTitle":"((?:[^"\\]|\\.)*)"/);
    // у карточки со скидкой две цены: сначала original_price (зачёркнутая), потом sale_price — берём цену продажи (замер 14.10: 35 из 59)
    const price = chunk.match(/"priceType":"sale_price"[^}]*?"minPrice":([\d.]+)/) || chunk.match(/"minPrice":([\d.]+)/);
    const img = chunk.match(/"imgUrl":"([^"]+)"/);
    if (!title || !price) continue;
    seen.add(id);
    let t;
    try { t = JSON.parse('"' + title[1] + '"'); } catch { t = title[1]; }
    out.push({
      id, title: t, list_price: parseFloat(price[1]), img: img ? abs(img[1]) : null,
      // метки карточки: бесплатная доставка / цена для новичков / «лучшая цена такого же» по версии сайта
      free_ship: chunk.includes("Free_Shipping") || chunk.includes("platformFreeShipping"),
      welcome: chunk.includes("welcomedeal"),
      same_style_best: chunk.includes("SAME_STYLE_PRICE_BEST"),
      // «Пропозиції комплектів» (Bundle deals): карточка ведёт на BundleDeals2?productIds=<товар>:<вариант>,
      // скидка — на заказ из нескольких РАЗНЫХ товаров («грн.150 off on 3 items»), не на штуку (замер 14.10)
      bundle: /BundleDeals\d*\?productIds=/.test(chunk)
        ? (() => { const n = chunk.match(/"title":"((?:[^"\\]|\\.)*?off on \d+ items?)"/); try { return n ? JSON.parse('"' + n[1] + '"') : "bundle"; } catch { return n ? n[1] : "bundle"; } })()
        : null,
    });
  }
  return out;
}

export function itemIdFromUrl(url) {
  const m = String(url || "").match(/\/item\/(\d+)/) || String(url || "").match(/(\d{10,})/);
  return m ? m[1] : null;
}

export function skuFromUrl(url) {
  const m = String(url || "").match(/(?:skuId=|%21)(12\d{12,})/);
  return m ? m[1] : null;
}
