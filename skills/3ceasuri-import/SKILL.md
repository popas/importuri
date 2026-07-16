---
name: 3ceasuri-import
description: Import watch listings to 3ceasuri.ro Django admin. Harness injection, brand selection, form filling, image injection, submission verification. Part of 3ceasuri watch automation project.
---

# 3ceasuri.ro Watch Import Skill

**Project:** `/opt/data/proiecte/3ceasuri/`
**Orchestrator:** `Watch_Listing_Automation_Plan.md`
**Harness:** `scripts/import-watch.js` (authoritative, v3)
**Brand IDs:** `references/brand-ids.md`

Import watch data extracted from Facebook into the 3ceasuri.ro Django admin panel. Handles brand selection (direct injection via ID mapping), all field filling, image fetching + encoding, payload verification, and submission.

## Quick Start

**⚠️ WORKFLOW: Import ONE watch at a time. Find → Extract → Import → Confirm → Repeat. Do NOT batch-collect multiple watches before importing.**

**⚠️ TOOL SELECTION: The plan mandates specific tools for specific jobs:**
- **browser-use CLI** (`browser-use --cdp-url <url> tab/eval/scroll/screenshot`) for multi-tab operations and JS eval on problematic pages (FB)
- **browser_scroll + browser_console** for the FB scrolling + DOM reading loop (per Phase 0 of the plan)
- **browser_navigate** for single-tab navigation on the admin site
- **Raw CDP via Python websockets** only as a last resort when both browser-use and browser_console fail
- Do NOT default to raw CDP — use browser-use first, fall back to raw CDP only when browser-use also fails

### Contact & Communication Style
- **Keep responses concise and action-oriented.** No fluff, no narrating every step.
- Show progress as "X/5 done" 
- Don't explain what you're about to do — just do it and report results
- If user says "stop", stop immediately and summarize
- **Follow the skill steps exactly.** Don't improvise or skip steps. If a step fails, report the failure and ask for guidance.

### Method A: Commerce Listing Page (PREFERRED)

Facebook commerce listings (`/commerce/listing/ID/`) provide the cleanest access:
- All images are in the DOM simultaneously (no Next button clicking needed)
- Structured data: brand, condition, price are in labeled fields
- No proxy iframe issues

1. Navigate to `https://www.facebook.com/commerce/listing/LISTING_ID/`
2. Extract text data from the page (title, price, condition, brand, location, description)
3. Collect ALL images via DOM query (see Commerce Page Image Collection below)
4. Navigate to admin: `https://3ceasuri.ro/admin/watches/watch/add/`
5. Inject harness → `importWatch({...})` → verify green banners
6. Repeat for next watch

### Method B: Group Post Page

Use when commerce listing URL is not available:

1. Navigate to `https://www.facebook.com/groups/vanzareceasuri/posts/POST_ID/`
2. Extract text + ALL images (see Feed Image Collection below)
3. Navigate to admin and import as above

### Finding Watch Posts

1. Navigate to the group feed: `https://www.facebook.com/groups/vanzareceasuri/` or buy/sell: `https://www.facebook.com/groups/978581759677150/buy_sell_discussion`
2. **⚠️ Scrolling does NOT load more posts.** The group is small — only ~5 posts are in the initial HTML. JS scroll, keyboard End/PageDown, and mouse wheel all fail to trigger FB infinite scroll.
3. **Extract posts from the initial HTML** using regex on `document.documentElement.outerHTML`:
   - Post texts: regex `"message":{"text":"..."` 
   - Post IDs: regex `vanzareceasuri/posts/ID` or `vanzareceasuri/permalink/ID`
   - Commerce listing IDs: regex `commerce/listing/ID`
4. Look for posts with prices >= 500 RON (or >= 100 EUR/$), brand names, watch keywords
5. **Quick filter**: skip cars, bulk lots, items without images, posts below price threshold
6. Navigate directly to `/commerce/listing/ID/` when available (preferred), or `/groups/vanzareceasuri/posts/ID/`
7. **Import immediately** — don't scroll endlessly collecting IDs first

### Qualifying Criteria

- Price >= 500 RON or >= 100 EUR/$
- Has brand + model mentioned
- NOT replica/AAA+, NOT bulk, NOT non-watch item
- Has visible images

## Commerce Page Image Collection (Method A)

On commerce listing pages, ALL images are already in the DOM. No need to click through:

```javascript
// Get ALL unique image URLs from the commerce listing page
var allImgs = Array.from(document.querySelectorAll('img'));
var seen = new Set();
var urls = [];
allImgs.forEach(function(img) {
  if (img.src && img.src.includes('scontent') && img.naturalWidth > 200) {
    var base = img.src.split('?')[0];
    if (!seen.has(base)) {
      seen.add(base);
      urls.push(img.src); // COMPLETE URL with ALL query params
    }
  }
});
// urls now contains ALL unique image URLs for this listing
```

The page shows 5 thumbnails (Thumbnail 0-4) plus the main image. The `img[src*="scontent"]` with `naturalWidth > 200` filter catches them all.

## Feed/Post Image Collection (Method B)

For group post pages where images are in a photo viewer carousel:

```javascript
// Step 1: Click image in post to open photo viewer
document.querySelector('[role="dialog"] a[href*="/photo/"]').click();

// Step 2: Collect current image, click Next, repeat
var urls = []; var seen = new Set();
function collect() {
  var imgs = Array.from(document.querySelectorAll('img')).filter(function(i) {
    return i.naturalWidth > 400 && i.getBoundingClientRect().width > 50 &&
           !i.src.includes('static.xx.fbcdn') && !i.src.startsWith('data:');
  });
  if (imgs.length > 0) {
    var base = imgs[0].src.split('?')[0];
    if (!seen.has(base)) { seen.add(base); urls.push(imgs[0].src); }
  }
  // Commerce pages use "View next image" button
  var next = document.querySelector('div[aria-label="Next photo"]') ||
             document.querySelector('[aria-label="View next image"]') ||
             Array.from(document.querySelectorAll('button')).find(function(b) {
               return (b.getAttribute('aria-label')||'').includes('Next');
             });
  if (next && !next.disabled) { next.click(); return true; }
  return false;
}
// Run collect() repeatedly with 2-3s waits until it returns false
```

**⚠️ NEVER stop at 1 image. Always collect ALL images.**

## Admin Form Harness

Inject this ONCE per session via `browser_console`, then call per watch:

```javascript
importWatch({
  brand: "Orient",
  model: "Bambino Automatic",
  price: 1200,
  images: ["https://scontent-hel3-1.xx.fbcdn.net/v/..."], // FULL URLs only
  condition: "new",
  movement: "automatic",
  type: "men",
  description: "Full post text from Facebook — seller's exact description",
  sourceUrl: "https://www.facebook.com/groups/vanzareceasuri/posts/POST_ID/",
  fbListingId: "POST_ID"
});
```

**⚠️ ALWAYS provide `description`, `sourceUrl`, and `fbListingId` for every watch.** The description is the full Facebook post text. The sourceUrl is the Facebook post URL (powers the "Vezi sursa originală" back-link on the watch page). Without these, listings look incomplete.

## Brand Management — Direct Injection (primary)

**Scrape the brand list once and use direct injection.** This is instant and reliable.

Current mapping (29 brands, scrape from `/admin/watches/brand/` to refresh):
```
Certina:28, Spinnaker:27, Atlantic:26, Orient:25, Cauny:24, Doxa:23, Seconda:22, Fossil:21, Maurice Lacroix:20, Bischoff:19, Longines:18, Hamilton:17, Zenith:16, Seiko:15, Tudor:14, Citizen:13, Tissot:12, Poljot:11, Cartier:10, Le Duc:9, Racheta:8, Omega:7, TITUS Geneve:6, Glashutte:5, Rotary:4, Rolex:3, Casio:2, Aerowatch:1
```

To set a brand (one call, instant):
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

**Do NOT use Select2 search as the primary method.** The harness's `importWatch()` handles both direct injection and Select2 fallback automatically.

## Mandatory Quality Gates (per watch)

- [ ] Brand selected (value is numeric ID)
- [ ] Model name filled
- [ ] Price filled (numeric)
- [ ] Condition selected
- [ ] Movement selected
- [ ] **Description filled** (`id_description` — full Facebook post text)
- [ ] **Source URL filled** (`id_source_url` — Facebook post URL for "Vezi sursa originală")
- [ ] **Facebook listing ID filled** (`id_facebook_listing_id` — numeric post ID)
- [ ] ALL images collected (count matches expected)
- [ ] All images fetched successfully (no "Bad URL hash")
- [ ] images_payload.length > 500 (real base64 data)
- [ ] Submit returns BOTH green banners

**If any image fails → do NOT skip the watch → re-extract URLs from Facebook and retry.**

## Pitfalls

### Facebook Proxy Iframe
The Facebook buy/sell feed (`/groups/978581759677150/buy_sell_discussion`) loads content through a cross-origin iframe (`fbsbx.com/maw_proxy_page`). You **cannot** access the iframe's DOM from the parent page. Photo links, post permalinks, and post IDs inside the iframe are invisible to JS eval on the parent page.

**Workaround**: Navigate directly to the group page (`/groups/vanzareceasuri/`) instead of the buy/sell URL. The main group page loads posts in the same origin, making all links accessible. Even better: navigate directly to commerce listing pages (`/commerce/listing/ID/`) when you have the listing ID.

### document.title Blocked for Signed URLs
Chrome extensions block `document.title` values containing signed query parameters (`oh=`, `oe=`, `_nc_ohc=`, etc.). Reading image URLs via `document.title` will silently fail or return truncated values. **Always read image URLs directly from `img.src` in the DOM**, never via `document.title`.

### Commerce Listing Image Thumbnails
Commerce listing pages render all images as thumbnail buttons (`Thumbnail 0`, `Thumbnail 1`, etc.) plus a main display image. All are in the DOM simultaneously — **do not try to click through them**. A single `querySelectorAll('img[src*="scontent"]')` with `naturalWidth > 200` filter captures all unique images at once.

### Feed Scrolling Without Progress
If the feed shows repeated "Facebook" branding text but no actual post content, you're looking at the proxy iframe (cross-origin). Navigate to the non-proxy group URL instead.

### Feed Scrolling Doesn't Load More Posts
**All scroll methods fail** (JS `window.scrollBy`, keyboard End/PageDown, mouse wheel, `browser_scroll`). The group is small — only ~5 posts are in the initial HTML. **Extract posts from the initial HTML** using regex on `document.documentElement.outerHTML`:
- Post texts: regex `"message":{"text":"..."` 
- Post IDs: regex `vanzareceasuri/posts/ID` or `vanzareceasuri/permalink/ID`
- Commerce listing IDs: regex `commerce/listing/ID`
Do NOT waste time trying to scroll to load more posts. Navigate between main group and buy/sell pages to refresh the feed instead.

### Harness Lost on Page Navigation
The `importWatch` function is injected via `<script>` tag. Every time `browser_navigate` is called, the page reloads and the harness is lost. **You must re-inject the harness after every navigation to the admin page.** Re-inject the full harness from `scripts/import-watch.js` (this skill's scripts/ directory) using the script-tag injection method.

### browser_console Expression Size Limit
The `browser_console` tool has an expression size limit. The full harness (~7KB) is **too large** to inject in a single `browser_console` call — it fails with "Invalid or unexpected token". When the harness is lost and can't be re-injected, **fall back to manual field filling** via smaller JS eval calls:

```javascript
// Step 1: Set brand
const select = document.getElementById('id_brand');
const opt = document.createElement('option');
opt.value = '25'; opt.textContent = 'Orient'; opt.selected = true;
select.appendChild(opt);
select.value = '25';
select.dispatchEvent(new Event('change', {bubbles: true}));
document.querySelector('#select2-id_brand-container').textContent = 'Orient';

// Step 2: Fill all fields
const set = (id, val) => { if (!val) return; const el = document.getElementById(id); if (!el) return; el.value = String(val); el.dispatchEvent(new Event('change', {bubbles: true})); };
set('id_model_name', 'Model Here');
set('id_price', '900');
set('id_condition', 'good');
set('id_movement', 'automatic');
set('id_type', 'men');
set('id_currency', 'RON');
set('id_description', 'Full post text...');
set('id_source_url', 'https://www.facebook.com/groups/vanzareceasuri/posts/POST_ID/');
set('id_facebook_listing_id', 'POST_ID');
set('id_case_material', 'steel');
// ... any other fields with data

// Step 3: Inject images (separate call, also keep small)
// Then submit
document.querySelector('input[name="_addanother"]').click();
```

Keep each `browser_console` expression under ~3KB to avoid the size limit. Split into multiple calls if needed.

### CDP Async Timeout on Image Fetching
The `importWatch` function fetches all images via `async/await` in the browser. When fetching many images (5-10), the CDP `Runtime.evaluate` call may timeout with "Inspected target navigated or closed" even though the import succeeded. **Always re-check the page after a timeout error** — look for green banners confirming the import worked before assuming failure.

### New Brands Not in Mapping
When encountering a brand not in the 28-brand ID mapping:
1. Navigate to `https://3ceasuri.ro/admin/watches/brand/add/`
2. Fill Name (e.g., "Dugena") and Slug (e.g., "dugena")
3. Click Save
4. Note the new brand ID from the redirect URL (e.g., `/brand/29/change/` → ID=29)
5. Update `window.BRAND_IDS` in the harness before importing

### browser-use CLI — Connection & Usage

**ALWAYS connect browser-use before starting FB operations.** The built-in `browser_navigate`/`browser_snapshot` fail with UTF-8 encoding errors on FB CDN content. The browser-use CLI is the primary tool for FB.

The plan mandates browser-use for multi-tab operations. Connection requires the **browser-level** WS URL:

```bash
# 1. Get browser-level WS URL (not page-level!)
curl -s http://192.168.65.254:9222/json/version | python3 -c "import json,sys; print(json.load(sys.stdin)['webSocketDebuggerUrl'])"
# Returns: ws://192.168.65.254:9222/devtools/browser/<id>

# 2. Close existing session first if needed
browser-use close

# 3. Connect
browser-use --cdp-url "ws://192.168.65.254:9222/devtools/browser/<id>" tab list

# 4. Tab operations
browser-use --cdp-url "<url>" tab switch <index>
browser-use --cdp-url "<url>" tab new <url>
browser-use --cdp-url "<url>" eval "<js>"
browser-use --cdp-url "<url>" scroll down
browser-use --cdp-url "<url>" screenshot
```

**Key details:**
- Page-level WS URLs (`/devtools/page/<id>`) get HTTP 404 — must use browser-level (`/devtools/browser/<id>`)
- If you get "Session 'default' is already running with different config", run `browser-use close` first
- `browser-use eval` works on FB pages even when `browser_console` fails with UTF-8 encoding errors
- Use for: tab list/new/switch/close, scrolling, screenshots, JS eval on problematic pages
- The built-in `browser_*` tools (browser_navigate, browser_snapshot, browser_scroll, browser_console) are for single-tab use on the connected browser

### CDP Python WebSocket Fallback

When `browser_console` is too slow or unreliable, connect directly via Python websockets:

```python
import json, asyncio, websockets, urllib.request

# Get tab WS URLs
tabs = json.loads(urllib.request.urlopen('http://192.168.65.254:9222/json').read())
fb_tab = next(t for t in tabs if t['type']=='page' and 'buy_sell_discussion' in t.get('url',''))
ws_url = fb_tab['webSocketDebuggerUrl']

async def cdp_eval(expr):
    async with websockets.connect(ws_url, max_size=100*1024*1024) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":expr,"returnByValue":True}}))
        while True:
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if resp.get('id') == 1:
                return resp.get('result',{}).get('result',{})
```

**WebSocket connections drop** after heavy page operations (scrolling, large DOM queries). Use short-lived connections per CDP call — reconnect for each operation. Keep JS expressions short to avoid timeouts.

### FB Post Pages Are Unreliable for Extraction

Individual post pages (`/groups/vanzareceasuri/posts/ID/`) take 10+ seconds to load, show loading skeletons for article content, and the `[role="dialog"]` often shows Facebook notifications instead of post content. **Avoid navigating to individual post pages for data extraction.** Instead, extract all data from the feed page HTML JSON as described in "Finding Watch Posts" above.
When Facebook CDN URLs with non-ASCII characters (e.g., `oh=00_Af...` params with special chars) enter the browser context, the CDP session can become corrupted. Symptoms:
- `browser_navigate` fails with `'utf-8' codec can't decode byte 0xcf in position 28`
- `browser_snapshot` fails with the same encoding error
- `browser_console` JS eval still works

**Workaround**: Use `window.location.replace()` via `browser_console` to navigate instead of `browser_navigate`:
```javascript
window.location.replace('https://www.facebook.com/groups/vanzareceasuri/');
```
After navigating away from Facebook, the encoding issue resolves and `browser_navigate`/`browser_snapshot` work again.

**Full CDP Python WebSocket fallback**: If `browser_console` is also too slow, connect directly to `http://192.168.65.254:9222/json/list`, get the tab's `webSocketDebuggerUrl`, and use Python `websockets` to send CDP commands. Navigate via `Runtime.evaluate` with `window.location.replace()`.

### Image Injection — One at a Time
When injecting multiple images, some Facebook CDN URLs cause `'utf-8' codec can't decode` errors when passed as strings in `browser_console` expressions. **Inject images one at a time** in separate `browser_console` calls:

```javascript
// Image 1
(async () => {
  const url = "https://scontent-hel3-1.xx.fbcdn.net/v/t39.30808-6/...";
  const resp = await fetch(url);
  const blob = await resp.blob();
  const dataUrl = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(blob); });
  document.getElementById('images_payload').value = JSON.stringify([{data_url: dataUrl}]);
  return 'img1 OK';
})();

// Image 2 (separate call)
(async () => {
  const url = "https://scontent-hel3-1.xx.fbcdn.net/v/t39.30808-6/...";
  const resp = await fetch(url);
  const blob = await resp.blob();
  const dataUrl = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(blob); });
  const existing = JSON.parse(document.getElementById('images_payload').value || '[]');
  existing.push({data_url: dataUrl});
  document.getElementById('images_payload').value = JSON.stringify(existing);
  return 'img2 OK, total: ' + existing.length;
})();
// Repeat for each additional image...
```

### Missing Description and Source URL
Imported watches must include `description`, `source_url`, and `facebook_listing_id`. Without `description`, the watch page shows no "Descriere" section. Without `source_url`, there is no "Vezi sursa originală" back-link to Facebook. These are not optional — always extract the full post text and post URL from Facebook and pass them to `importWatch()` as `description`, `sourceUrl`, and `fbListingId`.

### 3ceasuri.ro Database Outages
The admin may return `OperationalError: failed to resolve host 'anunturi1-anunturi.h.aivencloud.com'` when the PostgreSQL database is unreachable. This is a server-side infrastructure issue. Check by navigating to the admin page — if you get a Django error page with traceback, the DB is down. Wait and retry later.

### Image Fetching Failures (CORS/Network Issues)
The `importWatch` function attempts to fetch images directly from Facebook URLs using `fetch()`. This can fail due to:
- **CORS restrictions** when running from 3ceasuri.ro domain to fbcdn.net
- **Network timeouts** on large images or slow connections
- **Expired Facebook CDN URLs** (signed URLs expire after a few hours)

**If image fetching fails but you have the raw URLs:**
1. Proceed with the import anyway - the watch can be saved without images
2. Or, manually inject images as data URLs using a separate process:
   - Fetch and convert images to data URLs in execute_code (where CORS doesn't apply)
   - Pass the data URLs to importWatch instead of raw Facebook URLs
   - Or, set `#images_payload.value` directly with the JSON array of data URL objects

**To diagnose fetch issues:** Check the browser console for `[HARNESS] FETCH FAIL:` messages after running importWatch. If you see fetch errors but some images succeeded, the import may still work with partial images.

**Never skip a watch solely due to image issues** — extract the data and save the watch, then retry image fetching separately if needed.

## Session Notes

- 2026-06-21: Agent used raw CDP websockets instead of browser-use CLI. Root cause: didn't load/follow existing skills. Key lessons: (1) Always load skill first, (2) Follow steps exactly, (3) browser-use CLI primary for FB, (4) Extract from feed HTML regex, (5) Individual post pages show notifications, (6) Keep responses concise. See `references/session-2026-06-21.md`
- 2026-06-20: Feed scrolling doesn't work. Extract from HTML regex. browser-use CLI requires browser-level WS URL.

## Form Field Reference

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

## Post/Listing ID Discovery

Commerce listing IDs are found in the feed as `a[href*="commerce/listing/"]`:
```javascript
document.querySelectorAll('a[href*="commerce/listing/"]').forEach(function(a) {
  var m = a.href.match(/commerce\/listing\/(\d+)/);
  if (m) console.log(m[1]); // Commerce listing ID
});
```

Then navigate directly: `https://www.facebook.com/commerce/listing/LISTING_ID/`
