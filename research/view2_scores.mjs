import fs from "node:fs";
globalThis.chrome = { runtime: {}, storage: { local: { get: async () => ({}) } } };
const { Model } = await import("../extension/lib/model.js");
const d = JSON.parse(fs.readFileSync(process.argv[2]));
const m = new Model({ base: "http://192.168.1.104:8920", model: "minicpm-v4.7", kind: "openai" });
const Q = "Image 1 is the product the shopper wants. Does image 2 show the same product (any colour) clearly, with its front side, ports, " +
  "buttons or display visible — not a different product, not mostly text, not a scene where the product is tiny? Answer Yes or No.";
for (const g of d.gallery) console.log(await m.yesProb(Q, ["data:image/jpeg;base64," + d.ref, g]));
