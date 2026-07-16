# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A **browser-automation runbook**, not a conventional codebase. It scrapes watch-sale
posts from a Facebook group and imports them into the 3ceasuri.ro Django admin, one
watch at a time. There is no build, test, or lint step. "Running" the project means
driving a CDP-controlled Chrome browser by following the plan and skills below.

## Read-order (every session)

1. `Watch_Listing_Automation_Plan.md` — the orchestrator. Read it completely before acting; it defines the SETUP → PHASE 0–4 loop step by step.
2. `skills/browser-use/SKILL.md` — Facebook scraping (feed extraction, post IDs, image collection, CDP fallbacks).
3. `skills/3ceasuri-import/SKILL.md` — Django admin import (harness injection, brand selection, form filling, verification).

**Skills are the single source of truth; the plan orchestrates.** When plan and skill
conflict on a detail, the skill wins. When two skills conflict (e.g. whether the FB feed
can be scrolled to load more posts), the newer/more specific guidance in the plan's
"Known Pitfalls" and the skill Session Notes reflects the current reality — treat those
as authoritative and prefer HTML/regex extraction over scrolling.

## Architecture

```
Watch_Listing_Automation_Plan.md   ← orchestrator (the loop)
state.json                         ← progress tracker (imported/skipped/target); load at start, update after each watch
skills/
  browser-use/                     ← FB side: discover posts, extract text + images
  3ceasuri-import/
    scripts/import-watch.js        ← THE HARNESS (authoritative, v5)
    references/brand-ids.md        ← brand→ID mapping source of truth
  3ceasuri/scripts/import-watch.js ← symlink → 3ceasuri-import/scripts/import-watch.js
```

Data flows one direction per watch: **FB post → extract fields + full image URLs → inject
harness into admin tab → `importWatch({...})` → verify two green banners → update `state.json`.**

### The harness (`skills/3ceasuri-import/scripts/import-watch.js`)

This ~13KB script is injected via a `<script>` tag into the admin add-watch page. It
exposes `window.importWatch(data)` plus extractor helpers. You pass **raw** FB data; the
harness does the formatting:

- Selects brand by ID from `window.BRAND_IDS` (direct `<option>` injection; Select2 search only as fallback for unknown brands).
- `buildProfessionalDescription()` turns extracted fields + raw FB text into the structured Romanian description — **do not pre-format the description**, pass `data.rawDescription` / `description` as raw text.
- Auto-generates slug, detects currency, and has extractors for phone/location/seller/year/reference.
- Fetches each image URL in-browser with 3-attempt retry, base64-encodes into `#images_payload`, then submits via `input[name="_addanother"]`.

**The harness is lost on every page navigation/submit — re-inject it before each watch.**

## Critical conventions

- **One watch at a time.** Find → Extract → Import → Confirm → Repeat. Never batch-collect multiple watches before importing (FB CDN URLs expire within the session).
- **Never modify image URLs.** Facebook CDN URLs carry signed params (`_nc_ohc`, `oh`, `oe`). Stripping or "upgrading" them causes "Bad URL hash". Use the exact `img.src`.
- **Verify by page content, not return value.** `importWatch` can return `success:false` even on success, and CDP often times out on image-heavy imports. Confirm by checking `document.body.innerText` for both `imagini salvate` and `added successfully`.
- **Brand field is special.** Never use `browser_type` or click Select2 for the Brand field — use direct `<option>` injection via the ID mapping. `browser_type` is unreliable for all fields; prefer `.value =` + `dispatchEvent(new Event('change'))`.
- **Always fill `description`, `sourceUrl`/`source_url`, and `fbListingId`/`facebook_listing_id`.** Missing these leaves listings looking incomplete (no description, no "Vezi sursa originală" back-link).
- **FB pages break the built-in browser tools.** `browser_navigate`/`browser_snapshot` throw `'utf-8' codec can't decode` on FB CDN content. Use the `browser-use` CLI or `window.location.replace()` via `browser_console` for FB; `browser_navigate` is fine for the admin site.

## Tool policy (strict — see plan's Tool Policy table)

| Job | Tool |
|-----|------|
| FB tabs / scrolling / eval on FB pages | `browser-use` CLI (needs the **browser-level** WS URL, not page-level) |
| FB feed scroll + DOM read loop | `browser_scroll` + `browser_console` (synchronous JS only) |
| Admin-site navigation | `browser_navigate` |
| Admin form fields (not Brand) | JS `.value =` + `change` event |
| Last resort only | raw CDP via Python websockets |

## Known path discrepancy (important)

Every skill and the plan hardcode the project root as `/opt/data/proiecte/3ceasuri/`
(e.g. the harness-injection `open(...)` snippets, the CDP host `192.168.65.254:9222`).
The actual working directory here is `/Users/stelian/.hermes/proiecte/3ceasuri/`. When
following those snippets, **translate the path to the real repo location** (or wherever
the file is mounted in the browser-automation environment). The CDP endpoint host may
likewise differ from the running environment.

## Adding a new brand

1. Create it at `https://3ceasuri.ro/admin/watches/brand/add/` (Name + Slug).
2. Note the new ID from the redirect URL (`/brand/<ID>/change/`).
3. Add it to `window.BRAND_IDS` in `import-watch.js` **and** to `references/brand-ids.md`.

> Note: `brand-ids.md` currently lists `Saint Honoré:34`, but `window.BRAND_IDS` in
> `import-watch.js` is missing it (harness stops at `Oris:33`). Keep the two in sync when
> touching brands.
