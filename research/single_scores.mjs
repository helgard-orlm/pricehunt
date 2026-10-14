import fs from "node:fs";
globalThis.chrome = { runtime: {}, storage: { local: { get: async () => ({}) } } };
const { Model } = await import("../extension/lib/model.js");
const d = JSON.parse(fs.readFileSync(process.argv[2]));
const m = new Model({ base: "http://192.168.1.104:8920", model: "minicpm-v4.7", kind: "openai" });
const Q = "Does this photo show exactly ONE product item on its own (not several sizes or variants side by side, not a scene with other objects, not mostly text or a diagram)? Answer Yes or No.";
for (const g of d.gallery) console.log(await m.yesProb(Q, [g]));
