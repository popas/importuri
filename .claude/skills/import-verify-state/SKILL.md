---
name: import-verify-state
description: Invoke immediately after every importWatch() call — verify the import by page content (never by return value) and update state.json.
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
    fbId: g('id_facebook_listing_id'), imgs
  });
})()
```

**The element IDs are non-obvious** — reference is `id_reference_number` and diameter is
`id_case_diameter_mm`; reading `id_reference`/`id_diameter` returns null and fakes a bug
(happened 2026-07-24). Confirm: `brandId` numeric and correct, `price`/`currency` match,
`ref`/`diameter` present when the post stated them, `fbId` set, and `imgs` equals the count
you collected. Any mismatch → treat as a failed field (fix + re-inject + re-save that field),
even though the banners were green.

## 4. Partial images — still imported

If only partial images saved, the watch is still imported — note the image count discrepancy. Fetch failures come from CORS restrictions (3ceasuri.ro → fbcdn.net), network timeouts, and expired FB CDN signed URLs. Diagnose via `[HARNESS] FETCH FAIL:` messages in the browser console. The watch can be saved without images. **NEVER skip a watch solely due to image issues** — save it, then retry image fetching separately.

## 5. Failure path — no green banners

If NO green banners, check `document.body.innerText` for error messages. Fix the issue, re-inject harness, re-inject images, and retry (max 2 retries per the retry policy in `watch-troubleshooting`).

## 6. Update state.json

State file: `$PROJECT_ROOT/state.json`. Update after EVERY import or skip — this enables crash recovery.

```json
{
  "imported": [
    {"id": "POST_ID", "brand": "Orient", "model": "Bambino", "price": 1200, "images": 5, "timestamp": "2026-06-20T12:00:00", "author_id": "100078...", "author_name": "Costi Schiverniciuc"}
  ],
  "skipped": [
    {"id": "POST_ID", "reason": "duplicate"},
    {"id": "POST_ID", "reason": "repost (author+brand+model match)", "existing_fb_id": "OTHER_POST_ID"}
  ],
  "total_imported": 0,
  "target": 20
}
```

`total_imported` is the running count of successful imports; `target` is the session goal.

## Next

If the session target isn't reached, loop back to `fb-find-posts` for the next watch. The harness form is ready again via "Save and add another", but it must be re-injected — see `admin-import-watch`.
