---
name: olx-troubleshooting
description: Invoke ONLY when an OLX discovery or import step fails — 403s and bot checks, empty categories, ad JSON that won't load, photo download failures, brand creation errors, missing banners.
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
of base64. Unlike Facebook, OLX photo URLs are unsigned and do **not** expire, so a
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

Same rules as the Facebook path — the CDP exception on `importWatch` is the normal
path, not a failure, because the submit navigates the tab out from under the
evaluate. **Never retry on that exception; verify by page content first**, or you
double-import the watch. See `import-verify-state` §2.

If the banners are genuinely absent, read `document.body.innerText` for the form's
error list. A rejected required field (brand, model, price, condition, movement) is
the usual cause.

## The record saved but a field is empty

Read it back (`import-verify-state` §3). If `source`, `external_listing_id`,
`seller_id` or `seller_name` are missing while everything else saved, the deployed
admin is still on the pre-2026-08-09 field names. The harness writes through a
fallback (`id_external_listing_id` → `id_facebook_listing_id`), so the id is not
lost — it lands in the old column and the migration's backfill relabels it by
`source_url` when the deploy lands. Nothing to fix by hand.

## Everything else

Failure modes shared with the Facebook path (admin login expired, harness injection,
image fetch retries, Select2 brand fallback) are in `watch-troubleshooting`.
