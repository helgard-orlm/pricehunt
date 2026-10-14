// Мост: страница (MAIN world) -> расширение.
window.addEventListener("message", (e) => {
  if (e.source === window && e.data && e.data.__pricehunt) {
    try { chrome.runtime.sendMessage({ kind: e.data.kind, data: e.data.data }); } catch (err) {}
  }
});
