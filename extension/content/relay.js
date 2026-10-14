// Мост: страница (MAIN world, hook.js / страницы выдачи) -> расширение. Добавляет адрес страницы.
window.addEventListener("message", (e) => {
  if (e.source === window && e.data && e.data.__pricehunt) {
    try { chrome.runtime.sendMessage({ kind: e.data.kind, data: e.data.data, url: location.href }); } catch (err) {}
  }
});
