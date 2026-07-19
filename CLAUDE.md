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
     connects browser-use, opens tabs, loads `state.json`, asks the user for a target)
   - `fb-find-posts` → `fb-extract-post` → `admin-import-watch` → `import-verify-state`
     — per watch, in that order (duplicate check is `admin-import-watch` Step 1,
     done before extraction)
   - `watch-troubleshooting` — only when something fails

Do not load the whole runbook or multiple skills at once — each skill is
self-contained for its phase and points to the next.

## Architecture

```
Watch_Listing_Automation_Plan.md   ← orchestrator (the loop + iron rules, nothing else)
state.json                         ← progress tracker; schema in import-verify-state
.claude/skills/
  watch-session-setup/             ← env vars, browser-use connect, tabs, state, target
  fb-find-posts/                   ← discover qualifying posts (feed HTML regex primary)
  fb-extract-post/                 ← fields + ALL image URLs from ONE post
  admin-import-watch/              ← duplicate check, harness injection, importWatch()
  import-verify-state/             ← green-banner verification, state.json update
  watch-troubleshooting/           ← failure modes & fallbacks only
harness/                           ← shared assets (NOT skills — no SKILL.md here)
  3ceasuri-import/
    scripts/import-watch.js        ← THE HARNESS (authoritative, v5) — pointed to by skills
    references/brand-ids.md        ← brand→ID mapping source of truth
  browser-use/references/          ← historical session logs / deep references
```

Skills live ONLY in `.claude/skills/` (each a `SKILL.md`, invoked with the Skill tool).
`harness/` holds shared data/scripts the skills read — it is not itself a skill.

Data flows one direction per watch: **FB post → extract fields + full image URLs →
inject harness into admin tab → `importWatch({...})` → verify two green banners →
update `state.json`.**

`$PROJECT_ROOT` and `$CDP_HOST` are placeholders defined once in `watch-session-setup`;
all paths and CDP endpoints in skills use them, so there is no environment-specific
path baked into any skill.

## Adding a new brand

Follow the "New brand procedure" in `admin-import-watch` — it keeps `window.BRAND_IDS`
(in the harness) and `references/brand-ids.md` in sync; always update BOTH.
