# -*- coding: utf-8 -*-
"""第一步：快速验证候选链接是否能抓到（不调 LLM，只测抓取）。"""
import json
import time

import scraper

CANDIDATES = [
    # 品类多样性
    ("智能音箱", "https://www.amazon.com/dp/B09B8V1LZ3"),
    ("露营椅", "https://www.amazon.com/VTOY-Chairs%EF%BC%8CCamping-Foldable-Shadefor-Camping/dp/B0CXT9RSGQ"),
    ("耳机", "https://www.amazon.com/dp/B0BDHWDR12"),
    ("Kindle", "https://www.amazon.com/dp/B08KTZ8249"),
    ("水杯", "https://www.amazon.com/dp/B00HZVOKME"),
    ("乐高", "https://www.amazon.com/dp/B09BC4FCL2"),
    ("游戏机", "https://www.amazon.com/dp/B0BCJKGN2P"),
    ("厨房小家电", "https://www.amazon.com/dp/B0758B9QG4"),
    ("宠物用品", "https://www.amazon.com/dp/B07QK2SPP7"),
    # URL 形态泛化
    ("gp/product 格式", "https://www.amazon.com/gp/product/B09B8V1LZ3"),
    ("英站点", "https://www.amazon.co.uk/dp/B09B8V1LZ3"),
]

out = []
for label, url in CANDIDATES:
    t0 = time.time()
    try:
        d = scraper.fetch_product(url)
        ok = bool(d["title"])
        print(f"[OK {time.time()-t0:5.1f}s] {label} | {d['source']} | {d['currency']} {d['price']} | {(d['title'] or '')[:48]}")
        out.append({"label": label, "url": url, "ok": True, "title": (d["title"] or "")[:60],
                    "price": d["price"], "currency": d["currency"], "images": len(d["images"])})
    except Exception as e:
        print(f"[FAIL {time.time()-t0:5.1f}s] {label} | {str(e)[:80]}")
        out.append({"label": label, "url": url, "ok": False, "error": str(e)[:100]})

json.dump(out, open("_candidates.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n可用:", sum(1 for x in out if x["ok"]), "/", len(out))
