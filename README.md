# pricehunt

Find the **real** cheapest offer on AliExpress: the variant you actually want **plus shipping to your country**, checked by a local open-weight vision model.

Marketplace search shows the lowest price of *any* variant. Very often that is not the thing in the title:

| Listing title | Price shown in search | What that price buys | Real price of the charger |
|---|---|---|---|
| "40W Fast Charger Type C Dual Port PD" | $1.09 | a 0.25 m USB-C cable | $2.55 |
| "120W Fast Charger 4 Port USB Type C" | $2.28 | a 0.25 m cable | $4.09 |
| "Original Samsung 25W Charger PD" | $1.15 | a cable | $3.16 |

*(measured 2026-10-14, shipping to Ukraine, USD)*

pricehunt opens every variant, reads its own price and the shipping cost, flags new-shopper bait prices, and uses **MiniCPM-V 4.7** (running locally on an 8 GB GPU) to look at each variant photo and say what it really is.

Status: work in progress for the DEV Hacktoberfest 2026 Open-Source AI Challenge, week 2 ("Side Hustle"). Started 2026-10-14.

## License
MIT
