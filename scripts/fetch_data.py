"""Fetch stock data from Typesense into data/stocks.json (Option A)."""
import json, os, sys, time, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config.json")
OUT = os.path.join(ROOT, "data", "stocks.json")


def norm_name(n):
    return " ".join(str(n or "").lower().split())


def resolve_tickers(hits):
    """Post-fetch hook: resolve ADR/foreign stocks to home-market tickers.

    Returns (enriched_hits, unmatched_list).
    """
    # home-market entries: dotted ticker + non-US company
    home_map = {}
    for h in hits:
        doc = h["document"]
        t = str(doc.get("ticker") or "")
        if "." in t and doc.get("company_country") != "US":
            home_map.setdefault(norm_name(doc.get("name")), t)

    records = []
    for h in hits:
        doc = dict(h["document"])
        orig_ticker = str(doc.get("ticker") or "")
        cc = doc.get("company_country")
        name = doc.get("name")
        is_home = ("." in orig_ticker) and (cc != "US")
        is_foreign_adr = (cc != "US") and ("." not in orig_ticker) and (doc.get("isMainTicker") == 1)

        resolved = orig_ticker
        aliases = {orig_ticker}
        foreign_ticker = None
        unmatched = False

        if is_foreign_adr:
            home_t = home_map.get(norm_name(name))
            if home_t:
                resolved = home_t
                aliases.add(home_t)
            else:
                resolved = "???"
                foreign_ticker = orig_ticker
                unmatched = True

        records.append({
            "hit": h,
            "doc": doc,
            "orig_ticker": orig_ticker,
            "is_home": is_home,
            "resolved": resolved,
            "aliases": aliases,
            "foreign_ticker": foreign_ticker,
            "unmatched": unmatched,
            "name": name,
        })

    # dedupe key:
    #   - matched/home entries: (normalized name, resolved ticker)  -> merges ADR+home dupes
    #   - unmatched entries: (orig ticker, name) so different foreign stocks are NOT merged
    groups = {}
    for rec in records:
        if rec["unmatched"]:
            key = ("__unmatched__", rec["orig_ticker"], norm_name(rec["name"]))
        else:
            key = ("matched", norm_name(rec["name"]), rec["resolved"])
        groups.setdefault(key, []).append(rec)

    deduped = []
    unmatched_list = []
    seen_unmatched = set()
    for key, grp in groups.items():
        if len(grp) == 1:
            rec = grp[0]
        else:
            home_recs = [r for r in grp if r["is_home"]]
            rec = home_recs[0] if home_recs else grp[0]
            for r in grp:
                rec["aliases"] |= r["aliases"]
        rec["doc"]["ticker"] = rec["resolved"]
        rec["doc"]["aliases"] = sorted(rec["aliases"])
        if rec["foreign_ticker"]:
            rec["doc"]["foreignTicker"] = rec["foreign_ticker"]
        new_hit = dict(rec["hit"])
        new_hit["document"] = rec["doc"]
        deduped.append(new_hit)
        if rec["unmatched"]:
            ut = rec["foreign_ticker"]
            if ut not in seen_unmatched:
                seen_unmatched.add(ut)
                unmatched_list.append({"name": rec["name"], "ticker": ut})

    unmatched_list.sort(key=lambda x: (x["name"] or "").lower())
    return deduped, unmatched_list


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

    deduped, unmatched = resolve_tickers(all_hits)
    print(f"resolver: {len(all_hits)} -> {len(deduped)} (removed {len(all_hits)-len(deduped)} dupes), unmatched={len(unmatched)}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "source": base, "found": total, "count": len(deduped),
                   "unmatched": unmatched,
                   "hits": deduped}, f)
    print(f"Wrote {len(deduped)} hits to {OUT}")


if __name__ == "__main__":
    main()
