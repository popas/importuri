---
name: olx-import-watch
description: Invoke PER WATCH to import one OLX classic-watch ad (category 1677) in two passes: contract out, filled back, then import.
---

# olx-import-watch

Imports ONE OLX classic-watch ad into the 3ceasuri admin. `$PROJECT_ROOT` /
`$CDP_HOST` come from `olx-session-setup`; the ad id comes from
`.candidates-olx-watches.json`.

## Two passes, because YOU do the inference

OLX's structured params answer condition, case material, gender, style and price
outright. What they never answer is **which watch this is** — the model, the
movement, the reference. That is pass 1's job to ask you.

### Pass 1 — the contract (writes NOTHING)

```bash
export BU_CDP_URL="http://$CDP_HOST"
AD_ID=<id> browser-use < $PROJECT_ROOT/harness/3ceasuri-import/scripts/olx-import-watch.py
```

It dedups on the ad id, reads `/api/v1/offers/<id>/`, checks the blocklist, maps
the OLX params, downloads the photos to
`$PROJECT_ROOT/harness/3ceasuri-import/.photos/olx-<id>/`, and emits:

```
EXTRACT: {ad_id, title, images, chars, seller_id, seller_name, business, city}
EXTRACT_PROMPT: {ad_id, prompt, photos:[paths], photos_failed, rerun}
```

**Read the prompt AND at least one photo.** The ad naming no model at all is the
normal case, not the exception — the dial answers it. Open a second photo only when
you need the caseback for a reference.

### Pass 2 — import

```bash
AD_ID=<id> CONFIRM=1 OVERRIDES='{…the filled contract…}' \
  browser-use < $PROJECT_ROOT/harness/3ceasuri-import/scripts/olx-import-watch.py
```

Validate → repost dedup → ensure brand → inject harness → `importWatch()` → both
green banners → readback → `RESULT:`.

## The contract is authoritative, including about silence

A contract field you leave out is **CLEARED**, not kept from the OLX params. The
prompt shows you what OLX already answered under "Known from OLX" — restate those
values in your answer. Answer in full, every time.

An `is_wristwatch` key in `OVERRIDES` is what marks the answer as a full contract;
a targeted fix without it still merges over the baseline.

## Classic-watch rules worth repeating

- `model` — the model NAME only, short, no brand, never a sentence. Never a filler
  noun ("Original", "Ceas", "Dama"). If the photos identify a model the seller did
  not name, that is OUR classification: put it in `model`, say so in `notes`, and
  leave `description` as the seller wrote it.
- `reference` — the COMPLETE reference, only from text you can actually READ.
  **Never derive one from the design.**
- `movement` — infer it, don't just copy it, and never let it default. An ad that
  never states a movement stops for review; the harness would otherwise write
  `quartz` (that mislabelled a 1970s Poljot once already).
- **Wall clocks import.** `is_wristwatch: false` **plus** `category: "wall"` is an
  import, not a skip. Unbranded ones use brand `Fără marcă`, `caseMat` is usually
  `wood`, and `diameter` is in MILLIMETRES (a 30 cm clock is `300`). Pocket, mantel,
  table and alarm clocks are still out: `is_wristwatch: false` with `category` null.
- `movement: "smart"` stops for review — that ad belongs to
  `olx-import-smartwatch.py`, which fills the three smartwatch facets.

## Seller phone numbers

Pass 1 reveals the seller's phone and reports `phone_status`. OLX masks the number
in its JSON and answers `/api/v1/offers/<id>/phones/` with 400, so the importer
clicks the page's show-phone button — the one place it reads the ad's HTML rather
than its JSON.

**Log into olx.ro before the session** (see `olx-session-setup`). Signed in, both
private and business sellers give up their number; signed out, private ads show a
login wall instead.

| `phone_status` | meaning |
|---|---|
| `ok` | number captured — it appears in the "Known from OLX" block |
| `login_required` | not signed in to olx.ro; sign in and re-run pass 1 |
| `no_button` | the seller published no number (`contact.phone: false`), chat only — normal, not a failure |
| `not_revealed` | the click missed; see `olx-troubleshooting` |

A missing phone never fails an import — a watch with no number is imported exactly like any other. When a number does come back, restate it in
your answer like any other contract field — and if you leave it out, pass 2
re-reveals it rather than clearing it, since a phone is marketplace metadata and
not a claim in the ad text.

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

## Review gate

`REVIEW:` fires and nothing is written when: the brand is new, the model/price/
movement did not infer, a wall clock has no case material, fewer than 2 photos, or
the description is thin. Fix what it flagged and re-run with `CONFIRM=1`.

`CONFIRM=1` passes the review and skip gates; it cannot wave through a missing
brand/model/price — the form would reject those.

## New brand procedure

When `NEW_BRAND:` appears, update **both** and commit:

1. `harness/3ceasuri-import/scripts/import-watch.js` → add `"Name":<id>` to `window.BRAND_IDS`
2. `harness/3ceasuri-import/references/brand-ids.md` → add the same row

## Then

Invoke `import-verify-state`, then `/clear` and take the next id.

When anything fails → `olx-troubleshooting`.
