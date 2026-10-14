// Агент pricehunt: ищет тот же товар (выбранный вариант) дешевле. Перенос hunt.py стенда.
//
// Настоящая цена = цена НУЖНОГО варианта + самая дешёвая доставка (как показывает AliExpress пользователю).
// Метод helgard: фото -> точно такие по миниатюре -> дословное название совпадения -> выдача, разделённая
// самим агентом на бесплатную / платную доставку и отсортированная самим (сортировке сайта не верим) -> новый лучший -> снова.
// Глубина по правилу helgard: 3 уровня свободно, дальше уровень без находки дешевле = +1 утомления, находка сбрасывает.
// Проценты — вероятность ответа Yes у модели (как у моделей класса Jev); это оценка, не откалиброванная вероятность.

import * as browse from "./browse.js";
import { toJpegB64 } from "./model.js";
import { t } from "./i18n.js";
import { cheapestShip } from "./parse.js";

export const SAME_MIN = 0.3;      // ниже — «другой», чем образец
export const EXACT_MIN = 0.7;     // от этого — «точно такой»; лучшим может быть только он
const FREE_LEVELS = 3, FATIGUE_LIMIT = 3, MAX_LEVELS = 9;
const PER_LEVEL = 8;              // сколько карточек открывать за уровень (helgard открывает ~10)
const PER_VIEW = 5;               // сколько самых дешёвых проверять в каждой части выдачи
const TIME_BUDGET = 20 * 60 * 1000;

const SPEC_RE = /(\d+(?:[.,]\d+)?)\s*(w|mah|mm|cm|inch|in|gb|tb|ah)\b/gi;   // напряжение не жёстко: «200-240V» ≠ «220V»

function specTokens(text) {
  const out = new Map();
  for (const m of String(text || "").matchAll(SPEC_RE)) {
    let u = m[2].toLowerCase();
    if (u === "in") u = "inch";
    const num = m[1].replace(",", ".");
    out.set(num + u, [num, u]);
  }
  return [...out.values()];
}
function hasSpec(text, [num, unit]) {
  const alt = unit === "inch" ? "(?:inch|in|\"|'')" : unit;
  return new RegExp(`(?<![\\d.])${num.replace(".", "\\.")}\\s*${alt}\\b`, "i").test(text || "");
}
const unitsIn = (text) => new Set([...String(text || "").matchAll(SPEC_RE)].map((m) => (m[2].toLowerCase() === "in" ? "inch" : m[2].toLowerCase())));

const PLUG = { GB: "UK", US: "US", CA: "US", AU: "AU" };
function plugOf(attrs) { const m = attrs.join(" ").match(/\b(EU|US|UK|AU|KR)\b/i); return m ? m[1].toUpperCase() : null; }

const money = (v, cur) => (v == null ? "?" : (!cur || cur === "USD" ? "$" + v.toFixed(2) : v.toFixed(2) + " " + cur));

export class Hunt {
  /**
   * @param ref  {id, item, variant} — товар с открытой страницы и выбранный пользователем вариант
   * @param model экземпляр Model
   * @param on   {log(text), update(state), captcha(on)}
   */
  constructor({ ref, model, on, shipTo }) {
    this.ref = ref; this.model = model; this.on = on; this.shipTo = shipTo || "UA";
    this.seen = new Map(); this.checked = new Map(); this.thumb = new Map();
    this.levels = []; this.fatigue = 0; this.best = null; this.top = [];
    this.titlesUsed = new Set(); this.cancelled = false; this.blocked = false; this.done = false;
    this.confidence = null; this.t0 = Date.now(); this.image = null; this.intent = null; this.refEval = null;
    this.hooks = { onCaptcha: () => { this.log(t("a_captcha")); this.on.captcha?.(true); } };
  }

  log(t) { this.on.log?.(t); }
  cur() { return this.ref.item.currency || "USD"; }
  m(v) { return money(v, this.cur()); }
  elapsed() { return Math.round((Date.now() - this.t0) / 1000); }

  // ---------- требования ----------
  hardSpecs() { return specTokens(this.ref.variant ? this.ref.variant.attrs.join(" ") : ""); }
  /** Характеристики для отбора карточек выдачи: из выбранного варианта; если там нет — из названия образца, когда она одна (33W). */
  pickSpecs() {
    const v = this.hardSpecs();
    if (v.length) return v;
    const tt = specTokens(this.ref.item.title);
    return tt.length === 1 ? tt : [];
  }

  async understand() {
    const v = this.ref.variant ? this.ref.variant.attrs.map((a) => a.split(":").pop().trim()).join("; ") : "";
    const it = await this.model.askJson(
      "A shopper is on this AliExpress product and wants the SAME product cheaper.\n" +
      `Listing title: ${this.ref.item.title}\n` + (v ? `Chosen variant: ${v}\n` : "") +
      "The photo shows EXACTLY the product they want: base the description, must-haves and wrong items on what the photo shows " +
      "(type, shape/form factor, how it is connected or powered, built-in parts). JSON fields: " +
      '"what" (short exact product description), "must" (1-5 key features), ' +
      '"not" (things that look similar but are wrong), "queries" (4 short English search queries, most likely first).',
      this.image ? ["data:image/jpeg;base64," + this.image] : [], 500, {});
    const intent = it && it.what ? it : { what: this.ref.item.title, must: [], not: [], queries: [] };
    intent.must = intent.must || []; intent.not = intent.not || [];
    intent.queries = (intent.queries || []).filter(Boolean).slice(0, 6);
    if (v) intent.must.push("exactly this variant: " + v);
    this.intent = intent;
    this.log(t("a_understood", { what: intent.what }) + (intent.not.length ? t("a_not", { x: intent.not.join(", ") }) : ""));
  }

  // ---------- сравнение с образцом ----------
  async sameAsRef(img) {
    return this.model.yesProb(
      "Image 1 is the product the shopper wants. Image 2 is a marketplace offer. " +
      "Is the product in image 2 the same type as in image 1 — same form factor/shape, same kind of board or body, " +
      "same connection type (ignore background, text labels, colour of light, and which size/power is shown)? Answer Yes or No.",
      ["data:image/jpeg;base64," + this.image, img]).catch(() => null);
  }

  tier(c) {
    if (c.source === "ref") return 0;
    if (c.same == null) return 1;
    return c.same >= EXACT_MIN ? 0 : c.same >= SAME_MIN ? 1 : 2;
  }

  // ---------- проверка карточки ----------
  async evaluate(it, source = "agent") {
    let variants = (source === "ref" && this.ref.variant ? [this.ref.variant] : it.variants)
      .filter((v) => v.salable !== false && v.price);
    if (!variants.length) return null;
    let ans;
    if (source === "ref") ans = { match: [0], note: t("a_your_variant") };
    else {
      const lines = variants.map((v, i) => `${i}. ${v.attrs.join("; ") || "default"} — ${v.price}`).join("\n");
      ans = await this.model.askJson(
        `Wanted product: ${this.intent.what}. Must have: ${this.intent.must.join(", ")}. Wrong items: ${this.intent.not.join(", ")}.\n` +
        `Listing title: ${it.title}\nVariants:\n${lines}\n\n` +
        "Which variant numbers are exactly the wanted product (not an accessory, cable only, or a different item)? " +
        'JSON: {"match": [numbers], "note": "one short sentence"}', [], 200, {}) || {};
    }
    let match = (ans.match || []).filter((i) => Number.isInteger(i) && i >= 0 && i < variants.length).map((i) => variants[i]);
    const flags = [];
    if (source !== "ref") {
      for (const tok of this.hardSpecs()) {
        // число из выбранного варианта обязательно, если у товара вообще есть варианты с этой единицей
        if (variants.some((v) => unitsIn(v.attrs.join(" ")).has(tok[1]))) {
          const keep = match.filter((v) => hasSpec(v.attrs.join(" "), tok));
          if (!keep.length && match.length) ans.note = t("a_no_spec_variant", { s: tok[0] + tok[1].toUpperCase() });
          match = keep;
        } else if (match.length && !hasSpec(it.title, tok)) {
          flags.push(t("a_spec_not_in_title", { s: tok[0] + tok[1].toUpperCase() }));
        }
      }
    }
    const url = `https://www.aliexpress.com/item/${it.id}.html`;
    if (!match.length) return { id: it.id, title: it.title, url, source, rejected: true, note: ans.note || t("a_no_variant") };
    const want = PLUG[this.shipTo] || "EU";
    const plugs = new Set(match.map((v) => plugOf(v.attrs)).filter(Boolean));
    if (plugs.size) {
      const mine = match.filter((v) => [want, null].includes(plugOf(v.attrs)));
      if (mine.length) match = mine; else flags.push(t("a_no_plug", { w: want, p: [...plugs].join(", ") }));
    }
    // цена для новичка недоступна старому покупателю: считаем по обычной (честно)
    const real = (v) => (v.welcome_deal ? v.original || v.price : v.price);
    const v = match.reduce((a, b) => (real(b) < real(a) ? b : a));
    const cheapest = variants.reduce((a, b) => (b.price < a.price ? b : a));
    if (cheapest.price < v.price - 0.01 && !match.includes(cheapest))
      flags.push(t("a_list_price", { p: this.m(cheapest.price), v: cheapest.attrs.join("; ") }));
    if (v.welcome_deal) flags.push(t("a_welcome", { p: this.m(v.price), r: this.m(real(v)) }));
    const bundle = this.seen.get(it.id)?.bundle || null;     // метка «Пропозиції комплектів» с карточки выдачи
    if (bundle && source !== "ref") flags.push(t("a_bundle_flag", { n: bundle }));
    const img = v.img || it.main_images[0] || null;
    let same = null;
    if (source !== "ref" && img && this.image) {
      same = this.thumbFor(it.id);   // миниатюра уже дала уверенное «да» — второй раз не сравниваем
      if (same == null || same < 0.99) same = await this.sameAsRef(img);
      if (same != null && same < SAME_MIN) {
        const diff = await this.model.ask("Image 1 is what the shopper wants, image 2 is an offer. In max 15 words: the main difference?",
          ["data:image/jpeg;base64," + this.image, img], 50).catch(() => "");
        flags.push(t("a_not_like", { p: Math.round(same * 100) }) + (diff ? `: ${diff}` : ""));
      }
    }
    const { ship, fee } = cheapestShip(it.shipping, real(v));
    return {
      id: it.id, title: it.title, url, source, rejected: false, img, same, flags, note: ans.note || "", bundle,
      variant: v.attrs.join("; ") || "default", price: real(v), shown_price: v.price,
      shipping: fee, ship_company: ship?.company, ship_days: ship?.days,
      total: Math.round((real(v) + (fee || 0)) * 100) / 100, currency: it.currency || this.cur(),
    };
  }

  thumbFor(id) { return this.thumb.has(id) ? this.thumb.get(id) : null; }

  async open(ids, source = "agent") {
    let opened = 0;
    for (const pid of ids) {
      if (this.cancelled || this.blocked) break;
      let it;
      try { it = await browse.item(pid, this.hooks); }
      catch (e) {
        if (e instanceof browse.Captcha) { this.blocked = true; this.log(t("a_captcha_stop")); break; }
        this.log(`  ${t("a_not_opened", { id: pid })}: ${e.message}`); continue;
      }
      this.on.captcha?.(false);
      if (!it) { this.log("  " + t("a_not_opened", { id: pid })); continue; }
      opened++;
      const ev = await this.evaluate(it, source);
      if (!ev) continue;
      this.checked.set(pid, ev);
      if (ev.rejected) this.log(`  ✗ ${it.title.slice(0, 60)} — ${ev.note}`);
      else this.log(`  ✓ ${t("a_ok_line", { t: this.m(ev.total), p: this.m(ev.price), s: this.m(ev.shipping) })} · ${ev.variant.slice(0, 40)}` + (ev.flags.length ? " ⚠" : ""));
      this.updateBest(); this.publish();
    }
    return opened;
  }

  // ---------- поиск ----------
  async search(q, sort) {
    let res = await browse.search(q, { sort }, this.hooks);
    if (!res.length && sort !== "default") {
      // AliExpress иногда нарочно отдаёт пусто на сортировку/фильтр — это отказ, не «товаров нет»
      this.log("  " + t("a_sort_refused"));
      res = await browse.search(q, { sort: "default" }, this.hooks);
    }
    if (sort === "price_asc" && res.length) {
      const pr = res.map((x) => x.list_price);
      if (pr.slice(1).filter((b, i) => b < pr[i] - 0.005).length > pr.length / 10) this.log("  " + t("a_unsorted"));
    }
    return res;
  }

  nextExactTitle() {
    const titles = [...this.checked.values()].filter((c) => !c.rejected && c.source !== "ref" && this.tier(c) === 0)
      .sort((a, b) => a.total - b.total).map((c) => c.title);
    titles.push(...[...this.thumb].filter(([id, p]) => p >= EXACT_MIN && this.seen.has(id))
      .map(([id]) => this.seen.get(id)).sort((a, b) => a.list_price - b.list_price).map((h) => h.title));
    titles.push(this.ref.item.title);
    for (const t of titles) {
      const clean = String(t || "").replace(/[^\p{L}\p{N}\s.,+/-]/gu, " ").split(/\s+/).filter(Boolean).slice(0, 16).join(" ");
      if (clean && !this.titlesUsed.has(clean.toLowerCase())) { this.titlesUsed.add(clean.toLowerCase()); return clean; }
    }
    return null;
  }

  plan(n) {
    if (n === 1) return [[t("a_photo_ref"), () => browse.photoSearch(this.image, this.hooks)]];
    const plan = [];
    const title = this.nextExactTitle();
    if (title) {
      plan.push([t("a_exact_title", { t: title.slice(0, 60) }), () => this.search(title, "default")]);
      plan.push([t("a_title_price"), () => this.search(title, "price_asc")]);
    }
    if (this.best && n % 2 === 1)
      plan.push([t("a_photo_best"), async () => browse.photoSearch(await toJpegB64(this.best.img), this.hooks)]);
    if (!title) {
      const q = (this.intent.queries || []).find((x) => !this.titlesUsed.has(x.toLowerCase()));
      if (q) { this.titlesUsed.add(q.toLowerCase()); plan.push([t("a_query", { q }), () => this.search(q, "default")]); }
    }
    return plan;
  }

  async pick(hits) {
    const pool = hits.filter((h) => !this.checked.has(h.id));
    const byPrice = (a, b) => a.list_price - b.list_price;
    const free = pool.filter((h) => h.free_ship).sort(byPrice), paid = pool.filter((h) => !h.free_ship).sort(byPrice);
    this.log("  " + t("a_split", { f: free.length, p: paid.length, n: PER_VIEW }));
    const nb = pool.filter((h) => h.bundle).length;
    if (nb) this.log("  " + t("a_bundle_seen", { n: nb }));
    // сначала карточки с той же характеристикой в названии (33W, 100W…): иначе 5 «самых дешёвых» съедают кабели,
    // другие мощности и цены для новичков (14.10: находка helgard стояла 13-й среди платной доставки, впереди — 20W/30W/кабели)
    const want = this.pickSpecs();
    const fits = (h) => want.every((tok) => hasSpec(h.title, tok));
    const view = (part) => {
      if (!want.length) return part.slice(0, PER_VIEW);
      const yes = part.filter(fits), no = part.filter((h) => !fits(h));
      return [...yes.slice(0, PER_VIEW), ...no.slice(0, Math.max(0, PER_VIEW - yes.length, 1))];
    };
    if (want.length) this.log("  " + t("a_spec_first", { s: want.map((x) => x[0] + x[1].toUpperCase()).join(" "), n: pool.filter(fits).length, m: pool.length }));
    const look = [...view(free), ...view(paid)].filter((h) => h.img && !this.thumb.has(h.id));
    let good = 0;
    for (const h of look) {
      if (this.cancelled) break;
      const p = await this.sameAsRef(h.img);
      if (p != null) { this.thumb.set(h.id, p); if (p >= EXACT_MIN) good++; }
    }
    if (look.length) this.log("  " + t("a_thumbs", { n: look.length, g: good }));
    const exact = [...this.thumb].filter(([id, p]) => p >= EXACT_MIN && !this.checked.has(id) && this.seen.has(id))
      .map(([id]) => this.seen.get(id)).sort(byPrice);
    const pick = exact.slice(0, PER_LEVEL);
    this.log("  " + t("a_opening", { n: pick.length }));
    return pick;
  }

  updateBest() {
    const ok = [...this.checked.values()].filter((c) => !c.rejected && c.source !== "ref" && this.tier(c) === 0);
    this.best = ok.length ? ok.reduce((a, b) => (b.total < a.total ? b : a)) : null;
  }

  rows() {
    const rows = [...this.checked.values()].filter((c) => !c.rejected && c.source !== "ref");
    if (this.refEval && !this.refEval.rejected) rows.push(this.refEval);
    return rows.sort((a, b) => this.tier(a) - this.tier(b) || a.total - b.total);
  }

  publish() {
    this.on.update?.({
      level: this.levels.length, fatigue: this.fatigue, seen: this.seen.size, checked: this.checked.size,
      elapsed: this.elapsed(), best: this.best, ref: this.refEval, rows: this.rows().slice(0, 12).map((c) => ({ ...c, tier: this.tier(c) })),
      done: this.done, confidence: this.confidence, blocked: this.blocked, cancelled: this.cancelled,
    });
  }

  // ---------- фото-образец: одиночное фото товара точнее коллажа всех размеров (наблюдение helgard 14.10) ----------
  async refPhoto() {
    if (this.ref.image) { this.log(t("a_photo_user")); return this.ref.image; }
    if (this.ref.variant && this.ref.variant.img) { this.log(t("a_photo_variant")); this.on.refPhoto?.(this.ref.variant.img); return this.ref.variant.img; }
    const gallery = (this.ref.item.main_images || []).slice(0, 6);
    if (gallery.length > 1) {
      const v = this.ref.variant ? this.ref.variant.attrs.map((a) => a.split(":").pop().trim()).join("; ") : "";
      let best = null;
      for (let i = 0; i < gallery.length && !this.cancelled; i++) {
        const p = await this.model.yesProb(
          "Does this photo show exactly ONE product item on its own (not several sizes or variants side by side, " +
          "not a scene with other objects, not mostly text or a diagram)?" + (v ? ` The wanted variant is: ${v}.` : "") + " Answer Yes or No.",
          [gallery[i]]).catch(() => null);
        if (p != null && (!best || p > best.p)) best = { i, p };
      }
      if (best && best.p >= 0.5) {
        this.log(t("a_photo_pick", { n: best.i + 1, p: Math.round(best.p * 100) }));
        this.on.refPhoto?.(gallery[best.i]);
        return gallery[best.i];
      }
    }
    if (gallery.length) { this.log(t("a_photo_first")); this.on.refPhoto?.(gallery[0]); }
    return gallery[0] || null;
  }

  // ---------- главный цикл ----------
  async run() {
    this.log(t("a_model", { m: this.model.label() }));
    const img = await this.refPhoto();
    this.image = img ? await toJpegB64(img) : null;
    if (!this.image) throw new Error(t("a_no_photo"));
    await this.understand();
    this.refEval = await this.evaluate(this.ref.item, "ref");
    if (this.refEval) this.log(t("a_reference", { t: this.m(this.refEval.total), p: this.m(this.refEval.price), s: this.m(this.refEval.shipping) }));
    this.publish();
    let n = 0;
    while (n < MAX_LEVELS && Date.now() - this.t0 < TIME_BUDGET && !this.cancelled) {
      n++;
      this.log(t("a_level", { n, f: this.fatigue, l: FATIGUE_LIMIT }));
      const hits = [];
      for (const [desc, fn] of this.plan(n)) {
        if (this.cancelled) break;
        let h = [];
        try { h = await fn(); } catch (e) { this.log("  " + t("a_err", { d: desc, e: e.message })); continue; }
        const fresh = h.filter((x) => !this.seen.has(x.id));
        for (const x of h) if (!this.seen.has(x.id)) this.seen.set(x.id, x);
        this.log("  " + t("a_found", { d: desc, n: h.length, k: fresh.length }));
        hits.push(...fresh);
      }
      const pick = this.cancelled ? [] : await this.pick(hits);
      const before = this.best ? this.best.total : Infinity;
      const opened = await this.open(pick.map((h) => h.id));
      this.updateBest();
      const improved = this.best && this.best.total < before - 0.005;
      this.levels.push({ n, found: hits.length, opened, improved: !!improved });
      if (improved) { this.fatigue = 0; this.log("  " + t("a_new_best", { p: this.m(this.best.total) })); }
      else if (n >= FREE_LEVELS && (opened || !pick.length)) this.fatigue++;
      this.publish();
      if (this.blocked) break;
      if (this.fatigue >= FATIGUE_LIMIT) { this.log(t("a_tired")); break; }
      if (!hits.length && n > FREE_LEVELS + 2) break;
    }
    await this.score();
    this.done = true;
    this.log(t("a_done", { s: this.elapsed(), l: this.levels.length, n: this.seen.size, k: this.checked.size }));
    this.publish();
  }

  // ---------- проценты (оценка модели, не откалиброванная вероятность) ----------
  async score() {
    const rows = this.rows().slice(0, 10);
    if (!rows.length) return;
    let quiet = 0;
    for (const lv of [...this.levels].reverse()) { if (lv.improved) break; quiet++; }
    const table = rows.map((c, i) => `#${i + 1} ${c.total} total (item ${c.price} + shipping ${c.shipping}) — variant «${c.variant}» — ${c.title.slice(0, 90)}` +
      (c.same != null ? ` — looks like the reference: ${Math.round(c.same * 100)}%` : "") + (c.source === "ref" ? " — the shopper's own page" : "") +
      (c.flags.length ? ` — warnings: ${c.flags.join("; ")}` : "")).join("\n");
    const head = `A shopper wants: ${this.intent.what}. Must have: ${this.intent.must.join(", ")}.\nChecked offers:\n${table}\n` +
      `Search depth: ${this.levels.length} levels, ${this.seen.size} listings seen, ${this.checked.size} opened; the last ${quiet} levels found nothing cheaper.` +
      (this.blocked ? " The search was cut short by a captcha." : "") + "\n";
    // оценки «хорошая покупка» по каждой карточке убраны (helgard 14.10: скачут и только путают); остаётся одна — «дешевле нет»
    const best = this.best || rows[0];
    const bi = rows.indexOf(best) + 1 || 1;
    this.confidence = await this.model.yesProb(head + `\nConsidering how deep the search went, is offer #${bi} really the cheapest correct offer on the whole marketplace? Answer Yes or No.`);
  }

  /** «Я против агента»: ссылки пользователя проходят ту же проверку. */
  async addMine(urls) {
    const ids = urls.map((u) => (String(u).match(/\/item\/(\d+)/) || String(u).match(/(\d{10,})/) || [])[1]).filter(Boolean);
    this.log(t("a_mine", { n: ids.length }));
    this.blocked = false;
    await this.open(ids, "human");
    this.updateBest();
    this.publish();
  }
}
