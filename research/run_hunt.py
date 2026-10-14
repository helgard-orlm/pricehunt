import sys, os, json; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hunt
h = hunt.Hunt(ship_to="UA", query=sys.argv[1], log=lambda s: print(s, flush=True))
h.run()
st = h.state()
print("\nCONFIDENCE", st["confidence"])
for i, c in enumerate(st["top"], 1):
    print(f"{i}. ${c['total']:.2f}  good={c.get('p_good')}  {c['variant'][:30]} | {c['title'][:60]}\n    {c['why']}\n    flags={c['flags']}")
json.dump(st, open("data/hunt_last.json", "w"), ensure_ascii=False, indent=1)
