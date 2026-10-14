// Берёт задания у сервера pricehunt по одному: открыть страницу товара во вкладке, дождаться данных, закрыть.
// Капча -> вкладка становится видимой, человек сдвигает ползунок, данные приходят -> задание выполнено.
const api = typeof browser !== "undefined" ? browser : chrome;
const DEFAULT_SERVER = "http://192.168.1.107:8931";
const PAUSE_MS = 2500;      // одно действие за раз и пауза между страницами
const PAGE_TIMEOUT = 60000;
let running = false;
let state = { connected: false, done: 0, current: null, lastError: null };
const pending = {};         // tabId -> {task, timer, captcha}

async function server() {
  const s = await api.storage.local.get("server");
  return (s.server || DEFAULT_SERVER).replace(/\/$/, "");
}
async function post(path, body) {
  const r = await fetch((await server()) + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return r.json();
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function finish(tabId, payload) {
  const p = pending[tabId];
  if (!p) return;
  clearTimeout(p.timer);
  delete pending[tabId];
  post("/api/ext/result", Object.assign({ id: p.task.id }, payload)).catch(() => {});
  api.tabs.remove(tabId).catch(() => {});
  if (payload.raw) state.done++;
  state.current = null;
  p.resolve();
}

function runTask(task) {
  return new Promise(async (resolve) => {
    state.current = task.pid;
    const tab = await api.tabs.create({ url: task.url, active: false });
    pending[tab.id] = { task, resolve, captcha: false,
      timer: setTimeout(() => finish(tab.id, { error: "timeout" }), PAGE_TIMEOUT) };
  });
}

api.runtime.onMessage.addListener((msg, sender) => {
  const tabId = sender.tab && sender.tab.id;
  const p = pending[tabId];
  if (!p) return;
  if (msg.kind === "pdp" && msg.data && msg.data.length > 5000) {
    finish(tabId, { raw: msg.data });
  } else if (msg.kind === "captcha" && !p.captcha) {
    p.captcha = true;
    clearTimeout(p.timer);
    p.timer = setTimeout(() => finish(tabId, { error: "captcha not solved" }), 300000);
    post("/api/ext/result", { id: p.task.id, captcha: true }).catch(() => {});
    api.tabs.update(tabId, { active: true }).catch(() => {});
    api.tabs.get(tabId).then((t) => api.windows.update(t.windowId, { focused: true })).catch(() => {});
  }
});

async function loop() {
  if (running) return;
  running = true;
  try {
    await post("/api/ext/hello", { browser: navigator.userAgent.includes("Firefox") ? "firefox" : "chrome",
                                   version: api.runtime.getManifest().version, ua: navigator.userAgent });
    state.connected = true;
    for (;;) {
      const r = await fetch((await server()) + "/api/ext/next");
      const task = await r.json();
      state.connected = true;
      if (task && task.type === "item") {
        await runTask(task);
        await sleep(PAUSE_MS);
      }
    }
  } catch (e) {
    state.connected = false;
    state.lastError = String(e);
  } finally {
    running = false;
  }
}

api.alarms.create("pricehunt", { periodInMinutes: 0.5 });
api.alarms.onAlarm.addListener(() => loop());
api.runtime.onStartup.addListener(() => loop());
api.runtime.onInstalled.addListener(() => loop());
api.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.kind === "status") { reply(state); return true; }
  if (msg.kind === "reconnect") { loop(); reply({ ok: true }); return true; }
});
loop();
