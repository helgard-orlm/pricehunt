// Модель агента: любая с OpenAI-совместимым /v1/chat/completions — Ollama на компьютере пользователя
// или любой другой адрес (llama.cpp, vLLM, облако). Проценты «как у Jev» = вероятность первого токена Yes/No
// из logprobs (их отдают и Ollama, и llama-server — проверено 14.10).
import { t } from "./i18n.js";

const api = typeof browser !== "undefined" ? browser : chrome;

export const DEFAULT_SETTINGS = { base: "http://localhost:11434", kind: "ollama", model: "", key: "" };

export async function loadSettings() {
  const s = await api.storage.local.get("model");
  return Object.assign({}, DEFAULT_SETTINGS, s.model || {});
}

export async function saveSettings(cfg) {
  await api.storage.local.set({ model: cfg });
  await api.runtime.sendMessage({ kind: "model_host", base: cfg.base }).catch(() => {});
}

function root(base) {
  return String(base || "").replace(/\/+$/, "").replace(/\/v1$/, "");
}

/** Ollama? (у неё есть /api/tags). Возвращает список моделей с пометкой «видит картинки», или null. */
export async function listOllama(base) {
  try {
    const r = await fetch(root(base) + "/api/tags", { signal: AbortSignal.timeout(5000) });
    if (!r.ok) return null;
    const tags = (await r.json()).models || [];
    const out = [];
    for (const t of tags) {
      if (/embed|bge/i.test(t.name)) continue;
      let caps = [];
      try {
        const s = await fetch(root(base) + "/api/show", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: t.name }), signal: AbortSignal.timeout(8000) });
        caps = (await s.json()).capabilities || [];
      } catch {}
      if (caps.length && !caps.includes("completion")) continue;
      out.push({ name: t.name, vision: caps.includes("vision"), size: t.size });
    }
    return out;
  } catch {
    return null;
  }
}

/** Любой OpenAI-совместимый сервер: /v1/models. */
export async function listOpenAI(base, key) {
  try {
    const r = await fetch(root(base) + "/v1/models", {
      headers: key ? { Authorization: "Bearer " + key } : {}, signal: AbortSignal.timeout(5000) });
    if (!r.ok) return null;
    const j = await r.json();
    return (j.data || j.models || []).map((m) => ({ name: m.id || m.name || m.model, vision: null }));
  } catch {
    return null;
  }
}

// ---------- картинки: всё в JPEG (AliExpress отдаёт AVIF/WebP, не все модели их читают) ----------
const jpegCache = new Map();

// CDN фото (Akamai) после серии быстрых запросов отвечает 403 text/html с cache-control на год (замер 14.10) ->
// проверяем статус и тип, при отказе ждём и берём в обход кэша браузера другой размер.
export async function fetchImage(url) {
  const sizes = [null, "_220x220.jpg", "_640x640.jpg"];
  let last;
  for (let i = 0; i < sizes.length; i++) {
    let u = url;
    if (sizes[i]) {
      u = url.split("?")[0].replace(/(\.(?:jpe?g|png|webp|avif))_.*$/i, "$1");
      if (!/alicdn|aliexpress-media/.test(u)) u = url;
      else u += sizes[i];
      await new Promise((r) => setTimeout(r, 1500 * i));
    }
    try {
      const r = await fetch(u, i ? { cache: "reload" } : {});
      const b = await r.blob();
      if (r.ok && b.type.startsWith("image/")) return await createImageBitmap(b);
      last = new Error(`image ${r.status} ${b.type}`);
    } catch (e) { last = e; }
  }
  throw last;
}

export async function toJpegB64(src, maxSide = 1024) {
  const key = typeof src === "string" ? src + "|" + maxSide : null;
  if (key && jpegCache.has(key)) return jpegCache.get(key);
  let blob, url;
  if (src instanceof Blob) blob = src;
  else {
    url = src.startsWith("//") ? "https:" + src : src;
    if (/alicdn|aliexpress-media/.test(url) && !/_\d+x\d+/.test(url) && !url.includes("?")) url += "_350x350.jpg";
  }
  const bmp = blob ? await createImageBitmap(blob) : await fetchImage(url);
  const k = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
  const c = new OffscreenCanvas(Math.max(1, Math.round(bmp.width * k)), Math.max(1, Math.round(bmp.height * k)));
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  const out = await c.convertToBlob({ type: "image/jpeg", quality: 0.9 });
  const b64 = await new Promise((res) => {
    const fr = new FileReader();
    fr.onload = () => res(String(fr.result).split(",")[1]);
    fr.readAsDataURL(out);
  });
  if (key) {
    if (jpegCache.size > 300) jpegCache.clear();
    jpegCache.set(key, b64);
  }
  return b64;
}

// ---------- отпечаток фото (dHash 16×16 = 256 бит): продавцы копируют фото друг у друга (наблюдение helgard 14.10) ----------
// Копии одного файла дают 0–1 бит разницы, перерисованные порты на той же сцене — 6 (замер 14.10, Essager C+A против C+C).
const hashCache = new Map();
export const imgKey = (u) => String(u || "").replace(/^\/\//, "https://").split("?")[0].replace(/(\.(?:jpe?g|png|webp|avif))_.*$/i, "$1");

export function dhashFromGray(g, w) {      // g: яркости (w+1)×w, по строкам
  const bits = new Uint8Array(w * w / 8);
  for (let y = 0; y < w; y++)
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      if (g[y * (w + 1) + x] > g[y * (w + 1) + x + 1]) bits[i >> 3] |= 1 << (i & 7);
    }
  return bits;
}

export function hamming(a, b) {
  let n = 0;
  for (let i = 0; i < a.length; i++) { let v = a[i] ^ b[i]; while (v) { n += v & 1; v >>= 1; } }
  return n;
}

export async function imgHash(src, w = 16) {
  const key = imgKey(src);
  if (hashCache.has(key)) return hashCache.get(key);
  const p = (async () => {
    let url = key;
    if (/alicdn|aliexpress-media/.test(url)) url += "_350x350.jpg";
    const bmp = await fetchImage(url);
    const mid = new OffscreenCanvas(64, 64), mc = mid.getContext("2d");     // в два шага: прямое 350 -> 17 даёт алиасинг
    mc.imageSmoothingQuality = "high"; mc.drawImage(bmp, 0, 0, 64, 64);
    const c = new OffscreenCanvas(w + 1, w), cx = c.getContext("2d");
    cx.imageSmoothingQuality = "high"; cx.drawImage(mid, 0, 0, w + 1, w);
    const d = cx.getImageData(0, 0, w + 1, w).data, g = new Float32Array((w + 1) * w);
    for (let i = 0; i < g.length; i++) g[i] = 0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2];
    return dhashFromGray(g, w);
  })().catch(() => null);
  if (hashCache.size > 2000) hashCache.clear();
  hashCache.set(key, p);
  p.then((h) => { if (!h) hashCache.delete(key); });   // сбой загрузки не запоминаем
  return p;
}

export class Model {
  constructor(cfg) {
    this.cfg = Object.assign({}, DEFAULT_SETTINGS, cfg || {});
    this.base = root(this.cfg.base);
    this.vision = this.cfg.vision !== false;
  }

  label() {
    return `${this.cfg.model} (${this.cfg.kind === "ollama" ? "Ollama" : this.base})`;
  }

  async _chat(content, maxTokens, extra = {}) {
    const body = { model: this.cfg.model, temperature: 0, max_tokens: maxTokens,
                   messages: [{ role: "user", content }], ...extra };
    if (this.cfg.kind === "ollama") body.reasoning_effort = "none";          // без «размышлений»
    else body.chat_template_kwargs = { enable_thinking: false };            // llama.cpp: иначе думает и молчит (замер 14.10)
    const headers = { "Content-Type": "application/json" };
    if (this.cfg.key) headers.Authorization = "Bearer " + this.cfg.key;
    const r = await fetch(this.base + "/v1/chat/completions", { method: "POST", headers, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(t("model_http", { s: r.status, t: (await r.text()).slice(0, 160) }));
    return r.json();
  }

  async _content(text, images) {
    const content = [];
    if (images && images.length && this.vision) {
      for (const im of images) {
        const b64 = typeof im === "string" && im.startsWith("data:") ? im.split(",")[1] : await toJpegB64(im);
        content.push({ type: "image_url", image_url: { url: "data:image/jpeg;base64," + b64 } });
      }
    } else if (images && images.length) {
      text = "(No image available: answer from the text only.)\n" + text;
    }
    content.push({ type: "text", text });
    return content;
  }

  async ask(text, images = [], maxTokens = 400) {
    const r = await this._chat(await this._content(text, images), maxTokens);
    return String(r.choices?.[0]?.message?.content || "").trim();
  }

  async askJson(text, images = [], maxTokens = 600, fallback = null) {
    const out = await this.ask(text + "\nAnswer with JSON only, no comments.", images, maxTokens);
    const m = out.match(/[\[{][\s\S]*[\]}]/);
    try { return m ? JSON.parse(m[0]) : fallback; } catch { return fallback; }
  }

  /** Оценка «да» по вероятностям первого токена. Сервер без logprobs (облачные модели Ollama) -> сам ответ: Yes 1, No 0. */
  async yesProb(text, images = []) {
    let r, lps;
    try {
      r = await this._chat(await this._content(text, images), 1, { logprobs: true, top_logprobs: 10 });
    } catch {
      return null;
    }
    lps = r.choices?.[0]?.logprobs?.content?.[0]?.top_logprobs;
    if (!lps) {
      this.noLogprobs = true;
      const w = String(r.choices?.[0]?.message?.content || "").trim().toLowerCase();
      return w.startsWith("yes") ? 1 : w.startsWith("no") ? 0 : null;
    }
    let yes = 0, no = 0;
    for (const t of lps) {
      const w = String(t.token).trim().toLowerCase();
      const p = Math.exp(t.logprob);
      if (w === "yes") yes += p; else if (w === "no") no += p;
    }
    return yes + no > 0 ? Math.round((yes / (yes + no)) * 1000) / 1000 : null;
  }
}
