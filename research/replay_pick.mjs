// Повтор отбора (pick) по журналу поиска helgard: попадает ли цель в сравнение миниатюр. Модель — заглушка.
import fs from 'fs';
globalThis.chrome = { runtime: {}, storage: {} };
const { Hunt } = await import(process.cwd() + '/lib/agent.js');
const [file, target] = process.argv.slice(2);
const d = JSON.parse(fs.readFileSync(file, 'utf8'));
const st = d.trace.find((e) => e.ev === 'start'), re = d.trace.find((e) => e.ev === 'ref_eval');
const h = new Hunt({ ref: { id: st.ref_id, variant: { attrs: st.variant || [] }, item: { title: st.title, main_images: [], variants: [] } }, model: {}, on: { log: (x) => console.log(x) } });
h.refEval = re.result;
const looked = [];
h.sameModelAsRef = async (img) => { looked.push(img); return img === target ? 0.99 : 0; };
for (const s of d.trace.filter((e) => e.ev === 'search')) {
  const hits = s.items.map(([id, p, ship, w, b, title]) => ({ id, list_price: p, free_ship: ship === 'free', welcome: !!w, bundle: b || null, title, img: id }));
  const fresh = hits.filter((x) => !h.seen.has(x.id)); for (const x of hits) if (!h.seen.has(x.id)) h.seen.set(x.id, x);
  if (s.desc.includes('за ціною') || s.desc.includes('по цене') || s.desc.includes('by price')) continue;
  console.log('--- уровень', s.level, s.desc.slice(0, 50));
  const pick = await h.pick(fresh);
  console.log('   цель сравнена:', looked.includes(target), '| к открытию:', pick.map((x) => x.id).includes(target));
  if (looked.includes(target)) break;
}
