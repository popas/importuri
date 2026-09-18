---
name: olx-find-watches
description: Invoke ONCE per session (not per watch) to sweep OLX category 1677 (classic watches) and triage the candidates it returns.
---

# olx-find-watches

Discovery for OLX category **1677** — `/moda-frumusete/ceasuri/`. Run **once per
session**, not per watch. It writes a status-bearing work queue, so a stopped
session resumes without sweeping again.

## 1. Run it

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

Full records, each `status: "pending"`, go to
`$PROJECT_ROOT/harness/3ceasuri-import/.candidates-olx-watches.json`.

## 2. Report `STATS.admin_total`

That is the live site count — the only number worth quoting. Never quote a local
file.

## 3. Triage the snippets

The script already dropped everything a regex gets right every time: inactive, no
price, below floor, explicit replica wording, accessories, price ranges,
activation-locked, explicit shop stock, blocklisted sellers, already-imported.
Drops are counts; `DEBUG_DROPS=1` shows them.

Answer with one line per candidate and nothing else:

```
KEEP <id>
DROP <id> <reason-code>
```

Reason codes: `bulk_lot` · `stock_photos` · `parts_only` · `unattributable_photos`
· `not_a_watch` · `other`.

Apply this table. When none of it fires, `KEEP`.

| In the snippet | Verdict |
|---|---|
| plural title over one price, or one photo of several watches | `DROP … bulk_lot` |
| several watches each with its own price, run together in one ad | `DROP … bulk_lot` |
| "nu functioneaza", "pentru piese", non-runner sold as a watch | `DROP … parts_only` |
| too few photos to attribute to one watch | `DROP … unattributable_photos` |
| `looks_smart: true` | `KEEP` — route it to `olx-import-smartwatch` |
| `looks_wall: true` | `KEEP` — import with `category: "wall"` |
| `business: true` (amanet, reseller) | `KEEP` — business sellers are wanted |
| a price that seems too low | `KEEP` — the floors already ran; do not second-guess them |

Stock photos, renders and inflated claims are **not** drops here. The photos arrive
at import time and settle it.

## Next

Do NOT re-run discovery mid-session. Drive the queue:

```bash
python3 $PROJECT_ROOT/harness/3ceasuri-import/scripts/candidates.py next \
  $PROJECT_ROOT/harness/3ceasuri-import/.candidates-olx-watches.json
```

Then invoke `olx-import-watch` per id (or `olx-import-smartwatch` for a
`looks_smart` one — route by kind, not by category).

Anything fails → `olx-troubleshooting`.
Why any of this is the way it is: `harness/3ceasuri-import/references/olx-lore.md`.
