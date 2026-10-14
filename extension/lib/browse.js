// Как агент смотрит AliExpress: только через браузер пользователя (его вход, его страна и валюта, его капча).
// Одно действие за раз: страница товара — во вкладке на фоне, данные ловит content/hook.js; выдача — fetch с куки;
// поиск по фото — вкладка главной, «камера» нажимается как человеком (content/imgsearch.js).

import { parseItem, pdpResult, parseSearch } from "./parse.js";
import { t } from "./i18n.js";

const api = typeof browser !== "undefined" ? browser : chrome;
const PAUSE_MS = 800;
const PAGE_TIMEOUT = 60000;
const CAPTCHA_WAIT = 5 * 60000;
const cache = new Map();          // pid -> карточка (в пределах сессии панели)

export class Captcha extends Error {}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let last = 0;
async function polite() {
  const w = PAUSE_MS - (Date.now() - last);
  if (w > 0) await sleep(w);
  last = Date.now();
}

/** Открыть вкладку на фоне и ждать сообщения от её content-скрипта. onCaptcha — сообщить человеку. */
function withTab(url, accept, { onCaptcha, onReady } = {}) {
  return new Promise(async (resolve, reject) => {
    let tabId = null, timer = null, captcha = false, done = false, ready = false;
    const finish = (val, err) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      api.runtime.onMessage.removeListener(onMsg);
      api.tabs.onUpdated.removeListener(onUpd);
      if (tabId != null) api.tabs.remove(tabId).catch(() => {});
      err ? reject(err) : resolve(val);
    };
    const toCaptcha = () => {
      if (captcha) return;
      captcha = true;
      clearTimeout(timer);
      timer = setTimeout(() => finish(null, new Captcha(t("captcha_timeout"))), CAPTCHA_WAIT);
      api.tabs.update(tabId, { active: true }).catch(() => {});
      api.tabs.get(tabId).then((t) => api.windows.update(t.windowId, { focused: true })).catch(() => {});
      onCaptcha && onCaptcha();
    };
    const onMsg = (msg, sender) => {
      if (!sender.tab || sender.tab.id !== tabId) return;
      if (msg.kind === "captcha") return toCaptcha();
      if (msg.kind === "home_ready" && onReady) { if (!ready) { ready = true; onReady(tabId); } return; }
      if (msg.kind === "imgsearch_error") return finish(null, new Error(msg.data));
      const v = accept(msg);
      if (v !== undefined) finish(v);
    };
    const onUpd = (id, info) => {
      if (id === tabId && info.url && /punish|_____tmd_____/.test(info.url)) toCaptcha();
    };
    api.runtime.onMessage.addListener(onMsg);
    api.tabs.onUpdated.addListener(onUpd);
    try {
      const tab = await api.tabs.create({ url, active: false });
      tabId = tab.id;
      timer = setTimeout(() => finish(null), PAGE_TIMEOUT);
    } catch (e) {
      finish(null, e);
    }
  });
}

/** Карточка товара: варианты, цены, доставка — как видит её пользователь. */
export async function item(pid, hooks = {}) {
  if (cache.has(pid)) return cache.get(pid);
  await polite();
  const raw = await withTab(`https://www.aliexpress.com/item/${pid}.html`,
    (m) => (m.kind === "pdp" && m.data && m.data.length > 5000 ? m.data : undefined), hooks);
  if (!raw) return null;
  const it = parseItem(pdpResult(raw));
  it.id = pid;
  cache.set(pid, it);
  return it;
}

/** Карточка из уже полученного ответа страницы (то, что пользователь открыл сам). */
export function itemFromRaw(pid, raw) {
  const it = parseItem(pdpResult(raw));
  it.id = pid;
  cache.set(pid, it);
  return it;
}

/** Выдача поиска: сначала просто скачать с куки пользователя, не вышло — открыть вкладкой. */
export async function search(query, { sort = "default", page = 1 } = {}, hooks = {}) {
  await polite();
  // «/» и прочие знаки в пути ломают поиск (EU/US/UK -> 302 и 0 товаров, замер 14.10) — оставляем буквы, цифры, точку
  const q = encodeURIComponent(query.replace(/[^\p{L}\p{N}.]+/gu, " ").trim().replace(/\s+/g, "-"));
  const url = `https://www.aliexpress.com/w/wholesale-${q}.html?SortType=${sort}&page=${page}`;
  try {
    const r = await fetch(url, { credentials: "include" });
    const html = await r.text();
    if (html.includes('"productId"') && !/punish|_____tmd_____/.test(r.url)) return parseSearch(html);
  } catch {}
  const html = await withTab(url, (m) => (m.kind === "search_html" ? m.data : undefined), hooks);
  return html ? parseSearch(html) : [];
}

/** Поиск по фото, как кнопка-камера на сайте. jpegB64 — картинка в base64. */
export async function photoSearch(jpegB64, hooks = {}) {
  await polite();
  const html = await withTab("https://www.aliexpress.com/",
    (m) => (m.kind === "search_html" ? m.data : undefined),
    { ...hooks, onReady: (tabId) => api.tabs.sendMessage(tabId, { kind: "do_imgsearch", image: jpegB64 }).catch(() => {}) });
  return html ? parseSearch(html) : [];
}
