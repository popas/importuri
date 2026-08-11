---
name: admin-import-watch
description: Invoke per watch — first for the duplicate check (?q=POST_ID) BEFORE extracting images, then after extraction to re-inject the harness and call importWatch() on the admin add-watch tab.
---

# admin-import-watch

The admin side of importing ONE watch. `$PROJECT_ROOT` / `$CDP_HOST` from `watch-session-setup`.

## One-shot importer — THE DEFAULT PATH

`$PROJECT_ROOT/harness/3ceasuri-import/scripts/import-post.py` collapses this skill +
`fb-extract-post` + `import-verify-state` into a single `browser-use` call for one post. It
runs **both dedup stages**, gates on `pcb.<ID>`, **captures the video permalink of
video-first posts (→ `video_url`) and skips blocklisted sellers**, collects the carousel, infers fields (RO→enum + defaults + the
gold-plating rule), creates the brand if missing, injects the harness, calls `importWatch`,
verifies both banners, and **reads the saved record back**.

```bash
export BU_CDP_URL="http://$CDP_HOST"
POST_ID=<id>    browser-use < $PROJECT_ROOT/harness/3ceasuri-import/scripts/import-post.py
LISTING_ID=<id> browser-use < $PROJECT_ROOT/harness/3ceasuri-import/scripts/import-post.py  # kind:"listing"
```

**Do not run a DRY_RUN pass first.** It doubles the browser work and the output on posts that
need no supervision. The script judges its own confidence and stops on its own when it should:
if the brand is new, the model or price didn't infer, fewer than 2 images came back, or the
description is thin, it emits `REVIEW:` and imports **nothing** — no DB write, no brand
created. Fix what it flagged and re-run:

```bash
POST_ID=<id> CONFIRM=1 OVERRIDES='{"brand":"Westbury","model":"Chronograph Valjoux 7733"}' \
  browser-use < $PROJECT_ROOT/harness/3ceasuri-import/scripts/import-post.py
```

`CONFIRM=1` passes the review gate; it cannot wave through a missing brand/model/price — the
form would reject those. `DRY_RUN=1` still exists for deliberate inspection.

## The extraction contract — YOU do the inference

**There is no API call anywhere in this pipeline.** The script's regexes are a baseline that is
reliably wrong on the same fields (`model` = the post's whole first sentence, `reference` cut at
the first dot, `movement` defaulted to `quartz`). You are the model in the loop, so the first
pass hands you the contract instead of importing on that baseline:

```
POST_ID=<id> browser-use < .../import-post.py     # pass 1: emits EXTRACT_PROMPT, writes nothing
POST_ID=<id> CONFIRM=1 OVERRIDES='{…}' browser-use < .../import-post.py   # pass 2: imports
```

`EXTRACT_PROMPT.prompt` (from `scripts/infer_fields.py`) carries the field list with every legal
DB enum value, the rules that exist because they were broken before, and the post text. **Read
it and answer it** — fill the JSON, pass it as `OVERRIDES`, re-run with `CONFIRM=1`.

**A filled contract is authoritative about silence too.** Any contract field you leave out is
**cleared**, not left to the regex guess — the Tissot listing never stated a case material and
the regex still proposed `steel`. So answer the contract in full: a field you omit is you saying
the post does not state it. `price`, `brand`, and `model` are hard requirements, so omitting
those fails the run rather than importing something half-empty. A **targeted** `OVERRIDES` fix
(one without `is_wristwatch`) still merges over the baseline the old way — that is the signal
that distinguishes the two, since the contract requires `is_wristwatch` and never allows null.

Two contract-only fields never reach the form: `is_wristwatch: false` and `is_bulk_lot: true`
each stop the import (`CONFIRM=1` overrides). `OVERRIDES` are validated against the enums first,
so an illegal value (`movement: "mecanic"`, a decade in `year`) fails loudly instead of being
dropped silently by the admin form.

`SKIP_PROMPT=1` imports on the regex baseline without the contract pass — only for posts where
the baseline is obviously right, and expect to hand-fix `model`.

Marker lines: `EXTRACT: SKIP: INFER: EXTRACT_PROMPT: REVIEW: NEW_BRAND: RESULT: ERROR:`. After a `NEW_BRAND:`
line update `BRAND_IDS` + `references/brand-ids.md` and commit. Parse `RESULT:` to append to
`history.jsonl` (see `import-verify-state`). Fall back to the manual steps below only when the
post needs hand-holding.

## Step 1: Duplicate check — TWO STAGES (SEPARATE tab; never navigate the add-watch tab)

Dedup on two things: the exact post id (Stage 1) **and** the author+watch fingerprint
(Stage 2, which catches the SAME watch reposted under a NEW post id — Stage 1 cannot).

On browser-use ≥3.0 (old `--cdp-url ... tab new` syntax is dead — see `watch-session-setup`):

### Stage 1 — exact `facebook_listing_id` (BEFORE extracting images)

```python
t = new_tab("https://3ceasuri.ro/admin/watches/watch/?q=POST_ID")
time.sleep(3)
js('(() => document.querySelector(".paginator").innerText)()')   # "0 watchs" = new
```

- results found → **skip this post** (already imported), close tab, next
- "0 watchs" → proceed to extraction, then Stage 2

### Stage 2 — author + brand/model fingerprint

Needs the post author id (`fbAuthorId`) from `fb-extract-post`, so it runs **after
extraction, before `importWatch`**. Same separate tab:

```python
goto_url("https://3ceasuri.ro/admin/watches/watch/?q=AUTHOR_ID")   # search hits facebook_author_id
time.sleep(3)
rows = js("(() => JSON.stringify([...document.querySelectorAll('#result_list tbody tr')].map(tr=>({"
          "brand:(tr.querySelector('td.field-brand')||{}).innerText,"
          "model:(tr.querySelector('td.field-model_name')||{}).innerText,"
          "fbid:(tr.querySelector('td.field-facebook_listing_id')||{}).innerText}))))()")
close_tab(t)
```

- a returned row whose **model matches** this post → **repost → skip** (log which `fbid` it
  matched). Price is NOT required to match — a repost with a dropped price is still a repost.
  **Match on model, not brand:** the changelist renders the BRAND cell as empty text even for
  records that definitely have one (verified 2026-07-27), so a `brand AND model` rule never
  fires — that was dead code, and a known Helfer repost went straight through it. Brand is
  only useful to *veto* a match when it is non-empty and different.
- Search by the **model string as well as the author id**. Records imported before author
  capture existed have no `facebook_author_id`, so an author-only lookup cannot see them.
- A model-only match on a *generic* name (short, one word, no digits) is reported as
  `REVIEW:` instead of skipped — neither silently dropping a new watch nor silently
  importing a duplicate.
- the author has only *different* watches (e.g. one seller listing 4 distinct pieces) → not
  a match → import normally.
- no `fbAuthorId` captured → fall back to `?q=PHONE` for Stage 2, or skip Stage 2
  (Stage-1-only, the old behavior) when there's no phone either.

`import-post.py` performs **both stages automatically** (Stage 1 up front, Stage 2 after
inference), so the one-shot path needs no manual dedup.

**Both scripts already do this for you.** `find-posts.py` batches Stage 1 across every
candidate at discovery time (the admin is our own site, so it has no FB-style rate concern),
and `import-post.py` re-runs Stage 1 up front plus Stage 2 after inference. The manual steps
above are for the fallback path only. Iron rule #1 still holds: only ONE watch gets
extracted+imported at a time; batching cheap durable lookups is not batching watches.

The admin is also the **only** trustworthy answer to "have I imported this already" — the
local tracker is session bookkeeping, not a record of the site (see `import-verify-state`).

## Step 2: Re-inject the harness (repeat before EVERY watch)

The harness (v5, authoritative) exposes `window.importWatch(data)`. It is **LOST on every page navigation/submit** — re-inject before each watch.

```python
import json
with open('$PROJECT_ROOT/harness/3ceasuri-import/scripts/import-watch.js') as f:
    script = f.read()
wrapper = "(() => { const s = document.createElement('script'); s.textContent = " + json.dumps(script) + "; document.head.appendChild(s); return window.importWatch ? 'OK' : 'NO_FUNC'; })()"
```

Pass `wrapper` to `browser_console(expression=wrapper)`. Expect `"OK"`. If injection fails twice (size limit), see `watch-troubleshooting` for the manual field-filling fallback.

**Under browser-use, write `wrapper` to a temp file and read it back inside the heredoc** —
don't inline a ~14KB string (or Romanian text / signed URLs) into the heredoc, where quoting
and encoding bite:

```python
# generation step (plain python3): open('/tmp/.../wrapper.js','w').write(wrapper)
# browser-use step:
js(open('/tmp/.../wrapper.js').read())          # -> 'OK'
js('(() => String(window.BRAND_IDS["Sandoz"]))()')   # sanity-check a new brand landed
```

Build the `importWatch(...)` call the same way — `json.dumps(data, ensure_ascii=False)` into
a `call.js` file. This survived 5/5 imports incl. diacritics and 10-image payloads.

## Step 3: Call importWatch

Pass **raw** FB URLs — the harness fetches internally with retry:

```javascript
await importWatch({
  brand: "Orient",
  model: "Bambino Automatic",
  price: 1200,
  images: ["https://scontent-...jpg?stp=...&_nc_ohc=...&oh=..."],  // COMPLETE URLs, no modification
  condition: "good",
  movement: "automatic",
  type: "men",
  diameter: 40,
  caseMat: "steel",
  braceletMat: "leather",
  year: 1965,                       // id_year is <input type="number"> — ONE year, never a range
  waterRes: "water_resistant_yes",
  displayMat: "sapphire",
  reference: "ABC-1234",
  description: "Raw FB post text here — harness auto-formats to professional description",
  sourceUrl: "https://www.facebook.com/groups/vanzareceasuri/posts/POST_ID/",
  source: "facebook",
  externalId: "POST_ID",
  sellerId: "100078...",         // FB poster's numeric id — Stage-2 dedup key
  sellerName: "Costi Schiverniciuc",
  phone: "0731394148",
  location: "Satu Mare, Bihor",
  seller: "Razvan Vasile",
  currency: "RON",
  priceNote: "negociabil"
});
```

**Field notes:** `description` is raw FB text (harness formats it); `currency` auto-detected if omitted (`$`→USD, `€`→EUR, `lei`→RON); `phone` stripped of spaces/dots; `location` = "City, County"; `seller` = full name; `fbAuthorId`/`fbAuthorName` = the FB poster's numeric id + display name (from `fb-extract-post`; `fbAuthorId` is the Stage-2 dedup key — stored in `facebook_author_id`); `year` = a SINGLE year (`id_year` is `<input type="number">`; a range like "1970-1980" is silently dropped — verified 2026-08-04, leave it empty when the post only gives a decade); `movement` is required by the DB and the harness defaults it to `quartz`, so `import-post.py` now stops for REVIEW when the post never states one — pass `OVERRIDES {"movement":"manual"}` rather than letting a vintage mechanical be labelled quartz; `reference` from "ref. ABC-1234"; `priceNote` = free text ("negociabil"). See the field-value table for `waterRes`/`displayMat` and all other enums.

**NEVER modify image URLs.** No regex upgrades, no param stripping. The harness fetches them as-is with automatic retry (3 attempts).

**ALWAYS provide `description`, `sourceUrl`, and `fbListingId` for every watch.** Without `description` the watch page has no "Descriere" section; without `sourceUrl` there is no "Vezi sursa originală" back-link.

## Brand selection

The harness selects the brand by ID from `window.BRAND_IDS` automatically (direct `<option>` injection; Select2 search only as fallback for unknown brands). Mapping source of truth: `$PROJECT_ROOT/harness/3ceasuri-import/references/brand-ids.md`. **Never `browser_type` or click Select2 for the Brand field.** For unknown brands, see "New brand procedure". Manual brand injection (used by the troubleshooting fallback):

```javascript
var brandId = 25; // Orient
var select = document.getElementById('id_brand');
var opt = document.createElement('option');
opt.value = brandId; opt.textContent = 'Orient'; opt.selected = true;
select.appendChild(opt);
select.value = brandId;
select.dispatchEvent(new Event('change', {bubbles: true}));
document.querySelector('#select2-id_brand-container').textContent = 'Orient';
```

## New brand procedure

1. Navigate to `https://3ceasuri.ro/admin/watches/brand/add/`
2. Fill Name + Slug, Save
3. Note the new ID from the redirect URL (`/brand/<ID>/change/`)
4. Add it BOTH to `window.BRAND_IDS` in `$PROJECT_ROOT/harness/3ceasuri-import/scripts/import-watch.js` AND to `$PROJECT_ROOT/harness/3ceasuri-import/references/brand-ids.md` (keep the two in sync)
5. Re-inject the harness

## Quality gates (per watch, at submit)

- [ ] Brand selected (value is numeric ID); Model name, Price (numeric), Condition, Movement filled
- [ ] **Description, Source URL, Facebook listing ID filled** (`id_description`, `id_source_url`, `id_facebook_listing_id` — see always-fill rule above)
- [ ] ALL images collected (count matches expected)
- [ ] All images fetched successfully (no "Bad URL hash")
- [ ] images_payload.length > 500 (real base64 data)
- [ ] Submit returns BOTH green banners

A payload of ~200 chars containing `QmFkIFVSTCBoYXNo` means ALL images failed with "Bad URL hash" — re-extract fresh URLs from Facebook and retry. **If any image fails → do NOT skip the watch → re-extract URLs and retry.**

## Form field values reference

| Field | ID | Valid Values |
|-------|-----|-------------|
| Condition | id_condition | new, excellent, good, fair, broken |
| Movement | id_movement | automatic, manual, quartz, smart |
| Case material | id_case_material | titanium, carbon, aluminium, steel, gold, silver, plastic, ceramic, other |
| Bracelet | id_bracelet_material | titanium, carbon, aluminium, steel, gold, silver, plastic, rubber, leather, nylon, other |
| Gender | id_gender | women, men, unisex, kids |
| Style | id_style | sport, dress, diver, chronograph, smart |
| Water resistance | id_water_resistance | water_resistant_yes, water_resistant_no |
| Display material | id_display_material | sapphire, mineral, acrylic, plastic, other |
| Display color | id_display_color | black, white, silver, gold, other |
| Display type | id_display_type | digital, analog, analog_digital, smart, none |
| Display size | id_display_size | small, medium, large |
| Currency | id_currency | RON, EUR |
| Description | id_description | Free text (Facebook post body) — **ALWAYS FILL** |
| Source URL | id_source_url | Full Facebook post URL — **ALWAYS FILL** ("Vezi sursa originală") |
| Facebook Listing ID | id_facebook_listing_id | Numeric post/listing ID — **ALWAYS FILL** |

Romanian → English mappings:
- Nou → new | Excelent/Ca nou → excellent | Bun/Folosit → good | Acceptabil/Uzat → fair | Defect/Stricat → broken
- Automat → automatic | Mecanism → manual | Quartz → quartz
- Otel → steel | Aur → gold | Titan → titanium | Piele → leather | Cauciuc → rubber
- Barbati → men | Femei → women

## Pitfalls

- Harness lost on every navigation/submit — re-inject.
- `browser_type` types into the wrong element — always JS `.value` + `change` event.
- images_payload / field values are lost if the form re-renders (e.g. validation error) — re-inject.
- Currency values are `"RON"` / `"EUR"` (value attr), NOT display text (`"Lei"` / `"Euro"`).

**Next:** after calling `importWatch`, invoke `import-verify-state` — do NOT trust the return value.

