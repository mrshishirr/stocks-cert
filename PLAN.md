# Living Plan — Musaffa Stock Screener SPA (stocks-cert)

> **Living document.** Update this file as work progresses: tick checkboxes, append to the Changelog, revise decisions. Last updated: 2026-10-22.

## Status

- Phases 0-4 complete. Phase 5 (Pages) published.
- Phase 5: Pages deploy workflow added; not yet deployed.
- Pending: key-refresh step, XLSX export, responsive polish, empty-state refinement, GitHub Pages publish.

## Goal

Build a single-page app (SPA) that replicates [musaffa.com/stock-screener](https://musaffa.com/stock-screener/?country=US&page=1) for browsing/filtering/sorting halal-screened stocks, hosted on GitHub Pages. Data sourced from the Musaffa Typesense endpoint (see `config.json`), periodically fetched and stored in-repo (Option A) so the SPA reads a local JSON file instead of hitting the API directly.

## Decisions

- **Hosting:** GitHub Pages (static).
- **Framework:** Vue 3 via CDN (no build tooling) + Tailwind via CDN.
- **Data strategy (Option A):** GitHub Actions scheduled workflow fetches Typesense → writes `data/stocks.json` (+ per-country splits) → commits to repo → Pages serves it. SPA reads local JSON.
- **API key:** Stored in `config.json` (client-readable). Public key, already exposed by musaffa. Mechanism to refresh: (1) manual edit of `config.json`, (2) optional workflow step that scrapes the key from the musaffa screener page HTML/JS if the configured key returns 401/403. Never commit secrets beyond this already-public key.
- **Sort "most desired (halal)":** Client-side composite: `musaffaHalalRating` (COMPLIANT → QUESTIONABLE → NON_COMPLIANT → unrated) → `musaffa_iri_score` desc → `businessCompliantRatio` desc → `doubtful_revenue_percent` asc → `interestBearingDebtRatio` asc.
- **Scope v1:** Core screener (country/exchange/compliance filters, sort, pagination, table) + detail view + CSV export.

## Architecture

```
stocks-cert/
├── index.html              # Vue 3 SPA (CDN)
├── config.json             # endpoint, api key, countries, exchanges
├── data/
│   └── stocks.json         # fetched dataset (committed by workflow)
├── scripts/
│   └── fetch_data.py       # Typesense paginator -> data/*.json
├── .github/workflows/
│   ├── fetch-data.yml      # scheduled fetch + commit
│   └── deploy-pages.yml    # Pages deploy on push
├── PLAN.md                 # this file (living)
└── README.md
```

## Phases

### Phase 0 — Scaffold
- [x] Create repo structure (index.html, config.json, scripts, workflows)
- [x] Add .gitignore, README.md
- [x] Init git + commits

### Phase 1 — Data pipeline (Option A)
- [x] Port `fetch_data.py` (done, 6592 hits) (paginate per_page=250, all compliance levels, US exchanges)
- [x] Write `data/stocks.json` (31MB) with metadata (fetched_at, count, source)
- [x] Add `fetch-data.yml` (cron daily + manual dispatch) committing changes only if diff
- [ ] Key-refresh step: (pending) if API returns 401/403, scrape key from musaffa page (best-effort) and update config.json; else fail loudly
- [x] SEC resolver v2 (hybrid base/digit/override/name + manual overrides) — 6217/6231 resolved, 14 unmatched

### Phase 2 — SPA core
- [x] Vue 3 app shell, Tailwind styling
- [x] Load `data/stocks.json`
- [x] Filters: exchange, sharia_compliance (multi-select), search by ticker/name
- [x] Sort: halal/mcap/iri/name
- [x] Pagination (client-side, 50/page)
- [x] Table view with compliance badge, IRI, market cap

### Phase 3 — Detail view
- [x] Row click → detail modal (financials, ratios, revenue compliance breakdown)
- [x] Back/close handling

### Phase 4 — Export
- [x] CSV export of filtered view
- [ ] (Optional) XLSX via SheetJS CDN

### Phase 5 — Deploy & polish
- [x] GitHub Pages via Actions (workflow added)
- [ ] Responsive/mobile layout (partial - Tailwind responsive classes used)
- [x] Loading/error states (empty state pending)

## API key refresh mechanism

- `config.json` holds `apiKey` and `endpoint`.
- Workflow reads key from config; on 401/403 from Typesense, attempts to extract the key from `https://musaffa.com/stock-screener/?country=US&page=1` (regex over inline JS/config). If found and differs, updates config.json and retries once.
- If scrape fails, workflow fails (no silent stale data) and opens an issue (optional).
- Manual override: edit `config.json` and push.

## Open questions / risks

- Typesense public key rotation cadence unknown; scrape may break if musaffa obfuscates. Mitigation: fail loudly + manual fallback.
- Repo size: 6,577 docs × ~200 fields ≈ large JSON (~tens of MB). Consider trimming fields in fetch script to needed columns to keep Pages fast.
- GitHub Pages 1GB / 100GB bandwidth limits; trim payload.

## Changelog

- 2026-10-22: Plan created.
- 2026-10-22: Seeded data/stocks.json (6592 hits). Phase 2 core + detail view + CSV export implemented in index.html. Chose Option A for data. Decided Vue 3 CDN + Tailwind. Identified key-refresh requirement.
- 2026-10-22: Fixed stray EOF text; added last-updated display, browser cache + once/day background refresh, light/dark mode toggle.
- 2026-10-22: Fixed dark mode (config before CDN); made all column headers sortable with toggle; default sort market cap desc.
- 2026-10-22: Dark mode fixed with CSS fallback + sun/moon glyph toggle.
- 2026-10-22: Dark mode background fix (!important on body).
- 2026-10-22: Fixed tailwind.config (not nested) for darkMode class strategy.
- 2026-10-22: Dark mode reimplemented with pure CSS .dark class (dropped Tailwind dark: variants).
- 2026-10-22: Default dark mode; AAA contrast audit (badges/muted/btn/hover/focus) passed.
- 2026-10-22: On fetch failure keep cached data and report 'fetch failed'.
- 2026-10-22: Row click opens right side panel (toggle/close); table remains navigable.
- 2026-10-22: Multi-sort columns with priority order and clear-sort.
- 2026-10-22: Multi-sort fixed (not pinned; new sort primary; fully unsortable).
- 2026-10-22: Added post-fetch resolver (fetch_data.py): foreign stocks -> '???' + unmatched list; dedup exact dupes.
- 2026-10-22: On-demand force-fetch button (left of dark toggle).
- 2026-10-22: Fixed forceFetch scoping bug.
- 2026-10-22: SEC resolver v2 implemented (6217/6231 resolved, 14 unmatched). Snapshot data/sec_tickers.json committed.
