---
name: import-verify-state
description: Invoke after every pass-2 import to confirm the watch really saved and to record the outcome in history.jsonl and state.json.
---

# Import verify & state

Run right after pass 2. **The importer already verified.** Read `RESULT:`; do not
re-run the verification by hand.

## 1. Read `RESULT:`

```
RESULT: {"ad_id":"…", "ok":true, "banners":{"images_ok":true,"added_ok":true},
         "readback_ok":true, "expected_images":7, "readback":{…}, "state_entry":{…}}
```

| Condition | Meaning | Action |
|---|---|---|
| `ok: true`, `readback.imgs == expected_images` | fully imported | §2 |
| `ok: true`, `imgs < expected_images` | imported, some photos missing | §2, note the count. **Never skip a watch over images** |
| `readback_ok: true`, `banners.added_ok: false` | saved; the banner is flaky on multi-image saves | treat as success, §2 |
| `ok: false` | not proven | §3 |
| no `RESULT:` line | the payload died mid-import | §3 |

## 2. Record it

```bash
<the pass-2 output> | python3 $PROJECT_ROOT/harness/3ceasuri-import/scripts/olx-log-result.py
```

Appends to `history.jsonl` with `event` and `ts`, bumps `session_imported` /
`session_skipped` in `state.json`, prints `LOGGED: {…}`. An unverified `RESULT:`
(`ok: false`) logs nothing — a failed import can never be recorded as a success.

The importer has already marked the work queue, so nothing else is needed.

Never answer "is this imported?" or "how many are there?" from a local file:

- *Is this ad on the site?* → admin `?q=<ad_id>` (the importer does this as dedup stage 1)
- *How many are on the site?* → `STATS.admin_total` from discovery

## 3. Only when `RESULT:` is missing or `ok: false`

The record may still have saved. `importWatch` raising `Inspected target navigated
or closed` or `Runtime.evaluate timed out` is **the success path**.

**Never retry the import on that exception — verify first, or you double-import.**

```bash
export BU_CDP_URL="http://$CDP_HOST"
browser-use <<'PY'
import time
goto_url("https://3ceasuri.ro/admin/watches/watch/?q=AD_ID_HERE")
time.sleep(3)
print(js('(() => {const a=document.querySelector(\'#result_list tbody tr a[href*="/change/"]\');'
         'return JSON.stringify({found:!!a, url:a?a.href:null});})()'))
PY
```

| Result | Action |
|---|---|
| found | it imported — log it as `event: import` and move on |
| not found | read `document.body.innerText` on the add page for the form's error list. A rejected required field (brand, model, price, condition, movement) is the usual cause. Fix it, re-run pass 2. **Max 2 retries**, then log a skip and take the next id. |

Element ids for a manual readback are non-obvious (`id_reference_number`,
`id_case_diameter_mm`, `id_external_listing_id`) — the table is in
`references/olx-lore.md` §7.

## Next

`candidates.py next` for the following id — do not re-run discovery.
Anything fails → `olx-troubleshooting`.
Why any of this is the way it is: `harness/3ceasuri-import/references/olx-lore.md`.
