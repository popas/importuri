---
name: olx-import-smartwatch
description: Invoke PER WATCH to import one OLX smartwatch ad (category 1943) in two passes: seeded contract draft out, edited back, then import.
---

# olx-import-smartwatch

Imports ONE OLX smartwatch ad. `$PROJECT_ROOT` / `$CDP_HOST` come from
`olx-session-setup`; the id comes from `candidates.py next`.

```bash
CAND=$PROJECT_ROOT/harness/3ceasuri-import/.candidates-olx-smart.json
SCRIPT=$PROJECT_ROOT/harness/3ceasuri-import/scripts/olx-import-smartwatch.py
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

`movement`, `style`, `displayType` and `category` are **not** yours to decide here —
the category already answered them (`smart`/`smart`/`smart`/`wrist`). They are not
in `todo`.

## 2. Fill only `todo`

Read the `prompt` and **exactly one photo** from `photos`.

Edit the `draft` file in place. Change only the fields named in `todo`. Save.

| Field | Rule |
|---|---|
| `model` | the model NAME only. Short, no brand, never a sentence. Ads routinely inflate the generation — the photo settles it, not the title. |
| `connectivity` | `gsm` (has its own SIM/eSIM) or `no_gsm`. Required. |
| `compatibility` | `ios`, `android` or `both`. Required. |
| `is_wristwatch` | `false` only for an accessory (strap, charger, case, dock, empty box) — that is a skip |
| `is_bulk_lot` | `true` if one price covers several watches |
| `notes` | our own classification, if the photos identified a model the seller did not name. Leave `description` as the seller wrote it. |

There is **no `series` field.** `infer_fields.validate()` rejects any key outside
the contract, which is a hard `ERROR` in pass 2. The generation belongs in `model`.

**A field you blank is CLEARED.** The draft removes the retyping, not the clearing.
Leave alone anything not in `todo`.

If `phone_status` is `login_required`, sign in to olx.ro and re-run pass 1. Every
other value is fine — a missing phone never fails an import.

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

A draft that sets `movement` to anything but `smart` raises `misrouted_classic`
(`skip`) — that ad belongs to `olx-import-watch`.

## 5. Log the outcome

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
