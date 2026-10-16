---
title: I taught a local vision model to find the same AliExpress item cheaper — variant and shipping included
published: false
tags: devchallenge, hf26challenge, ai, opensource
cover_image: <!-- upload share/1/cover.png -->
---

*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12)*

<!-- cover caption is not shown by DEV; the line below says it -->
*Cover: AI-generated illustration. Everything below is real screenshots from the extension.*

## What I Built

**pricehunt** is a browser extension. Open an AliExpress product, pick the exact variant you want (power, colour, plug…) and press **Find the same thing cheaper**. An open-weight vision model running on your own computer then looks for the *same* item at a lower *real* price, and you watch it work in the side panel.

<!-- IMAGE: share/1/2.jpg -->
![The panel after a search: the same Essager 33W charger, black, EU plug, found for $8.42 instead of $12.43](UPLOAD_2.jpg)
*A real run: my reference listing was $12.43. The agent found the same charger (same model, same black EU plug variant, free shipping) for $8.42 in 134 seconds.*

I buy electronics parts on AliExpress all the time, and the cheapest price on the search page is almost never what you pay:

| Listing title | Price in search | What that price buys | Real price of the charger |
|---|---|---|---|
| "40W Fast Charger Type C Dual Port PD" | $1.09 | a 0.25 m USB-C cable | $2.55 |
| "120W Fast Charger 4 Port USB Type C" | $2.28 | a 0.25 m cable | $4.09 |
| "Original Samsung 25W Charger PD" | $1.15 | a cable | $3.16 |

*(measured 14 Oct 2026, shipping to Ukraine)*

The search page shows the cheapest price of *any* variant, often of a different product. Shipping isn't in that number. Some prices are "welcome deals" you only get once. "Sort by price" comes back out of order, and sometimes a sort or filter returns nothing at all. Finding the real cheapest offer by hand means opening dozens of tabs.

**Who would pay for it:** people whose margin *is* the buying price. Repair shops and makers who order the same modules every month. Small resellers who buy on AliExpress and sell locally. Anyone who has ordered a "charger" and received a cable. Saving $4 on one charger is a coffee. On a cart of 30 parts reordered every month, it's the difference between a side hustle that pays and one that doesn't.

## Demo

<!-- VIDEO: upload share/1/1.mp4 to YouTube, then: {% embed https://youtu.be/XXXX %} -->

<!-- IMAGE: share/1/1.png -->
![Before the search: the variant chips, the reference photo strip and the local model in the settings](UPLOAD_1.png)
*Before the search: the variant is chosen with chips (33W Black EU Plug), the reference photo strip is below, and the model is my local MiniCPM-V 4.7.*

The panel shows:
- the variant chips and the **reference photo** the agent will search with (click another photo if needed);
- live progress: level, fatigue, listings seen and opened;
- results grouped as **EXACT MATCH / SIMILAR / DIFFERENT**, each with the price split into item + shipping, plus warnings such as *"the listing price $8.28 is for 'Black US Plug', not the wanted item"*, *"$1.09 is for new buyers only"* or **BUNDLE DEAL** (the extra discount needs 3 different items).

## Code

{% github helgard-orlm/pricehunt %}

Install: download the zip from Releases → `chrome://extensions` → Developer mode → **Load unpacked**. Then point it at Ollama or any OpenAI-compatible server.

## How I Built It

**The model: MiniCPM-V 4.7** (35B-A3B MoE, open weights) served by **llama.cpp** on a home PC: RTX 5060 8 GB, 32 GB RAM. With `--cpu-moe` the experts stay in system RAM and the GPU holds about 4 GB. One model does everything: it reads the listing, looks at photos and answers Yes/No questions.

I didn't want "the AI says it's 87% good", so every match decision is a **Yes/No question whose probability I read from the token logprobs**. And the wording of the question turned out to matter more than anything else. On 16 Essager chargers that I labelled by eye:

| Question | Same model accepted | Other models accepted |
|---|---|---|
| "Is it the same *type* of product?" | 5 / 5 | **7 / 11** |
| "Is it the same *model*: same body, ports, display, printed power?" | 5 / 5 | **1 / 11** |

So only the strict question can make a listing an **exact match**; "same type" can at most make it "similar".

**The search method isn't mine, it's how I hunt by hand**, turned into an agent:
1. **Search by photo, a photo of one item.** Listings open with a collage of all sizes. The chosen variant's own photo is far more precise. With the single 100 W photo instead of the collage, MiniCPM-V recognised 8 matching COB panels in the same 25 listings instead of 0.
2. **Open only exact matches**, cheapest first, judged by comparing search thumbnails to the reference.
3. **Search by the seller's verbatim title** of an exact match. Many parts (an ESP32 board with a screen, a COB chip) have no common name, but the sellers' own titles find each other.
4. **Split results into free and paid shipping and sort them myself.** Never trust the site's sort, and treat an empty result as a refusal, not "no products".
5. **Open the product, read every variant.** The model picks the variant that really is the wanted thing. Hard specs from your choice (33 W stays 33 W) and the plug for your country are checked in code.
6. **Repeat from the new best** with a fatigue rule: 3 levels free, then each level without a cheaper find adds fatigue, and a cheaper find resets it.

**The trick that isn't AI: sellers copy each other's photos.** The vision model still missed one listing of the very same charger, because my reference photo shows it from the side and that listing shows it from the front. I tried to fix it with smarter questions and failed four times. Then I remembered how I actually recognise the same item by hand: nobody photographs their own stock, everyone reuses the same 2–3 factory photos. So version 1.6 fingerprints the reference's product photos (a 256-bit difference hash; brand banners are filtered out first with one Yes/No question each) and treats a listing that reuses one of them as the same item, as long as the model agrees it's the same kind of product. A thumbnail with a copied photo is opened without asking the model at all. On the Essager listings, the same model shared 2–3 product photos with my reference, other models shared none. One look-alike with two USB-C ports shared only the brand banners and a scene where the seller had redrawn the ports, which the hash tells apart (copies are 0 bits apart, the redraw 4). That's one product family, so I count it as a promising idea, not a proven one.

**Everything runs inside the extension**, in your own browser, one page at a time: your login, your country, your currency. If AliExpress shows a captcha, the tab comes to the front and the agent waits for *you*. It doesn't try to solve or bypass it.

**What I measured** (all on MiniCPM-V 4.7):

| Test | Result |
|---|---|
| Variant photos: charger / cable / charger+cable / car charger (49 photos, 6 listings) | **49 / 49** |
| Me vs the agent: COB LED chip 220 V 100 W, my own manual search | **tie at $3.39**: the agent found exactly the offer in my cart |
| Me vs the agent: Essager 33W GaN charger (black, EU plug), starting from a $12.43 listing | agent found **$8.42** for the same model; my own manual find was $8.89 |
<!-- TODO before publishing: re-run ESP-01 with v1.6 (Choice shipping fix in 1.3.3) or check against my cart; until then keep this row out
| ESP-01 programmer adapter, starting from a $2.16 listing | agent found **$0.70** for the same board in 5 minutes |
-->

And what I *didn't* prove: how well it catches listings that **lie** (the title says charger, the photo shows a cable). The 49/49 are honestly named variants. Two matches against a human are two matches, not a benchmark.

**Bugs worth a mention**, all found by testing against real listings:
- The search parser was reading the **struck-out** price on 35 of 59 discounted cards.
- The agent added $0.49 shipping where AliExpress itself shows free shipping, because I didn't read the site's own free-shipping rule.
- The photo CDN answers a burst of requests with **403 + an HTML page, marked cacheable for a year**. Image downloads now check the status and retry later, bypassing the browser cache.
- My first Gemma-vs-MiniCPM comparison used the collage as the reference, which was unfair to both, so I re-ran it.

I also built a developer log: the extension can send a structured trace of every search (what it saw, which thumbnails it opened and why, every variant it read) to a small receiver on my machine. Most fixes in versions 1.5 and 1.6 came from reading those traces of my own real searches instead of guessing.

## Why Does Open Innovation Matter?

**Because the marketplace will never build this.** AliExpress's own sorting and "best price" labels serve AliExpress. A tool whose only job is to find you the lower price has to be on *your* side: running on your machine, with a model you can inspect and swap.

What being open made possible here:
- **Privacy:** the agent browses with your logged-in session. Your cookies, cart and photos never leave your computer. That's only acceptable with a local model.
- **Cost:** one search is dozens of image comparisons. On a paid vision API that's a bill per search. Locally it's electricity.
- **Logprobs:** the match percentages come from token probabilities that my local llama.cpp server exposes. The Ollama Cloud model I tried returned none, so the extension falls back to a plain Yes/No.
- **Swapping models and measuring them:** I could put several open models through the same test. Gemma 4 12B scored 45/49 on the variant photos and Gemma 4 31B (via Ollama Cloud) 47/49, both falling for the "cable only" trap. On "same type as the reference?", Gemma accepted 5 COB listings of a different type that MiniCPM-V rejected. So the extension works with any vision model, and the numbers in this post say which one they were measured on.
- **No lock-in:** Ollama on your PC, llama.cpp on a home server, or any OpenAI-compatible endpoint. The extension doesn't care.

<!-- My Agent Session: optional. Remove or add a DevRelay link. -->

<!-- My First User: only if someone besides me used it; otherwise remove this section. -->

<!-- Built with help from an AI coding agent (Claude Code); the method, the tests against my own purchases and every decision are mine. -->
