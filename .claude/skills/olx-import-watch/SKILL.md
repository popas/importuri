---
name: olx-import-watch
description: Invoke PER WATCH to import one OLX classic-watch ad (category 1677) in two passes: seeded contract draft out, edited back, then import.
---

# olx-import-watch

Imports ONE OLX classic-watch ad. `$PROJECT_ROOT` / `$CDP_HOST` come from
`olx-session-setup`; the id comes from `candidates.py next`.

```bash
CAND=$PROJECT_ROOT/harness/3ceasuri-import/.candidates-olx-watches.json
SCRIPT=$PROJECT_ROOT/harness/3ceasuri-import/scripts/olx-import-watch.py
export BU_CDP_URL="http://$CDP_HOST"
```

## 1. Pass 1 — the contract draft (writes NOTHING)

```bash
AD_ID=<id> CANDIDATES_FILE=$CAND browser-use < $SCRIPT
```

Emits:

```
EXTRACT: {ad_id, title, images, chars, seller_id, seller_name, business, city}
EXTRACT_PROMPT: {ad_id, draft, todo, prompt, photos:[paths], photos_failed, phone_status, rerun}
```

`draft` is a JSON file holding the **whole contract, already filled in** from the
OLX params: brand, price, condition, materials, the cleaned description, the phone,
the location. You never retype any of it.

## 2. Fill only `todo`

Read the `prompt` and **exactly one photo** from `photos`. Open a second only when
you need the caseback for a `reference`.

Edit the `draft` file in place. Change only the fields named in `todo`. Save.

| Field | Rule |
|---|---|
| `model` | the model NAME only. Short, no brand, never a sentence, never a filler noun ("Original", "Ceas", "Dama"). The ad naming no model is the normal case — the dial answers it. |
| `movement` | judge it from the ad and the photos. If nothing states or shows it, leave it null: the gate will stop the watch, and that is correct. |
| `reference` | only from text you can READ on a photo or in the ad. **Never derive one from the design.** Null is fine. |
| `is_wristwatch` | `false` for a wall clock, pocket, mantel, table or alarm clock |
| `category` | `"wall"` for a wall clock — that plus `is_wristwatch: false` is an IMPORT, not a skip. Unbranded → brand `Fără marcă`, `caseMat` usually `wood`, `diameter` in MILLIMETRES (30 cm = `300`). |
| `is_bulk_lot` | `true` if one price covers several watches |
| `notes` | our own classification, if the photos identified a model the seller did not name. Leave `description` as the seller wrote it. |

**A field you blank is CLEARED.** The draft removes the retyping, not the clearing.
Leave alone anything not in `todo`.

If `phone_status` is `login_required`, sign in to olx.ro and re-run pass 1. Every
other value (`ok`, `no_button`, `not_revealed`) is fine — a missing phone never
fails an import.

## 3. Pass 2 — import

```bash
AD_ID=<id> CANDIDATES_FILE=$CAND CONFIRM=1 browser-use < $SCRIPT
```

Validate → repost dedup → ensure brand → inject harness → `importWatch()` → both
banners → readback → `RESULT:`.

`OVERRIDES='{…}'` still works and wins over the draft — it is for a human patching
one field from the shell, not for you.

## 4. If `REVIEW:` fires

Each reason is `{code, action, message, field}`. **You never override a gate.**

| `action` | What you do |
|---|---|
| `fix` | put the field named in `field` into the draft, re-run step 3. ONCE. Still gated → treat as `skip`. |
| `skip` | the candidate is already marked in the queue. Log it (step 5) and take the next id. |

`CONFIRM=1` is not a skeleton key: it is in the command because the draft is the
answer, and it cannot wave through a gate you did not satisfy, a suspiciously cheap
listing, or a missing brand/model/price.

`movement` null → `movement_missing` (`skip`). That is deliberate: the harness would
otherwise write `quartz`, which mislabelled a 1970s Poljot.
`movement: "smart"` → `misrouted_smart` (`skip`) — that ad belongs to
`olx-import-smartwatch`.

## 5. Log the outcome

Pipe the pass-2 output through the logger:

```bash
AD_ID=<id> CANDIDATES_FILE=$CAND CONFIRM=1 browser-use < $SCRIPT \
  | tee /dev/stderr \
  | python3 $PROJECT_ROOT/harness/3ceasuri-import/scripts/olx-log-result.py
```

It appends to `history.jsonl` and bumps `state.json`. An unverified `RESULT:` logs
nothing, by design.

## New brand procedure

On `NEW_BRAND:`, update **both** and commit:

1. `harness/3ceasuri-import/scripts/import-watch.js` → add `"Name":<id>` to `window.BRAND_IDS`
2. `harness/3ceasuri-import/references/brand-ids.md` → add the same row

## Next

`candidates.py next` for the following id. Anything fails → `olx-troubleshooting`.
Why any of this is the way it is: `harness/3ceasuri-import/references/olx-lore.md`.
