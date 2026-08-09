# Watch Listing Automation — OLX.ro → 3ceasuri.ro (Orchestrator)

This file only sequences the work. Each step below is a skill — invoke the skill for
the phase you are in (via the Skill tool) and follow it. Load only the skill for the
current phase. The Facebook source has its own orchestrator,
`Watch_Listing_Automation_Plan.md`; do not mix the two in one session.

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

PER WATCH (repeat until target reached — ONE FRESH CONTEXT EACH)
  ├── take the next id from the candidates file
  ├── invoke `olx-import-smartwatch` OR `olx-import-watch` → TWO passes:
  │     pass 1: AD_ID=<id> browser-use < olx-import-*.py
  │             (dedup → ad JSON → params → photos → EXTRACT_PROMPT, writes NOTHING)
  │     you:    read the contract AND one photo, fill every field
  │     pass 2: AD_ID=<id> CONFIRM=1 OVERRIDES='{…}' browser-use < olx-import-*.py
  │             (validate → repost dedup → import → verify → readback)
  │     a field you leave out is CLEARED, so answer in full
  ├── invoke `import-verify-state` → append to history.jsonl, bump session counters
  └── /clear, then next id
```

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
6. **Route by kind, not by category.** A smartwatch found in category 1677 is
   flagged `looks_smart`, not dropped — import it with the smartwatch script so
   `series`/`connectivity`/`compatibility` get filled. A classic watch in 1943 is
   flagged `looks_classic` and goes the other way.

Rule 2 in the Facebook orchestrator ("never modify image URLs") does **not** apply
here: OLX links are unsigned and templated, and the importer deliberately rewrites
`{width}x{height}` to `1000x1000`.

## Assets

- Skills: `.claude/skills/<name>/SKILL.md` — `olx-session-setup`,
  `olx-find-smartwatches`, `olx-find-watches`, `olx-import-smartwatch`,
  `olx-import-watch`, `olx-troubleshooting`; `import-verify-state` is shared with
  the Facebook path.
- Discovery: `.../scripts/olx-find-smartwatches.py` (cat 1943),
  `.../scripts/olx-find-watches.py` (cat 1677)
- Importers: `.../scripts/olx-import-smartwatch.py`, `.../scripts/olx-import-watch.py`
- Shared: `.../scripts/olx_api.py` (API, param map, photos),
  `.../scripts/admin_import.py` (the admin half, shared with Facebook),
  `.../scripts/infer_fields.py` (the contract, profiles `classic` / `smart`),
  `.../scripts/import-watch.js` (harness v6, authoritative)
- Brand ID mapping: `.../references/brand-ids.md` · blocklist:
  `.../references/seller-blocklist.json` (`olx_sellers`)
- Session state: `$PROJECT_ROOT/state.json` (bookkeeping only) · local log:
  `history.jsonl` · **ground truth for what is imported: the 3ceasuri.ro admin**

`$PROJECT_ROOT` and `$CDP_HOST` are defined in `olx-session-setup`.
