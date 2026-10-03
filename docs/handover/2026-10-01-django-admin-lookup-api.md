# Handover: JSON lookup endpoints in the 3ceasuri.ro Django admin

**For:** an agent working in the Django repo (`../app` next to this repo, GitHub `popas/ceasuri`).
**From:** the OLX import runbook (`../importuri`, next to the Django repo), 2026-10-01.
**Goal:** replace HTML scraping of the admin changelists with a few batched JSON
endpoints, so the importer asks the database directly instead of loading one admin
page per question.

---

## 0. The problem, in one paragraph

The importer has **no machine-readable way to ask the site anything**. Every
question it asks ("is this OLX ad already on the site?", "is this the same
watch the same seller listed before?", "does brand X exist, and what is its
id?", "did my save actually land?") is answered by loading an admin HTML page in
a browser and scraping the DOM. It also writes by filling the admin add form
through injected JavaScript. As a result:

1. **It is slow.** About 6–8 page loads per watch before the save. One discovery
   sweep spends about 4 minutes checking candidate ids one page at a time.
2. **It is fragile and gives wrong answers.** The changelist `?q=` is a free-text
   search over many columns, so a listing id can "match" a phone or reference
   number. Brand lookups by name vs. slug already created duplicate brands.
   Success is judged by banner text, which has flaked.
3. **Its state drifts from the truth.** The brand→id map is copied by hand into
   the harness and goes stale. Counts come from parsing paginator text.
   Decisions like "this ad is a fake, skip it" live only in local files, so the
   next sweep reviews the same ads again.

The new functionality gives the importer a small JSON API inside the admin (same
login, staff-only) that answers these questions with one query each, in bulk
where possible, and lets it write through a validated endpoint instead of a
scripted form.

## 1. Why (details)

The importer drives a logged-in Chrome over CDP. Everything it knows about the
database it learns by **opening admin pages and reading the DOM**. It does this for
every lookup, one page per question:

| Question | Where it happens today | Cost today |
|---|---|---|
| Discovery: is each of ~85 candidate ids already imported? | `olx-find-*.py` → `admin_count(A, id)` | 1 changelist page load per id (~3 s each, ~4 min per sweep), plus parsing the paginator text |
| Import: is this ad id already imported? | `admin_import.already_imported` → `admin_rows(?q=<id>)` | new tab + page load + DOM scrape |
| Is it a repost (same seller, same model)? | `admin_import.find_repost` | 2 more changelist scrapes (`?q=<seller_id>`, `?q=<model>`) |
| Does the brand exist? What is its id? | `ensure_brand` → `_lookup_brand` (`/admin/watches/brand/?q=`) | page load + scrape; then fill and submit the brand add form; then scrape again |
| Total number of watches | `admin_count()` | parses "1 2 … 1333 watchs" out of the paginator |
| Did the save really happen? | `verify()` | changelist search, open the change page, read form inputs back |

Known problems this causes:
- It's slow: roughly 6–8 page loads per watch before the actual save.
- It's brittle: `?q=` is a free-text `search_fields` match, so an ad id also matches
  phone numbers, reference numbers and so on. Brand search goes by name and not
  slug, and that already caused duplicate brands (`f-r-marc` next to
  `fara-marca`).
- The brand list is cached in the harness (`window.BRAND_IDS` in `import-watch.js`
  plus `references/brand-ids.md`). It drifts away from the DB and has to be synced
  by hand with a commit for every new brand.

## 2. What exists now (read before changing)

- `watches/models.py`
  - `Brand(name, slug unique, created_at, updated_at)`: no uniqueness on `name`.
  - `Watch.source` (`facebook` | `olx`), `Watch.external_listing_id`
    (`PositiveBigIntegerField`, indexed, nullable), `seller_id` (indexed),
    `seller_name`, `model_name` (indexed), `brand` FK, `is_active`.
    `Picture(watch FK related_name="pictures")`.
- `watches/admin.py`
  - `WatchAdmin` already overrides `get_urls()`, adding `import/`
    (`watches_watch_import`) wrapped in `self.admin_site.admin_view(...)`. That
    is the pattern to follow.
  - `save_model` reads `images_payload`, a JSON list of `{"data_url": ...}`.
    Leave this alone; the harness depends on it.
  - `BrandAdmin.search_fields = ("name",)`, with the slug prepopulated from the name.
- Deployment: pushing `main` auto-deploys through Coolify and runs migrations.
  **Ask the user before pushing.** Run `git pull --rebase` first, because upstream
  commits land independently. Phase 1 below needs **no migration**.

## 3. Phase 1: read-only lookups plus brand ensure (do this)

All endpoints go under the existing admin URL space, wrapped in
`self.admin_site.admin_view(...)`. That gives staff-only access through the
session cookie, which the importer's browser already has, so no new tokens or
auth are needed. They return `JsonResponse`. GET endpoints must not write
anything. The POST endpoint relies on Django's normal CSRF protection: the
importer reads the `csrftoken` cookie and sends `X-CSRFToken`.

### 3.1 Batch listing-id lookup (the big win)

```
GET /admin/watches/watch/lookup/?source=olx&ids=308040530,301687264,999
```

- `ids`: comma-separated. Keep only digit strings and cap the list at 500 (return
  400 if it's longer). `source` is optional; when given, filter by it too.
- One query: `Watch.objects.filter(external_listing_id__in=ids[, source=...])`.
- Response:

```json
{
  "existing": {
    "308040530": {"pk": 1350, "source": "olx", "is_active": true,
                   "brand": "Rolex", "model_name": "GMT-Master II",
                   "seller_id": "1380866987", "pictures": 3,
                   "change_url": "/admin/watches/watch/1350/change/"}
  },
  "missing": ["999"]
}
```

- Keys are strings, because the client sends strings. Use `annotate(Count("pictures"))`
  for `pictures`, which lets the same call double as the post-save readback.
- If one listing id somehow matches several rows, return a list under that key,
  or pick the newest and add `"duplicates": n`. Say which you chose; the importer
  treats any hit as "already imported".

### 3.2 Repost candidates

```
GET /admin/watches/watch/reposts/?seller_id=1380866987&model=GMT-Master%20II&exclude_id=308040530
```

- Return two lists of rows (same shape as above, plus `external_listing_id`):
  - `by_seller`: `seller_id` equals the given value and the normalized
    `model_name` equals the normalized `model`.
  - `by_model`: normalized `model_name` equals the normalized `model`, from any
    seller, limited to 20.
- "Normalized" means case-insensitive and diacritic-insensitive, and must match
  the importer's `norm()`: NFKD, drop combining marks, lowercase, strip. `iexact`
  alone is enough for a first version. If you want real accent-insensitivity on
  PostgreSQL, `django.contrib.postgres` `Unaccent` is available, but don't add the
  extension unless it's already installed. Check the production DB first. The
  production DB is PostgreSQL on Aiven; local dev may be SQLite.
- Exclude rows whose `external_listing_id == exclude_id`.
- **Do not decide strong vs. weak here.** The importer keeps that rule: only a
  same-seller hit is a strong repost.

### 3.3 Brands

```
GET  /admin/watches/brand/all/                 -> {"brands": [{"id": 10, "name": "Cartier", "slug": "cartier"}, ...]}
GET  /admin/watches/brand/lookup/?names=Rolex,ZIM,Fără%20marcă
                                               -> {"found": {"Rolex": {"id":..,"name":..,"slug":..}}, "missing": ["..."]}
POST /admin/watches/brand/ensure/   body: {"name": "Duxot"}
                                               -> {"id": 263, "name": "Duxot", "slug": "duxot", "created": true}
```

- Matching is by normalized name (see 3.2). The brand table is small (~265 rows),
  so loading all brands and normalizing in Python is fine and portable.
- `ensure` must be idempotent: if a brand with the same normalized name exists,
  return it with `created: false`. Otherwise create it with
  `slug = slugify(unidecode-or-NFKD(name))`, and on slug collision append `-2`,
  `-3` and so on. Wrap it in `transaction.atomic()`. It must never create a second
  row for a name that already exists; that bug is the whole reason for this
  endpoint.
- Reject empty names and `"Alt brand"` (400). User rule: "Alt brand" is never a
  stored brand, and unbranded is `Fără marcă`.
- `all/` lets the importer refresh its brand cache at session start, so a new
  brand no longer needs a hand-edited commit.

Recommended but optional: a one-off management command (report only, no deletes)
that lists brands whose normalized names collide, so the user can merge them.

### 3.4 Totals

```
GET /admin/watches/watch/stats/ -> {"total": 1333, "active": 1290, "by_source": {"olx": 900, "facebook": 433}}
```

This replaces the paginator parsing in `admin_count()`.

### 3.5 Implementation notes

- Add the paths in `WatchAdmin.get_urls()` / a new `BrandAdmin.get_urls()`,
  **before** `super().get_urls()`. Otherwise the admin's `<path:object_id>/`
  catch-all swallows `lookup/`.
- Check permissions with `self.has_view_permission(request)` on reads and
  `has_add_permission` on `ensure`; return 403 JSON when they fail.
- `JsonResponse(..., json_dumps_params={"ensure_ascii": False})`, because brand
  names carry diacritics.
- Tests go in `watches/tests.py` with the Django test client and a staff user:
  - 3.1: ids that exist, ids that don't, junk ids filtered out, more than 500 → 400,
    the `source` filter, the picture count.
  - 3.2: a same-seller match, a model-only match, the excluded id.
  - 3.3: `ensure` twice returns the same id (`created` true, then false);
    `"Fara Marca"` finds `"Fără marcă"`; `"Alt brand"` → 400; a slug collision.
  - All endpoints: anonymous → redirect to login / 403; a GET must not create.

## 4. Phase 2: JSON import endpoint (approved by the user, 2026-10-01)

**Problem it solves:** the write path is the most fragile part of the importer.
It depends on the add form's DOM ids, a 64 KB per-message limit in browser-use
(which forced the photos into 40 KB slices), and scraping two banners that have
flaked. On 2026-09-29 every save failed silently for a day because the photo
fetch inside the admin page was blocked, and nothing on the page said why.

Today the importer injects `import-watch.js` into the add form, fills about 40
inputs through the DOM, pushes base64 photos in 40 KB slices (browser-use caps
each message at 64 KB), clicks `_addanother`, waits, and scrapes the success
banners. A single endpoint would replace all of that:

```
POST /admin/watches/watch/import-json/   multipart: contract=<json>, images[]=<files>
  -> 201 {"pk":..., "change_url":..., "pictures": n}
  -> 409 {"existing_pk":...}          if (source, external_listing_id) already exists
  -> 400 {"errors": {field: [...]}}   from a ModelForm built on Watch
```

- Validate through a `ModelForm` so the rules stay identical to the admin form.
- Reuse the `save_model` picture-saving code by factoring it into a helper.
- Consider a DB unique constraint on `(source, external_listing_id)` where the id
  is not null. **That is a migration**, so check existing data for duplicates
  before adding it.

- Optional: also accept `image_urls[]` and fetch them server-side. The OLX CDN
  answers a plain server GET with 200; it only refuses browser requests that
  carry a foreign `Origin`. Keep the file-upload path as the default either way.
- Return clear JSON errors. A save that fails must say why; that is the point
  of this phase.

The user approved Phase 2. The unique constraint is still a migration: check
the data first and mention it in the PR/commit.

## 4b. Other processes worth moving into Django (proposals: confirm each with the user)

These come from the same importer sessions. Each one lists the problem it solves.
Only 4b.1 needs no schema change.

### 4b.1 Retire listings that are gone from OLX
**Problem:** nothing ever marks a site listing inactive when the OLX ad is sold
or deleted. In the 2026-09-29 session, 20 of 80 queued ads already returned
HTTP 410. Watches like that are very likely still shown as available on
3ceasuri.ro.
**Proposal:** `GET watch/active-ids/?source=olx` (active external ids, paginated)
and `POST watch/deactivate/ {"ids": [...], "reason": "olx_410"}`, which does a
bulk `update(is_active=False)`. The importer already has a logged-in olx.ro tab,
so it checks the status of each id and posts the gone ones. No migration.

### 4b.2 Store import decisions server-side
**Problem:** skips ("suspected counterfeit", "bulk lot", "repost", "not a
watch") are recorded only in local queue files and `history.jsonl`. A new sweep
re-discovers the same ads and a human or agent reviews them again. The Omega
repost came back twice in one session.
**Proposal:** model `ImportDecision(source, external_listing_id, decision
[imported|skipped], reason_code, note, created_at)`, unique on
`(source, external_listing_id)`, with an admin list and filter. Endpoint 3.1
also returns `"decided": {...}` for skipped ids, so discovery drops them in the
same query. Migration required.

### 4b.3 Seller blocklist as data, not a file
**Problem:** never-import sellers live in `references/seller-blocklist.json`
in the harness repo. Editing it means a commit, and the site's staff can't see
or manage it.
**Proposal:** model `BlockedSeller(source, seller_id, name, reason, created_at)`
editable in the admin. Endpoint 3.1 (or a `seller/blocked/?ids=` lookup) reports
matches. Migration required.

### 4b.4 Keep the operator's note on the record
**Problem:** the importer writes a one-sentence note when it infers something
("movement inferred", "model read off the photo", "ad reference is wrong").
`Watch` has no field for it, so the note is lost and staff can't see why a
value is what it is.
**Proposal:** `Watch.internal_note = TextField(blank=True)`, admin-only and never
rendered on the public site. The harness sets `id_internal_note`, or Phase 2
accepts it in the contract. Migration required.

### 4b.5 Normalize județ / localitate on save
**Problem:** the county spelling table (`Brasov`→`Brașov`, city→county seat)
lives in the importer (`admin_import.COUNTY_SPELLING`, `COUNTY_SEATS`). Anything
entered by hand in the admin bypasses it, so filters can split "Iasi" and "Iași".
**Proposal:** move that normalization into `Watch.save()` (or `services.py`,
next to `normalize_ro_phone`), with a data-fix management command for existing
rows. No schema change; the data fix is optional.

## 5. What the importer side will do once this is live

The importer side is not your job; it's listed so you know which contract you're
serving.

- `admin_import.already_imported`, `admin_count`, and the discovery dedup loop →
  one call to 3.1 per sweep or per ad, run through `fetch()` from the admin tab.
- `find_repost` → one call to 3.2.
- `ensure_brand` / `_lookup_brand` → 3.3; the BRAND_IDS cache is refreshed from `all/`.
- `verify()` readback → 3.1 on the saved id (pictures count included).
- If any endpoint returns 404 (not deployed yet), the importer falls back to the
  current scraping, so the deploy order doesn't matter.

## 6. Done means

- Phase 1 endpoints exist, are staff-only, and pass the tests above
  (`uv run python manage.py test watches`; `SECRET_KEY` must be set in the env).
- No migration in phase 1.
- Phase 2 endpoint exists with the same tests, plus: a duplicate returns 409, a
  bad field returns 400 with the field errors, and photos are saved.
- 4b items: only the ones the user confirms.
- A short note in the Django repo's docs listing the URLs and response shapes
  (copy section 3).
- Nothing pushed to `main` without the user's go-ahead, because a push deploys
  to production.
