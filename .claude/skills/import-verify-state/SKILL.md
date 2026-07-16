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
    added_ok: t.includes('added successfully'),
    banner_text: t.substring(0, 500)
  });
})()
```

Both `images_ok` and `added_ok` must be true.

## 2. CDP timeout means recheck — never assume failure

The `importWatch` function fetches all images via `async/await` in the browser. When fetching many images (5-10), the CDP `Runtime.evaluate` call may time out with "Inspected target navigated or closed" even though the import succeeded. **Always re-check the page for green banners after a timeout error before assuming failure** — the import likely succeeded.

## 3. Partial images — still imported

If only partial images saved, the watch is still imported — note the image count discrepancy. Fetch failures come from CORS restrictions (3ceasuri.ro → fbcdn.net), network timeouts, and expired FB CDN signed URLs. Diagnose via `[HARNESS] FETCH FAIL:` messages in the browser console. The watch can be saved without images. **NEVER skip a watch solely due to image issues** — save it, then retry image fetching separately.

## 4. Failure path — no green banners

If NO green banners, check `document.body.innerText` for error messages. Fix the issue, re-inject harness, re-inject images, and retry (max 2 retries per the retry policy in `watch-troubleshooting`).

## 5. Update state.json

State file: `$PROJECT_ROOT/state.json`. Update after EVERY import or skip — this enables crash recovery.

```json
{
  "imported": [
    {"id": "POST_ID", "brand": "Orient", "model": "Bambino", "price": 1200, "images": 5, "timestamp": "2026-06-20T12:00:00"}
  ],
  "skipped": [
    {"id": "POST_ID", "reason": "duplicate"}
  ],
  "total_imported": 0,
  "target": 20
}
```

`total_imported` is the running count of successful imports; `target` is the session goal.

## Next

If the session target isn't reached, loop back to `fb-find-posts` for the next watch. The harness form is ready again via "Save and add another", but it must be re-injected — see `admin-import-watch`.
