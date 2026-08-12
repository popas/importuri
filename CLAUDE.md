# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A **browser-automation runbook**, not a conventional codebase. It reads watch-sale
listings from two marketplaces and imports them into the 3ceasuri.ro Django admin,
one watch at a time. "Running" the project means driving a CDP-controlled Chrome
browser by following the orchestrator and the skill for the current phase. The only
tests are offline stubs: `python3 tests/test_*.py`, no browser, no network.

## Pick your source first

The two sources have separate orchestrators, separate skills and separate scripts.
Do not mix them in one session.

| Source | Orchestrator | What it reads |
|---|---|---|
| Facebook group | `Watch_Listing_Automation_Plan.md` | `vanzareceasuri` feed + posts (DOM scraping, carousels, signed URLs) |
| OLX.ro | `OLX_Listing_Automation_Plan.md` | categories 1943 (smartwatch-uri) and 1677 (moda/ceasuri) via OLX's JSON API |

OLX is the simpler path: its API answers from a page already on olx.ro (a plain GET
is 403), returning structured params and durable photo URLs — no scrolling, no
carousel, no expiry. Facebook needs the whole scraping apparatus.

## Read-order — Facebook (every session)

1. `Watch_Listing_Automation_Plan.md` — the orchestrator (≤60 lines). It defines the
   loop and the 5 iron rules.
2. Invoke ONLY the skill for the phase you are in (Skill tool, `.claude/skills/`):
   - `watch-session-setup` — once per session (defines `$PROJECT_ROOT` / `$CDP_HOST`,
     connects browser-use, opens tabs, reads session state, asks the user for a target)
   - `fb-find-posts` — once per session; runs `find-posts.py` and returns candidates
   - `admin-import-watch` → `import-verify-state` — per watch, in a FRESH context each
     (`/clear` between watches). `import-post.py` runs TWO passes: pass 1 emits the
     extraction contract + photos and writes nothing, you fill it, pass 2 imports with
     `CONFIRM=1 OVERRIDES=…`. `fb-extract-post` is a fallback, not a routine step.
   - `watch-troubleshooting` — only when something fails

## Read-order — OLX (every session)

1. `OLX_Listing_Automation_Plan.md` — the orchestrator.
2. Invoke ONLY the skill for the phase you are in:
   - `olx-session-setup` — once per session (env vars, browser-use, admin + olx.ro
     tabs, session state, target)
   - `olx-find-smartwatches` (category 1943) or `olx-find-watches` (category 1677) —
     once per session; runs the matching discovery script and returns candidates
   - `olx-import-smartwatch` / `olx-import-watch` → `import-verify-state` — per
     watch, in a FRESH context each. Same two passes as Facebook: pass 1 emits the
     extraction contract + photos and writes nothing, you fill it, pass 2 imports
     with `CONFIRM=1 OVERRIDES=…`.
   - `olx-troubleshooting` — only when something fails

Do not load the whole runbook or multiple skills at once — each skill is
self-contained for its phase and points to the next.

## Architecture

```
Watch_Listing_Automation_Plan.md   ← FB orchestrator (the loop + iron rules, nothing else)
OLX_Listing_Automation_Plan.md     ← OLX orchestrator (same shape, different source)
state.json                         ← SESSION bookkeeping only (no cumulative totals)
history.jsonl                      ← append-only local log of every import + skip
.claude/skills/
  watch-session-setup/             ← FB: env vars, browser-use connect, tabs, state, target
  fb-find-posts/                   ← FB: run find-posts.py once/session, triage candidates
  fb-extract-post/                 ← FB: FALLBACK only (listings, script errors, overrides)
  admin-import-watch/              ← FB: run import-post.py; manual form path as fallback
  watch-troubleshooting/           ← FB: failure modes & fallbacks only
  olx-session-setup/               ← OLX: env vars, browser-use connect, tabs, state, target
  olx-find-smartwatches/           ← OLX: category 1943 sweep, triage candidates
  olx-find-watches/                ← OLX: category 1677 sweep, triage candidates
  olx-import-smartwatch/           ← OLX: per-ad import, smart profile
  olx-import-watch/                ← OLX: per-ad import, classic profile
  olx-troubleshooting/             ← OLX: failure modes only
  import-verify-state/             ← BOTH: banner verification, history.jsonl append
harness/                           ← shared assets (NOT skills — no SKILL.md here)
  3ceasuri-import/
    scripts/import-watch.js        ← THE HARNESS (authoritative, v7) — injected into admin
    scripts/admin_import.py        ← the admin half, shared: dedup, brand, inject, verify
    scripts/infer_fields.py        ← the extraction contract: DB enums + prompt + validator,
                                     profiles `classic` / `smart` (NO API call — the agent
                                     in the loop fills it via OVERRIDES)
    scripts/find-posts.py          ← FB: whole-feed discovery in ONE browser-use call
    scripts/import-post.py         ← FB: per-watch flow; TWO passes (contract out, filled back)
    scripts/price_sanity.py        ← BOTH: price floors — suspiciously cheap = fake, dropped
    scripts/olx_api.py             ← OLX: in-page API, param→enum map, photo URLs, phone reveal
    scripts/olx-find-smartwatches.py  ← OLX: category 1943 discovery
    scripts/olx-find-watches.py       ← OLX: category 1677 discovery
    scripts/olx-import-smartwatch.py  ← OLX: per-ad flow, smart profile
    scripts/olx-import-watch.py       ← OLX: per-ad flow, classic profile
    .candidates.json               ← FB discovery output; lets a /clear'd context resume
    .candidates-olx-smart.json     ← OLX 1943 discovery output
    .candidates-olx-watches.json   ← OLX 1677 discovery output
    references/brand-ids.md        ← brand→ID mapping source of truth
    references/feed-dom.md         ← FB discovery DOM lore — read ONLY when find fails
    references/post-extraction.md  ← FB extraction/carousel lore + photo-identification policy
    references/seller-blocklist.json ← sellers never to import (`authors` FB, `olx_sellers` OLX)
    tests/                         ← offline stubs: python3 tests/test_*.py (no browser)
  browser-use/references/          ← historical session logs / deep references
```

Skills live ONLY in `.claude/skills/` (each a `SKILL.md`, invoked with the Skill tool).
`harness/` holds shared data/scripts the skills read — it is not itself a skill.

The six numbered `.py` scripts are **browser-use payloads**: pipe them on stdin
(`POST_ID=… browser-use < import-post.py`, `AD_ID=… browser-use < olx-import-watch.py`),
never `python3 script.py`. They print parseable marker lines (`CANDIDATES: STATS:
EXTRACT: EXTRACT_PROMPT: INFER: REVIEW: RESULT: …`) and keep everything else inside
their own process — that is the whole point, so don't reimplement their steps as
individual `js()` calls. `admin_import.py`, `olx_api.py` and `infer_fields.py` are
plain modules the payloads import; they take the CDP helpers via `bind(globals())`.

Data flows one direction per watch, identically for both sources: **candidate id →
pass 1 (dedup → read the listing → `EXTRACT_PROMPT` + photos, no DB write) → you fill
the contract → pass 2 (`CONFIRM=1 OVERRIDES=…` → validate → inject harness →
`importWatch({...})` → two green banners → readback) → append `history.jsonl`.** A
contract field you omit is cleared, not defaulted — answer it in full.

Provenance is source-agnostic in the DB since 2026-08-09: `source` (`facebook`|`olx`),
`external_listing_id`, `seller_id`, `seller_name` — one set of columns, renamed from
the old `facebook_*` ones. The harness writes through a fallback to the old element
ids, so imports work either side of that deploy.

**Ground truth for "is this imported / how many are there" is the 3ceasuri.ro admin**,
never a local file. The old `state.json` counter drifted to 33 while the site held 80+.

`$PROJECT_ROOT` and `$CDP_HOST` are placeholders defined once in `watch-session-setup`;
all paths and CDP endpoints in skills use them, so there is no environment-specific
path baked into any skill.

## Adding a new brand

Follow the "New brand procedure" in `admin-import-watch` — it keeps `window.BRAND_IDS`
(in the harness) and `references/brand-ids.md` in sync; always update BOTH.
