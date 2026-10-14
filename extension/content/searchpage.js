// Страница выдачи (обычный поиск или поиск по фото): отдать HTML расширению, когда товары на месте.
(function () {
  let sent = false;
  const trySend = () => {
    if (sent) return;
    const html = document.documentElement.outerHTML;
    if (html.indexOf('"productId"') >= 0) {
      sent = true;
      try { chrome.runtime.sendMessage({ kind: "search_html", data: html, url: location.href }); } catch (e) {}
    }
  };
  trySend();
  const t = setInterval(() => { trySend(); if (sent) clearInterval(t); }, 1000);
  setTimeout(() => clearInterval(t), 30000);
})();
