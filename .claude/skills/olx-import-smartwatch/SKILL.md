---
name: olx-import-smartwatch
description: Invoke per smartwatch to import ONE OLX ad from category 1943 — pass 1 emits the extraction contract and photos, you fill it, pass 2 imports with CONFIRM=1 OVERRIDES. Use a fresh context per watch.
---

# olx-import-smartwatch

Imports ONE OLX smartwatch ad into the 3ceasuri admin. `$PROJECT_ROOT` / `$CDP_HOST`
come from `olx-session-setup`; the ad id comes from `.candidates-olx-smart.json`.

## Two passes, because YOU do the inference

OLX's structured params answer condition, gender, style and price outright. What
they never answer is **which watch this is** — the model, the generation, whether
it is the cellular variant. That is pass 1's job to ask you.

### Pass 1 — the contract (writes NOTHING)

```bash
export BU_CDP_URL="http://$CDP_HOST"
AD_ID=<id> browser-use < $PROJECT_ROOT/harness/3ceasuri-import/scripts/olx-import-smartwatch.py
```

It dedups on the ad id, reads `/api/v1/offers/<id>/`, checks the blocklist, maps
the OLX params, downloads the photos to
`$PROJECT_ROOT/harness/3ceasuri-import/.photos/olx-<id>/`, and emits:

```
EXTRACT: {ad_id, title, images, chars, seller_id, seller_name, business, city}
EXTRACT_PROMPT: {ad_id, prompt, photos:[paths], photos_failed, rerun}
```

**Read the prompt AND at least one photo.** The dial and the crown answer the model
and the cellular question far more often than the ad text does. Read a second photo
only when you need the back or a box label.

### Pass 2 — import

```bash
AD_ID=<id> CONFIRM=1 OVERRIDES='{…the filled contract…}' \
  browser-use < $PROJECT_ROOT/harness/3ceasuri-import/scripts/olx-import-smartwatch.py
```

Validate → repost dedup → ensure brand → inject harness → `importWatch()` → both
green banners → readback → `RESULT:`.

## The contract is authoritative, including about silence

A contract field you leave out is **CLEARED**, not kept from the OLX params. The
prompt shows you what OLX already answered under "Known from OLX" — restate those
values in your answer. Answer in full, every time.

An `is_wristwatch` key in `OVERRIDES` is what marks the answer as a full contract;
a targeted fix without it still merges over the baseline.

## Smartwatch-specific rules

- `movement`, `style` and `displayType` are always `smart` — the script forces them
  so the harness can never default `movement` to quartz. An answer that says
  `automatic` is treated as a **routing mistake** and stops: that ad belongs to
  `olx-import-watch.py`.
- `series`, `connectivity` and `compatibility` are required. Missing any of the
  three stops for review. Apple Watch → `ios`; Galaxy Watch 4+ → `android`; Garmin,
  Amazfit, Huawei, Xiaomi, Fitbit → `both`. Cellular models: "LTE"/"Cellular"/"4G"/
  "eSIM" in the ad, or the red ring/dot on an Apple Watch crown.
- `is_wristwatch: false` means **accessory** here (strap, charger, case, dock, empty
  box) and skips the import. Say which in `notes`.
- Most smartwatch brands are NOT in `BRAND_IDS` yet, so `NEW_BRAND:` is the normal
  case. Follow the new-brand procedure below every time it fires.

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

A missing phone never fails an import. When a number does come back, restate it in
your answer like any other contract field — and if you leave it out, pass 2
re-reveals it rather than clearing it, since a phone is marketplace metadata and
not a claim in the ad text.

## Review gate

`REVIEW:` fires and nothing is written when: the brand is new, the model or price
did not infer, any of the three smart facets is missing, fewer than 2 photos, or the
description is thin. Fix what it flagged and re-run with `CONFIRM=1`.

`CONFIRM=1` passes the review and skip gates; it cannot wave through a missing
brand/model/price — the form would reject those.

## New brand procedure

When `NEW_BRAND:` appears, the brand was created in (or found in) the DB, but the
local map is now stale. Update **both**, then commit:

1. `harness/3ceasuri-import/scripts/import-watch.js` → add `"Name":<id>` to `window.BRAND_IDS`
2. `harness/3ceasuri-import/references/brand-ids.md` → add the same row

## Then

Invoke `import-verify-state`, then `/clear` and take the next id.

When anything fails → `olx-troubleshooting`.
