---
name: olx-troubleshooting
description: Invoke ONLY when an OLX step fails: 403s and bot checks, ad JSON or photos that won't load, brand errors, missing banners.
---

# olx-troubleshooting

Symptom → cause → action. Read only when something has actually failed. The
reasoning behind each rule is in `harness/3ceasuri-import/references/olx-lore.md`.

## First, the two that cost you a watch if you get them wrong

| Situation | Do |
|---|---|
| `importWatch` raised `Inspected target navigated or closed` or `Runtime.evaluate timed out` | **Do NOT retry.** That is the success path — the submit navigated the tab out from under CDP. Verify by page content (`import-verify-state` §3). A retry double-imports. |
| `REVIEW:` fired | **Never override it.** `action: fix` → supply the named field in the draft, re-run pass 2 once. `action: skip` → log the code, take the next id. |

## Discovery dies on page 0

`ERROR: OLX returned no offers for category …` — the `fetch()` came back non-200 or
unparseable.

| Cause | Check | Fix |
|---|---|---|
| the tab is not on olx.ro (most likely) | `js('(() => location.href)()')` | navigate it to the category URL — same-origin is what makes the API answer |
| a bot check or cookie banner | open the category URL and look | clear it by hand once; the cookie covers later calls |
| the category id changed | read `category.id` off any ad in it | update `CATEGORY_SMARTWATCH` / `CATEGORY_WATCHES` in `scripts/olx_api.py` |

```python
print(js('(async () => { const r = await fetch("/api/v1/offers/<AD_ID>/",'
         '{headers:{Accept:"application/json"}}); const d = await r.json();'
         ' return JSON.stringify(d.data.category); })()'))
```

## One ad won't load

`ERROR: OLX ad <id> did not load` — removed, expired, or the bot check. Confirm by
opening `https://www.olx.ro/d/oferta/…`. Genuinely gone → mark the candidate
`skipped` and move on; nothing was written.

`SKIP: ad is not active` is **not** a failure — OLX marks sold and withdrawn ads
that way.

## Photos empty or short

`photos_failed > 0` means a CDN fetch returned under 500 bytes of base64. OLX photo
URLs do not expire, so re-running pass 1 is safe and usually works (use `FRESH=1` if
a draft already exists). All photos failing → check the CDN host is reachable from
the browser.

## `REVIEW: draft_invalid`

The validator caught something the admin form would have silently dropped. Fix the
draft file (`EXTRACT_PROMPT.draft`) and re-run pass 2. **Do not re-run pass 1** — it
re-seeds the draft and destroys your answers (`FRESH=1` does that on purpose).

| Message | Fix |
|---|---|
| `model is required and was left null in the draft` | answer it |
| `series is not a field in the contract` | there is no `series` field; the generation goes in `model` |
| `connectivity='LTE' is not one of gsm\|no_gsm` | use the legal enum |
| `year='1970-1980' is not a int` | `year` is an integer; put the decade in `model` |
| `movement='mecanic'` | `manual` |

## Pass 1 runs again instead of pass 2

Pass 2 is `CONFIRM=1` with **no** `OVERRIDES` — it reads the draft from disk. If
pass 1 runs instead, the draft is missing: check
`harness/3ceasuri-import/.contracts/olx-<id>.json`. It is gitignored, so a clean
checkout has none.

## The queue does not advance

```bash
python3 $PROJECT_ROOT/harness/3ceasuri-import/scripts/candidates.py counts <file>
```

`QUEUE_EMPTY` with everything `imported`/`skipped`/`error` → the sweep really is
done; re-run discovery. A candidate marked `skipped` by mistake → edit its `status`
back to `pending` by hand.

`WARN: could not mark the queue` on an otherwise good import → only bookkeeping
failed; `CANDIDATES_FILE` points at a path that does not exist. The import
succeeded. Fix the path before the next id.

## `failed to create/find brand` / `BRAND_FAILED`

The row may exist even though the lookup failed. **Look before retrying** or you
create a duplicate with a mangled slug:
`https://3ceasuri.ro/admin/watches/brand/?q=<name>` — search by **NAME, not slug**.

Exists → add it to `BRAND_IDS` in `import-watch.js` **and**
`references/brand-ids.md`, then re-run pass 2.

## No green banners

Read the CDP-exception rule at the top first. If the banners are genuinely absent,
read `document.body.innerText` on the add page for the form's error list — a
rejected required field (brand, model, price, condition, movement) is the usual
cause.

## `phone_status` is not `ok`

| Value | Meaning | Action |
|---|---|---|
| `login_required` | the CDP Chrome is not signed in to olx.ro | sign in (`olx-session-setup`), re-run pass 1 |
| `no_button` | the seller published no number; chat-only | none — roughly 1 ad in 5, not a failure |
| `not_revealed` | a control was clicked, no `tel:` appeared | lore §5: only VISIBLE controls, native `.click()` |
| `wrong_page` | the tab had not navigated to the target ad yet | re-run pass 1 |

A missing phone never fails an import. Do NOT gate the reveal on a "looks logged
in" check — the wall text is the only reliable signal (lore §5). A tab stranded on
`login.olx.ro` is steered back automatically on the next run.

## Harness injection fails

`RuntimeError: harness injection failed` — `window.importWatch` was not defined
after the `<script>` append. Retry once. Still failing → the CDP expression size
limit; fall back to small `js()` calls, each under ~3 KB:

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

Each `images_payload` entry MUST be `{"data_url": "…"}`, never a plain string — a
plain string raises `AttributeError: 'str' object has no attribute 'get'`
server-side.

## A field saved empty

Read it back (`import-verify-state` §3). `source`, `external_listing_id`,
`seller_id` or `seller_name` missing while everything else saved → the deployed
admin is still on the pre-2026-08-09 field names. The harness writes through a
fallback, so nothing is lost and there is nothing to fix by hand (lore §7).

## Admin DB outage

`OperationalError: failed to resolve host 'anunturi1-anunturi.h.aivencloud.com'` —
PostgreSQL is unreachable, server-side. Wait 30 s and retry; persistent → stop the
session and report.

## Retry / rollback policy

| Failure | Action |
|---|---|
| `importWatch` timeout / CDP exception | **Do not retry.** Verify by page content — it likely succeeded |
| Harness injection fails | Retry once, then manual field filling |
| No green banners | Re-inject, re-run pass 2. Max 2 retries, then log a skip |
| `REVIEW:` `action: fix` | Supply the named field in the draft, re-run pass 2 ONCE |
| `REVIEW:` `action: skip` | **Never override.** Log the code, take the next id |
| `draft_invalid` | Fix the draft; never re-run pass 1 (it re-seeds) |
| Ad JSON won't load | Confirm the ad exists; gone → mark skipped, move on |
| Photos all fail | Re-run pass 1 (OLX URLs don't expire) |
| Admin DB down | Wait 30 s, retry. Persistent → stop and report |
| Already imported | Skip, log it, next candidate |
| WebSocket drops | Reconnect; browser-use uses short-lived connections per call |

Why any of this is the way it is: `harness/3ceasuri-import/references/olx-lore.md`.
