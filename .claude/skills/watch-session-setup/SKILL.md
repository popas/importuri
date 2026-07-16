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
content, so browser-use is the primary tool for FB. Connection requires the
**browser-level** WS URL:

```bash
# 1. Get browser-level WS URL (NOT page-level!)
curl -s http://$CDP_HOST/json/version | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['webSocketDebuggerUrl'])"
# Returns: ws://$CDP_HOST/devtools/browser/<id>

# 2. Close existing session first if needed
browser-use close

# 3. Connect
browser-use --cdp-url "ws://$CDP_HOST/devtools/browser/<id>" tab list

# 4. Tab operations
browser-use --cdp-url "<url>" tab switch <index>
browser-use --cdp-url "<url>" tab new <url>
browser-use --cdp-url "<url>" eval "<js>"
browser-use --cdp-url "<url>" scroll down
browser-use --cdp-url "<url>" screenshot
```

**Key details:**
- Page-level WS URLs (`/devtools/page/<id>`) get HTTP 404 — must use browser-level (`/devtools/browser/<id>`)
- If you get "Session 'default' is already running with different config", run `browser-use close` first
- `browser-use eval` works on FB pages even when `browser_console` fails with UTF-8 encoding errors

## Open required tabs

```bash
# Tab 0: Admin add-watch form
browser-use --cdp-url <url> tab new https://3ceasuri.ro/admin/watches/watch/add/

# Tab 1: FB buy/sell
browser-use --cdp-url <url> tab new https://www.facebook.com/groups/978581759677150/buy_sell_discussion
```

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
