# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

## What this project is

A **browser-automation runbook**, not a conventional codebase. It reads watch-sale ads
from OLX.ro and imports them into the 3ceasuri.ro Django admin, one watch at a time.
"Running" the project means driving a CDP-controlled Chrome by following the
orchestrator and the skill for the current phase. The only tests are offline stubs:
`python3 harness/3ceasuri-import/tests/test_*.py` — no browser, no network.

**Facebook was a second source and is archived** (2026-09-19). It is parked, not broken:
`archive/facebook/README.md` says what moved and how to bring it back. Do not read it
unless you are reactivating that source.

## Import loop: use the driver, skip the read-order

For importing from a queue that has pending ids, follow **Prompt B in
`OLX_IMPORT_SESSION_PROMPT.md`** and nothing else: `scripts/olx-step.py` does
setup, both passes, logging, routing and verification, and prints the literal next
command. It replaces `olx-session-setup`, the two importer skills and
`import-verify-state` for that loop — do not load them. The read-order below is for
discovery, troubleshooting and changing the harness.

## Read-order (discovery / troubleshooting / harness work)

1. `OLX_Listing_Automation_Plan.md` — the orchestrator (≤60 lines): the loop and the
   iron rules.
2. Invoke ONLY the skill for the phase you are in (Skill tool, `.claude/skills/`):
   - `olx-session-setup` — once per session (defines `$PROJECT_ROOT` / `$CDP_HOST`,
     connects browser-use, opens the admin + olx.ro tabs, reads session state, asks
     for a target)
   - `olx-find-smartwatches` (category 1943) or `olx-find-watches` (category 1677) —
     once per session; runs the matching discovery script and returns candidates
   - `olx-import-smartwatch` / `olx-import-watch` → `import-verify-state` — per watch.
     Both importers run TWO passes: pass 1 seeds a complete contract draft on disk
     and writes nothing, you edit only the fields it lists in `_todo`, pass 2 reads
     the draft with `CONFIRM=1`. The candidates file is a work queue, so a fresh
     session resumes from it rather than from memory.
   - `olx-troubleshooting` — only when something fails

Do not load multiple skills at once — each is self-contained for its phase and points
to the next.

## Architecture

```
OLX_Listing_Automation_Plan.md     ← orchestrator (the loop + iron rules, nothing else)
state.json                         ← SESSION bookkeeping only (no cumulative totals)
history.jsonl                      ← append-only local log of every import + skip
.claude/skills/                    ← one per phase, invoked with the Skill tool
harness/3ceasuri-import/
  scripts/import-watch.js          ← THE HARNESS (authoritative, v8) — injected into admin
  scripts/olx_import.py            ← THE per-ad flow, both profiles (the two importer
                                     payloads are wrappers that pick one)
  scripts/admin_import.py          ← the admin half: dedup, brand, inject, submit, verify
  scripts/site_api.py              ← the admin's JSON endpoints: lookups + import-json, and
                                     the one probe that says whether they are deployed
  scripts/infer_fields.py          ← the extraction contract: DB enums + prompt + validator,
                                     profiles `classic` / `smart` (NO API call — the agent
                                     in the loop fills it)
  scripts/contract_draft.py        ← the seeded contract draft: build / write / read, _todo
  scripts/candidates.py            ← the work queue (python3, NOT a browser payload)
  scripts/olx-log-result.py        ← history.jsonl + state.json (python3, NOT a payload)
  scripts/olx-step.py              ← THE LOOP DRIVER: start/next/finish/skip/stop
                                     (python3, NOT a payload; it runs the payloads)
  scripts/olx_api.py               ← in-page API, param→enum map, photo URLs, phone reveal
  scripts/price_sanity.py          ← price floors — suspiciously cheap = fake, dropped
  scripts/photo_dedup.py           ← byte-identical photos of an imported ad = a relist,
                                     skipped in pass 1 (`duplicate_photos`); the site's
                                     import-json refuses one too (409, every listing).
                                     Also finds the shop cards (`shop_cards`)
  scripts/olx-find-smartwatches.py ← category 1943 discovery
  scripts/olx-find-watches.py      ← category 1677 discovery
  scripts/olx-import-smartwatch.py ← wrapper: olx_import.run("smart", globals())
  scripts/olx-import-watch.py      ← wrapper: olx_import.run("classic", globals())
  scripts/olx-check-active.py      ← which active OLX listings are gone from OLX; APPLY=1
                                     ends them (wrapper: active_check.run(globals()))
  scripts/active_check.py          ← the gone-listing sweep: list, classify, deactivate
  .contracts/olx-<id>.json         ← the per-ad contract draft (gitignored)
  .runs/                           ← olx-step.py: raw payload logs + run state (gitignored)
  .candidates-olx-smart.json       ← 1943 discovery output; the work queue
  .candidates-olx-watches.json     ← 1677 discovery output; the work queue
  references/brand-ids.md          ← brand→ID mapping source of truth
  references/olx-lore.md           ← why the rules are the rules; read when troubleshooting
  references/seller-blocklist.json ← never-import sellers (`olx_sellers`; `authors` = FB)
  references/shop-cards.json       ← never-import PHOTOS: shop cards, learned; commit it
  references/django-backend.md     ← where the Django app lives and what it expects
  tests/                           ← offline stubs: python3 tests/test_*.py (no browser)
archive/facebook/                  ← the archived FB source (see its README)
docs/superpowers/specs/            ← design docs; read the two newest before changing the flow
```

Skills live ONLY in `.claude/skills/` (each a `SKILL.md`). `harness/` holds the scripts
and data they read — it is not itself a skill.

The hyphenated `olx-find-*.py` / `olx-import-*.py` / `olx-check-active.py` scripts are **browser-use
payloads**: pipe them on stdin (`AD_ID=… browser-use < olx-import-watch.py`), never
`python3 script.py`. They print parseable marker lines (`CANDIDATES: STATS: EXTRACT:
EXTRACT_PROMPT: INFER: REVIEW: RESULT: WARN: …`) and keep everything else inside their
own process — that is the whole point, so don't reimplement their steps as individual
`js()` calls. `olx_import.py`, `admin_import.py`, `olx_api.py`, `infer_fields.py` and
`contract_draft.py` are plain modules the payloads import; they take the CDP helpers
via `bind(globals())` or, for `olx_import.run(profile, globals())`, straight from the
globals dict.

**Three scripts are the exception and ARE run with `python3`**: `candidates.py` (the
work queue), `olx-log-result.py` (history + counters) and `olx-step.py` (the loop
driver — it pipes the payloads into browser-use for you).

Data flows one direction per watch: **`candidates.py next` → pass 1 (dedup → read the
ad → seeded draft + `EXTRACT_PROMPT` + photos, no DB write) → you edit the draft's
`_todo` fields, `description` always among them → pass 2 (`CONFIRM=1` → read draft →
validate → `import-json` when the admin's JSON endpoints are deployed, else the DOM
harness: inject → `importWatch({...})` → two green banners → readback) →
`olx-log-result.py`.** A
contract field you blank is cleared, not defaulted — the draft removes the retyping,
not the clearing rule. `OVERRIDES='{…}'` still works and still wins, for a human
patching one field from the shell.

**Never override a `REVIEW:` gate.** Each reason carries `{code, action, message,
field}`: `action: fix` means supply the named field and re-run pass 2 once,
`action: skip` means log the code and take the next id.

## Facts that bite

- **Ground truth for "is this imported / how many are there" is the 3ceasuri.ro admin**,
  never a local file. The old `state.json` counter drifted to 33 while the site held 80+.
- **A days-old seller account asking a lot is a scam** (user directive 2026-09-22):
  under 30 days old and >= 1000 RON is a hard skip in pass 1 (`new_seller_expensive`,
  `price_sanity.new_seller_risk`). Only a human's `ALLOW_NEW_SELLER=1` overrides it.
- **"Alt brand" is never a stored brand** (user directive 2026-09-22). An item with no
  maker mark is stored as `Fără marcă` (id 54); the importer rewrites a final answer of
  "Alt brand" to it. OLX's own "Alt brand" dropdown label means "a brand OLX does not
  list", NOT "unbranded" — read the real maker off the dial/caseback/box first.
- **The listing description is the seller's text, lightly corrected** (user directive
  2026-10-04, replacing the 2026-10-03 "rewrite it as descriptively as possible"): it
  must read as if the author wrote it and still look like the OLX ad. Fix diacritics,
  typos, punctuation; drop price, contact, shipping, sign-offs; add nothing but a
  missing brand/model. Never a word about the seller, the ad or the photos
  ("vânzătorul precizează", "fotografiile prezintă") — those listings are what this
  rule ended. Gates, all `fix`: `description_unedited`, `description_meta`,
  `description_drifted` (`olx_import.py`); `olx_api.strip_phones` scrubs phone numbers.
- **About 40% of the site's "active" OLX listings are gone from OLX** (measured
  2026-10-04: 30 of 72 sampled answered 410/404; none had ever been deactivated).
  `olx-check-active.py` finds them; ending them needs the `deactivate/` endpoint from
  `docs/handover/2026-10-04-deactivate-gone-olx-listings.md`. A missing admin endpoint
  answers **200 + a redirect to /admin/**, not 404 — test for JSON, not for the status.
- **The admin's JSON endpoints are detected, never assumed** (`scripts/site_api.py`,
  endpoint list in `references/django-backend.md`): deployed ⇔ the answer is JSON and
  not redirected — never "not 404". A redirect to `/admin/login/` is a lost session
  (an ERROR), not "not deployed". `API=off` is the kill switch back to the DOM
  harness; a POST to import-json never falls back to it (the server may have saved).
- **A shop's cards are never imported** (user directive 2026-10-07): logo cards,
  storefront and shop-interior photos, "why buy from us" panels, catalogue box shots —
  ads for another business, sometimes with its phone number. `photo_dedup.shop_cards`
  drops them in BOTH passes, before anything counts or compares photos: a file is a card
  when it is in `references/shop-cards.json`, or when it sits beside two different
  watches (each ad has ≥ 2 photos the other lacks). Learned cards are written to the
  list — commit it, the other machine reads it. A real watch photo in the list: delete
  its entry. Photo N of an ad stays `NN.jpg`; the kept ones travel with their numbers.
- **Never import a suspiciously cheap listing.** Below the floors in
  `scripts/price_sanity.py` a watch is a fake, not a bargain. `CONFIRM=1` does not wave
  one through.
- **OLX answers a plain GET with 403.** Every OLX read is a `fetch()` from a page already
  on `www.olx.ro` — that is why these scripts need a browser at all.
- Provenance is source-agnostic since 2026-08-09: `source` (`facebook`|`olx`),
  `external_listing_id`, `seller_id`, `seller_name`. The harness writes through a
  fallback to the old `facebook_*` element ids, so imports work either side of that deploy.
- `$PROJECT_ROOT` and `$CDP_HOST` are placeholders defined once in `olx-session-setup`;
  every skill uses them, so no environment-specific path is baked into any skill.
- The Django app is a **separate repo**: `../ceasuri` (the sibling checkout of `github.com:popas/ceasuri`; named `../app` on the Linux machine). See
  `references/django-backend.md`.

## Adding a new brand

Follow the "New brand procedure" in `olx-import-watch` / `olx-import-smartwatch` — it
keeps `window.BRAND_IDS` (in `import-watch.js`) and `references/brand-ids.md` in sync;
always update BOTH, then commit.
