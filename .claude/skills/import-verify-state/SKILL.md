---
name: import-verify-state
description: Invoke after every pass-2 import to confirm the watch really saved and to record the outcome in history.jsonl and state.json.
---

# Import Verify & State

Run this right after pass 2 of `olx-import-watch` / `olx-import-smartwatch`.

## 1. The importer already verified — read `RESULT:` first

`admin_import.verify()` runs inside pass 2: it checks both green banners, follows the
saved record's change link and reads the fields back. All of it is on the `RESULT:` line:

```
RESULT: {"ad_id":"…", "ok":true, "banners":{"images_ok":true,"added_ok":true},
         "readback_ok":true, "expected_images":7,
         "readback":{"brandId":"57","price":"850","currency":"RON","ref":null,
                     "diameter":"44","source":"olx","extId":"307673714",
                     "sellerId":"…","sellerName":"…","imgs":7},
         "state_entry":{…}}
```

**Do not re-run that verification by hand.** It is done, and re-running it on whatever
tab you happen to be on is how a good import gets reported as a failure.

Read it like this:

| Condition | Meaning | Action |
|---|---|---|
| `ok: true` and `readback.imgs == expected_images` | fully imported | go to §3 |
| `ok: true`, `imgs < expected_images` | imported, some photos missing | go to §3, note the count in the log. **Never skip a watch over image issues** |
| `readback_ok: true` but `banners.added_ok: false` | saved; the banner is flaky on multi-image saves | treat as success, go to §3 |
| `ok: false` | not proven — go to §2 | |
| no `RESULT:` line at all | the payload died mid-import — go to §2 | |

## 2. Only when `RESULT:` is missing or `ok: false`

The record may still have saved: the form submit navigates the tab out from under CDP,
so the `importWatch` call raising `{'code': -32000, 'message': 'Inspected target
navigated or closed'}` or a `Runtime.evaluate timed out` is **the normal path, not a
failure**. On 2026-07-17 it fired 5/5 times and all 5 had both banners; every CDP
timeout in session 19 was likewise a false negative.

**Never retry the import on that exception — verify first, or you double-import.**

Check the admin directly, by listing id:

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

Found → it imported; open the `/change/` URL and read the fields back:

```javascript
(() => {
  const g = id => { const e = document.getElementById(id);
    return e ? (e.tagName === 'SELECT' ? (e.options[e.selectedIndex]||{}).value : e.value)
             : 'MISSING:' + id; };
  const imgs = document.querySelectorAll('.field-image img, [id*="images-group"] img, img[src*="/media/"]').length;
  return JSON.stringify({
    brandId: g('id_brand'),               // numeric brand ID (NOT the name)
    price: g('id_price'), currency: g('id_currency'),
    ref: g('id_reference_number'),        // NOTE: id_reference_number, not id_reference
    diameter: g('id_case_diameter_mm'),   // NOTE: id_case_diameter_mm, not id_diameter
    source: g('id_source'),               // 'olx'
    extId: g('id_external_listing_id'),   // renamed from id_facebook_listing_id 2026-08-09
    imgs
  });
})()
```

**The element ids are non-obvious.** Reference is `id_reference_number` and diameter is
`id_case_diameter_mm`; reading `id_reference` / `id_diameter` returns null and fakes a
bug (happened 2026-07-24). A readback showing `MISSING:id_external_listing_id` means the
deployed admin still has the pre-2026-08-09 names — read `id_facebook_listing_id`
instead; the harness writes through the same fallback, so nothing is lost.

Not found → read `document.body.innerText` on the add page for the form's error list. A
rejected required field (brand, model, price, condition, movement) is the usual cause.
Fix it, re-inject the harness, re-run pass 2. Max 2 retries, then log a skip and move on.

## 3. Record the outcome

**Ground truth is the admin, not a local file.** On 2026-07-27 the tracker claimed 33
imports while the site held 80+ — a hand-maintained counter had drifted for weeks.
Never answer "is this already imported?" or "how many do we have?" from a local file:

- *Is this ad on the site?* → admin `?q=<ad_id>` (both importers do this automatically)
- *How many watches are on the site?* → `STATS.admin_total`, reported once per session
  by the discovery script

Two local files, each with one job:

**`history.jsonl`** — append-only, one JSON object per line, never read back in bulk.
Append after every import and every skip. An append cannot drift the way a counter does.

```json
{"event":"import","id":"307673714","source":"olx","brand":"Apple","model":"Watch Series 9","price":1150,"currency":"RON","images":7,"ts":"2026-09-19T12:00:00","seller_id":"529077689","seller_name":"Stanciu Adrian"}
{"event":"skip","id":"307821602","source":"olx","brand":"Rodania","reason":"no price stated in the ad"}
```

The `RESULT:` line carries a ready-made `state_entry` — append it with `event` and `ts`
added:

```bash
python3 -c 'import json,sys,time;r=json.loads(sys.argv[1]);r.update(event="import",ts=time.strftime("%Y-%m-%dT%H:%M:%S"));open("'"$PROJECT_ROOT"'/history.jsonl","a").write(json.dumps(r,ensure_ascii=False)+"\n")' "$STATE_ENTRY"
```

Skips the scripts make (`SKIP:` lines) are worth appending too: the admin records what
*was* imported, only `history.jsonl` records what was rejected and why.

**`state.json`** — session bookkeeping only: `session_date`, `target`,
`session_imported`, `session_skipped`, `status`, `note`. Update the counters as you go so
a crashed session can be resumed. It holds no cumulative totals by design; do not
reintroduce them.

## Next

If the session target isn't reached, take the next id from `.candidates-olx-smart.json`
or `.candidates-olx-watches.json` — do **not** re-run discovery. Start it in a fresh
context (`/clear`): nothing from this watch is needed for the next one, and carrying it
forward is what pushes a session past 150k tokens. The admin form is ready again via
"Save and add another", but the harness must be re-injected — the importers do that
themselves.
