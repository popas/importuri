---
name: olx-find-watches
description: Invoke once per OLX watch session to sweep category 1677 (moda-frumusete/ceasuri) with olx-find-watches.py and triage the returned candidates. Not per watch — run it once, then import from the candidates file.
---

# olx-find-watches

Discovery for OLX category **1677** — `/moda-frumusete/ceasuri/` (classic watches:
mechanical, automatic, quartz). `$PROJECT_ROOT` / `$CDP_HOST` come from
`olx-session-setup`.

Run this **once per session**, not per watch. It walks the category through OLX's
JSON API, applies the objective filters, dedups against the admin, and writes every
surviving candidate to disk so a `/clear`'d context can import without sweeping again.

## Run it

```bash
export BU_CDP_URL="http://$CDP_HOST"
MAX_CANDIDATES=8 browser-use < $PROJECT_ROOT/harness/3ceasuri-import/scripts/olx-find-watches.py
```

Env: `MAX_CANDIDATES` (8), `MAX_PAGES` (5 × 40 ads), `MIN_RON` (100), `MIN_EUR` (20),
`SNIPPET` (180), `NO_DEDUP=1`, `DEBUG_DROPS=1`, `OUT`.

Output:

```
CANDIDATES: [{id, price, cur, brand, new_brand, business, seller_name, photos, looks_smart, looks_wall, snip}, …]
STATS: {candidates, seen, pages, category_total, dropped:{…}, admin_total, out}
```

Full records go to `$PROJECT_ROOT/harness/3ceasuri-import/.candidates-olx-watches.json`.

## What the script decides vs what YOU decide

It drops only what a regex gets right every time: inactive ads, no price, price
below the floor, explicit replica wording, accessories (straps, cases, loose
movements, "pentru piese"), price ranges (a range means several items), blocklisted
sellers, already-imported ids. Rejects are counts; `DEBUG_DROPS=1` shows them.

Two things are **flagged, never dropped** — dropping them was how good listings got
lost:

- **`looks_smart: true`** — an Apple/Samsung/Garmin watch listed here. Import it
  with `olx-import-smartwatch.py`, which fills `series` / `connectivity` /
  `compatibility`. Do not push it through the classic importer.
- **`looks_wall: true`** — a wall clock. The site lists those since 2026-08-09
  (`category="wall"`), so import it with `olx-import-watch.py` and answer
  `is_wristwatch: false` **plus** `category: "wall"`.

Yours to judge from the snippets:

- **Amanet and reseller stock.** Business sellers are kept by user directive and
  flagged. They relist the same watch under fresh ad ids constantly — the importer's
  seller+model dedup catches most of that, but read the snippet anyway.
- **Bulk in disguise.** "Ceasuri Hugo Boss" plural, or a photo of six watches with
  one price.
- **Replicas that do not say replica.** A "Rolex Submariner" at 600 lei is not one.
- **Parts and non-runners** sold as watches ("nu functioneaza", "pentru piese").

## Then

For each id you keep, in a FRESH context (`/clear` between watches):

```
invoke `olx-import-watch`     → pass 1 (contract) → you fill it → pass 2 (import)
invoke `import-verify-state`  → append to history.jsonl, bump the counters
```

Never re-run discovery mid-session — take the next id from the candidates file.

When anything fails → `olx-troubleshooting`.
