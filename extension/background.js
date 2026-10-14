// Фон: (1) кнопка расширения открывает боковую панель; (2) запоминает данные товара, открытого пользователем,
// чтобы панель сразу показала его варианты; (3) правило для Ollama: запросы расширения она отклоняет по заголовку
// Origin (403) — подменяем его на адрес, которому Ollama доверяет, только для адреса модели пользователя (замер 14.10).
const api = typeof browser !== "undefined" ? browser : chrome;

if (api.sidePanel && api.sidePanel.setPanelBehavior) {
  api.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
} else if (api.action && typeof browser !== "undefined" && browser.sidebarAction) {
  api.action.onClicked.addListener(() => browser.sidebarAction.toggle());
}

const RULE_ID = 1;
async function setModelHost(base) {
  try {
    const u = new URL(base || "http://localhost:11434");
    await api.declarativeNetRequest.updateDynamicRules({
      removeRuleIds: [RULE_ID],
      addRules: [{
        id: RULE_ID, priority: 1,
        action: { type: "modifyHeaders", requestHeaders: [{ header: "origin", operation: "set", value: "http://127.0.0.1" }] },
        condition: { urlFilter: `|${u.protocol}//${u.host}/`, resourceTypes: ["xmlhttprequest", "other"] },
      }],
    });
  } catch (e) { console.warn("pricehunt: правило для модели не поставлено", e); }
}

async function init() {
  const s = await api.storage.local.get("model");
  await setModelHost((s.model || {}).base);
}
api.runtime.onInstalled.addListener(init);
api.runtime.onStartup.addListener(init);

api.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.kind === "model_host") { setModelHost(msg.base).then(() => reply({ ok: true })); return true; }
  // данные товара со страницы, которую пользователь открыл сам (не вкладки агента — их панель ловит сама)
  if (msg.kind === "pdp" && sender.tab && msg.data && msg.data.length > 5000) {
    api.storage.session.set({ ["pdp_" + sender.tab.id]: { raw: msg.data, url: msg.url || sender.tab.url, t: Date.now() } }).catch(() => {});
  }
});
api.tabs.onRemoved.addListener((tabId) => { api.storage.session.remove("pdp_" + tabId).catch(() => {}); });
