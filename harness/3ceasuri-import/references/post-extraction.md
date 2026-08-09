# Post extraction reference (import fallback)

`import-post.py` encodes everything here. **Read this only when that script fails** — when a
post won't surface its photo set, the carousel misbehaves, or you must fill the form by hand.
Nothing here is needed on the happy path.

Methods in order: **A (commerce listing page) → B (feed HTML) → C (individual post page).**

## Method A: commerce listing page (preferred)

Navigate to `https://www.facebook.com/commerce/listing/LISTING_ID/`. All images are in the DOM
simultaneously — 5 thumbnails plus the main image, no Next button, no carousel, no stuck
viewer. Do NOT click through them.

```javascript
(() => {
  const seen = new Set(); const urls = [];
  Array.from(document.querySelectorAll('img')).forEach(img => {
    if (img.src && img.src.includes('scontent') && img.naturalWidth > 200) {
      const base = img.src.split('?')[0];
      if (!seen.has(base)) { seen.add(base); urls.push(img.src); }  // COMPLETE URL
    }
  });
  return JSON.stringify({urls, count: urls.length});
})()
```

## Method B: feed HTML text + photo-viewer carousel

Use the post text already captured during discovery, and collect images through the post's
`set=pcb.` photo link.

- `set=pcb.<PHOTO_SET_ID>` opens a viewer with a WORKING "Next photo" carousel
  (`div[aria-label="Next photo"]`, class `x1qjc9v5`).
- `set=gm.<POST_ID>` opens a viewer whose Next button does NOT advance — do not use it.

```javascript
var urls = []; var seen = new Set();
for (var step = 0; step < 15; step++) {
  var imgs = Array.from(document.querySelectorAll('img')).filter(function(i) {
    return i.naturalWidth > 400 && i.getBoundingClientRect().width > 50 &&
           !i.src.includes('static.xx.fbcdn') && !i.src.startsWith('data:');
  });
  imgs.sort((a,b) => b.naturalWidth - a.naturalWidth);
  if (imgs.length > 0) {
    var base = imgs[0].src.split('?')[0].split('/').pop();
    if (!seen.has(base)) { seen.add(base); urls.push(imgs[0].src); }
  }
  var btns = document.querySelectorAll('div[aria-label="Next photo"]');
  var clicked = false;
  for (var i = 0; i < btns.length; i++) {
    if (btns[i].getBoundingClientRect().width > 0 && btns[i].className.indexOf('x1qjc9v5') > -1) {
      btns[i].click(); clicked = true; break;
    }
  }
  if (!clicked) break;
  await new Promise(r => setTimeout(r, 2500 + Math.random() * 2500)); // human-ish 2.5–5s
}
```

**The carousel wraps — it does not run out of Next buttons.** `!clicked` almost never fires
(0/4 times on 2026-07-17c). Termination comes from **filename dedupe + a step cap**: run
step-cap = expected images + 4; the wrap re-serves images you already have, so the unique count
simply stops growing. Trust the deduped count, not the loop exit.

**The feed's `+N` badge undercounts the set** — a Certina previewing `+4` held 8 real images.
Never cap collection at the badge number.

**Verify you never left the set.** A wrap is harmless; drifting into another post's photos is
not. Assert after the loop, and discard the URLs if it fails:

```python
js('(() => location.href.indexOf("pcb.<POST_ID>") > -1 ? "same-set" : location.href)()')
# expect "same-set"
```

Other notes: ArrowRight does NOT work in the CDP browser — click the div. On some pages the
control is `[aria-label="View next image"]`. Under browser-use ≥3.0 `js()` is synchronous, so
drive the loop from Python with `time.sleep(2.5 + random.random()*2.5)` between clicks.

## Method C: individual post page

Navigate to `https://www.facebook.com/groups/vanzareceasuri/posts/POST_ID/` and wait **~15
seconds** (8–10s was not enough on 2026-07-17c). This is the **only** way to reach a post the
virtualized feed has dropped, and it worked 6/6 times once given enough time.

**The trap — it renders the HOME FEED first, and looks convincing.** At ~10s `document.title`
already showed the correct post title while `document.body` was still the home feed. Photo
links scraped at that moment belonged to a **completely different post**
(`pcb.36937378642577166`) and would have imported someone else's photos under this watch.

**Never trust the title as a readiness signal.** Gate on the post's own set appearing:

```python
js('''(() => {
  let hit = null;
  document.querySelectorAll('a[href*="/photo/"]').forEach(l => {
    if ((l.href||'').indexOf('pcb.<POST_ID>') > -1) hit = l.href.split('&__cft__')[0];
  });
  return JSON.stringify({hit, ready: !!hit});
})()''')
```

Proceed only once `hit` is non-null — that link is also the carousel entry point. Expand the
body with a `See more` / `Vezi mai mult` click inside `div[role="dialog"]` before reading text.

## NEVER modify image URLs

FB CDN URLs carry signed params (`_nc_ohc=`, `oh=`, `oe=`) that are REQUIRED. Stripping,
truncating, or regex-"upgrading" them returns "Bad URL hash". Use the EXACT `img.src`. They
also expire within hours — extract and import in the same session, re-extract on retry.

## Author capture (repost dedup key)

```javascript
// within the post container (the article/dialog holding the pcb.<POST_ID> photo link)
(() => {
  // the poster has TWO /user/ links: the avatar (no text) then the name (text).
  const aus = [...cont.querySelectorAll('a[href*="/user/"]')];
  let fbAuthorId = null, fbAuthorName = null;
  for (const a of aus) {
    if (!fbAuthorId) { const m = (a.href || '').match(/\/user\/(\d+)/); if (m) fbAuthorId = m[1]; }
    const tx = (a.innerText || '').trim().replace(/\s+/g, ' ');
    if (tx && !fbAuthorName) fbAuthorName = tx;
  }
  return JSON.stringify({fbAuthorId, fbAuthorName});
})()
```

`fbAuthorId` is the real dedup key — stable and always present. If no `/user/` link is found,
leave both unset; Stage 2 falls back to phone or is skipped. Only *read* the href — clicking an
author link navigates to the profile.

## Fields to extract

| Field | How | Example |
|-------|-----|---------|
| Brand / Model | post text or listing title | "Oris" / "Mecanic Vintage" |
| Condition, Movement, Type, Materials | RO→enum table below | |
| Price / Currency | numeric; `$`→USD, `€`→EUR, `lei`→RON | 800 |
| Case diameter | `(\d+(?:\.\d+)?)\s*mm` | 39 |
| Year | `(19\|20)\d{2}(?:\s*[-–]\s*(19\|20)\d{2})?` | "1960-1970" |
| Phone | `(?:\+?40[\s.]?\|0)7\d{2}[\s.]?\d{3}[\s.]?\d{3}` | "0731394148" |
| Location | "în [City], [County]" / "Listed in [City]" | "Satu Mare" |
| Seller | listing "Seller details\n[Name]" | "Razvan Vasile" |
| Author id / name | `a[href*="/user/"]` → `/user/<id>` + link text | "100078…" |
| Reference | `ref\.?\s*[:\-]?\s*([A-Z0-9\-\/]+)` | "ABC-1234" |
| Description | full raw post text (harness formats it) | |
| ALL image URLs | `img[src*="scontent"]`, `naturalWidth > 200` | complete URLs |

## RO→enum mapping & defaults

Infer only what the text supports; apply a default only when the text is silent — never invent
a specific claim.

| Field | cues → value | Default when silent |
|-------|--------------|---------------------|
| `condition` | nou→`new`; ca nou/excelent/impecabil→`excellent`; bun/folosit→`good`; acceptabil/uzat→`fair`; defect→`broken` | `good` |
| `movement` | automat→`automatic`; mecanic/manual/cheiță→`manual`; quartz/baterie→`quartz`; smart→`smart` | *(none)* |
| `caseMat` | otel/inox→`steel`; aur masiv/solid gold→`gold`; titan→`titanium`; **placat/gold-plated/AU\d+/dublé → `steel`** | `steel` |
| `braceletMat` | piele→`leather`; metal/otel/brățară→`steel`; cauciuc→`rubber`; nylon/textil→`nylon`; aur→`gold` | *(none)* |
| `type` | barbati→`men`; femei/dama→`women`; unisex→`unisex`; copii→`kids`; sport→`sports` | `men` |
| `displayMat` | safir→`sapphire`; mineral→`mineral`; acrilic/plexi→`acrylic` | *(none)* |
| `waterRes` | rezistent la apă/WR/\d+m/ATM→`water_resistant_yes`; nu e rezistent→`water_resistant_no` | *(none)* |
| `currency` | `€`/euro→`EUR`; `lei`/`ron`→`RON`; bare number → `RON` | `RON` |

- **Gold-plating trap:** "placat cu aur", "gold plated", "AU20", "dublé" describe a *coating*
  over a base case (usually steel). Set `caseMat: "steel"` and mention the plating in
  `description`. On 2026-07-24 a plated Slava was wrongly filed as a solid-gold case.
- Leave a field **unset** rather than guessing an enum the text doesn't support — an empty
  field is honest, a wrong one misrepresents the watch.

## Pitfalls

- Individual post pages are slow (~15s) and render the home feed first; a correct
  `document.title` does NOT mean the post is loaded.
- **Always verify the photo set ID belongs to the post you think you're extracting.** Both the
  post page (before load) and a drifting carousel can hand you another post's images.
  Cross-post contamination is silent and survives into the import.
- `document.title` is blocked for values containing signed query params — read `img.src`.
- Timestamp links do NOT open dialogs in the CDP browser; clicking an author name navigates.

## Identifying the watch from its photos (2026-08-04)

The ad naming no model is the normal case, not the exception — 3 of 7 imports on
2026-08-04. The photos answer it: a Fossil ladies' watch with a crystal bezel, Roman
numerals and a 4:30 date is a **Jacqueline**, and that listing's text said only "Ceas
Fossil original". Gender, style, case/bracelet material and dial colour come free from
the same photo, and the text almost never states them.

`EXTRACT_PROMPT.images` carries the URLs. They are FB CDN signed URLs — they expire
within the session, so fetch them during the run, not later.

### How many photos to read

**One, by default — the dial.** Open a second only when you need the caseback for a
`reference`. Measured on the Fossil listing (1999212757387077):

| | |
|---|---|
| What FB serves | 720×960 (0.69 MP) |
| Tokens per photo (≈ w×h/750) | ~920 |
| Cost per photo (Opus 5 input, $5/MTok) | ~$0.005 |
| One photo vs. the whole ad's text (~150 tok) | ~6× |
| All four photos of one watch | ~3,700 tok ≈ $0.018 |

Three things that matter more than that number:

- **Don't add downscaling.** The model's cap is 2576 px on the long edge (~4,784 tokens
  per image); FB already serves ~720×960, so we sit at the cheap end for free. Resizing
  would complicate the script and save nothing.
- **The real cost is carrying photos in context, not reading them.** An image stays in
  the context window and is re-sent on every later turn of that conversation. Four
  photos read early in a long session multiply across every step after. This is exactly
  what the one-fresh-context-per-watch rule protects against — keep `/clear`ing between
  watches and the photos are paid for once.
- **It is cheaper than being wrong.** A wrong model means a correction pass: another
  browser-use call, admin navigation, and the reasoning around it — thousands of
  transcript tokens. One 920-token photo prevents that.

### What a photo may NOT establish

A design match identifies a model *family*, not the exact variant — Jacqueline ships
under several references. **Never write a `reference` from a design match**; it may only
come from text actually read (the ad, or a legible caseback/papers photo). A wrong
reference on a public listing is worse than an empty field.

A model identified this way is our classification, not the seller's claim: put it in
`model`, note it in `notes`, and leave their `description` as they wrote it.

## Smartwatch fields (series / connectivity / compatibility)

Since 2026-08, smartwatch posts (`movement` = smart) carry three extra contract
fields. The Django DB enums are `connectivity`: gsm | no_gsm and
`compatibility`: ios | android | both; `series` is free text ("Series 9",
"SE 2", "Galaxy Watch 7" — normalized, no brand, no case size).

Identifying GSM from photos when the ad doesn't say: Apple Watch cellular
models have a red ring (Series 4–5) or red crescent/dot (Series 6+) on the
digital crown; Galaxy Watch LTE models say "LTE" on the caseback. Textual
cues: "LTE", "Cellular", "4G", "eSIM", "GPS + Cellular". "GPS" alone means
no_gsm. When neither text nor photos settle it, leave null — the import stops
for review rather than guessing.

Compatibility follows from the model, not the ad: Apple Watch = ios; Galaxy
Watch 4 and newer = android (needs a Samsung/Android phone); Garmin, Amazfit,
Huawei, Xiaomi, Fitbit = both.

## Wall clocks (`category` = wall)

Since 2026-08, wall clocks are importable rather than skipped. The DB enum is
`category`: wrist | wall, and `caseMat` gained `wood`. A wall-clock post is
still `is_wristwatch: false` — that flag records what the object is, while
`category` records where it belongs on the site; the skip gate now only fires
when a non-wristwatch has no `category`.

Identifying one from photos: a pendulum or weights hanging below the dial, a
key-wind hole (or two) on the dial face, a cuckoo door, a diameter the seller
gives in centimetres, or a photo of the clock already hanging on a wall.
"Ceas de perete", "pendulă", "cu cuc", "cartel" in the text settle it outright.

Brands: most are unbranded → `Fără marcă` (a real Brand row, seeded by
migration). Junghans, Kienzle, Gustav Becker, Schatz, Hermle and Meister
Anker are genuine makers and usually printed on the dial or stamped on the
movement plate — check before falling back.

Still out of scope (mark `is_wristwatch: false`, leave `category` null so the
post skips): mantel/table clocks, pocket watches, alarm clocks, wristwatch
straps and parts.
