import fs from 'fs';
globalThis.chrome = { runtime: {}, storage: {} };
const { parseSearch } = await import(process.cwd() + '/lib/parse.js');
const { Hunt } = await import(process.cwd() + '/lib/agent.js');
const hits = parseSearch(fs.readFileSync('../data/bundle/s_default.html', 'utf8'));
const h = new Hunt({ ref: { id: '1005008151904193', variant: { attrs: ['Plug Type: EU Plug', 'Color: Black'] },
  item: { title: 'Essager 33W GaN USB Type C Charger Digital Display PD Fast Charging For  iPhone 16 15 14 Pro Max iPad Mini 6 Xiaomi Samsung S22', main_images: [], variants: [] } },
  model: {}, on: { log: (x) => console.log(x) } });
const looked = [];
h.sameAsRef = async (img) => { looked.push(img); return 0; };
for (const x of hits) h.seen.set(x.id, x);
await h.pick(hits);
const target = hits.find((x) => x.id === '1005008033224158');
console.log('спецификации:', h.pickSpecs(), '| просмотрено миниатюр:', looked.length, '| находка среди них:', looked.includes(target.img));
