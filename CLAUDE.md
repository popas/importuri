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

## Read-order (every session)

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
  scripts/import-watch.js          ← THE HARNESS (authoritative, v7) — injected into admin
  scripts/olx_import.py            ← THE per-ad flow, both profiles (the two importer
                                     payloads are wrappers that pick one)
  scripts/admin_import.py          ← the admin half: dedup, brand, inject, submit, verify
  scripts/infer_fields.py          ← the extraction contract: DB enums + prompt + validator,
                                     profiles `classic` / `smart` (NO API call — the agent
                                     in the loop fills it)
  scripts/contract_draft.py        ← the seeded contract draft: build / write / read, _todo
  scripts/candidates.py            ← the work queue (python3, NOT a browser payload)
  scripts/olx-log-result.py        ← history.jsonl + state.json (python3, NOT a payload)
  scripts/olx_api.py               ← in-page API, param→enum map, photo URLs, phone reveal
  scripts/price_sanity.py          ← price floors — suspiciously cheap = fake, dropped
  scripts/olx-find-smartwatches.py ← category 1943 discovery
  scripts/olx-find-watches.py      ← category 1677 discovery
  scripts/olx-import-smartwatch.py ← wrapper: olx_import.run("smart", globals())
  scripts/olx-import-watch.py      ← wrapper: olx_import.run("classic", globals())
  .contracts/olx-<id>.json         ← the per-ad contract draft (gitignored)
  .candidates-olx-smart.json       ← 1943 discovery output; the work queue
  .candidates-olx-watches.json     ← 1677 discovery output; the work queue
  references/brand-ids.md          ← brand→ID mapping source of truth
  references/olx-lore.md           ← why the rules are the rules; read when troubleshooting
  references/seller-blocklist.json ← never-import sellers (`olx_sellers`; `authors` = FB)
  references/django-backend.md     ← where the Django app lives and what it expects
  tests/                           ← offline stubs: python3 tests/test_*.py (no browser)
archive/facebook/                  ← the archived FB source (see its README)
docs/superpowers/specs/            ← design docs; read the two newest before changing the flow
```

Skills live ONLY in `.claude/skills/` (each a `SKILL.md`). `harness/` holds the scripts
and data they read — it is not itself a skill.

The four hyphenated `olx-find-*.py` / `olx-import-*.py` scripts are **browser-use
payloads**: pipe them on stdin (`AD_ID=… browser-use < olx-import-watch.py`), never
`python3 script.py`. They print parseable marker lines (`CANDIDATES: STATS: EXTRACT:
EXTRACT_PROMPT: INFER: REVIEW: RESULT: WARN: …`) and keep everything else inside their
own process — that is the whole point, so don't reimplement their steps as individual
`js()` calls. `olx_import.py`, `admin_import.py`, `olx_api.py`, `infer_fields.py` and
`contract_draft.py` are plain modules the payloads import; they take the CDP helpers
via `bind(globals())` or, for `olx_import.run(profile, globals())`, straight from the
globals dict.

**Two scripts are the exception and ARE run with `python3`**: `candidates.py` (the work
queue) and `olx-log-result.py` (history + counters). Neither touches a browser.

Data flows one direction per watch: **`candidates.py next` → pass 1 (dedup → read the
ad → seeded draft + `EXTRACT_PROMPT` + photos, no DB write) → you edit the draft's
`_todo` fields → pass 2 (`CONFIRM=1` → read draft → validate → inject harness →
`importWatch({...})` → two green banners → readback) → `olx-log-result.py`.** A
contract field you blank is cleared, not defaulted — the draft removes the retyping,
not the clearing rule. `OVERRIDES='{…}'` still works and still wins, for a human
patching one field from the shell.

**Never override a `REVIEW:` gate.** Each reason carries `{code, action, message,
field}`: `action: fix` means supply the named field and re-run pass 2 once,
`action: skip` means log the code and take the next id.

## Facts that bite

- **Ground truth for "is this imported / how many are there" is the 3ceasuri.ro admin**,
  never a local file. The old `state.json` counter drifted to 33 while the site held 80+.
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
- The Django app is a **separate repo**: `~/projects/anunturi/ceasuri`. See
  `references/django-backend.md`.

## Adding a new brand

Follow the "New brand procedure" in `olx-import-watch` / `olx-import-smartwatch` — it
keeps `window.BRAND_IDS` (in `import-watch.js`) and `references/brand-ids.md` in sync;
always update BOTH, then commit.
