"""Fetch stock data from Typesense into data/stocks.json (Option A).

Post-fetch resolver uses SEC company_tickers.json to resolve foreign (dotted)
home-market tickers to their US tickers. SEC snapshot is stored in-repo
(data/sec_tickers.json) and only re-downloaded on force-refresh.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config.json")
OUT = os.path.join(ROOT, "data", "stocks.json")
SEC_OUT = os.path.join(ROOT, "data", "sec_tickers.json")


def norm_name(n):
    return " ".join(str(n or "").lower().split())


def norm_title(s):
    s = str(s or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    for w in ["inc", "corp", "corporation", "ltd", "limited", "plc", "sa", "ag", "nv",
              "co", "company", "group", "holdings", "holding", "llc", "the"]:
        s = re.sub(r"\b" + w + r"\b", " ", s)
    return " ".join(s.split())

def load_overrides():
    """Load manual ticker overrides from data/manual_overrides.json (if present)."""
    path = os.path.join(ROOT, "data", "manual_overrides.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def load_override_aliases():
    path = os.path.join(ROOT, "data", "manual_override_aliases.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


MANUAL_OVERRIDES = load_overrides()
OVERRIDE_ALIASES = load_override_aliases()




def strip_trailing_digits(s):
    return re.sub(r"\d+$", "", s)


def load_sec(cfg, force=False):
    """Load SEC snapshot from disk; download if missing or force."""
    if os.path.exists(SEC_OUT) and not force:
        with open(SEC_OUT) as f:
            return json.load(f)
    url = cfg.get("secUrl", "https://www.sec.gov/files/company_tickers.json")
    headers = {
        "User-Agent": cfg.get("secUserAgent", "stocks-cert research (contact: mrshishirr@gmail.com)"),
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    os.makedirs(os.path.dirname(SEC_OUT), exist_ok=True)
    with open(SEC_OUT, "w") as f:
        json.dump(data, f)
    print(f"Downloaded SEC tickers -> {SEC_OUT} ({len(data)} entries)")
    return data


def resolve_tickers(hits, sec_data):
    """Post-fetch hook: resolve foreign (dotted) tickers to US tickers via SEC.

    Returns (enriched_hits, unmatched_list).
    """
    sec_entries = [(v["ticker"], v["title"]) for v in sec_data.values()]
    sec_set = {t.upper() for t, _ in sec_entries}
    sec_by_title_norm = {}
    for t, title in sec_entries:
        sec_by_title_norm.setdefault(norm_title(title), t)

    # inverted index for fuzzy matching
    from collections import defaultdict
    idx = defaultdict(list)
    sec_norm_list = [(t, title, norm_title(title)) for t, title in sec_entries]
    for i, (_, _, tn) in enumerate(sec_norm_list):
        for tok in set(tn.split()):
            idx[tok].append(i)

    def sec_lookup_name(name):
        n = norm_title(name)
        if n in sec_by_title_norm:
            return sec_by_title_norm[n]
        toks_u = set(n.split())
        if not toks_u:
            return None
        cands = set()
        for tok in toks_u:
            cands.update(idx.get(tok, []))
        best = None
        bestscore = 0
        for i in cands:
            t, title, tn = sec_norm_list[i]
            toks_s = set(tn.split())
            if not toks_s:
                continue
            inter = len(toks_u & toks_s)
            score = inter / max(len(toks_u), len(toks_s))
            if score > bestscore:
                bestscore = score
                best = t
        if best and bestscore >= 0.9:
            return best
        return None

    # home-market map from Typesense data itself
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

        if is_home:
            base = orig_ticker.split(".")[0].upper()
            cand = None
            if base in sec_set:
                cand = base
            elif strip_trailing_digits(base) in sec_set:
                cand = strip_trailing_digits(base)
            elif orig_ticker in MANUAL_OVERRIDES:
                cand = MANUAL_OVERRIDES[orig_ticker]
            else:
                cand = sec_lookup_name(name)
            if cand:
                resolved = cand
                aliases.add(cand)
                for a in OVERRIDE_ALIASES.get(orig_ticker, []):
                    aliases.add(a)
            else:
                resolved = "???"
                foreign_ticker = orig_ticker
                unmatched = True
        elif is_foreign_adr:
            # already a US-listed foreign stock; optionally verify against SEC
            sec_t = sec_lookup_name(name)
            if sec_t and sec_t.upper() != orig_ticker.upper():
                aliases.add(sec_t)

        # add SEC title as alias for partial-text search
        sec_title = None
        for t, title in sec_entries:
            if t.upper() == (resolved if resolved != "???" else orig_ticker).upper():
                sec_title = title
                break
        if sec_title:
            aliases.add(sec_title)

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

    # dedupe
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Force re-download SEC snapshot")
    args = parser.parse_args()
    force = args.force or os.environ.get("FORCE_REFRESH") == "1"

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

    sec_data = load_sec(cfg, force=force)
    deduped, unmatched = resolve_tickers(all_hits, sec_data)
    print(f"resolver: {len(all_hits)} -> {len(deduped)} (removed {len(all_hits)-len(deduped)} dupes), unmatched={len(unmatched)}")
    resolved_count = sum(1 for h in deduped if h["document"].get("ticker") != "???")
    print(f"  resolved/unresolved tickers: {resolved_count}/{len(deduped)-resolved_count}")

    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"fetched_at": fetched_at,
                   "source": base, "found": total, "count": len(deduped),
                   "unmatched": unmatched,
                   "hits": deduped}, f)
    version_file = os.path.join(os.path.dirname(OUT), "version.txt")
    with open(version_file, "w") as f:
        f.write(fetched_at)
    print(f"Wrote version -> {version_file}")
    print(f"Wrote {len(deduped)} hits to {OUT}")


if __name__ == "__main__":
    main()
