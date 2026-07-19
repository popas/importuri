# Watch Listing Automation — Facebook → 3ceasuri.ro (Orchestrator)

This file only sequences the work. Each step below is a skill — invoke the skill for
the phase you are in (via the Skill tool) and follow it. Load only the skill for the
current phase; skills point to each other and to shared assets.

## The loop

```
SETUP (once per session)
  └── invoke `watch-session-setup`
        (env vars, browser-use connect, admin + FB tabs, load state.json, ask user for target)

PER WATCH (repeat until target reached)
  ├── invoke `fb-find-posts`        → next qualifying post + post ID
  ├── duplicate check               → `admin-import-watch` Step 1 (?q=POST_ID, separate tab)
  ├── invoke `fb-extract-post`      → fields + ALL image URLs from that ONE post
  ├── invoke `admin-import-watch`   → re-inject harness, call importWatch({...})
  ├── invoke `import-verify-state`  → two green banners, update state.json
  └── repeat
```

When anything fails at any step → invoke `watch-troubleshooting`.

## The 5 iron rules

1. **One watch at a time.** Find → Extract → Import → Confirm → Repeat. Never
   batch-collect multiple watches (FB CDN URLs expire within the session).
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
- Brand ID mapping: `$PROJECT_ROOT/harness/3ceasuri-import/references/brand-ids.md`
- Progress tracker: `$PROJECT_ROOT/state.json`

`$PROJECT_ROOT` and `$CDP_HOST` are defined in `watch-session-setup`.
