"""Fetch stock data from Typesense into data/stocks.json (Option A)."""
import json, os, sys, time, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config.json")
OUT = os.path.join(ROOT, "data", "stocks.json")


def main():
    with open(CONFIG) as f:
        cfg = json.load(f)
    base = cfg["endpoint"]
    headers = {
        "accept": "application/json",
        "origin": cfg.get("origin", "https://musaffa.com"),
        "referer": cfg.get("referer", "https://musaffa.com/"),
        "x-typesense-api-key": cfg["apiKey"],
    }
    filter_by = (
        "status:=PUBLISH && country:=US && exchange:=["
        + ",".join(f"`{e}`" for e in cfg["exchanges"]) + "] && sharia_compliance:=["
        + ",".join(f"`{s}`" for s in cfg["shariaCompliance"]) + "]"
    )
    per_page = cfg.get("perPage", 250)
    all_hits, page, total = [], 1, None
    while True:
        params = {"q": "*", "filter_by": filter_by, "sort_by": "usdMarketCap:desc",
                  "per_page": per_page, "page": page}
        url = base + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                print("API key rejected (HTTP %d). Update config.json apiKey." % e.code, file=sys.stderr)
                sys.exit(2)
            raise
        if total is None:
            total = data["found"]
        all_hits.extend(data.get("hits", []))
        print(f"page {page}: {len(data.get('hits', []))} (cumulative {len(all_hits)}/{total})", flush=True)
        if len(all_hits) >= total or not data.get("hits"):
            break
        page += 1
        time.sleep(0.2)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "source": base, "found": total, "count": len(all_hits),
                   "hits": all_hits}, f)
    print(f"Wrote {len(all_hits)} hits to {OUT}")


if __name__ == "__main__":
    main()
