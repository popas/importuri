# OLX import — design

**Date:** 2026-08-09
**Status:** IMPLEMENTED (f580729) — `olx_api.py`, the two discovery scripts and the two
importers all ship. Kept as the rationale record; the live loop is
`OLX_Listing_Automation_Plan.md`.

Add olx.ro as a second import source alongside Facebook, feeding the same
3ceasuri.ro admin. Smartwatches come from category **1943**
(`/electronice-si-electrocasnice/gadgets-wearables-si-camere-foto-video/smartwatch-uri/`),
regular watches from category **1677** (`/moda-frumusete/ceasuri/`). Each category
gets its own discovery script, its own importer, and its own skill, so the two
loops never share instructions.

## What the live probe established

OLX rejects a plain HTTP GET with 403 (bot protection), but its JSON API answers
normally from inside a page already on `olx.ro`:

- `GET /api/v1/offers/?offset=N&limit=40&category_id=<id>&sort_by=created_at:desc&filter_float_price:from=<n>`
  — the whole category, paged, with `metadata.total_elements`.
- `GET /api/v1/offers/<id>/` — one ad in full.

An ad returns: numeric `id`, `url`, `title`, `description` (HTML, `<br />` line
breaks), `created_time`, `status`, `business`, `user` (`id`, `name`), `location`
(`city`, `district`, `region`), `category.id`, and `params` — seller-declared
structured attributes that map almost one-to-one onto our DB enums. Photos come as
templated links (`https://frankfurt.apollo.olxcdn.com/v1/files/<hash>-RO/image;s={width}x{height}`)
which are unsigned and durable.

Consequences for the design: no feed scrolling, no carousel walk, no hydration
gates, no expiring image URLs, no DOM lore. Discovery is one API page loop and
extraction is one API call. The two-pass extraction contract stays — the model
name still has to be read off the dial.

## Architecture

```
harness/3ceasuri-import/scripts/
  import-watch.js            shared harness, v6 (source-agnostic admin field ids)
  infer_fields.py            shared contract; gains profiles: classic | smart
  admin_import.py            NEW shared: dedup query, ensure-brand, inject,
                             submit, verify banners, readback
  olx_api.py                 NEW shared-per-source: in-page API fetch, photo URLs
  find-posts.py              FB discovery, unchanged
  import-post.py             FB importer; admin half now delegates to admin_import
  olx-find-smartwatches.py   NEW  category 1943
  olx-find-watches.py        NEW  category 1677
  olx-import-smartwatch.py   NEW
  olx-import-watch.py        NEW
  .candidates-olx-smart.json      NEW discovery output (never clobbers FB's)
  .candidates-olx-watches.json    NEW
```

The four OLX mode scripts are deliberately **separate files, not one script with a
MODE switch**: a change to the smartwatch loop can never break the watch loop. They
stay thin because everything source-agnostic lives in `admin_import.py` and
everything OLX-generic lives in `olx_api.py`.

Like the Facebook scripts, all four are **browser-use payloads**: pipe them on
stdin, never `python3 script.py`. They emit the same parseable marker lines
(`CANDIDATES: STATS: EXTRACT: EXTRACT_PROMPT: SKIP: REVIEW: NEW_BRAND: RESULT: ERROR:`)
and keep everything else inside their own process.

## Discovery — `olx-find-smartwatches.py`, `olx-find-watches.py`

One browser-use process each, same output contract as `find-posts.py`.

1. Resolve an `olx.ro` tab (create and navigate if absent). Same-origin is what
   makes the API answer.
2. Page the offers API in the page context until `MAX_CANDIDATES` survive or
   `MAX_PAGES` is exhausted. `filter_float_price:from` is passed as a server-side
   hint only — the floor is re-applied in Python, because the API accepted the
   parameter during the probe without its effect being confirmed.
3. Apply **objective filters only** — everything requiring judgement stays with
   the operator, who reads the emitted snippets:
   - `status != "active"`
   - no price, or price below `MIN_RON` / `MIN_EUR`
   - replica wording: `replic`, `clon`, `copie`, `aaa+`, `homage`
   - accessory wording: `curea`, `brățară de schimb`, `încărcător`, `husă`,
     `folie`, `doar cutia`, `doar bratara`
   - blocklisted seller (`references/seller-blocklist.json`, new `olx_sellers` list)
   - already imported (Stage-1 admin dedup, batched `?q=<ad id>`)
4. Business sellers are **kept**. Every candidate carries `business` and `seller`
   so the operator can triage shop stock, amanet listings and 2-year-warranty
   resellers by hand.
5. Cross-category leakage is **flagged, not dropped**: an Apple Watch found in
   category 1677 comes back with `looks_smart: true` so it gets routed to the
   smartwatch importer rather than lost.
6. Emit a compact `CANDIDATES:` line plus `STATS:`; write full records to the
   mode's own candidates file so a `/clear`'d context can resume without
   re-querying.

Env: `PROJECT_ROOT`, `MAX_CANDIDATES` (default 8), `MAX_PAGES` (default 5),
`MIN_RON` (default 100), `MIN_EUR` (default 20), `SNIPPET`, `NO_DEDUP=1`,
`DEBUG_DROPS=1`, `OUT`.

## Per-ad import — `olx-import-smartwatch.py`, `olx-import-watch.py`

Two passes, exactly as the Facebook importer, because the agent in the loop does
the inference.

**Pass 1** (`AD_ID=<id>`, no `OVERRIDES`) — writes nothing:
dedup on the ad id → `GET /api/v1/offers/<id>/` → blocklist check on `user.id` →
map OLX params to DB enums → download photos to `.photos/olx-<id>/` at
`s=1000x1000` (fetched in the page context, saved to disk) → emit
`EXTRACT_PROMPT:` with the mode's contract, the prefilled values and the photo
paths → exit.

**Pass 2** (`AD_ID=<id> CONFIRM=1 OVERRIDES='{…}'`):
validate against `infer_fields.validate()` → ensure the brand exists (create +
`NEW_BRAND:` if not) → inject the harness → `importWatch()` → verify both banners
→ read the saved record back → `RESULT:`.

The review gate carries over from `import-post.py`: a new brand, a missing
model/price/movement, fewer than two photos or a thin description emits `REVIEW:`
and imports nothing.

Stage-2 dedup carries over too, and works better here than on Facebook: the ad id
catches a straight re-import, and `seller_id` + `model` catches the same watch
relisted under a new ad id — which is the normal behaviour of the shop and amanet
sellers we are now keeping. A model match with a confirmed seller match skips; a
generic model name with no seller match emits `REVIEW:` instead of deciding.

### OLX params → DB fields

| OLX param | DB field | Notes |
|---|---|---|
| `state` | `condition` | Nou → `new`; Nou cu etichetă → `new`; Purtat o singură dată → `excellent`; În condiții bune → `good`; Utilizat → `good`; Defect → `broken`; unknown → null |
| `material_carcasa` | `caseMat` | Oțel inoxidabil → `steel`, Aur → `gold`, Titan → `titanium`, Ceramică → `ceramic`, Aluminiu → `aluminium`, Plastic → `plastic` |
| `afisaj` | `displayType` | Analogic → `analog`, Digital → `digital`, Analogic-digital → `analog_digital` |
| `rezistenta_la_apa` | `waterRes` | any ATM value → `water_resistant_yes`; Nu → `water_resistant_no` |
| `pentru` | `gender` | Bărbați → `men`, Femei → `women`, Unisex → `unisex`, Copii → `kids` |
| `stil` | `style` | Sport → `sport`, Elegant → `dress`; anything else → null |
| `brand` | `brand` | matched against `BRAND_IDS`, diacritic-insensitive |
| `price` | `price`, `currency`, `priceNote` | `negotiable: true` → `priceNote: "negociabil"` |
| `location` | `location` | `city.name` + `region.name` |
| `description` | `description` | `<br />` → newline, tags stripped |
| `culoare_carcasa` | — | **deliberately unmapped**: it is the case colour, while `displayColor` means the dial |

Unmapped or unrecognised param values become `null` and the contract answers them.

### The contract stays authoritative

Prefilled values appear in the prompt under **"Known from OLX — restate these
unless a photo contradicts them"**. The existing rule is unchanged and has no
exceptions: a contract field the answer omits is **cleared, not defaulted**. OLX
params are strong evidence, not a second source of truth competing with the
filled contract.

### Mode differences

`infer_fields.py` gains a `profile` argument to `build_prompt()`:

- **classic** — today's rules, including the `wall` clock path (pendulums do
  appear in moda/ceasuri) and the `Fără marcă` fallback for unbranded clocks.
- **smart** — pins `movement: smart`, `style: smart`, `displayType: smart`, and
  its review gate blocks on a missing `series`, `connectivity` or
  `compatibility`. Apple Watch → `ios`; Galaxy Watch 4 and newer → `android`;
  Garmin, Amazfit, Huawei, Xiaomi → `both`. Cellular models are identified by
  "LTE"/"Cellular"/"4G"/"eSIM" wording or, on Apple Watch, the red ring on the
  crown. The smartwatch category's brands are mostly absent from `BRAND_IDS`, so
  the `NEW_BRAND:` path is the normal case there, not the exception.

`ENUMS`, `SCHEMA_FIELDS` and `validate()` are shared unchanged — the DB is the same.

## Django changes (separate repo: `~/projects/anunturi/ceasuri`)

The three FB-shaped columns are referenced only by `models.py`, `admin.py` and one
test — no templates, no public views — so generalising them is cheap.

Migration `0015`:

- add `source = CharField(choices=Source.choices, default="facebook", db_index=True)`
  with `Source = {facebook, olx}`. Every existing row is a Facebook import, so the
  default backfills correctly.
- `RenameField`: `facebook_listing_id → external_listing_id`,
  `facebook_author_id → seller_id`, `facebook_author_name → seller_name`.

`WatchAdmin` gains `source` in `list_display` and `list_filter`; `search_fields`,
`list_display` and the `EmptyFieldListFilter` entry follow the renames.
`watches/tests.py::test_facebook_listing_id_optional_and_persisted` is renamed to
match. `external_listing_id` stays a `PositiveBigIntegerField` — OLX ad ids are
numeric (9 digits) and cannot collide with Facebook post ids (16 digits).

## Harness v6

`import-watch.js` writes the renamed fields through a tolerant setter:

```js
const setAny = (ids, val) => {
  for (const id of ids) if (document.getElementById(id)) return set(id, val);
};
setAny(['id_external_listing_id', 'id_facebook_listing_id'], data.externalId);
setAny(['id_seller_id',           'id_facebook_author_id'],  data.sellerId);
setAny(['id_seller_name',         'id_facebook_author_name'], data.sellerName);
set('id_source', data.source);
```

So the Facebook importer keeps working before, during and after the Django deploy,
and there is no ordering dependency between the two repos. `import-post.py` is
updated to emit `source: "facebook"`, `externalId`, `sellerId`, `sellerName`
instead of `fbListingId` / `fbAuthorId` / `fbAuthorName`, and its readback reads
the new element ids with the same fallback.

## Docs and skills

- `OLX_Listing_Automation_Plan.md` — sibling orchestrator, same shape and length
  as `Watch_Listing_Automation_Plan.md`: the loop, the iron rules that still
  apply, and pointers to the OLX skills.
- `CLAUDE.md` — a "pick your source" read-order at the top; the two orchestrators
  sit side by side.
- New skills in `.claude/skills/`: `olx-session-setup`, `olx-find-smartwatches`,
  `olx-find-watches`, `olx-import-smartwatch`, `olx-import-watch`,
  `olx-troubleshooting`.
- `import-verify-state` is reused unchanged for both sources.
- `history.jsonl` entries gain `"source": "olx"` going forward. Existing lines are
  left alone — they are all Facebook.
- `references/seller-blocklist.json` gains an `olx_sellers` list alongside
  `authors`.

The iron rules that carry over to OLX: one watch at a time; verify by page content
(both banners), not by return value; re-inject the harness after every navigation;
always fill `description`, `sourceUrl` and the external id. The rule about never
modifying image URLs is Facebook-specific — OLX links are unsigned, and the
importer deliberately rewrites `{width}x{height}` to `1000x1000`.

## Tests

`tests/` (offline stubs, `python3 tests/test_*.py`, no browser):

- `test_olx_find.py` — canned API JSON through a stubbed `js()`; asserts each
  objective filter drops what it should and keeps what it should, that business
  sellers survive, and that `looks_smart` is flagged rather than dropped.
- `test_olx_import.py` — canned single-ad JSON; asserts the param map, the
  `<br />` description cleanup, the photo URL rewrite, and that pass 1 writes
  nothing.
- a table test for the param→enum map, including unknown values falling to null.
- `test_import_post.py` and `test_find_posts.py` are re-run unchanged to cover the
  `admin_import.py` extraction.

## Out of scope

- Phone numbers behind OLX's "arată numărul" button — not fetched.
- OLX chat, delivery and safedeal metadata.
- Backfilling `source` on `history.jsonl`.
- Any change to the Facebook scrape path beyond delegating its admin half.
