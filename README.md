# pricehunt — the same thing, cheaper

A browser extension that finds the **real** cheapest offer for an AliExpress product: **the exact variant you want plus shipping to your country**. It's checked by an open-weight vision model running on **your own machine**.

Open a product page, pick the variant with buttons (power, colour, plug…), press **Find the same thing cheaper**, and watch the agent work in the side panel.

> Built for the DEV Hacktoberfest 2026 Open-Source AI Challenge, week 2 ("Side Hustle"). Started 2026-10-14.

## Why

Marketplace search shows the lowest price of *any* variant, and very often that's not the thing in the title:

| Listing title | Price shown in search | What that price buys | Real price of the charger |
|---|---|---|---|
| "40W Fast Charger Type C Dual Port PD" | $1.09 | a 0.25 m USB-C cable | $2.55 |
| "120W Fast Charger 4 Port USB Type C" | $2.28 | a 0.25 m cable | $4.09 |
| "Original Samsung 25W Charger PD" | $1.15 | a cable | $3.16 |

*(measured 2026-10-14, shipping to Ukraine, USD)*

Other traps the agent handles:
- **Shipping isn't in the listed price.** A $0.90 item with $3 shipping loses to a $2.10 item with free shipping. pricehunt always compares *variant + cheapest shipping*.
- **"Welcome deal" prices** ($1.09, "max 1 pcs per shopper") apply only to new buyers. They're flagged and counted at the regular price.
- **Bundle deals.** Some cards in the results are "Bundle deals" ("грн.150 off on 3 items"): an extra discount only if you order at least 3 *different* bundle items. pricehunt marks them with a BUNDLE DEAL tag instead of mixing them silently with single-item prices.
- **"Sort by price" isn't trustworthy.** Results come back out of order. Sometimes a sort or filter returns *nothing* on purpose. pricehunt splits and sorts results itself and treats an empty page as a refusal, not as "no products".
- **Same look, different product.** A photo of a 220 V COB panel with an on-board driver returns DC copper COB chips that look similar. Every candidate photo is compared with your product photo.

## How the agent searches

It follows the method a human bargain hunter uses (this is how the author finds parts by hand):

1. **Search by photo — of one item.** Listings often open with a collage of all sizes; a photo of the single item you chose is far more precise. pricehunt uses the chosen variant's own photo, otherwise asks the model which gallery photo shows one item; the panel shows the reference photo and you can click another. (On the same 25 cached COB listings, MiniCPM-V called 0 of them a match when the reference was the all-sizes collage, and 8 when it was the single 100 W photo.) The photo goes into AliExpress' own camera search.
2. **Open likely matches, label only true ones.** A thumbnail only has to be the same *type* to be opened. The EXACT MATCH label needs a stricter question on the opened card's variant photo: the *same model* (shape, ports, display, printed power), not another model of the same brand. On 16 Essager chargers from one search, "same type" accepted 7 of 11 other models, "same model" accepted 1 of 11, and both kept all 5 true matches.
   **Keep only exact matches.** The model compares each thumbnail with your photo and opens only the ones that are the same product, cheapest first.
3. **Search by the seller's verbatim title.** The title of an exact match is a better query than any words you'd invent, because many parts (an ESP32 board with a screen, a COB chip) have no common name.
4. **Split the results itself** into free and paid shipping, sort each part by price and check the cheapest of each.
5. **Open the product and read every variant.** The model picks the variant that is really the wanted thing (not the cable, not the car charger), and checks the hard specs from your chosen variant (100W stays 100W) and the plug for your country.
6. **Repeat from the new best**, with a fatigue rule: 3 levels for free, then each level that finds nothing cheaper adds fatigue; a cheaper find resets it.

Everything happens **in your browser**, one page at a time, with your login, your country and currency. If AliExpress shows a captcha, the tab comes to the front and the agent waits for you to drag the slider. It does not try to solve or bypass it.

## Results (all on MiniCPM-V 4.7)

All numbers below were measured with **MiniCPM-V 4.7 (35B-A3B, Q6_K)** served by llama.cpp on a home PC: RTX 5060 8 GB, 32 GB RAM, about 4 GB of VRAM used with experts kept in RAM.

| Test | Result |
|---|---|
| Variant photos: charger / cable / charger+cable / car charger (6 listings, 49 variant photos) | **49 / 49** correct |
| Match vs a human: COB LED chip 220 V 100 W, author's own manual search | **tie, $3.39**: the agent found exactly the offer in the author's cart |
| ESP-01 programmer adapter, starting from a $2.16 listing | agent found **$0.70** (same board, 97% photo match) in 301 s. ⚠ Both prices were computed before the Choice shipping fix (v1.3.3), which may have added $0.49 that the site doesn't charge. Re-check pending. |

What is **not** measured yet:
- How well it catches *lying* listings, where the title says charger and the photo shows a cable. The 49/49 above are honestly named variants.
- Other models only partly. Gemma 4 12B (Ollama `gemma4:12b-it-qat`) scored 45/49 on variant photos: it mistook "cable only" for "charger with cable". Gemma 4 31B through Ollama Cloud (`gemma4:31b-cloud`) scored 47/49, falling for the same trap, and it's fast (0.9 s per photo). We also asked "is this the same type of product as the reference photo?" with the single 100 W COB photo as the reference, on 25 cached COB listings. In 5 cases Gemma said yes and MiniCPM-V said no. We looked at all 5: each is a different type (copper DC chips, a plant-grow board, small round/square COBs). One sample, so treat it as a hint, not a benchmark. Cloud models also send your photos to the cloud and return no logprobs. In that case the extension falls back to a plain Yes/No, so the percentages turn into 0%/100%.
- The percentages on result cards are the model's probability of answering "Yes". That's an estimate, not a calibrated probability.

## Install (developer mode)

**Chrome / Edge / Brave**
1. Download `pricehunt-<version>.zip` from [Releases](https://github.com/helgard-orlm/pricehunt/releases) and unzip it, or clone the repo and use the `extension/` folder.
2. Open `chrome://extensions`, turn on **Developer mode** and click **Load unpacked**. Pick the folder that contains `manifest.json`.
3. Pin the pricehunt icon, open any AliExpress product and click the icon. The side panel opens.

**Firefox 128+**: the manifest includes a Firefox sidebar, but it's **not tested yet**. To try it, go to `about:debugging` → This Firefox → Load Temporary Add-on → `manifest.json`.

## Model

The panel asks for a model address on first start (⚙):

- **Ollama** (default `http://localhost:11434`): install from [ollama.com](https://ollama.com/download), then pull any vision model, for example `ollama pull gemma4:12b-it-qat`. No `OLLAMA_ORIGINS` setup is needed: the extension rewrites the Origin header for your model address only.
- **Any OpenAI-compatible server** (llama.cpp, vLLM, LM Studio, a cloud endpoint), with an optional API key. Our MiniCPM-V setup:
  ```
  llama-server -m MiniCPM-V-4_7-35B-A3B-Q6_K.gguf --mmproj mmproj-model-f16-4x.gguf \
    -ngl 99 --cpu-moe -c 32768 -fa on --jinja --host 0.0.0.0 --port 8920 --alias minicpm-v4.7
  ```
  Then enter `http://<that machine>:8920` in the panel and allow the address when the browser asks.

The model must see images, and the server should return `logprobs` (Ollama and llama.cpp both do) for the match percentages.

## Developer log

⚙ → *Developer log* takes an address. If you set it, every search POSTs its detailed trace there: each query and what came back, which thumbnails were compared and their scores, every opened card with its variants, shipping, "same type" and "same model" scores, and why it was rejected. `research/logsink.py` is a tiny receiver that stores the traces as JSON files. **Empty by default: nothing is sent anywhere.**

## Languages

The panel and the agent's log are in English, Russian and Ukrainian (⚙ → Language). By default the panel follows the browser language. The agent's questions to the model are always in English, because that is how everything above was measured.

## Repository

- `extension/`: the product. `lib/agent.js` is the search agent, `lib/browse.js` browses through the user's tabs, `lib/model.js` talks to Ollama/OpenAI and computes Yes-probabilities, `lib/parse.js` parses AliExpress data, `lib/i18n.js` holds the languages.
- `ali.py`, `hunt.py`, `models.py`, `server.py`, `web/`: the Python test bench used during development ("human vs agent" matches). It isn't needed to use the extension.
- `research/`: probes and tests.

## License
MIT
