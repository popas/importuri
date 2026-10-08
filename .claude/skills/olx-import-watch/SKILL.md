---
name: olx-import-watch
description: Invoke PER WATCH to import one OLX classic-watch ad (category 1677) in two passes: seeded contract draft out, edited back, then import.
---

# olx-import-watch

**The loop now runs through `scripts/olx-step.py`** (Prompt B in
`OLX_IMPORT_SESSION_PROMPT.md`): it runs both passes, prints each open field with its
rule, logs the outcome and enforces fix-once. This skill is the reference for WHY the
fields are decided the way they are, and for running a pass by hand.

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
| `model` | the model LINE only. Short, no brand, never a sentence, never a filler noun ("Original", "Ceas", "Dama"). One of the brand's models on the site (the prompt lists them) whenever it is this watch's line, spelled exactly. The ad naming no model is the normal case — the dial answers it. |
| `variant` | what sets this watch apart from others of its model: complication, dial, edition, nickname ("Chronograph Panda", "41 Wimbledon", "Pepsi Jubilee"). Never the size, condition, reference or year. Null when there is nothing. |
| `new_model` | only after an `unknown_model` fix, and only for a line the brand really makes that the site lacks: `true` makes pass 2 add it first. |
| `movement` | judge it from the ad and the photos. If nothing states or shows it, leave it null: the gate will stop the watch, and that is correct. |
| `reference` | only from text you can READ on a photo or in the ad. **Never derive one from the design.** Null is fine. |
| `is_wristwatch` | `false` for a pocket watch, wall, mantel, table or alarm clock |
| `category` | `"pocket"` for a pocket watch — that plus `is_wristwatch: false` is an IMPORT, not a skip. `braceletMat` null (a chain is not a bracelet), `diameter` in MILLIMETRES. Wall, mantel, table and alarm clocks keep `category` null and skip. |
| `is_bulk_lot` | `true` if one price covers several watches |
| `notes` | our own classification, if the photos identified a model the seller did not name. |
| `description` | **the seller's own text, lightly corrected** (user directive 2026-10-04) — it must read as if the author wrote it and still look like the OLX ad. The draft holds their text: keep their sentences, order, person and facts (defects included); fix only diacritics, typos, punctuation, ALL CAPS; drop price, negotiation, shipping/meeting terms, phone, links, contact, sign-offs and copied filler. Add nothing but a brand/model they left out, inside their own sentence — no description of the photos. **Never** write about the seller, the ad or the photos ("vânzătorul precizează", "fotografiile prezintă"), even when the seller did. Gates, all `fix`: `description_unedited` (handed back untouched), `description_meta`, `description_drifted` (mostly not their words). Phone numbers are stripped by the script anyway. |

**A field you blank is CLEARED.** The draft removes the retyping, not the clearing.
Leave alone anything not in `todo`.

If `phone_status` is `login_required`, sign in to olx.ro and re-run pass 1. Every
other value (`ok`, `no_button`, `not_revealed`) is fine — a missing phone never
fails an import.

## 3. Pass 2 — import

```bash
AD_ID=<id> CANDIDATES_FILE=$CAND CONFIRM=1 browser-use < $SCRIPT
```

Validate → repost dedup → one `import-json` POST when the admin's JSON endpoints are
deployed, else ensure brand → inject harness → `importWatch()` → both banners →
readback; the same `RESULT:` either way.

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
listing, or a missing brand/model/price. The one gate it still waives is
`weak_repost` (a model-name match from another seller), which pass 2 lets through.
A brand not yet in `BRAND_IDS` is not a gate: it imports and emits `NEW_BRAND:`.

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
