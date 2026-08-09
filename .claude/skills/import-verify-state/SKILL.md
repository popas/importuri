---
name: import-verify-state
description: Invoke immediately after every importWatch() call, for either source — verify the import by page content (never by return value) and update state.json.
---

# Import Verify & State

Run this right after every `importWatch()` call. **Verify by PAGE CONTENT, never by return value:** `importWatch` can return `success: false` even on success, and CDP often times out on image-heavy imports.

## 1. Verify the two green banners

Wait 5 seconds after `importWatch` returns. Check for BOTH green banners:

```javascript
(() => {
  const t = document.body.innerText;
  return JSON.stringify({
    images_ok: t.includes('imagini salvate'),
    added_ok: t.includes('added successfully') || t.includes('adăugat cu succes'),
    banner_text: t.substring(0, 500)
  });
})()
```

Both `images_ok` and `added_ok` must be true. (The admin may render the success
banner in Romanian — "a fost adăugat cu succes" — or English "added successfully";
the check accepts either.)

## 2. CDP timeout means recheck — never assume failure

The `importWatch` function fetches all images via `async/await` in the browser. When fetching many images (5-10), the CDP `Runtime.evaluate` call may time out with "Inspected target navigated or closed" even though the import succeeded. **Always re-check the page for green banners after a timeout error before assuming failure** — the import likely succeeded.

**Expect this error on EVERY import — it is the normal path, not an edge case.** On
2026-07-17c `{'code': -32000, 'message': 'Inspected target navigated or closed'}` fired 5/5
times, and all 5 imports had both green banners (3–10 images each). The form submit
navigates the tab out from under the evaluate; that IS success in progress.

Under browser-use the raised exception will abort your heredoc **before** you verify, which
looks like a failed import. Always wrap the call and press on:

```python
try:
    js(open('/tmp/.../call.js').read())
except Exception as e:
    print('EXC (expected):', str(e)[:100])   # do NOT retry the import here
time.sleep(20)                                # 25–30s for 8+ images
js(BANNER_CHECK)                              # the page is the only source of truth
```

Retrying on this exception would double-import the watch. Verify first, always.

## 3. Read back the saved record — "saved" ≠ "correct"

The two green banners prove the row was **saved**, not that every field **persisted**. Fields
the harness maps to the wrong element, enum values the form rejects, or images that failed to
attach are all invisible at the banner stage. After the banners pass, **open the saved
record's change page and read the fields back** — this is the only check that catches a silent
field/image drop.

The banners render on the blank *add* page (post "Save and add another"), so navigate to the
saved row first: `.../admin/watches/watch/?q=<POST_ID>` → follow its `/change/` link, then:

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
    source: g('id_source'),               // 'facebook' | 'olx'
    extId: g('id_external_listing_id'),   // was id_facebook_listing_id before 2026-08-09
    imgs
  });
})()
```

**Both sources use these same fields.** The provenance columns were renamed on
2026-08-09 (`facebook_listing_id` → `external_listing_id`, `facebook_author_id` →
`seller_id`, `facebook_author_name` → `seller_name`, plus a new `source`). If a
readback shows `MISSING:id_external_listing_id`, the deployed admin still has the
old names — read `id_facebook_listing_id` instead. The harness writes through the
same fallback, so nothing is lost either way.

**The element IDs are non-obvious** — reference is `id_reference_number` and diameter is
`id_case_diameter_mm`; reading `id_reference`/`id_diameter` returns null and fakes a bug
(happened 2026-07-24). Confirm: `brandId` numeric and correct, `price`/`currency` match,
`ref`/`diameter` present when the post stated them, `extId` set, and `imgs` equals the count
you collected. Any mismatch → treat as a failed field (fix + re-inject + re-save that field),
even though the banners were green.

## 4. Partial images — still imported

If only partial images saved, the watch is still imported — note the image count discrepancy. Fetch failures come from CORS restrictions (3ceasuri.ro → fbcdn.net), network timeouts, and expired FB CDN signed URLs. Diagnose via `[HARNESS] FETCH FAIL:` messages in the browser console. The watch can be saved without images. **NEVER skip a watch solely due to image issues** — save it, then retry image fetching separately.

## 5. Failure path — no green banners

If NO green banners, check `document.body.innerText` for error messages. Fix the issue, re-inject harness, re-inject images, and retry (max 2 retries per the retry policy in `watch-troubleshooting`).

## 6. Record the outcome

**Ground truth is the admin, not a local file.** On 2026-07-27 the tracker claimed 33 imports
while the site held 80+ — a hand-maintained counter had been drifting for weeks. Never answer
"is this already imported?" or "how many do we have?" from a local file:

- *Is this watch on the site?* → admin `?q=<post_id>` (both scripts do this automatically)
- *How many watches are on the site?* → the changelist paginator; `find-posts.py` already
  reports it once per session as `STATS.admin_total`, so read it there rather than navigating

Two local files, each with one job:

**`history.jsonl`** — append-only, one JSON object per line, never read back in bulk. Append
after every import and every skip. An append cannot drift the way a counter does.

```json
{"event":"import","id":"POST_ID","brand":"Orient","model":"Bambino","price":1200,"currency":"RON","images":5,"ts":"2026-07-27T12:00:00","source":"facebook","seller_id":"100078…","seller_name":"Costi Schiverniciuc"}
{"event":"skip","id":"AD_ID","source":"olx","brand":"Rodania","reason":"no price stated in the ad"}
```

The `RESULT:` line from `import-post.py` and the OLX importers carries a ready-made `state_entry` (including `source`) — append it with
`event` and `ts` added. Skips the scripts make (`SKIP:` lines) are worth appending too: the
admin records what *was* imported, only `history.jsonl` records what was rejected and why.

```bash
python3 -c 'import json,sys,time;r=json.loads(sys.argv[1]);r.update(event="import",ts=time.strftime("%Y-%m-%dT%H:%M:%S"));open("'"$PROJECT_ROOT"'/history.jsonl","a").write(json.dumps(r,ensure_ascii=False)+"\n")' "$STATE_ENTRY"
```

**`state.json`** — session bookkeeping only: `session_date`, `target`, `session_imported`,
`session_skipped`, `status`, `note`. Update the counters as you go so a crashed session can be
resumed. It holds no cumulative totals by design; do not reintroduce them.

## Next

If the session target isn't reached, take the next id from the candidates file for
your source — `.candidates.json` (Facebook), `.candidates-olx-smart.json` or
`.candidates-olx-watches.json` (OLX) — do **not** re-run discovery. Start it in a fresh
context (`/clear`): nothing from this watch is needed for the next one, and carrying it
forward is what pushes a session past 150k tokens. The harness form is ready again via "Save
and add another", but it must be re-injected — see `admin-import-watch` (Facebook) or
`olx-import-smartwatch` / `olx-import-watch` (OLX).
