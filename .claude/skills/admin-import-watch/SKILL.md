---
name: admin-import-watch
description: Invoke per watch — first for the duplicate check (?q=POST_ID) BEFORE extracting images, then after extraction to re-inject the harness and call importWatch() on the admin add-watch tab.
---

# admin-import-watch

The admin side of importing ONE watch. `$PROJECT_ROOT` / `$CDP_HOST` from `watch-session-setup`.

## One-shot importer (preferred when the post ID is known)

`$PROJECT_ROOT/harness/3ceasuri-import/scripts/import-post.py` collapses this skill +
`fb-extract-post` + `import-verify-state` into a single `browser-use` call for one post. It
gates on `pcb.<ID>`, **skips video-first (ad) posts**, collects the carousel, infers fields
(RO→enum + defaults + the gold-plating rule from `fb-extract-post`), creates the brand if
missing, injects the harness, calls `importWatch`, verifies both banners, and **reads the
saved record back** (the `id_reference_number` / `id_case_diameter_mm` check).

```bash
export BU_CDP_URL="http://$CDP_HOST"
# review first — DRY_RUN extracts + infers + prints, imports nothing:
POST_ID=<id> DRY_RUN=1 browser-use < $PROJECT_ROOT/harness/3ceasuri-import/scripts/import-post.py
# then import (override anything the inference got wrong):
POST_ID=<id> OVERRIDES='{"model":"...","caseMat":"steel"}' \
  browser-use < $PROJECT_ROOT/harness/3ceasuri-import/scripts/import-post.py
```

Still run the **duplicate check (Step 1 below) first**, and after a `NEW_BRAND:` line update
`BRAND_IDS` + `references/brand-ids.md` and commit. Parse the `RESULT:` line (banners +
readback) to update `state.json`. Fall back to the manual steps below when inference is
unreliable or the post needs hand-holding.

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

- a returned row whose **brand AND model match** this post → **repost → skip** (log which
  `fbid` it matched). Price is NOT required to match — a repost with a dropped price is
  still a repost.
- the author has only *different* watches (e.g. one seller listing 4 distinct pieces) → not
  a match → import normally.
- no `fbAuthorId` captured → fall back to `?q=PHONE` for Stage 2, or skip Stage 2
  (Stage-1-only, the old behavior) when there's no phone either.

`import-post.py` performs **both stages automatically** (Stage 1 up front, Stage 2 after
inference), so the one-shot path needs no manual dedup.

**Batch Stage 1 against your cached post IDs.** One `new_tab`, then `goto_url` per ID
(~2.5s apart) — the admin is our own site, so it has no FB-style rate concern, and clearing
all candidates up front means a throttled feed can't strand you mid-loop. Stage 2 is
per-watch (it needs that watch's extracted author). Iron rule #1 still holds: only ONE watch
gets extracted+imported at a time; you're batching cheap durable lookups, not images.

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
  year: "1960-1970",
  waterRes: "water_resistant_yes",
  displayMat: "sapphire",
  reference: "ABC-1234",
  description: "Raw FB post text here — harness auto-formats to professional description",
  sourceUrl: "https://www.facebook.com/groups/vanzareceasuri/posts/POST_ID/",
  fbListingId: "POST_ID",
  fbAuthorId: "100078...",         // FB poster's numeric id — Stage-2 dedup key
  fbAuthorName: "Costi Schiverniciuc",
  phone: "0731394148",
  location: "Satu Mare, Bihor",
  seller: "Razvan Vasile",
  currency: "RON",
  priceNote: "negociabil"
});
```

**Field notes:** `description` is raw FB text (harness formats it); `currency` auto-detected if omitted (`$`→USD, `€`→EUR, `lei`→RON); `phone` stripped of spaces/dots; `location` = "City, County"; `seller` = full name; `fbAuthorId`/`fbAuthorName` = the FB poster's numeric id + display name (from `fb-extract-post`; `fbAuthorId` is the Stage-2 dedup key — stored in `facebook_author_id`); `year` = single or range ("1960-1970"); `reference` from "ref. ABC-1234"; `priceNote` = free text ("negociabil"). See the field-value table for `waterRes`/`displayMat` and all other enums.

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
| Type | id_type | women, men, unisex, kids, sports, smart, other |
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

