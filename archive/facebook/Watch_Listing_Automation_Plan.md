# Watch Listing Automation — Facebook → 3ceasuri.ro (Orchestrator)

This file only sequences the work. Each step below is a skill — invoke the skill for
the phase you are in (via the Skill tool) and follow it. Load only the skill for the
current phase; skills point to each other and to shared assets.

## The loop

```
SETUP (once per session)
  └── invoke `watch-session-setup`
        (env vars, browser-use connect, admin + FB tabs, session state, target)

DISCOVER (once per session, NOT per watch)
  └── invoke `fb-find-posts`  → runs find-posts.py → CANDIDATES: + STATS:
        (objective filters + Stage-1 dedup done inside; you triage the snippets)
        → surviving ids persist to harness/3ceasuri-import/.candidates.json

PER WATCH (repeat until target reached — ONE FRESH CONTEXT EACH)
  ├── take the next id from .candidates.json
  ├── invoke `admin-import-watch` → TWO passes, because YOU do the inference:
  │     pass 1: POST_ID=<id> browser-use < import-post.py
  │             (dedup → extract → EXTRACT_PROMPT + photos → writes NOTHING)
  │     you:    read the contract AND one photo, fill every field
  │     pass 2: POST_ID=<id> CONFIRM=1 OVERRIDES='{…}' browser-use < import-post.py
  │             (validate → import → verify → readback)
  │     a field you leave out is CLEARED, so answer in full
  ├── invoke `import-verify-state` → append to history.jsonl, bump session counters
  └── /clear, then next id
```

When anything fails at any step → invoke `watch-troubleshooting`.

**Why a fresh context per watch:** nothing from watch N is needed for watch N+1 — the
durable state is the candidates file, `history.jsonl`, and the admin. Carrying each
watch forward is what drags a session past 150k tokens. Never repeat discovery: it
costs a feed navigation and deepens FB throttling.

## The 5 iron rules

1. **One watch at a time.** Extract → Import → Confirm → Repeat. Never batch-collect
   *images* — FB CDN URLs expire within the session. Batching durable metadata (post
   ids, text, admin dedup lookups) is fine and is what discovery does.
2. **Never modify image URLs.** Signed params (`_nc_ohc`, `oh`, `oe`) are required;
   use the exact `img.src`.
3. **Verify by page content, not return value.** Check for both `imagini salvate`
   and `added successfully` banners; CDP timeouts usually mean success.
4. **Re-inject the harness after every page navigation/submit** — it is lost each time.
5. **Always fill `description`, `sourceUrl`, and `fbListingId`** — without them
   listings are incomplete.

## Assets

- Skills: `.claude/skills/<name>/SKILL.md` — `watch-session-setup`, `fb-find-posts`,
  `fb-extract-post`, `admin-import-watch`, `import-verify-state`, `watch-troubleshooting`
- Harness (v5, authoritative): `$PROJECT_ROOT/harness/3ceasuri-import/scripts/import-watch.js`
- Discovery: `.../scripts/find-posts.py` — whole feed sweep in one call
- Importer: `.../scripts/import-post.py` — whole per-watch flow in one call
- Fallback references (read only on failure): `.../references/feed-dom.md`,
  `.../references/post-extraction.md`
- Brand ID mapping: `.../references/brand-ids.md`
- Session state: `$PROJECT_ROOT/state.json` (bookkeeping only) · local log:
  `history.jsonl` · **ground truth for what is imported: the 3ceasuri.ro admin**

`$PROJECT_ROOT` and `$CDP_HOST` are defined in `watch-session-setup`.
