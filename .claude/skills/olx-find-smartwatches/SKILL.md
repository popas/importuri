---
name: olx-find-smartwatches
description: Invoke once per OLX smartwatch session to sweep category 1943 (smartwatch-uri) with olx-find-smartwatches.py and triage the returned candidates. Not per watch — run it once, then import from the candidates file.
---

# olx-find-smartwatches

Discovery for OLX category **1943** — `/electronice-si-electrocasnice/gadgets-wearables-si-camere-foto-video/smartwatch-uri/`.
`$PROJECT_ROOT` / `$CDP_HOST` come from `olx-session-setup`.

Run this **once per session**, not per watch. It walks the category through OLX's
JSON API, applies the objective filters, dedups against the admin, and writes every
surviving candidate to disk so a `/clear`'d context can import without sweeping again.

## Run it

```bash
export BU_CDP_URL="http://$CDP_HOST"
MAX_CANDIDATES=8 browser-use < $PROJECT_ROOT/harness/3ceasuri-import/scripts/olx-find-smartwatches.py
```

Env: `MAX_CANDIDATES` (8), `MAX_PAGES` (5 × 40 ads), `MIN_RON` (150), `MIN_EUR` (30),
`SNIPPET` (180), `NO_DEDUP=1`, `DEBUG_DROPS=1`, `OUT`.

The 150 RON floor is deliberately higher than the Facebook one: under it, the
smartwatch category is straps, chargers and clones almost without exception.

Output:

```
CANDIDATES: [{id, price, cur, brand, new_brand, business, seller_name, photos, looks_classic, snip}, …]
STATS: {candidates, seen, pages, category_total, dropped:{…}, admin_total, out}
```

Full records (including the whole ad text and the ad URL) go to
`$PROJECT_ROOT/harness/3ceasuri-import/.candidates-olx-smart.json`.

## What the script decides vs what YOU decide

It drops only what a regex gets right every time: inactive ads, no price, price
below the floor, explicit replica wording, accessories (a strap, charger, case,
dock or empty box is not a watch), blocklisted sellers, already-imported ids.
Rejects are reported as **counts**, so they cost you almost no context; add
`DEBUG_DROPS=1` when a sweep comes back suspiciously empty.

Everything requiring judgement is yours. Read the snippets and pick, watching for:

- **Stock photos and renders.** A "brand new sealed" ad with a press image is
  usually a dropshipper. Photos come with the contract at import time, so you can
  also defer this call to pass 1.
- **Grade A/B refurbished and shop inventory.** Business sellers are kept by user
  directive and flagged `business: true` — they are importable, just judge them.
- **Activation lock.** "iCloud", "cont Apple", "nu stiu parola" means the watch is
  unusable; skip it and note why.
- **`looks_classic: true`** — a mechanical watch that wandered into this category.
  Route it to `olx-import-watch.py`, do not import it here.
- **Generation claims.** Ads routinely call a Series 6 a "Series 9". The photos
  settle it at import time; flag anything that reads odd.

## Then

For each id you keep, in a FRESH context (`/clear` between watches):

```
invoke `olx-import-smartwatch`  → pass 1 (contract) → you fill it → pass 2 (import)
invoke `import-verify-state`    → append to history.jsonl, bump the counters
```

Never re-run discovery mid-session — take the next id from the candidates file.

When anything fails → `olx-troubleshooting`.
