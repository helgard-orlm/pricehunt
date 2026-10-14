import json, sys
from playwright.sync_api import sync_playwright
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ali
q = sys.argv[1]; n = int(sys.argv[2])
hits = ali.search(q)
print(f"search: {len(hits)} hits")
out = []
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, executable_path=ali.CHROME)
    for h in sorted(hits, key=lambda x: x["list_price"])[:n]:
        it = ali.item(h["id"], browser=b)
        if not it: print("FAIL", h["id"]); continue
        it["list_price"] = h["list_price"]; out.append(it)
        print(f"\n#{h['id']} list ${h['list_price']}  {it['title'][:90]}")
        for s in it["shipping"][:2]: print(f"   ship {s['fee']} {s['company']} {s['days']}d to {s['ship_to']}")
        for v in sorted(it["variants"], key=lambda v: v["price"] or 1e9)[:6]:
            print(f"   ${v['price']} (orig {v['original']}){' WELCOME' if v['welcome_deal'] else ''}  {'; '.join(v['attrs'])}")
    b.close()
json.dump(out, open("cheap.json", "w"), ensure_ascii=False, indent=1)
