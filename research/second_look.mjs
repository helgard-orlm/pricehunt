// Прогон настоящего кода «второго шанса» (agent.js) на живой модели, без браузера. Запуск из папки extension.
import fs from "node:fs";
globalThis.chrome = { runtime: {}, storage: { local: { get: async () => ({}) } } };   // browse.js ждёт API браузера
const { Hunt } = await import("../extension/lib/agent.js");
const { Model } = await import("../extension/lib/model.js");
const d = JSON.parse(fs.readFileSync(process.argv[2]));
const h = Object.create(Hunt.prototype);
h.model = new Model({ base: "http://192.168.1.104:8920", model: "minicpm-v4.7", kind: "openai" });
h.image = d.ref; h.refImgUrl = "https://ae-pic-a1.aliexpress-media.com/kf/S351af3223e5848e3940146771265b8ffr.jpg";
h.ref = { item: { main_images: d.gallery } }; h.cancelled = false;
const v2 = await h.refView2();
console.log("второй ракурс:", v2 ? d.gallery_urls[d.gallery.indexOf(v2)] : null);
for (const [name, img] of Object.entries(d.cands)) {
  const m = await h.sameModelAsRef(img), s = await h.sameAsRef(img);
  const r = m < 0.7 && s >= 0.5 ? await h.secondLook(img) : null;
  console.log(name.padEnd(14), "модель", m?.toFixed(3), "тип", s?.toFixed(3), r ? `второй: ${r.p?.toFixed(3)} ok=${r.ok} разъёмы ${JSON.stringify(r.ports_ref)} / ${JSON.stringify(r.ports)}` : "");
}
