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
| `POST /admin/watches/watch/import-json/` | 201 `{pk, pictures, image_errors, brand, saved}` · 400 `{errors}` (+ `models` for an unknown model) · 409 duplicate · 409 `duplicate_photos` · 422 `no_images` |
| `GET /admin/watches/watchmodel/list/?brand=Apple` | `{brand, models: [{name, listings}]}` — 404 `unknown_brand` |
| `POST /admin/watches/watchmodel/ensure/` `{brand, model_name}` | `{model_name, created}` — the site's spelling; 404 `unknown_brand` |

The first six ship together, so one probe (`GET lookup/?ids=0`) decides for them; the
two model endpoints came later, and `site_api` reads any other answer from them as None. Deployed ⇔
the answer is JSON and not redirected: a path the admin does not know redirects to
`/admin/` (200 HTML), never 404s. A redirect to `/admin/login/` is a lost session.
The POST endpoints answer a GET with a 405 JSON body.

### import-json refuses a model the brand does not have (2026-10-08)

A brand's models are those its listings carry plus those added ahead with
`watchmodel/ensure/` (or in the admin, *Modele*). Spelling, spaces, hyphens, case and a
spec tail ("46mm GPS") do not make a model new, and the site stores its own spelling.
Any other `model_name` is `400 {"errors": {"model_name": [...]}, "models": [the brand's
names]}`, nothing saved — unless the body sends `create_model: true`; a brand created by
the same import brings its first model. The harness never sends `create_model`: pass 1
shows the agent the brand's list (`site_api.brand_models`, the prompt's *Models … already
has on the site*), pass 2 calls `ensure` first when the contract says `new_model: true`
(`NEW_MODEL:` marker), and turns the 400 into an `unknown_model` fix on `model`.

What sets a watch apart from others of its model (dial, edition, nickname, strap) goes
in the contract's `variant`, sent as the Watch field `variant`: the site shows model +
variant as the listing's name, and only the model in its filters.

### import-json refuses a relist by its photos (2026-10-07)

The server hashes the photos it fetched (or was sent) and compares them with every
stored picture's `content_sha256`. A photo on 5+ listings is a shop's banner card and
does not count; 2 of the rest (1 when only one is left) on one ACTIVE listing →
`409 {"error": "duplicate_photos", "duplicate_of": <pk>, "external_listing_id",
"source", "shared", "change_url"}`, nothing saved. `site_api.import_json` sends
`"allow_duplicate_photos": true` only under `ALLOW_DUPLICATE_PHOTOS=1`; `olx_import.py`
turns the 409 into a `duplicate_photos` skip (never a retry, never the DOM path).
`dry_run` now fetches the photos and runs the check too.

The runbook never sends a shop's cards (`photo_dedup.shop_cards`,
`references/shop-cards.json`), so new listings never add cards to the site and two of a
shop's watches never share them; the server's 5-listing rule is only the safety net for
cards already stored.

It complements, not replaces, `photo_dedup.py`: that one runs in pass 1, before the
draft is written, but sees only this machine's `.photos/`; the server sees every
listing, but only in pass 2. `API=off` (the DOM path) skips the server check.
Server-side: `manage.py hash_pictures` backfills hashes of older pictures (run once
after the deploy — unhashed pictures are invisible to the check), and
`manage.py photo_duplicates` lists active listings that already share photos.
