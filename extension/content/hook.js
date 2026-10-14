// Работает внутри страницы товара (MAIN world). Ловит ответ AliExpress с вариантами и доставкой
// (mtop.aliexpress.pdp.pc.query) — он приходит JSONP-скриптом, иногда XHR/fetch — и замечает капчу.
(function () {
  if (window.__pricehuntHook) return;
  window.__pricehuntHook = true;
  const send = (kind, data) => window.postMessage({ __pricehunt: 1, kind, data }, "*");
  const isPdp = (u) => /mtop\.aliexpress\.pdp\.pc\.query/.test(String(u || "")) && !/punish/.test(String(u || ""));

  function wrapCallback(name) {
    const orig = window[name];
    if (typeof orig !== "function" || orig.__ph) return;
    const w = function (d) {
      try { send("pdp", typeof d === "string" ? d : JSON.stringify(d)); } catch (e) {}
      return orig.apply(this, arguments);
    };
    w.__ph = 1;
    window[name] = w;
  }
  function watch(el) {
    if (el && el.tagName === "SCRIPT" && isPdp(el.src)) {
      const m = String(el.src).match(/[?&]callback=([^&]+)/);
      if (m) wrapCallback(decodeURIComponent(m[1]));
    }
  }
  for (const fn of ["appendChild", "insertBefore"]) {
    const o = Node.prototype[fn];
    Node.prototype[fn] = function (el) { try { watch(el); } catch (e) {} return o.apply(this, arguments); };
  }
  const xo = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, u) {
    if (isPdp(u)) this.addEventListener("load", () => { try { send("pdp", this.responseText); } catch (e) {} });
    return xo.apply(this, arguments);
  };
  const fo = window.fetch;
  window.fetch = function (input) {
    const u = typeof input === "string" ? input : input && input.url;
    const p = fo.apply(this, arguments);
    if (isPdp(u)) p.then((r) => r.clone().text()).then((t) => send("pdp", t)).catch(() => {});
    return p;
  };
  let told = false;
  const check = () => {
    if (!told && document.querySelector('iframe[src*="punish"], iframe[src*="_____tmd_____"], #baxia-dialog-content')) {
      told = true;
      send("captcha", 1);
    }
  };
  new MutationObserver(check).observe(document, { childList: true, subtree: true });
})();
