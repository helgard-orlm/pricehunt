// Боковая панель pricehunt: товар с открытой вкладки, выбор варианта, агент и его прогресс — всё здесь.
import { Model, loadSettings, saveSettings, listOllama, listOpenAI } from "./lib/model.js";
import { variantGroups, itemIdFromUrl, skuFromUrl } from "./lib/parse.js";
import * as browse from "./lib/browse.js";
import { Hunt } from "./lib/agent.js";

const api = typeof browser !== "undefined" ? browser : chrome;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const money = (v, cur) => (v == null ? "?" : (!cur || cur === "USD" ? "$" + Number(v).toFixed(2) : Number(v).toFixed(2) + " " + cur));
const pct = (x) => (x == null ? "—" : Math.round(x * 100) + "%");

let cfg = null, product = null, pick = {}, hunt = null, logLines = [];

// ---------- модель ----------
async function showSetup(open) {
  cfg = await loadSettings();
  $("base").value = cfg.base;
  $("key").value = cfg.key || "";
  $("setup").hidden = !open;
  if (open) await probe();
}

async function probe() {
  const base = $("base").value.trim() || "http://localhost:11434";
  $("probeout").textContent = "проверяю…";
  $("help").hidden = true;
  // чужой адрес (не localhost:11434) — нужно разрешение на него; спрашиваем только по кнопке
  try {
    const origin = new URL(base).origin + "/*";
    if (!/^http:\/\/(localhost|127\.0\.0\.1):11434\/\*$/.test(origin) && api.permissions?.request)
      await api.permissions.request({ origins: [origin] });
  } catch {}
  await api.runtime.sendMessage({ kind: "model_host", base }).catch(() => {});
  let models = await listOllama(base), kind = "ollama";
  if (!models) { models = await listOpenAI(base, $("key").value.trim()); kind = "openai"; }
  if (!models) {
    $("probeout").innerHTML = `<span style="color:var(--warn)">не отвечает: ${esc(base)}</span>`;
    $("help").hidden = false;
    $("modelsel").innerHTML = "";
    return;
  }
  const vis = models.filter((m) => m.vision !== false);
  $("probeout").innerHTML = `<span style="color:var(--acc)">✓ ${kind === "ollama" ? "Ollama" : "сервер OpenAI-формата"}: моделей ${models.length}` +
    (kind === "ollama" ? `, со зрением ${models.filter((m) => m.vision).length}` : "") + "</span>";
  $("modelsel").innerHTML = models.map((m) => `<option value="${esc(m.name)}" data-vision="${m.vision}">${esc(m.name)}${m.vision ? " 👁" : m.vision === false ? " (без зрения)" : ""}</option>`).join("");
  const keep = models.find((m) => m.name === cfg.model) || vis[0] || models[0];
  if (keep) $("modelsel").value = keep.name;
  $("modelsel").dataset.kind = kind;
  if (kind === "ollama" && !vis.length) $("help").hidden = false;
}

$("gear").onclick = () => showSetup($("setup").hidden);
$("probe").onclick = probe;
$("savecfg").onclick = async () => {
  const opt = $("modelsel").selectedOptions[0];
  if (!opt) { $("probeout").textContent = "сначала проверь адрес — нужна модель"; return; }
  cfg = { base: $("base").value.trim() || "http://localhost:11434", kind: $("modelsel").dataset.kind || "ollama",
          model: opt.value, key: $("key").value.trim(), vision: opt.dataset.vision !== "false" };
  await saveSettings(cfg);
  $("setup").hidden = true;
  renderProduct();
};

// ---------- товар с открытой вкладки ----------
async function loadProduct() {
  if (hunt && !hunt.done) return;          // пока идёт поиск — не переключаемся
  // panel.html?tab=ID — для проверки панели отдельной вкладкой; обычно берём активную вкладку окна
  const forced = new URLSearchParams(location.search).get("tab");
  const [tab] = forced ? [await api.tabs.get(Number(forced))] : await api.tabs.query({ active: true, currentWindow: true });
  const pid = tab && itemIdFromUrl(tab.url);
  if (!pid || !/aliexpress\./.test(tab.url)) { product = null; renderProduct(); return; }
  if (product && product.id === pid) return;
  $("noproduct").textContent = "читаю товар…";
  try {
    const s = await api.storage.session.get("pdp_" + tab.id);
    const saved = s["pdp_" + tab.id];
    const item = saved && itemIdFromUrl(saved.url) === pid ? browse.itemFromRaw(pid, saved.raw) : await browse.item(pid);
    if (!item) throw new Error("страница не отдала данные — обнови её (F5)");
    product = { id: pid, item, groups: variantGroups(item), urlSku: skuFromUrl(tab.url) };
    const start = item.variants.find((v) => v.sku === product.urlSku) || item.variants.find((v) => v.salable !== false) || item.variants[0];
    pick = {};
    for (const g of product.groups) {
      const a = (start ? start.attrs : []).find((x) => x.startsWith(g.name + ": "));
      pick[g.name] = a ? a.slice(g.name.length + 2) : g.values[0].value;
    }
  } catch (e) {
    product = null;
    $("noproduct").textContent = "не получилось прочитать товар: " + e.message;
  }
  renderProduct();
}

function chosen() {
  if (!product) return null;
  if (!product.groups.length) return product.item.variants[0] || null;
  return product.item.variants.find((v) => product.groups.every((g) => v.attrs.includes(`${g.name}: ${pick[g.name]}`))) || null;
}

function renderProduct() {
  $("pcard").hidden = !product;
  $("noproduct").hidden = !!product;
  if (!product) { if (!$("noproduct").textContent.startsWith("не получилось")) $("noproduct").textContent = "Открой страницу товара на AliExpress — здесь появятся его варианты."; return; }
  const it = product.item, v = chosen();
  $("ptitle").textContent = it.title;
  $("pimg").src = (v && v.img) || it.main_images[0] || "";
  $("groups").innerHTML = product.groups.map((g) => `<div class="gname">${esc(g.name)}</div>` + g.values.map((x) => {
    const test = { ...pick, [g.name]: x.value };
    const exists = it.variants.some((vv) => product.groups.every((gg) => vv.attrs.includes(`${gg.name}: ${test[gg.name]}`)));
    return `<span class="chip${pick[g.name] === x.value ? " on" : ""}${exists ? "" : " off"}" data-g="${esc(g.name)}" data-v="${esc(x.value)}">${esc(x.value)}</span>`;
  }).join("")).join("");
  $("groups").querySelectorAll(".chip").forEach((c) => (c.onclick = () => { pick[c.dataset.g] = c.dataset.v; renderProduct(); }));
  const ships = it.shipping.filter((s) => s.fee != null).map((s) => s.fee);
  const ship = ships.length ? Math.min(...ships) : null;
  if (v) {
    const p = v.welcome_deal && v.original ? v.original : v.price;
    $("pprice").innerHTML = `<b>${money(p, it.currency)}</b> + доставка ${money(ship, it.currency)} = <b>${money(p + (ship || 0), it.currency)}</b>` +
      (v.welcome_deal ? ` <span class="mute">(цена для новичков ${money(v.price, it.currency)} не учтена)</span>` : "");
  } else $("pprice").textContent = "такого сочетания нет — выбери другое";
  const ready = cfg && cfg.model;
  $("go").disabled = !v || !ready || (hunt && !hunt.done);
  $("go").textContent = ready ? "Найти дешевле такой же" : "Сначала выбери модель (⚙)";
}

// ---------- поиск ----------
$("go").onclick = async () => {
  const v = chosen();
  if (!v || !cfg?.model) return;
  logLines = [];
  $("log").textContent = "";
  $("run").hidden = false; $("results").hidden = false; $("mine").hidden = true;
  $("list").innerHTML = ""; $("verdict").textContent = "";
  $("go").disabled = true; $("stop").hidden = false;
  hunt = new Hunt({
    ref: { id: product.id, item: product.item, variant: product.groups.length ? v : null },
    model: new Model(cfg),
    on: { log, update: render, captcha: (on) => ($("captcha").hidden = !on) },
  });
  try { await hunt.run(); }
  catch (e) { log("ОШИБКА: " + e.message); }
  $("stop").hidden = true; $("mine").hidden = false;
  renderProduct();
  saveHistory();
};
$("stop").onclick = () => { if (hunt) { hunt.cancelled = true; log("остановлено — показываю, что успел"); } };

$("cmp").onclick = async () => {
  const urls = $("minetext").value.split(/\s+/).filter((u) => /aliexpress|^\d{10,}$/.test(u));
  if (!urls.length || !hunt) return;
  $("cmp").disabled = true;
  await hunt.addMine(urls);
  $("cmp").disabled = false;
};

function log(t) {
  logLines.push(new Date().toLocaleTimeString().slice(0, 8) + " " + t);
  const lg = $("log"), bottom = lg.scrollTop + lg.clientHeight >= lg.scrollHeight - 20;
  lg.textContent = logLines.join("\n");
  if (bottom) lg.scrollTop = lg.scrollHeight;
}

function tagOf(c) {
  if (c.source === "ref") return '<span class="tag ref">ТВОЙ</span>';
  const t = c.tier === 0 ? '<span class="tag t0">ТОЧНО ТАКОЙ</span>' : c.tier === 1 ? '<span class="tag t1">ПОХОЖИЙ</span>' : '<span class="tag t2">ДРУГОЙ</span>';
  return (c.source === "human" ? '<span class="tag human">ТЫ НАШЁЛ</span>' : "") + t;
}

function render(s) {
  $("slevel").textContent = s.level || "—";
  $("sfat").textContent = `${s.fatigue}/3`;
  $("sseen").textContent = `${s.seen} / ${s.checked}`;
  $("stime").textContent = `${s.elapsed} с`;
  const cur = product?.item.currency;
  const exact = s.rows.filter((c) => c.tier === 0 && c.source !== "ref");
  const bestA = exact.filter((c) => c.source === "agent").sort((a, b) => a.total - b.total)[0];
  const bestH = exact.filter((c) => c.source === "human").sort((a, b) => a.total - b.total)[0];
  let v = "";
  if (s.ref && bestA) {
    const d = s.ref.total - bestA.total;
    v = d > 0.005 ? `✓ Нашёл дешевле твоего на ${money(d, cur)}: ${money(bestA.total, cur)} вместо ${money(s.ref.total, cur)}` :
        `Дешевле твоего пока не нашёл (лучший точно такой: ${money(bestA.total, cur)})`;
  } else if (s.done) v = "Точно такого же дешевле не нашлось.";
  if (bestH && bestA) v += bestH.total < bestA.total - 0.005 ? ` · 🏆 ты нашёл дешевле агента на ${money(bestA.total - bestH.total, cur)}`
    : bestA.total < bestH.total - 0.005 ? ` · агент нашёл дешевле тебя на ${money(bestH.total - bestA.total, cur)}` : " · ничья";
  if (s.done && s.confidence != null) v += ` · оценка «дешевле нет»: ${pct(s.confidence)}`;
  if (s.blocked) v += " · поиск оборван капчей";
  $("verdict").textContent = v;
  $("list").innerHTML = s.rows.map((c) => `
    <div class="item${c.tier === 2 ? " dim" : ""}">
      <a href="${esc(c.url)}" target="_blank" rel="noopener"><img src="${esc(c.img || "")}" alt="" loading="lazy"></a>
      <div>${tagOf(c)}<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a>
        <div class="mute small">${esc(c.variant)}${c.same != null ? ` · похож на образец ${pct(c.same)}` : ""}${c.p_good != null ? ` · оценка ${pct(c.p_good)}` : ""}</div>
        ${(c.flags || []).map((f) => `<span class="flag">⚠ ${esc(f)}</span>`).join("")}
      </div>
      <div><div class="total">${money(c.total, c.currency)}</div><div class="sub">${money(c.price, c.currency)} + ${money(c.shipping, c.currency)}</div></div>
    </div>`).join("");
}

async function saveHistory() {
  if (!hunt) return;
  try {
    const h = (await api.storage.local.get("history")).history || [];
    const best = hunt.best;
    h.unshift({ t: Date.now(), id: product?.id, title: product?.item.title, ref: hunt.refEval?.total, best: best?.total,
                bestUrl: best?.url, currency: product?.item.currency, confidence: hunt.confidence, secs: hunt.elapsed() });
    await api.storage.local.set({ history: h.slice(0, 30) });
  } catch {}
}

// ---------- старт ----------
api.tabs.onActivated.addListener(() => loadProduct());
api.tabs.onUpdated.addListener((id, info, tab) => {
  const forced = new URLSearchParams(location.search).get("tab");
  if ((forced ? String(id) === forced : tab.active) && (info.url || info.status === "complete")) loadProduct();
});
(async () => {
  await showSetup(false);
  if (!cfg.model) await showSetup(true);
  await loadProduct();
})();
