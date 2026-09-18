---
name: olx-session-setup
description: Invoke ONCE at the start of every OLX session, before any discovery or import: env vars, browser-use, tabs, state, target.
---

# OLX session setup

Run this once per session. It gets the browser-automation environment ready; the
per-watch loop lives in the discovery and import skills.

## Environment variables

- `$PROJECT_ROOT` = `/Users/stelian/.hermes/proiecte/3ceasuri`
- `$CDP_HOST` = `127.0.0.1:9222` on the user's local Mac (Chrome launched with
  `--remote-debugging-port=9222`). Verify:

```bash
curl -s http://$CDP_HOST/json/version
```

## Domains

- **Smartwatches (category 1943):** `https://www.olx.ro/electronice-si-electrocasnice/gadgets-wearables-si-camere-foto-video/smartwatch-uri/`
- **Watches (category 1677):** `https://www.olx.ro/moda-frumusete/ceasuri/`
- **Ad JSON:** `/api/v1/offers/<ad_id>/` · **Category JSON:** `/api/v1/offers/?category_id=…`
- **Admin:** `https://3ceasuri.ro/admin/watches/watch/add/`

## Why a browser at all

OLX answers a plain HTTP GET with **403** — there is bot protection in front of the
site. The same request issued from a page already on `olx.ro` succeeds, because it
carries the browser's cookies and headers. So every OLX read in these scripts is a
`fetch()` executed in the page context.

What that buys us: no feed scrolling, no hydration waits, no carousel walking, and
**photo URLs that do not expire**. Ad metadata comes back as JSON with the seller's own
structured attributes already filled in.

## Log into olx.ro FIRST — it decides whether phones are captured

Check the CDP Chrome is signed in before importing anything: open
`https://www.olx.ro/myaccount/` in the OLX tab and look for the account name.

Signed in, seller phone numbers are readable. Signed out they are **not**: private
ads render a "Intra in contul tau OLX ..." wall instead of the number, and clicking
the reveal button navigates the tab to `login.olx.ro`. Everything else (discovery,
ad JSON, photos) works either way — only the phone is lost, and the importer
records why in `phone_status`.

## Connect browser-use CLI

```bash
export BU_CDP_URL="http://$CDP_HOST"
browser-use <<'PY'
print(list_tabs())
PY
# Helpers: list_tabs(), switch_tab(id), new_tab(url), close_tab(id),
#   goto_url(url), js(code). js() is synchronous.
```

Every `browser-use` invocation is a cold process (several seconds of overhead), so
the OLX scripts each do their whole job in ONE call. Do not reimplement their steps
as individual `js()` calls.

## Open required tabs

`list_tabs()` first and reuse what is open. Otherwise:

- Tab 0 — `https://3ceasuri.ro/admin/watches/watch/add/`
- Tab 1 — either OLX category URL above (any olx.ro page works; the scripts steer it)

The scripts create and steer these themselves when they are missing, so this is a
convenience, not a precondition.

## Load state & decide target

1. Read `$PROJECT_ROOT/state.json` — session bookkeeping only. It holds **no**
   cumulative totals by design.
2. If `status` is not `idle`, a previous session crashed mid-run; check
   `harness/3ceasuri-import/.candidates-olx-smart.json` and
   `.candidates-olx-watches.json` for ids left unimported before running discovery
   again.
3. **Never quote an import total from a local file.** The live count arrives free
   as `STATS.admin_total` on the first discovery call.
4. ASK THE USER for this session's target, and whether it is smartwatches, classic
   watches, or both. Write the target and `status: "running"` before starting.

## Next

- Smartwatches → invoke `olx-find-smartwatches`
- Classic watches → invoke `olx-find-watches`

When anything fails → `olx-troubleshooting`.
