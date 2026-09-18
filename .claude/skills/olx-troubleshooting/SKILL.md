---
name: olx-troubleshooting
description: Invoke ONLY when an OLX step fails: 403s and bot checks, ad JSON or photos that won't load, brand errors, missing banners.
---

# olx-troubleshooting

Failure modes of the OLX path and what to do about them. Read this only when
something has actually failed.

## The API returns nothing / discovery dies on page 0

`ERROR: OLX returned no offers for category …` means the `fetch()` came back
non-200 or unparseable. In order of likelihood:

1. **The tab is not on olx.ro.** Same-origin is what makes the API answer at all; a
   fetch from any other origin gets the same 403 that `curl` gets. Check with
   `js('(() => location.href)()')` and navigate the tab to the category URL.
2. **A bot check is in the way.** Open the category URL in the browser and look:
   if there is a challenge page or a cookie banner covering the content, clear it by
   hand once. The session cookie then covers subsequent calls.
3. **The category id changed.** Verify by opening an ad from the category and
   reading `category.id`:

```python
print(js('(async () => { const r = await fetch("/api/v1/offers/<AD_ID>/",'
         '{headers:{Accept:"application/json"}}); const d = await r.json();'
         ' return JSON.stringify(d.data.category); })()'))
```

   If it differs from 1943 (smartwatches) / 1677 (watches), update
   `CATEGORY_SMARTWATCH` / `CATEGORY_WATCHES` in `scripts/olx_api.py`.

## An individual ad won't load

`ERROR: OLX ad <id> did not load` — the ad was removed, expired, or the bot check
is in the way. Confirm by opening `https://www.olx.ro/d/oferta/…` in the tab. If the
ad is genuinely gone, drop it from the candidates file and move on; nothing was
written.

`SKIP: ad is not active (status=…)` is not a failure — OLX marks sold and withdrawn
ads that way, and importing them would list something nobody can buy.

## Photos come back empty or short

`EXTRACT_PROMPT.photos_failed > 0` means the CDN fetch returned less than 500 bytes
of base64. OLX photo URLs are unsigned and do **not** expire, so a
retry is safe and usually works: re-run pass 1. If every photo fails, check the
CDN host is reachable from the browser (open one URL in a tab).

The importer rewrites `image;s={width}x{height}` to `1000x1000`. That is the
intended use of the template, not URL tampering — but if OLX ever rejects the size,
`olx_api.photo_urls(ad, width=..., height=...)` takes other values.

## `OVERRIDES are not valid DB values`

The validator caught an enum that the admin form would have silently dropped. The
message names the field and the legal values. Common ones:

- `connectivity: "LTE"` → the enum is `gsm` / `no_gsm`
- `year: "1970-1980"` → `year` is an integer; put the decade in `model`
- `movement: "mecanic"` → `manual`

## `failed to create/find brand`

The brand row may have been written even though the lookup failed. **Look before
retrying**, or you get a duplicate with a mangled slug:
`https://3ceasuri.ro/admin/watches/brand/?q=<name>` — search by NAME, not slug. If
the row is there, add it to `BRAND_IDS` in `import-watch.js` and
`references/brand-ids.md`, then re-run pass 2.

## No green banners after the import

The CDP exception on `importWatch` is the normal path, not a failure, because the
submit navigates the tab out from under the evaluate. **Never retry on that exception; verify by page content first**, or you
double-import the watch. See `import-verify-state` §2.

If the banners are genuinely absent, read `document.body.innerText` for the form's
error list. A rejected required field (brand, model, price, condition, movement) is
the usual cause.

## The phone comes back empty (`phone_status`)

Pass 1 reports how the phone reveal went:

- `ok` — the number was read. Works for **both private and business sellers**, as
  long as the browser is signed in to olx.ro.
- `login_required` — the CDP Chrome is not signed in to olx.ro. Private ads then
  show "Intra in contul tau OLX ... pentru a contacta acest vanzator" where the
  number would be. Sign in (see `olx-session-setup`) and re-run pass 1.
  The importer checks for that wall *before* clicking, deliberately: on such an ad
  the button navigates the tab to `login.olx.ro`, a different origin, and every
  later `/api/v1/` fetch from that tab 404s with "ad did not load".
- `no_button` — the seller published no number at all (`contact.phone: false` in
  the ad JSON); the ad is chat-only. Normal, not a failure — roughly one ad in five.
- `not_revealed` — a control was clicked but no `tel:` link appeared. If the number
  is plainly visible in your own browser, the click missed: OLX renders the control
  twice (sidebar + sticky bar) and the first in DOM order has width 0, so only
  VISIBLE controls may be clicked, using the native `.click()` — a synthetic
  MouseEvent does not fire the handler.

A missing phone never fails an import. If the tab did get stranded on
`login.olx.ro`, `olx_api.ensure_tab` steers it back on the next run — no manual fix.

Do NOT gate the reveal on a "looks logged in" check. Measured 2026-08-09: on a
private ad the my-account link was present while the session was not authenticated
for contact details, and the click still redirected. The wall text is the only
reliable signal.

## The record saved but a field is empty

Read it back (`import-verify-state` §3). If `source`, `external_listing_id`,
`seller_id` or `seller_name` are missing while everything else saved, the deployed
admin is still on the pre-2026-08-09 field names. The harness writes through a
fallback (`id_external_listing_id` → `id_facebook_listing_id`), so the id is not
lost — it lands in the old column and the migration's backfill relabels it by
`source_url` when the deploy lands. Nothing to fix by hand.

## Harness injection fails

`RuntimeError: harness injection failed` means `window.importWatch` was not defined
after the `<script>` append. Retry once. If it still fails, the CDP expression size
limit is the usual cause — fall back to filling the form with small `js()` calls:

```javascript
const set = (id, val) => { if (!val && val !== 0) return;
  const el = document.getElementById(id); if (!el) return;
  el.value = String(val); el.dispatchEvent(new Event('change', {bubbles: true})); };
set('id_model_name', '…'); set('id_price', '…'); set('id_condition', 'good');
set('id_movement', 'automatic'); set('id_currency', 'RON');
set('id_source', 'olx'); set('id_external_listing_id', 'AD_ID');
// … then the images payload, then submit:
document.querySelector('input[name="_addanother"]').click();
```

Keep each expression under ~3 KB. Each `images_payload` entry MUST be
`{"data_url": "…"}`, never a plain string — a plain string raises
`AttributeError: 'str' object has no attribute 'get'` server-side.

## Brand select fails

The harness sets `#id_brand` directly and falls back to Select2 (`selectBrandSelect2`,
5 attempts). If both fail it returns `{success:false, error:'BRAND_FAILED'}`. Check the
brand really exists: `https://3ceasuri.ro/admin/watches/brand/?q=<name>` — by NAME, not
slug. If it exists, add it to `BRAND_IDS` in `import-watch.js` and
`references/brand-ids.md`, then re-run pass 2.

## Admin DB outage

`OperationalError: failed to resolve host 'anunturi1-anunturi.h.aivencloud.com'` — a
Django error page with a traceback on the admin means PostgreSQL is unreachable. This is
server-side. Wait 30 s and retry; if it persists, stop the session and report.

## Retry / rollback policy

| Failure | Action |
|---|---|
| Harness injection fails | Retry once, then manual field filling (above) |
| `importWatch` timeout / CDP exception | **Do not retry.** Verify by page content — it likely succeeded |
| No green banners | Re-inject harness → re-run pass 2. Max 2 retries, then log a skip |
| Ad JSON won't load | Confirm the ad still exists; if gone, drop it and move on |
| Photos all fail | Re-run pass 1 (OLX URLs don't expire) |
| Admin DB down | Wait 30 s, retry. If persistent, stop and report |
| Already imported | Skip, log it, next candidate |
| WebSocket drops | Reconnect; browser-use uses short-lived connections per call |
