# Watch Listing Automation Plan — Facebook → 3ceasuri.ro

⚠️ **READ THIS PLAN COMPLETELY BEFORE EVERY SESSION AND FOLLOW IT STEP BY STEP. DO NOT SKIP STEPS.**

---

## Project Structure

```
/opt/data/proiecte/3ceasuri/
├── Watch_Listing_Automation_Plan.md    ← This file (orchestrator)
└── skills/
    ├── browser-use/                    ← FB scraping skill
    │   ├── SKILL.md
    │   └── references/                 ← Detailed references (CDP, photos, etc.)
    ├── 3ceasuri-import/                ← Admin import skill
    │   ├── SKILL.md
    │   ├── references/                 ← Brand IDs, workflows, sessions
    │   └── scripts/
    │       └── import-watch.js         ← Harness v3 (authoritative)
    └── 3ceasuri/
        └── scripts/
            └── import-watch.js         → symlink to 3ceasuri-import/scripts/
```

**Skills are the single source of truth.** This plan orchestrates; skills implement.

---

## Skill Loading Order (EVERY session)

Load these skills in order before doing anything:

1. `skill_view(name='browser-use')` — FB feed scrolling, post ID extraction, image collection
2. `skill_view(name='3ceasuri-import')` — Harness injection, admin form filling, submission

Keep both skill contents in context throughout the session.

---

## Tool Policy (STRICT)

| Tool | Use For | Never Use For |
|------|---------|---------------|
| `browser-use` CLI | FB tab management, FB scrolling, FB eval | Admin form filling |
| `browser_scroll` + `browser_console` | FB feed scroll + DOM reading loop | Admin form filling |
| `browser_navigate` | Admin site navigation | FB (UTF-8 encoding crash) |
| `browser_console` eval | JS extraction on FB and admin | Form field filling (use refs) |
| `browser_click` / `browser_type` | Admin form fields ONLY (not brand) | Brand Select2 (use JS injection) |
| Raw CDP websockets | Last resort ONLY when browser-use + browser_console both fail | Default approach |

**MANDATORY:** If `browser_navigate`/`browser_snapshot` fail with UTF-8 encoding error on FB, use `browser-use` CLI or `window.location.replace()` via `browser_console`.

**MANDATORY:** Do NOT use `browser_type` for the Brand field. Use JS direct injection via brand ID mapping.

---

## Domains

- **Facebook group:** `vanzareceasuri` (numeric ID: `978581759677150`)
- **Buy/sell URL:** `https://www.facebook.com/groups/978581759677150/buy_sell_discussion`
- **Main group URL:** `https://www.facebook.com/groups/vanzareceasuri/`
- **Post URL:** `https://www.facebook.com/groups/vanzareceasuri/posts/POST_ID/`
- **Commerce listing URL:** `https://www.facebook.com/commerce/listing/LISTING_ID/` (preferred when available)
- **Admin:** `https://3ceasuri.ro/admin/watches/watch/add/`

---

## Workflow Overview

**One watch at a time. Find → Extract → Import → Confirm → Repeat.**

```
SETUP (once per session)
  ├── Load skills
  ├── Connect browser-use CLI (browser-level WS URL)
  ├── Tab 0: Admin add-watch form
  └── Tab 1: FB buy/sell page

PER WATCH (loop)
  ├── PHASE 0: Scroll FB feed → find qualifying post
  ├── PHASE 1: Duplicate check (admin)
  ├── PHASE 2: Extract post details + ALL images
  ├── PHASE 3: Import to admin (harness)
  └── PHASE 4: Verify green banners → repeat
```

---

## SETUP (Once Per Session)

### Step 1: Connect browser-use

```bash
# Get browser-level WS URL (NOT page-level!)
curl -s http://192.168.65.254:9222/json/version | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['webSocketDebuggerUrl'])"
# Returns: ws://192.168.65.254:9222/devtools/browser/<id>

# Close stale session if needed
browser-use close

# Connect
browser-use --cdp-url "ws://192.168.65.254:9222/devtools/browser/<id>" tab list
```

### Step 2: Open required tabs

```bash
# Tab 0: Admin add-watch form
browser-use --cdp-url <url> tab new https://3ceasuri.ro/admin/watches/watch/add/

# Tab 1: FB buy/sell
browser-use --cdp-url <url> tab new https://www.facebook.com/groups/978581759677150/buy_sell_discussion
```

### Step 3: Inject harness (admin tab)

Switch to admin tab, then inject via `browser_console`:

```python
# In execute_code:
import json
with open('/opt/data/proiecte/3ceasuri/skills/3ceasuri-import/scripts/import-watch.js') as f:
    script = f.read()
wrapper = "(() => { const s = document.createElement('script'); s.textContent = " + json.dumps(script) + "; document.head.appendChild(s); return window.importWatch ? 'OK' : 'NO_FUNC'; })()"
# Print wrapper, then pass to browser_console(expression=wrapper)
```

Verify: `browser_console` returns `"OK"`.

**After every form submission**, the page reloads and the harness is lost. **Re-inject before each new watch.**

---

## PHASE 0: Find Qualifying Posts (FB Feed)

**Tool:** `browser_scroll` + `browser_console`. FB tab must be active.

### Primary Method: Extract from Initial HTML

FB scrolling often fails to load new posts. **Extract from the page HTML first** before scrolling:

```javascript
(() => {
  const html = document.documentElement.outerHTML;
  // Post texts from embedded JSON
  const texts = [];
  const re = /"message":\{"text":"([^"]+)"/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const t = m[1].replace(/\\n/g,' ').replace(/\\"/g,'"');
    if (t.length > 20) texts.push(t);
  }
  // Post IDs from photo links
  const ids = new Set();
  const links = Array.from(document.querySelectorAll('a[href*="/photo/"]'));
  links.forEach(l => {
    const href = l.href || l.getAttribute('href') || '';
    const m = href.match(/set=pcb\.(\d+)/) || href.match(/set=gm\.(\d+)/);
    if (m) ids.add(m[1]);
  });
  // Commerce listing IDs
  const listings = Array.from(document.querySelectorAll('a[href*="commerce/listing/"]'));
  listings.forEach(l => {
    const m = (l.href || '').match(/commerce\/listing\/(\d+)/);
    if (m) ids.add('listing:' + m[1]);
  });
  return JSON.stringify({ids: [...ids], texts, textLen: html.length});
})()
```

### Scrolling Protocol (secondary)

Only scroll if initial HTML has no qualifying posts:

```
REPEAT up to 10 times:
  1. browser_scroll(direction="down")
  2. Wait 3-4 seconds
  3. Run DOM reading JS (below)
  4. If new qualifying posts found → stop scrolling, process them
  5. If no new content after 3 scrolls → navigate to main group → back to buy/sell → re-extract
END REPEAT
```

### DOM Reading JS (synchronous, keep under 3KB)

```javascript
(() => {
  const f = document.querySelector('[role="feed"]') || document.body;
  const w = document.createTreeWalker(f, NodeFilter.SHOW_TEXT, {
    acceptNode: n => n.textContent.trim().length > 2 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP
  });
  let t = ''; let n;
  while (n = w.nextNode()) t += n.textContent;
  const links = Array.from(document.querySelectorAll('a[href*="/photo/"]'));
  const ids = new Set();
  links.forEach(l => {
    const href = l.href || l.getAttribute('href') || '';
    const m = href.match(/set=pcb\.(\d+)/) || href.match(/set=gm\.(\d+)/);
    if (m) ids.add(m[1]);
  });
  const listings = Array.from(document.querySelectorAll('a[href*="commerce/listing/"]'));
  listings.forEach(l => {
    const m = (l.href || '').match(/commerce\/listing\/(\d+)/);
    if (m) ids.add('listing:' + m[1]);
  });
  const prices = t.match(/\d[\d\s,.]*\s*(lei|ron|eur|€|\$)/gi) || [];
  return JSON.stringify({ids: [...ids], prices, textLen: t.length, text: t.substring(0, 6000)});
})()
```

### Quick-Filter (per post)

Collect post data, then filter:
- ✅ Price >= 500 RON (or >= 100 EUR/$)
- ✅ Brand + model mentioned in post body
- ❌ NOT replica/AAA+, NOT bulk, NOT non-watch item
- ❌ NOT Vinted invite links, NOT ads

Only proceed with posts that PASS all filters.

### Post ID Sources (priority order)

1. **Commerce listing links** (`a[href*="commerce/listing/"]`) — PREFERRED. Navigate to `/commerce/listing/ID/`
2. **Photo links with `set=pcb.ID`** (buy/sell feed) — Works with photo viewer carousel
3. **Photo links with `set=gm.ID`** — May have stuck carousel, less reliable

**NOTE:** FB scrolling often fails to load more posts in small groups. If stuck, navigate between main group and buy/sell pages to refresh the feed.

---

## PHASE 1: Duplicate Check

Before extracting images, verify the post hasn't been imported.

```bash
browser-use --cdp-url <url> tab new "https://3ceasuri.ro/admin/watches/watch/?q=POST_ID"
```

- If results found → **skip this post**, close tab, move to next
- If "0 watchs" → proceed to Phase 2

**Never navigate away from the add-watch form tab for duplicate checking.** Use a separate tab.

---

## PHASE 2: Extract Post Details + Images

### Method A: Commerce Listings (PREFERRED)

Navigate to `https://www.facebook.com/commerce/listing/LISTING_ID/`

**Why preferred:** All images are in the DOM simultaneously — no Next button, no carousel, no stuck viewer.

```javascript
// In browser_console on the commerce listing page
(() => {
  const seen = new Set();
  const urls = [];
  Array.from(document.querySelectorAll('img')).forEach(img => {
    if (img.src && img.src.includes('scontent') && img.naturalWidth > 200) {
      const base = img.src.split('?')[0];
      if (!seen.has(base)) { seen.add(base); urls.push(img.src); }  // COMPLETE URL
    }
  });
  return JSON.stringify({urls, count: urls.length});
})()
```

Extract text (title, price, condition, brand, description) from the same page.

### Method B: Group Posts (fallback)

Navigate to `https://www.facebook.com/groups/vanzareceasuri/posts/POST_ID/`

**⚠️ Wait 8-10 seconds.** Individual post pages are slow and may show notifications instead of content. If the dialog shows notifications, go back and use the feed HTML extraction from Phase 0 instead.

If content loads: click image to open photo viewer, collect ALL images via Next button. See `browser-use` skill for detailed carousel JS.

**⚠️ NEVER strip query params from image URLs.** `_nc_ohc`, `oh`, `oe` are required signatures.

### Data to Extract

From each qualifying FB post/listing, extract:

| Field | How to Extract | Example |
|-------|---------------|---------|
| **Brand** | From post text or commerce listing title | "Oris", "Seiko" |
| **Model name** | From post text, descriptive | "Mecanic Vintage", "Red Arrows Eco-Drive" |
| **Condition** | Map RO→EN | "nou"→`new`, "excelent"→`excellent`, "bun"→`good` |
| **Movement** | From text | "mecanic"→`manual`, "automatic"→`automatic`, "quartz"→`quartz` |
| **Price** | Numeric value | 800, 3000, 5500 |
| **Currency** | Auto-detect from text | `$`→`USD`, `€`→`EUR`, `lei`→`RON` |
| **Case diameter** | Regex: `(\d+(?:\.\d+)?)\s*mm` | 35.5, 39, 42 |
| **Case material** | From text | "otel"→`steel`, "aur"→`gold`, "titan"→`titanium` |
| **Bracelet material** | From text | "piele"→`leather`, "metal"→`steel`, "cauciuc"→`rubber` |
| **Year** | Regex: `(19\|20)\d{2}(?:\s*[-–]\s*(19\|20)\d{2})?` | "1960-1970", "1985" |
| **Watch type** | From text | "barbati"→`men`, "femei"→`women` |
| **Phone** | Regex: `/(?:\+?40[\s.]?\|0)7\d{2}[\s.]?[\s.]?\d{3}[\s.]?\d{3}/` | "0731394148" |
| **Location** | From text: "în [City], [County]" or "Listed in [City]" | "Satu Mare", "București" |
| **Seller** | From commerce listing: "Seller details\n[Name]" | "Razvan Vasile" |
| **Reference** | Regex: `/ref\.?\s*[:\-]?\s*([A-Z0-9\-\/]+)/i` | "ABC-1234" |
| **Description** | Full raw post text (harness auto-formats) | Raw FB text |
| **Source URL** | FB post/listing URL | Full URL |
| **FB listing/post ID** | Numeric ID from URL | "123456789" |
| **ALL image URLs** | From DOM: `img[src*="scontent"]` with `naturalWidth > 200` | Complete URLs |

### Professional Description Builder

The harness (`importWatch`) builds a professional description via `buildProfessionalDescription()`. Output format:

```
Oris Mecanic Vintage 1960-1970

Specificații:
- Mecanism: manual
- Diametru: 35.5 mm
- Carcasa: steel
- An: 1960-1970

Stare: Excelent

Preț: 800 RON
Locație: Satu Mare
Vânzător: Razvan Vasile

Detalii suplimentare:
[Cleaned original FB post text]
```

**The agent does NOT need to pre-format the description** — pass raw text + extracted fields, harness builds the professional version.

### Auto-Generated Fields

The harness also auto-generates:
- **Slug**: `-oris-mecanic-vintage-1960-1970` (from brand + model, ASCII-only)
- **Currency**: Detected from post text (`$`→USD, `€`→EUR, `lei`→RON)
- **Phone**: Extracted from post text, stripped of spaces/dots
- **Location**: Extracted from "în [City]" or "Listed in [City]" patterns
- **Seller**: Extracted from commerce listing "Seller details" section
- **Year**: Extracted as range ("1960-1970") or single year ("1985")
- **Reference**: Extracted from "ref. ABC-1234" patterns

### Image Retry

Images are fetched with automatic retry (max 3 attempts per image). If an image fails with 403, the harness waits 1s and retries. Failed images are logged but don't block the import — the watch is imported with whatever images succeeded.

---

## PHASE 3: Import to Admin

Switch to admin add-watch tab. The form should still be open from "Save and add another".

### Step 3.1: Re-inject harness

```python
import json
with open('/opt/data/proiecte/3ceasuri/skills/3ceasuri-import/scripts/import-watch.js') as f:
    script = f.read()
wrapper = "(() => { const s = document.createElement('script'); s.textContent = " + json.dumps(script) + "; document.head.appendChild(s); return window.importWatch ? 'OK' : 'NO_FUNC'; })()"
```

Pass `wrapper` to `browser_console(expression=...)`. Expect `"OK"`.

### Step 3.2: Call importWatch

The harness handles image fetching internally (browser fetch + FileReader). Just pass the raw FB URLs:

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
  phone: "0731394148",
  location: "Satu Mare, Bihor",
  seller: "Razvan Vasile",
  currency: "RON",
  priceNote: "negociabil"
});
```

**Field notes:**
- `description`: Pass raw FB text — harness builds professional description
- `currency`: Auto-detected if omitted (`$`→USD, `€`→EUR, `lei`→RON)
- `phone`: Extracted from post, stripped of spaces/dots
- `location`: "City, County" format
- `seller`: Full name from commerce listing
- `year`: Single year or range ("1960-1970")
- `reference`: From "ref. ABC-1234" patterns
- `priceNote`: Free text like "negociabil", "fix"
- `waterRes`: `water_resistant_yes` or `water_resistant_no`
- `displayMat`: `sapphire`, `mineral`, `acrylic`, `plastic`, `other`

**NEVER modify image URLs.** No regex upgrades, no param stripping. The harness fetches them as-is with automatic retry (3 attempts).

---

## PHASE 4: Verify

Wait 5 seconds after `importWatch` returns. Check for BOTH green banners:

```javascript
(() => {
  const t = document.body.innerText;
  return JSON.stringify({
    images_ok: t.includes('imagini salvate'),
    added_ok: t.includes('added successfully'),
    banner_text: t.substring(0, 500)
  });
})()
```

**If CDP times out** (common with many images): re-check the page. The import likely succeeded despite the timeout.

**If only partial images saved:** The watch is still imported. Note the image count discrepancy.

**If import failed** (no green banners): Check `document.body.innerText` for error messages. Fix the issue, re-inject harness, re-inject images, and retry.

### Update State

After each import or skip, update `state.json`:

```json
{
  "imported": [{"id": "POST_ID", "brand": "Orient", "model": "Bambino", "price": 1200, "images": 5}],
  "skipped": [{"id": "OTHER_ID", "reason": "duplicate"}],
  "total_imported": 1,
  "target": 20
}
```

---

## Retry / Rollback Strategy

| Failure | Action |
|---------|--------|
| FB page fails to load | Retry once. If still failing, navigate to main group → back to buy/sell |
| Post content not loading (skeletons) | Wait 10s. If still loading, skip post |
| Image extraction fails (0 images) | Try alternate method (commerce vs group post). If both fail, skip watch |
| Duplicate check: already exists | Skip watch, update state |
| Harness injection fails | Retry once. If still failing, use manual field filling (see 3ceasuri-import skill) |
| importWatch timeout | Re-check page. Likely succeeded. Verify green banners |
| Import fails (no green banners) | Re-inject harness → re-inject images → retry. Max 2 retries |
| Admin DB down | Wait 30s, retry. If persistent, stop and report |
| WebSocket drops | Reconnect. Use short-lived connections per CDP call |
| `browser-use tab new` shows notifications | Don't use `tab new` for FB. Navigate existing tab with `window.location.href` |
| WS closes after navigation | Expected. Reconnect with a fresh `websockets.connect()` after page loads |

## Known Pitfalls (read every session)

1. **UTF-8 encoding crash on FB:** `browser_navigate`/`browser_snapshot` fail. Use `browser-use` CLI or `window.location.replace()`.
2. **FB feed scrolling doesn't load more posts:** Navigate between main group and buy/sell to refresh.
3. **Individual post pages show notifications:** Avoid extracting from dialog. Use commerce listing pages or feed HTML.
4. **Harness lost on every page navigation:** Re-inject before each watch.
5. **Image URLs with signed params:** Never strip `_nc_ohc`, `oh`, `oe`. Use exact `img.src`. Re-extract fresh URLs each time.
6. **CDP timeout on image import:** Usually means success. Re-check page for green banners.
7. **importWatch returns `success: false` even on success:** Always verify by checking page content for green banners, NOT by return value.
8. **Select2 brand:** Use JS direct injection, NOT `browser_type`, NOT `browser_click` on Select2.
9. **browser_type on wrong field:** Never use for Brand. Use for text fields only (model, price).
10. **Admin DB outages:** Check for `OperationalError`. Wait and retry.
11. **FB CDN URLs expire:** Extract and import within same session.
12. **`browser-use tab new` doesn't load FB content:** New tabs show notifications. Navigate existing tab with `window.location.href` instead.
13. **Commerce listing pages don't load in new tabs:** Even with `window.location.href`, commerce/listing pages often show only notifications. Use `browser-use eval` on an already-loaded tab, or extract data from feed HTML instead.
14. **WebSocket closes after `window.location.href`:** The WS connection is tied to the page. After navigation, reconnect with a fresh connection.
15. **Description raw text needs cleaning:** Pass raw FB text to harness — `formatDescription()` handles Unicode, whitespace, duplicates, Vinted links.
16. **Phone numbers in post:** Extract with regex, strip spaces/dots.

---

## Adding New Brands

If brand not in BRAND_IDS mapping:

1. `browser-use tab new https://3ceasuri.ro/admin/watches/brand/add/`
2. Fill Name + Slug, Save
3. Note new ID from redirect URL
4. Re-inject harness with updated `window.BRAND_IDS["NewBrand"] = ID;`

---

## Form Field Values Reference

| Field ID | Values |
|----------|--------|
| `id_condition` | `new`, `excellent`, `good`, `fair`, `broken` |
| `id_movement` | `automatic`, `manual`, `quartz`, `smart` |
| `id_case_material` | `titanium`, `carbon`, `aluminium`, `steel`, `gold`, `silver`, `plastic`, `ceramic`, `other` |
| `id_bracelet_material` | `titanium`, `carbon`, `aluminium`, `steel`, `gold`, `silver`, `plastic`, `rubber`, `leather`, `nylon`, `other` |
| `id_type` | `women`, `men`, `unisex`, `kids`, `sports`, `smart`, `other` |
| `id_water_resistance` | `water_resistant_yes`, `water_resistant_no` |
| `id_display_material` | `sapphire`, `mineral`, `acrylic`, `plastic`, `other` |
| `id_display_color` | `black`, `white`, `silver`, `gold`, `other` |
| `id_display_type` | `digital`, `analog`, `analog_digital`, `smart`, `none` |
| `id_display_size` | `small`, `medium`, `large` |
| `id_currency` | `RON`, `EUR` |

Romanian → English mappings:
- Nou → new | Excelent/Ca nou → excellent | Bun/Folosit → good | Acceptabil/Uzat → fair | Defect/Stricat → broken
- Automat → automatic | Mecanism → manual | Quartz → quartz
- Otel → steel | Aur → gold | Titan → titanium | Piele → leather | Cauciuc → rubber
- Barbati → men | Femei → women

---

## Progress Tracking

State file: `/opt/data/proiecte/3ceasuri/state.json`

```json
{
  "imported": [
    {"id": "POST_ID", "brand": "Orient", "model": "Bambino", "price": 1200, "images": 5, "timestamp": "2026-06-20T12:00:00"}
  ],
  "skipped": [
    {"id": "POST_ID", "reason": "duplicate"}
  ],
  "total_imported": 0,
  "target": 20
}
```

Load state at session start. Update after each import/skip. This enables crash recovery.

---

## Known Pitfalls (read every session)

1. **UTF-8 encoding crash on FB:** `browser_navigate`/`browser_snapshot` fail. Use `browser-use` CLI or `window.location.replace()`.
2. **FB feed scrolling doesn't load more posts:** Navigate between main group and buy/sell to refresh.
3. **Individual post pages show notifications:** Avoid extracting from dialog. Use commerce listing pages or feed HTML.
4. **Harness lost on every page navigation:** Re-inject before each watch.
5. **Image URLs with signed params:** Never strip `_nc_ohc`, `oh`, `oe`. Use exact `img.src`.
6. **CDP timeout on image import:** Usually means success. Re-check page for green banners.
7. **Select2 brand:** Use JS direct injection, NOT `browser_type`, NOT `browser_click` on Select2.
8. **browser_type on wrong field:** Never use for Brand. Use for text fields only (model, price).
9. **Admin DB outages:** Check for `OperationalError`. Wait and retry.
10. **FB CDN URLs expire:** Extract and import within same session.

---

## Reference Files

- `skills/browser-use/SKILL.md` — FB scraping: scrolling, post IDs, image extraction, CDP fallback
- `skills/browser-use/references/photo-carousel-collection.md` — Photo viewer Next button patterns
- `skills/browser-use/references/post-id-extraction.md` — Post ID regex patterns for all page types
- `skills/browser-use/references/cdp-python-websocket.md` — Raw CDP fallback
- `skills/3ceasuri-import/SKILL.md` — Admin import: harness, form filling, verification
- `skills/3ceasuri-import/references/brand-ids.md` — Current brand ID mapping
- `skills/3ceasuri-import/scripts/import-watch.js` — Harness v3 (authoritative)
