# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A **browser-automation runbook**, not a conventional codebase. It scrapes watch-sale
posts from a Facebook group and imports them into the 3ceasuri.ro Django admin, one
watch at a time. There is no build, test, or lint step. "Running" the project means
driving a CDP-controlled Chrome browser by following the orchestrator and the skill
for the current phase.

## Read-order (every session)

1. `Watch_Listing_Automation_Plan.md` — the orchestrator (≤60 lines). It defines the
   loop and the 5 iron rules.
2. Invoke ONLY the skill for the phase you are in (Skill tool, `.claude/skills/`):
   - `watch-session-setup` — once per session (defines `$PROJECT_ROOT` / `$CDP_HOST`,
     connects browser-use, opens tabs, reads session state, asks the user for a target)
   - `fb-find-posts` — once per session; runs `find-posts.py` and returns candidates
   - `admin-import-watch` → `import-verify-state` — per watch, in a FRESH context each
     (`/clear` between watches; `import-post.py` does dedup+extract+import+verify in
     one call). `fb-extract-post` is now a fallback, not a routine step.
   - `watch-troubleshooting` — only when something fails

Do not load the whole runbook or multiple skills at once — each skill is
self-contained for its phase and points to the next.

## Architecture

```
Watch_Listing_Automation_Plan.md   ← orchestrator (the loop + iron rules, nothing else)
state.json                         ← SESSION bookkeeping only (no cumulative totals)
history.jsonl                      ← append-only local log of every import + skip
.claude/skills/
  watch-session-setup/             ← env vars, browser-use connect, tabs, state, target
  fb-find-posts/                   ← run find-posts.py once/session, triage candidates
  fb-extract-post/                 ← FALLBACK only (listings, script errors, overrides)
  admin-import-watch/              ← run import-post.py; manual form path as fallback
  import-verify-state/             ← banner verification, history.jsonl append
  watch-troubleshooting/           ← failure modes & fallbacks only
harness/                           ← shared assets (NOT skills — no SKILL.md here)
  3ceasuri-import/
    scripts/import-watch.js        ← THE HARNESS (authoritative, v5) — injected into admin
    scripts/find-posts.py          ← whole-feed discovery in ONE browser-use call
    scripts/import-post.py         ← whole per-watch flow in ONE browser-use call
    scripts/infer_fields.py        ← ONE structured LLM call: post text + DB schema → filled record
                                     (needs ANTHROPIC_API_KEY; falls back to regex without it)
    .candidates.json               ← discovery output; lets a /clear'd context resume
    references/brand-ids.md        ← brand→ID mapping source of truth
    references/feed-dom.md         ← discovery DOM lore — read ONLY when find fails
    references/post-extraction.md  ← extraction/carousel lore — read ONLY when import fails
    references/seller-blocklist.json ← authors never to import
    tests/                         ← offline stubs: python3 tests/test_*.py (no browser)
  browser-use/references/          ← historical session logs / deep references
```

Skills live ONLY in `.claude/skills/` (each a `SKILL.md`, invoked with the Skill tool).
`harness/` holds shared data/scripts the skills read — it is not itself a skill.

The two `.py` scripts are **browser-use payloads**: pipe them on stdin
(`POST_ID=… browser-use < import-post.py`), never `python3 script.py`. They print
parseable marker lines (`CANDIDATES: STATS: EXTRACT: INFER: REVIEW: RESULT: …`) and keep
everything else inside their own process — that is the whole point, so don't reimplement
their steps as individual `js()` calls.

Data flows one direction per watch: **candidate id → import-post.py (dedup → extract →
infer → inject harness → `importWatch({...})` → two green banners → readback) → append
`history.jsonl`.**

**Ground truth for "is this imported / how many are there" is the 3ceasuri.ro admin**,
never a local file. The old `state.json` counter drifted to 33 while the site held 80+.

`$PROJECT_ROOT` and `$CDP_HOST` are placeholders defined once in `watch-session-setup`;
all paths and CDP endpoints in skills use them, so there is no environment-specific
path baked into any skill.

## Adding a new brand

Follow the "New brand procedure" in `admin-import-watch` — it keeps `window.BRAND_IDS`
(in the harness) and `references/brand-ids.md` in sync; always update BOTH.
