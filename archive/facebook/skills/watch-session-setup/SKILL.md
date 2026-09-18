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
- `$CDP_HOST` = **`127.0.0.1:9222` on the user's local Mac** (verified 2026-07-17c; Chrome
  launched with `--remote-debugging-port=9222`). `192.168.65.254:9222` was the old
  container-era host. Verify at setup — the host may differ per environment:

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
#   goto_url(url), wait_for_load(), js(code), capture_screenshot(),
#   page_info(). js() is synchronous — drive multi-step flows (e.g. carousels)
#   with a Python loop + time.sleep between js() calls.
```

Keep the `targetId`s from `list_tabs()` — every later step needs `switch_tab(...)`, and each
bash call is a fresh browser-use process with no memory of which tab was active.

**Avoid the `scroll(x, y)` helper — it scrolled the FB feed the WRONG WAY** (2026-07-17c).
Use `js('window.scrollBy(0, 1400)')` instead; see `fb-find-posts` → Fallback.

**Old CLI (< 3.0, container era):** `browser-use --cdp-url "ws://$CDP_HOST/devtools/browser/<id>" tab list`
with subcommands `tab switch/new`, `eval`, `scroll`, `screenshot`; needed the
**browser-level** WS URL from `curl -s http://$CDP_HOST/json/version` (page-level
`/devtools/page/<id>` URLs get HTTP 404), and `browser-use close` if you hit
"Session 'default' is already running with different config".

- `browser-use` `js()`/`eval` works on FB pages even when `browser_console` fails with UTF-8 encoding errors
- If `browser-use` is not installed: `uv tool install browser-use` (or pipx/pip)

### Performance (each bash call is a cold browser-use process)

Every `browser-use <<PY` invocation spawns a fresh process that reconnects over CDP and
prints an update-check banner — several seconds of pure overhead per call. To keep a session
snappy:

- **Do as much as possible inside ONE heredoc.** `switch_tab` + `js()` + `time.sleep` loops
  all live in a single process; don't split a carousel or a multi-step probe across calls.
- **Batch the cheap admin lookups** (dedup checks, brand-ID lookups) into one `new_tab` +
  `goto_url` loop rather than one process each — see `admin-import-watch` Step 1.
- **Admin-side (3ceasuri.ro) steps have no UTF-8 problem**, so the built-in
  `claude-in-chrome` MCP tools work there and skip the browser-use process spin-up — reserve
  browser-use for FB pages where the UTF-8 codec crash forces it.
- Silence the update banner if it's noisy: `browser-harness --update -y` once, or ignore it.

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

1. Read `$PROJECT_ROOT/state.json` — session bookkeeping only (`session_date`, `target`,
   `session_imported`, `session_skipped`, `status`, `note`). It deliberately holds **no**
   cumulative totals: on 2026-07-27 the old counter said 33 while the site held 80+.
2. If `status` is not `idle`, the previous session crashed mid-run — say so, and check
   `harness/3ceasuri-import/.candidates.json` for ids left unimported before scraping anew.
3. **Never quote an import total from a local file.** The live count arrives free as
   `STATS.admin_total` on the first `find-posts.py` call; report it from there. `history.jsonl`
   is the local append-only log — `wc -l` it if the user wants local activity, but say plainly
   that the admin is authoritative.
4. ASK THE USER for this session's target number of watches. Any `target` already in the file
   is stale — do not trust it. Write the new target and `status: "running"` before starting.

The record-keeping rules (what to append where, after each watch) live in
`import-verify-state`.

**Worktree caution (both files live in git).** If you are running inside a git worktree (cwd
under `.claude/worktrees/`), that worktree has its **own** `state.json` and `history.jsonl`,
which can diverge from the main checkout's. `$PROJECT_ROOT` above points at the **main
checkout**, so the harness and references are read from there, but a worktree's local copies
are where your edits land. `history.jsonl` is append-only, so reconcile by concatenating and
de-duplicating on `id`+`event` rather than letting one file overwrite the other. Divergence no
longer risks a wrong dedup verdict — that question is answered by the admin, not by these
files.

Next: invoke `fb-find-posts`.
