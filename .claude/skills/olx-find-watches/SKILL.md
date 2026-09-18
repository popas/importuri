---
name: olx-find-watches
description: Invoke ONCE per session (not per watch) to sweep OLX category 1677 (classic watches) and triage the candidates it returns.
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
- **Multiple watches, each its own price, run together in one ad without a bulk
  keyword.** "Vand ceas Certina ... 450, vand ceas Nixon ... preț 300" reads like
  one seller's post but is several separate items — the `is_stock_listing` regex
  only catches ≥3 prices that carry an explicit currency word right next to them,
  so a run-on paragraph with the unit omitted on some prices slips through as a
  single candidate (seen 2026-08-11, brand happened to match a category-1677
  brand yet the ad surfaced in the 1943 sweep — the brand/category match is not
  a source-routing signal, read the snippet regardless of which sweep found it).
  Too few photos to attribute to individual watches → skip the whole ad rather
  than guess a split.
- **Replicas that do not say replica.** A "Rolex Submariner" at 600 lei is not one.
- **Parts and non-runners** sold as watches ("nu functioneaza", "pentru piese").

## Suspiciously cheap = fake, never imported

Standing user directive (2026-08-09): **a suspiciously cheap listing is not a
bargain, it is a fake.** A replica seldom says "replica"; the price is what gives
it away. Discovery drops these as `suspiciously_cheap`, and the importers refuse
them outright — before the photos are fetched, and `CONFIRM=1` does **not** wave
one through.

The floors live in one place, `scripts/price_sanity.py`: a per-brand table
(Rolex 6000 RON, Omega 1500, Breitling 2500 …) plus model-family floors for
smartwatches (any Watch Ultra 1200, Apple Watch Series 9-11 700 …). They are the
lowest price a GENUINE used example plausibly trades at, set generously so the
rule catches obvious fakes rather than shaving the honest market. Tune them there
and every script follows.

The brand is matched against the ad's own words as well as the marketplace's brand
field, because that field is unreliable — OLX offered "Swiss" for a Christophe
Duchamp. A listing that calls itself a Rolex is judged as one.

## Then

For each id you keep, in a FRESH context (`/clear` between watches):

```
invoke `olx-import-watch`     → pass 1 (contract) → you fill it → pass 2 (import)
invoke `import-verify-state`  → append to history.jsonl, bump the counters
```

Never re-run discovery mid-session — take the next id from the candidates file.

When anything fails → `olx-troubleshooting`.
