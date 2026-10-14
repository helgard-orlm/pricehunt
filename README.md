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
- **"Sort by price" isn't trustworthy.** Results come back out of order. Sometimes a sort or filter returns *nothing* on purpose. pricehunt splits and sorts results itself and treats an empty page as a refusal, not as "no products".
- **Same look, different product.** A photo of a 220 V COB panel with an on-board driver returns DC copper COB chips that look similar. Every candidate photo is compared with your product photo.

## How the agent searches

It follows the method a human bargain hunter uses (this is how the author finds parts by hand):

1. **Search by photo.** Your product photo goes into AliExpress' own camera search.
2. **Keep only exact matches.** The model compares each thumbnail with your photo and opens only the ones that are the same product, cheapest first.
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
| ESP-01 programmer adapter, starting from a $2.16 listing | agent found **$0.70** (same board, 97% photo match) in 301 s |

What is **not** measured yet:
- How well it catches *lying* listings, where the title says charger and the photo shows a cable. The 49/49 above are honestly named variants.
- Other models only partly. Gemma 4 12B (Ollama `gemma4:12b-it-qat`) scored 45/49 on variant photos: it mistook "cable only" for "charger with cable". Gemma 4 31B through Ollama Cloud (`gemma4:31b-cloud`) scored 47/49, with the same trap, and it's fast (0.9 s per photo). Its "same product as your photo?" answers were weaker, though: of 7 COB listings it called the same, about 6 were a different type (copper DC chips, SMD boards, 12 V panels), and it rejected 4 real ESP-01 adapters shown next to the modules. Cloud models also send your photos to the cloud and return no logprobs. In that case the extension falls back to a plain Yes/No, so the percentages turn into 0%/100%.
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

## Languages

The panel and the agent's log are in English, Russian and Ukrainian (⚙ → Language). By default the panel follows the browser language. The agent's questions to the model are always in English, because that is how everything above was measured.

## Repository

- `extension/`: the product. `lib/agent.js` is the search agent, `lib/browse.js` browses through the user's tabs, `lib/model.js` talks to Ollama/OpenAI and computes Yes-probabilities, `lib/parse.js` parses AliExpress data, `lib/i18n.js` holds the languages.
- `ali.py`, `hunt.py`, `models.py`, `server.py`, `web/`: the Python test bench used during development ("human vs agent" matches). It isn't needed to use the extension.
- `research/`: probes and tests.

## License
MIT
