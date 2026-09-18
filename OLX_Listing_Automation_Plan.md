# Watch Listing Automation — OLX.ro → 3ceasuri.ro (Orchestrator)

This file only sequences the work. Each step below is a skill — invoke the skill for
the phase you are in (via the Skill tool) and follow it. Load only the skill for the
current phase. OLX is the only live source; the Facebook path is parked in
`archive/facebook/` and is not part of this loop.

## The loop

```
SETUP (once per session)
  └── invoke `olx-session-setup`
        (env vars, browser-use connect, admin + olx.ro tabs, session state, target)

DISCOVER (once per session, NOT per watch — pick ONE category)
  ├── smartwatches → invoke `olx-find-smartwatches` → olx-find-smartwatches.py (cat 1943)
  └── watches      → invoke `olx-find-watches`      → olx-find-watches.py      (cat 1677)
        (objective filters + Stage-1 dedup done inside; you triage the snippets)
        → surviving ids persist to .candidates-olx-smart.json / -watches.json

PER WATCH (repeat until the queue is empty or the target is reached)
  ├── ID=$(candidates.py next <candidates file>)   ← a command, never a memory
  ├── invoke `olx-import-smartwatch` OR `olx-import-watch` → TWO passes:
  │     pass 1: AD_ID=$ID CANDIDATES_FILE=$CAND browser-use < olx-import-*.py
  │             (dedup → ad JSON → params → photos → seeded contract draft on disk,
  │              writes NOTHING to the DB)
  │     you:    read ONE photo, edit ONLY the fields in EXTRACT_PROMPT.todo,
  │             in the draft file named by EXTRACT_PROMPT.draft
  │     pass 2: AD_ID=$ID CANDIDATES_FILE=$CAND CONFIRM=1 browser-use < olx-import-*.py
  │             (read the draft → validate → repost dedup → import → verify → readback)
  │     a field you BLANK is CLEARED — the draft removes retyping, not the rule
  ├── invoke `import-verify-state` → pipe RESULT: to olx-log-result.py
  └── next id (the importer already marked the queue)
```

A context checkpoint is a first-class stop: the queue holds the progress, so a fresh
session resumes exactly where the last one stopped.

When anything fails at any step → invoke `olx-troubleshooting`.

## The iron rules

1. **One watch at a time.** Extract → Import → Confirm → Repeat.
2. **Read OLX only from a page already on olx.ro.** A plain GET is 403; the API
   answers from the page context. This is why the scripts need a browser at all.
3. **Verify by page content, not return value.** Check for both `imagini salvate`
   and `added successfully`; CDP timeouts usually mean success.
4. **Re-inject the harness after every page navigation/submit** — it is lost each time.
5. **Always fill `description`, `sourceUrl` and the listing id** — without them
   listings are incomplete.
6. **Never import a suspiciously cheap listing.** Below the floors in
   `scripts/price_sanity.py` a watch is a fake, not a bargain — discovery drops it
   and the importers refuse it, `CONFIRM=1` included.
7. **Route by kind, not by category.** A smartwatch found in category 1677 is
   flagged `looks_smart`, not dropped — import it with the smartwatch script so
   `connectivity`/`compatibility` get filled. A classic watch in 1943 is flagged
   `looks_classic` and goes the other way. (There is no `series` field; the
   generation goes in `model`.)
8. **Never override a `REVIEW:` gate.** Each reason carries an `action`: `fix` means
   supply the field it names and re-run pass 2 once; `skip` means log the code and
   take the next id. `CONFIRM=1` is a human flag, not a skeleton key.
9. **`movement` never silently defaults to quartz.** An ad that states no movement
   stops for review.

**Image URLs are rewritten on purpose here.** OLX links are unsigned and templated, so
the importer rewrites `{width}x{height}` to `1000x1000`. (The archived Facebook path
forbade touching image URLs — its signed CDN params were required. That rule is FB-only
and does not apply to OLX.)

## Assets

- Skills: `.claude/skills/<name>/SKILL.md` — `olx-session-setup`,
  `olx-find-smartwatches`, `olx-find-watches`, `olx-import-smartwatch`,
  `olx-import-watch`, `import-verify-state`, `olx-troubleshooting`.
- Discovery: `.../scripts/olx-find-smartwatches.py` (cat 1943),
  `.../scripts/olx-find-watches.py` (cat 1677)
- Importers: `.../scripts/olx-import-smartwatch.py`, `.../scripts/olx-import-watch.py`
- Shared: `.../scripts/olx_import.py` (THE per-ad flow, both profiles — the two
  importer files are wrappers that pick one), `.../scripts/olx_api.py` (API, param
  map, photos), `.../scripts/admin_import.py` (the admin half: dedup, brand, submit,
  verify), `.../scripts/infer_fields.py` (the contract, profiles `classic` /
  `smart`), `.../scripts/contract_draft.py` (the seeded draft),
  `.../scripts/import-watch.js` (harness v7, authoritative)
- No-browser CLIs (run with `python3`, unlike the payloads):
  `.../scripts/candidates.py` (the work queue), `.../scripts/olx-log-result.py`
  (history + counters)
- Why the rules are the rules: `.../references/olx-lore.md`
- Paste-per-session prompts: `OLX_IMPORT_SESSION_PROMPT.md`
- Brand ID mapping: `.../references/brand-ids.md` · blocklist:
  `.../references/seller-blocklist.json` (`olx_sellers`)
- Session state: `$PROJECT_ROOT/state.json` (bookkeeping only) · local log:
  `history.jsonl` · **ground truth for what is imported: the 3ceasuri.ro admin**

`$PROJECT_ROOT` and `$CDP_HOST` are defined in `olx-session-setup`.
