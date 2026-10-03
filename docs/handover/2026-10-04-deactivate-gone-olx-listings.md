# Handover: end listings whose OLX ad is gone (two admin JSON endpoints)

**For:** an agent working in the Django repo (`../app` next to this repo, GitHub `popas/ceasuri`).
**From:** the OLX import runbook (`../importuri`, next to the Django repo), 2026-10-04.
**Approved by the user:** 2026-10-04. This is item 4b.1 of
`2026-10-01-django-admin-lookup-api.md`, made concrete. It needs **no migration**.

---

## 0. The problem, with numbers

Nothing ever ends a listing on 3ceasuri.ro when its OLX ad is sold, deleted or expired.
On 2026-10-04 the admin held 1437 watches, **all active** — 1323 of them from OLX, and
not one OLX listing had ever been deactivated. A random sample of 60 of those 1323 was
checked against the OLX API:

| OLX answer | Listings |
|---|---|
| ad active | 37 |
| HTTP 410 (ad gone) | 22 |
| HTTP 404 (ad deleted) | 1 |

So about **38% (roughly 340–670 of 1323)** are shown as "Disponibil la … lei", with the
seller's phone number, for watches that are no longer for sale. The rate was the same
for August and late-September imports — one imported on 1 Oct was gone by 4 Oct — so
this has to run often (daily or weekly), not as a one-off cleanup.

The site already knows how to show an ended listing: `is_active=False` plus a
`status` and `deactivated_at` keep the URL alive as an archived price record
("anunț încheiat", `OutOfStock` / `SoldOut` in schema.org, out of every list). What is
missing is a machine way to flip it. The importer has a logged-in OLX tab and checks
each ad; it needs two endpoints on this side.

## 1. What exists now (read before changing)

- `watches/models.py`
  - `Watch.is_active` (indexed), `Watch.status` (`ListingStatus`: `active` | `sold` |
    `expired` | `withdrawn`), `Watch.deactivated_at`, `Watch.updated_at` (`auto_now`).
  - `Watch.source` (`facebook` | `olx`), `Watch.external_listing_id` (indexed, nullable).
  - `Watch.save()` normalizes `model_name`, recomputes `model_slug` and the phone.
- `watches/signals.py`
  - `record_listing_deactivation` (**pre_save**) keeps `is_active`, `status` and
    `deactivated_at` telling one story: a non-active `status` forces
    `is_active=False`, unticking `is_active` sets `status=withdrawn`, and
    `deactivated_at` is stamped the first time a listing goes down. **It only runs on
    `save()`** — a `QuerySet.update()` would skip it and leave the three fields
    disagreeing, and would also skip the price-history stamp.
  - `announce_listing_change` (**post_save**) pings IndexNow for every saved listing,
    each in **its own thread** (`indexnow.submit_in_background`). A bulk endpoint that
    saves 500 rows must not start 500 threads; see 2.3.
  - `indexnow.submit_batch(urls)` already exists (one POST, up to 10 000 URLs; it
    raises on failure).
- `watches/admin.py`: `WatchAdmin.get_urls()` adds `import/` before `super().get_urls()`
  and wraps it in `self.admin_site.admin_view(...)`. Follow that pattern.
- Deployment: pushing `main` auto-deploys through Coolify. **Ask the user before
  pushing**, and `git pull --rebase` first.

## 2. The endpoints

Both live in the admin URL space, wrapped in `self.admin_site.admin_view(...)` (staff
session, no new auth), and are added **before** `super().get_urls()` so the admin's
`<path:object_id>/` catch-all does not swallow them. Both return `JsonResponse(...,
json_dumps_params={"ensure_ascii": False})`.

### 2.1 List the active listings of a source

```
GET /admin/watches/watch/active-ids/?source=olx&after_pk=0&limit=500
```

- `has_view_permission(request)` or 403 JSON.
- `source` is required (400 without it) and must be a `Source` value.
- Rows: `is_active=True`, `source=<source>`, `external_listing_id` not null, ordered by
  `pk`, `pk > after_pk`, at most `limit` (default 500, max 1000; 400 above).
- Keyset pagination: `next_after_pk` is the last row's pk, or `null` on the last page.
- Response:

```json
{
  "count": 1323,
  "results": [
    {"pk": 1448, "external_listing_id": "298861458", "created_at": "2026-10-03T23:41:07+03:00"}
  ],
  "next_after_pk": 1448
}
```

- `count` is the total for the filter (not just this page). `external_listing_id` is a
  **string**, because the client compares strings.
- Must not write anything.

### 2.2 End a batch of listings

```
POST /admin/watches/watch/deactivate/
Content-Type: application/json        X-CSRFToken: <csrftoken cookie>

{
  "source": "olx",
  "dry_run": false,
  "items": [
    {"external_listing_id": "308842880", "status": "withdrawn", "reason": "olx_http_410"},
    {"external_listing_id": "305699583", "status": "expired",   "reason": "olx_outdated"}
  ]
}
```

- `has_change_permission(request)` or 403 JSON. Normal Django CSRF; the importer sends
  the cookie's token in `X-CSRFToken`.
- 400 when: the body is not JSON, `source` is missing/invalid, `items` is empty or has
  more than **500** entries.
- `status` per item must be **`withdrawn` or `expired`**. Reject `sold` and `active`
  per item (in `rejected`, not a 400 for the whole batch): OLX never says an ad was
  *sold*, and the model's own docstring is clear that nothing should assert a sale that
  may not have happened. A human can still mark a sale in the admin.
- `reason` is a short code (≤ 40 chars) recorded in the admin history (below).
- For each item, look up `Watch.objects.filter(source=source, external_listing_id=id)`:
  - no row → `not_found`;
  - only inactive rows → `already_inactive` (do not touch them: their `status` and
    `deactivated_at` are history and must not be rewritten);
  - otherwise, for **every** active row with that id (duplicates exist in principle):
    ```python
    watch.status = item["status"]
    watch.save(update_fields=["status", "is_active", "deactivated_at", "updated_at"])
    ```
    The pre_save signal then sets `is_active=False` and stamps `deactivated_at`.
    `update_fields` keeps the rest of the row (model name, slug, phone) exactly as it
    is — a deactivation must not re-normalize an old record.
  - Then `self.log_change(request, watch, f"Dezactivat automat ({item['reason']})")`, so
    the record's history in the admin says why it went down. There is no other field
    for the reason (see 4b.4 in the 2026-10-01 handover).
- `dry_run: true` → same validation and same response shape, **nothing saved**, no log
  entries, no IndexNow. The importer uses it for the first run.
- Wrap the batch in `transaction.atomic()`.
- Response (200):

```json
{
  "dry_run": false,
  "deactivated": ["308842880"],
  "already_inactive": [],
  "not_found": ["999"],
  "rejected": {"123": "status must be withdrawn or expired"}
}
```

### 2.3 IndexNow: one batch, not one thread per row

An ended listing should be recrawled (its title now says "anunț încheiat"), but not
through 500 threads. Suggested shape:

- Let `announce_listing_change` skip an instance carrying a flag, e.g.
  `if getattr(instance, "_skip_indexnow", False): return`.
- In the endpoint set `watch._skip_indexnow = True` before `save()`, collect
  `SITE_INFO["url"] + watch.get_absolute_url()` for the saved rows, and after commit
  send them in one go from a background thread:
  `transaction.on_commit(lambda: threading.Thread(target=_safe_batch, args=(urls,), daemon=True).start())`
  where `_safe_batch` calls `indexnow.submit_batch(urls)` and logs (not raises) on
  failure — a missed ping costs nothing.
- Nothing is sent when `settings.INDEXNOW_KEY` is empty or on `dry_run`.

### 2.4 Optional (cheap, and useful to staff)

An admin action on the changelist, "Marchează ca retras", that does the same per-row
`save(update_fields=...)` for the selected rows. Not needed by the importer.

## 3. Tests (`watches/tests.py`, Django test client, a staff user)

- **active-ids**: only active rows of the source with a listing id are returned; the
  `count` is the filter total; keyset paging (`after_pk`, `next_after_pk` null on the
  last page); `limit` > 1000 → 400; missing/invalid `source` → 400; anonymous →
  redirect to login; it writes nothing.
- **deactivate**:
  - a 410 item → row `is_active=False`, `status=withdrawn`, `deactivated_at` set,
    `model_name` / `model_slug` unchanged (use a name `normalize_model_name` *would*
    rewrite, to prove `update_fields` protects it), one `LogEntry` with the reason;
  - `expired` works the same; `sold` and `active` land in `rejected`;
  - an already-inactive row → `already_inactive`, its old `deactivated_at` untouched;
  - an unknown id → `not_found`; two active rows with the same id → both ended;
  - `dry_run: true` → nothing changes, no `LogEntry`;
  - 501 items → 400; bad JSON → 400; missing CSRF token → 403 (use
    `Client(enforce_csrf_checks=True)`); a staff user without change permission → 403;
  - IndexNow: with `INDEXNOW_KEY` set and `indexnow.submit_batch` / `submit_in_background`
    mocked, a batch of 3 calls `submit_batch` **once** with 3 URLs and
    `submit_in_background` **never** (use `self.captureOnCommitCallbacks(execute=True)`).
- Run: `SECRET_KEY=x uv run python manage.py test watches`.

## 4. What the importer does with this (not your job; it is the contract you serve)

`harness/3ceasuri-import/scripts/olx-check-active.py` in the runbook repo (already
written, works today without these endpoints):

1. Lists the active OLX ids — from `active-ids/`, or by scraping the changelist while
   the endpoint returns 404.
2. Fetches `/api/v1/offers/<id>/` for each from the logged-in OLX tab, about one per
   1.5 s. **410 / 404 → `withdrawn`**, `status: outdated` → `expired`,
   `status: removed_by_user` → `withdrawn`. Anything else that is not a clean
   "active" (a 403, a 429, a bot-check page, a timeout, an unfamiliar status) is
   **unknown and never sent** — and a run of blocked answers stops the sweep.
3. With `APPLY=1`, posts the gone ones to `deactivate/` in batches of 200; while the
   endpoint returns 404 it only writes the report.

## 5. Done means

- Both endpoints exist, are staff-only, and pass the tests above. No migration.
- A deactivation leaves `is_active`, `status` and `deactivated_at` consistent (through
  the signal) and the rest of the row byte-for-byte unchanged.
- A batch sends at most one IndexNow request.
- A short note in the Django repo's docs listing the two URLs and response shapes
  (copy section 2).
- Nothing pushed to `main` without the user's go-ahead — a push deploys to production.
