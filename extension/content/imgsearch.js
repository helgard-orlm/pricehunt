// Главная AliExpress: по команде расширения нажать «камеру» и подложить фото — как это делает человек.
(function () {
  const api = typeof browser !== "undefined" ? browser : chrome;
  const wait = (sel, ms) => new Promise((res, rej) => {
    const t0 = Date.now();
    const tick = () => {
      const el = document.querySelector(sel);
      if (el) return res(el);
      if (Date.now() - t0 > ms) return rej(new Error("нет элемента " + sel));
      setTimeout(tick, 300);
    };
    tick();
  });
  api.runtime.onMessage.addListener((msg) => {
    if (msg.kind !== "do_imgsearch") return;
    (async () => {
      try {
        const btn = await wait('[class*="picture-search-btn"]', 20000);
        btn.click();
        const input = await wait('input[type=file]', 10000);
        const bin = atob(msg.image);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        const dt = new DataTransfer();
        dt.items.add(new File([bytes], "photo.jpg", { type: "image/jpeg" }));
        input.files = dt.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      } catch (e) {
        api.runtime.sendMessage({ kind: "imgsearch_error", data: String(e) });
      }
    })();
  });
  api.runtime.sendMessage({ kind: "home_ready" });
})();
