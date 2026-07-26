# Django backend (the 3ceasuri.ro source)

The live site this runbook imports into is a Django project whose source lives at:

    /Users/stelian/projects/anunturi/ceasuri

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
Dedup (`admin-import-watch` Step 1) queries this admin by `?q=`. Only fields in
`WatchAdmin.search_fields` are queryable. To dedup on a new attribute, the attribute
must be BOTH a model field (migrated) AND listed in `search_fields`.
