# Django backend (the 3ceasuri.ro source)

The live site this runbook imports into is a Django project in its own repo,
`github.com:popas/ceasuri`, checked out next to this one:

    ../ceasuri        (relative to this repo's root; the Linux checkout is ../app)

This harness repo is only the browser-automation runbook. When a change requires
touching the actual database schema, admin config, or import view (i.e. not just the
harness JS), edit the Django project above.

## Deployment
Pushing to GitHub (`github.com:popas/ceasuri.git`, branch `main`) **auto-deploys** and
runs pending migrations on production. No manual migrate step needed on prod.

## Key files
- `watches/models.py` — the `Watch` model (fields: `facebook_listing_id`,
  `phone`, `location`, `price`, `brand` FK, `model_name`, `reference_number`,
  `source_url`, `description`, …). `Watch.save()` normalizes phone via
  `services.normalize_ro_phone`.
- `watches/admin.py` — `WatchAdmin`. `search_fields` controls what the dedup
  `?q=` query can match. No `fieldsets` → every editable model field auto-renders
  on the add/change form at DOM id `id_<fieldname>`, so the harness can set it.
- `watches/migrations/` — linear history; latest applied is `0008_watch_phone`.
- `watches/services.py` — helpers incl. `normalize_ro_phone`.

## Dedup-relevant note
Dedup (stage 1, in `admin_import.already_imported`) queries this admin by `?q=`. Only fields in
`WatchAdmin.search_fields` are queryable. To dedup on a new attribute, the attribute
must be BOTH a model field (migrated) AND listed in `search_fields`.

## Admin JSON endpoints (import API, 2026-10-04)

Staff-session endpoints in the admin URL space; the harness calls them through
`scripts/site_api.py` as `fetch()` from a signed-in admin tab. The contract-key →
model-field mapping is its `CONTRACT_TO_MODEL`, held to `import-watch.js` by
`tests/test_contract_mapping.py`. The server side lives in the Django repo's `watches/`.

| Endpoint | Answers |
|---|---|
| `GET /admin/watches/watch/lookup/?ids=a,b` (≤500) | `{existing: {id: row}, missing, duplicates}` — inactive rows count |
| `GET /admin/watches/watch/reposts/?model=&seller_id=&exclude_id=` | `{by_seller, by_model}` rows; the harness decides strong/weak |
| `GET /admin/watches/brand/all/` | `{brands: [{id, name, slug}]}` |
| `GET /admin/watches/brand/lookup/?names=a,b` (≤100) | `{found: {name: brand}, missing}` — matched on normalized names |
| `POST /admin/watches/brand/ensure/` `{name}` | the brand, `created` true/false; "Alt brand" → 400 |
| `POST /admin/watches/watch/import-json/` | 201 `{pk, pictures, image_errors, brand, saved}` · 400 `{errors}` · 409 duplicate · 422 `no_images` |

They ship together, so one probe (`GET lookup/?ids=0`) decides for all six. Deployed ⇔
the answer is JSON and not redirected: a path the admin does not know redirects to
`/admin/` (200 HTML), never 404s. A redirect to `/admin/login/` is a lost session.
The POST endpoints answer a GET with a 405 JSON body.
