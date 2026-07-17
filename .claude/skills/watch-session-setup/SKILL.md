---
name: watch-session-setup
description: Invoke once at the very start of every watch-import session — before any FB scraping or admin import — to define environment variables, connect the browser-use CLI, open the required tabs, load state.json, and confirm this session's target number of watches.
---

# Watch session setup

Run this once per session. It gets the browser-automation environment ready; the
per-watch loop (find → extract → import → verify) lives in the other skills.

## Environment variables

Define these first — every other skill references them.

- `$PROJECT_ROOT` = `/Users/stelian/.hermes/proiecte/3ceasuri`
  (the old container environment used `/opt/data/proiecte/3ceasuri`; if the repo is
  mounted elsewhere, use that path instead).
- `$CDP_HOST` = default `192.168.65.254:9222`. Verify at setup — the host may differ
  per environment:

```bash
curl -s http://$CDP_HOST/json/version
```

## Domains

- **Facebook group:** `vanzareceasuri` (numeric ID: `978581759677150`)
- **Buy/sell URL:** `https://www.facebook.com/groups/978581759677150/buy_sell_discussion`
- **Main group URL:** `https://www.facebook.com/groups/vanzareceasuri/`
- **Post URL:** `https://www.facebook.com/groups/vanzareceasuri/posts/POST_ID/`
- **Commerce listing URL:** `https://www.facebook.com/commerce/listing/LISTING_ID/` (preferred when available)
- **Admin:** `https://3ceasuri.ro/admin/watches/watch/add/`

## Connect browser-use CLI

ALWAYS connect browser-use before starting FB operations. The built-in
`browser_navigate`/`browser_snapshot` fail with UTF-8 encoding errors on FB CDN
content, so browser-use is the primary tool for FB.

**browser-use ≥ 3.0 (current, verified 2026-07-17):** connection is the `BU_CDP_URL`
env var set to the **HTTP** endpoint (a `ws://` URL fails with "unknown url type: ws"),
and commands are Python helpers piped on stdin:

```bash
export BU_CDP_URL="http://$CDP_HOST"
browser-use <<'PY'
print(list_tabs())          # [{'targetId': ..., 'title': ..., 'url': ...}, ...]
PY
# Helpers: list_tabs(), switch_tab(target_id), new_tab(url), close_tab(target_id),
#   goto_url(url), wait_for_load(), js(code), scroll(x, y), capture_screenshot(),
#   page_info(). js() is synchronous — drive multi-step flows (e.g. carousels)
#   with a Python loop + time.sleep between js() calls.
```

**Old CLI (< 3.0, container era):** `browser-use --cdp-url "ws://$CDP_HOST/devtools/browser/<id>" tab list`
with subcommands `tab switch/new`, `eval`, `scroll`, `screenshot`; needed the
**browser-level** WS URL from `curl -s http://$CDP_HOST/json/version` (page-level
`/devtools/page/<id>` URLs get HTTP 404), and `browser-use close` if you hit
"Session 'default' is already running with different config".

- `browser-use` `js()`/`eval` works on FB pages even when `browser_console` fails with UTF-8 encoding errors
- If `browser-use` is not installed: `uv tool install browser-use` (or pipx/pip)

## Open required tabs

Reuse existing tabs when the right pages are already open (`list_tabs()` first).
Otherwise open: Tab 0 = `https://3ceasuri.ro/admin/watches/watch/add/`,
Tab 1 = `https://www.facebook.com/groups/978581759677150/buy_sell_discussion`
(via `new_tab(url)`, or `tab new` on the old CLI).

If the FB tab shows notifications instead of the feed, don't retry `tab new` —
navigate the existing tab with `window.location.href` (see `watch-troubleshooting`).

The harness is injected into the admin tab per-watch, not here — see the
`admin-import-watch` skill.

## Load state & decide target

1. Load `$PROJECT_ROOT/state.json`.
2. Report the imported and skipped totals to the user.
3. ASK THE USER for this session's target number of watches. Any `target` value
   already in the file is stale — do not trust it.

The state.json update schema (applied after each watch) lives in the
`import-verify-state` skill.

Next: invoke `fb-find-posts`.
