---
name: olx-session-setup
description: Invoke ONCE at the start of every OLX session, before any discovery or import: env vars, browser-use, tabs, state, target.
---

# OLX session setup

Once per session. The per-watch loop lives in the discovery and import skills.

## 1. Set the environment

```bash
export PROJECT_ROOT="/Users/stelian/.hermes/proiecte/3ceasuri"
export CDP_HOST="127.0.0.1:9222"
export BU_CDP_URL="http://$CDP_HOST"
curl -s http://$CDP_HOST/json/version
```

No JSON back → Chrome is not running with `--remote-debugging-port=9222`. Stop and
tell the user.

## 2. Check browser-use answers

```bash
browser-use <<'PY'
print(list_tabs())
PY
```

Helpers: `list_tabs()`, `switch_tab(id)`, `new_tab(url)`, `close_tab(id)`,
`goto_url(url)`, `js(code)`. `js()` is synchronous.

Each `browser-use` call is a cold process, so every script does its whole job in ONE
call. Never reimplement a script's steps as individual `js()` calls.

## 3. Confirm olx.ro is signed in

Open `https://www.olx.ro/myaccount/` in the OLX tab and look for the account name.

| Signed in? | Effect |
|---|---|
| yes | seller phone numbers are readable |
| no | private ads show a login wall; only the phone is lost, everything else works |

## 4. Open the tabs

`list_tabs()` first and reuse what is open. Otherwise:

- `https://3ceasuri.ro/admin/watches/watch/add/`
- either OLX category URL below (any olx.ro page works; the scripts steer it)

The scripts create and steer these themselves, so this is convenience, not a
precondition.

| What | URL |
|---|---|
| Smartwatches (1943) | `https://www.olx.ro/electronice-si-electrocasnice/gadgets-wearables-si-camere-foto-video/smartwatch-uri/` |
| Watches (1677) | `https://www.olx.ro/moda-frumusete/ceasuri/` |
| Ad JSON | `/api/v1/offers/<ad_id>/` |
| Category JSON | `/api/v1/offers/?category_id=…` |
| Admin | `https://3ceasuri.ro/admin/watches/watch/add/` |

## 5. Read state, resume or start

1. Read `$PROJECT_ROOT/state.json` — session bookkeeping only, no cumulative totals.
2. If `status` is not `idle`, a previous session crashed. Check the queue before
   re-running discovery:

```bash
python3 $PROJECT_ROOT/harness/3ceasuri-import/scripts/candidates.py counts \
  $PROJECT_ROOT/harness/3ceasuri-import/.candidates-olx-smart.json
```

   Any `pending` → resume with the import skill; do NOT re-run discovery.
3. Never quote an import total from a local file. The live count arrives as
   `STATS.admin_total` on the first discovery call.
4. Ask the user for the target and the category. Write the target and
   `status: "running"` to `state.json` before starting.

## Next

- Smartwatches → invoke `olx-find-smartwatches`
- Classic watches → invoke `olx-find-watches`
- Anything fails → `olx-troubleshooting`

Why any of this is the way it is: `harness/3ceasuri-import/references/olx-lore.md`.
