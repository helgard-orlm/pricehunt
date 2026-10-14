// Боковая панель pricehunt: товар с открытой вкладки, выбор варианта, агент и его прогресс — всё здесь.
import { Model, loadSettings, saveSettings, listOllama, listOpenAI } from "./lib/model.js";
import { variantGroups, itemIdFromUrl, skuFromUrl } from "./lib/parse.js";
import * as browse from "./lib/browse.js";
import { Hunt } from "./lib/agent.js";
import { t, LANGS, getLang, setLang, applyDom } from "./lib/i18n.js";

const api = typeof browser !== "undefined" ? browser : chrome;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const money = (v, cur) => (v == null ? "?" : (!cur || cur === "USD" ? "$" + Number(v).toFixed(2) : Number(v).toFixed(2) + " " + cur));
const pct = (x) => (x == null ? "—" : Math.round(x * 100) + "%");

let probeSeq = 0;
let refPhoto = null;        // фото-образец, выбранное кликом (null — агент выбирает сам)           // только последняя проверка адреса пишет результат (старая может закончиться позже)
let cfg = null, product = null, pick = {}, hunt = null, logLines = [], readError = null, lastState = null;

// ---------- язык ----------
async function loadLang() {
  try { const s = await api.storage.local.get("lang"); if (s.lang) setLang(s.lang); } catch {}
  $("langsel").innerHTML = Object.entries(LANGS).map(([k, n]) => `<option value="${k}">${n}</option>`).join("");
  $("langsel").value = getLang();
  applyDom();
}
$("langsel").onchange = async () => {
  setLang($("langsel").value);
  try { await api.storage.local.set({ lang: getLang() }); } catch {}
  applyDom();
  renderProduct();
  if (lastState) render(lastState);
};

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
  const seq = ++probeSeq;
  $("probeout").textContent = t("probing");
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
  if (seq !== probeSeq) return;
  if (!models) {
    // частая путаница: вписан адрес тестового сайта pricehunt вместо адреса модели
    const stand = await fetch(base, { cache: "no-store" }).then((r) => r.text()).then((h) => /<title>[^<]*pricehunt/i.test(h)).catch(() => false);
    $("probeout").innerHTML = `<span style="color:var(--warn)">${esc(t("no_answer", { base }))}</span>` +
      (stand && seq === probeSeq ? `<br><span style="color:var(--warn)">${esc(t("stand_hint"))}</span>` : "");
    $("help").hidden = false;
    $("modelsel").innerHTML = "";
    return;
  }
  const vis = models.filter((m) => m.vision !== false);
  $("probeout").innerHTML = `<span style="color:var(--acc)">${esc(kind === "ollama"
    ? t("ok_ollama", { n: models.length, v: models.filter((m) => m.vision).length }) : t("ok_openai", { n: models.length }))}</span>`;
  $("modelsel").innerHTML = models.map((m) => `<option value="${esc(m.name)}" data-vision="${m.vision}">${esc(m.name)}${m.vision ? " 👁" : m.vision === false ? " " + t("no_vision") : ""}</option>`).join("");
  const keep = models.find((m) => m.name === cfg.model) || vis[0] || models[0];
  if (keep) $("modelsel").value = keep.name;
  $("modelsel").dataset.kind = kind;
  if (kind === "ollama" && !vis.length) $("help").hidden = false;
}

$("gear").onclick = () => showSetup($("setup").hidden);
$("probe").onclick = probe;
$("savecfg").onclick = async () => {
  const opt = $("modelsel").selectedOptions[0];
  if (!opt) { $("probeout").textContent = t("need_model"); return; }
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
  readError = null;
  $("noproduct").textContent = t("reading");
  try {
    const s = await api.storage.session.get("pdp_" + tab.id);
    const saved = s["pdp_" + tab.id];
    const item = saved && itemIdFromUrl(saved.url) === pid ? browse.itemFromRaw(pid, saved.raw) : await browse.item(pid);
    if (!item) throw new Error(t("no_data"));
    product = { id: pid, item, groups: variantGroups(item), urlSku: skuFromUrl(tab.url) };
    refPhoto = null;
    const start = item.variants.find((v) => v.sku === product.urlSku) || item.variants.find((v) => v.salable !== false) || item.variants[0];
    pick = {};
    for (const g of product.groups) {
      const a = (start ? start.attrs : []).find((x) => x.startsWith(g.name + ": "));
      pick[g.name] = a ? a.slice(g.name.length + 2) : g.values[0].value;
    }
  } catch (e) {
    product = null;
    readError = e.message;
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
  if (!product) { $("noproduct").textContent = readError ? t("read_fail", { e: readError }) : t("noproduct"); return; }
  const it = product.item, v = chosen();
  $("ptitle").textContent = it.title;
  $("pimg").src = refPhoto || (v && v.img) || it.main_images[0] || "";
  $("groups").innerHTML = product.groups.map((g) => `<div class="gname">${esc(g.name)}</div>` + g.values.map((x) => {
    const test = { ...pick, [g.name]: x.value };
    const exists = it.variants.some((vv) => product.groups.every((gg) => vv.attrs.includes(`${gg.name}: ${test[gg.name]}`)));
    return `<span class="chip${pick[g.name] === x.value ? " on" : ""}${exists ? "" : " off"}" data-g="${esc(g.name)}" data-v="${esc(x.value)}">${esc(x.value)}</span>`;
  }).join("")).join("");
  $("groups").querySelectorAll(".chip").forEach((c) => (c.onclick = () => { pick[c.dataset.g] = c.dataset.v; refPhoto = null; renderProduct(); }));
  // лента фото: своё фото варианта + галерея; подсвечено то, по которому будет искать агент
  const photos = [...new Set([v && v.img, ...it.main_images].filter(Boolean))];
  const cur = refPhoto || (v && v.img) || null;
  $("photos").innerHTML = photos.map((u) => `<img src="${esc(u)}" data-u="${esc(u)}" class="${u === cur ? "on" : ""}" alt="">`).join("");
  $("photos").querySelectorAll("img").forEach((im) => (im.onclick = () => { refPhoto = im.dataset.u; renderProduct(); }));
  const ships = it.shipping.filter((s) => s.fee != null).map((s) => s.fee);
  const ship = ships.length ? Math.min(...ships) : null;
  if (v) {
    const p = v.welcome_deal && v.original ? v.original : v.price;
    $("pprice").innerHTML = `<b>${money(p, it.currency)}</b> + ${t("shipping")} ${money(ship, it.currency)} = <b>${money(p + (ship || 0), it.currency)}</b>` +
      (v.welcome_deal ? ` <span class="mute">${esc(t("welcome_ignored", { p: money(v.price, it.currency) }))}</span>` : "");
  } else $("pprice").textContent = t("no_combo");
  const ready = cfg && cfg.model;
  $("go").disabled = !v || !ready || (hunt && !hunt.done);
  $("go").textContent = ready ? t("go") : t("pick_model");
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
    ref: { id: product.id, item: product.item, variant: product.groups.length ? v : null, image: refPhoto },
    model: new Model(cfg),
    on: { log, update: render, captcha: (on) => ($("captcha").hidden = !on),
          refPhoto: (u) => { $("photos").querySelectorAll("img").forEach((im) => im.classList.toggle("on", im.dataset.u === u)); $("pimg").src = u; } },
  });
  try { await hunt.run(); }
  catch (e) { log(t("error", { e: e.message })); }
  $("stop").hidden = true; $("mine").hidden = false;
  renderProduct();
  saveHistory();
};
$("stop").onclick = () => { if (hunt) { hunt.cancelled = true; log(t("stopped")); } };

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
  if (c.source === "ref") return `<span class="tag ref">${t("tag_ref")}</span>`;
  const tier = c.tier === 0 ? `<span class="tag t0">${t("tag_exact")}</span>` : c.tier === 1 ? `<span class="tag t1">${t("tag_similar")}</span>` : `<span class="tag t2">${t("tag_other")}</span>`;
  return (c.source === "human" ? `<span class="tag human">${t("tag_human")}</span>` : "") + tier;
}

function render(s) {
  lastState = s;
  $("slevel").textContent = s.level || "—";
  $("sfat").textContent = `${s.fatigue}/3`;
  $("sseen").textContent = `${s.seen} / ${s.checked}`;
  $("stime").textContent = t("sec", { n: s.elapsed });
  const cur = product?.item.currency;
  const exact = s.rows.filter((c) => c.tier === 0 && c.source !== "ref");
  const bestA = exact.filter((c) => c.source === "agent").sort((a, b) => a.total - b.total)[0];
  const bestH = exact.filter((c) => c.source === "human").sort((a, b) => a.total - b.total)[0];
  let v = "";
  if (s.ref && bestA) {
    const d = s.ref.total - bestA.total;
    v = d > 0.005 ? t("v_cheaper", { d: money(d, cur), a: money(bestA.total, cur), r: money(s.ref.total, cur) }) :
        t("v_not_yet", { a: money(bestA.total, cur) });
  } else if (s.done) v = t("v_none");
  if (bestH && bestA) v += bestH.total < bestA.total - 0.005 ? t("v_human_wins", { d: money(bestA.total - bestH.total, cur) })
    : bestA.total < bestH.total - 0.005 ? t("v_agent_wins", { d: money(bestH.total - bestA.total, cur) }) : t("v_tie");
  if (s.done && s.confidence != null) v += t("v_conf", { p: pct(s.confidence) });
  if (s.blocked) v += t("v_captcha");
  $("verdict").textContent = v;
  $("list").innerHTML = s.rows.map((c) => `
    <div class="item${c.tier === 2 ? " dim" : ""}">
      <a href="${esc(c.url)}" target="_blank" rel="noopener"><img src="${esc(c.img || "")}" alt="" loading="lazy"></a>
      <div>${tagOf(c)}<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a>
        <div class="mute small">${esc(c.variant)}${c.same != null ? " · " + esc(t("like_ref", { p: pct(c.same) })) : ""}${c.p_good != null ? " · " + esc(t("score", { p: pct(c.p_good) })) : ""}</div>
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
  await loadLang();
  await showSetup(false);
  if (!cfg.model) await showSetup(true);
  await loadProduct();
})();
