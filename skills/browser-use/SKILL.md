---
name: browser-use
description: FB group scraping for watch automation. Feed scrolling, post ID extraction, image collection. Part of 3ceasuri watch automation project.
---

# Facebook → 3ceasuri.ro: FB Scraping Skill

**Project:** `/opt/data/proiecte/3ceasuri/`
**Orchestrator:** `Watch_Listing_Automation_Plan.md`

Extract watch sale posts from Facebook group "Vanzare si cumparare de ceasuri" and collect images for import into 3ceasuri.ro admin.

## Tool Strategy

**For Facebook operations, use the `browser-use` CLI** (`browser-use --cdp-url <url> tab/eval/scroll`). Facebook's CDN content causes UTF-8 encoding errors with built-in `browser_navigate`/`browser_snapshot`. The browser-use CLI handles this correctly.

**For Django admin form filling, use the `3ceasuri-import` skill** — it has the `importWatch()` harness and brand ID mapping.

**For FB feed scrolling + DOM reading, use `browser_scroll` + `browser_console`** with synchronous JS only (no async/await). This is the plan's Phase 0 protocol.

**Raw CDP via Python websockets** only as a last resort when both browser-use and browser_console fail.

## Communication Style

**Keep responses concise and action-oriented.** Don't narrate every step — just do it and report results. Show progress as "X/5 done". If the user says "stop", stop immediately and summarize.

## Golden Rule: Scroll, Don't Search

**NEVER use the group search feature (`/search/?q=`) to find watch posts.** Scroll the feed instead. The user's explicit preference: scroll until you find posts that match the criteria. Searching wastes time and returns stale/irrelevant results.

## Workflow (Per Watch)

### Phase A: Discover posts by scrolling

1. **Facebook feed** → `browser_navigate` to `https://www.facebook.com/groups/<numeric-group-id>/buy_sell_discussion`
2. **Scroll aggressively** → Use `browser_scroll` (repeatedly) and `window.scrollBy(0, 2000)` via eval to load more posts. The buy/sell tab only loads a few posts at a time; you MUST keep scrolling to reveal more.
3. **Read feed text** → `browser_console eval`: `document.querySelector('[role="feed"]').innerText` — this returns seller names, post titles, descriptions, prices, locations as readable text despite obfuscated timestamps.
4. **Quick-filter each post** → Price >= 500 RON (or >= 100 EUR), has brand+model in post body, not replica/AAA+, has visible images. REJECTED posts are skipped immediately.

### Phase B: Extract from a qualifying post

5. **Open the post** → Try approaches in order:
   a) Click the **image link** in the feed (e.g., "May be an image of...") — this often opens a lightbox/dialog with full post content.
   b) Click the **post text/content area** itself (not the author name, not the timestamp).
   c) If neither works, look for any clickable element in the article that isn't the author link.
   **⚠️ The timestamp link ("about an hour ago") does NOT open a dialog in the CDP browser. Skip it.**
6. **Extract text from dialog** → If a `[role="dialog"]` appears, scope queries to it: `document.querySelector('[role="dialog"]').innerText`. If no dialog opens, use the feed text directly from Phase A.
7. **Extract images from dialog** → `document.querySelectorAll('img[src*="scontent"]')` inside the dialog, filtered by `getBoundingClientRect().width > 100`.
8. **Close dialog** → click Close button or press Escape.

### Phase C: Add to admin

9. **Navigate to admin** → `browser_navigate` to `https://3ceasuri.ro/admin/watches/watch/add/`
10. **Fill form, inject images, submit** → see Django Admin sections below
11. **Repeat** — form auto-resets after "Save and add another". Navigate back to Facebook to continue.

## Reading Facebook Feed Text

Desktop Facebook renders readable post text inside `[role="feed"]`:

```javascript
document.querySelector('[role="feed"]').innerText
// Returns: seller name, post title, description, price, location, etc.
```

Facebook obfuscates timestamps and author names as individual character spans, but post TITLES, DESCRIPTIONS, and PRICES render as normal readable text.

## Opening Individual Posts

**⚠️ Timestamp links do NOT work in the CDP browser.** Clicking "about an hour ago" or similar timestamp links has no effect — no dialog opens, the page doesn't change. Facebook's React event handlers don't fire on these links through CDP.

**Try these instead (in order of preference):**

1. **Click the image link** in the feed — posts have image thumbnails wrapped in `<a>` tags. The snapshot shows them as "May be an image of wrist watch" with ref IDs. Clicking these often opens the post dialog/lightbox.
2. **Click the post content area** — the post body text itself may be a clickable region that opens the full post view.
3. **Click the post's actions menu** ("Actions for this post") → look for a "View post" or "Open post" option.
4. **Fallback: use feed text only** — if no dialog opens, extract data directly from the feed's `[role="feed"].innerText`. You'll have brand, model, price, and description but NO images. Images can sometimes be found via `browser_get_images` on the feed page and matched to posts by position.

When a dialog DOES open, it appears as `[role="dialog"]` and contains the full post with all images.

## Extracting Images from Dialog

### From the post dialog (image thumbnails)
When you navigate to `/groups/vanzareceasuri/posts/POST_ID/`, the post opens as a `[role="dialog"]`. The dialog contains image thumbnail links shown as "May be an image of...". **Click the image link to open the Photo Viewer** (full-screen lightbox), then extract images from there.

### From the Photo Viewer (primary method — full-size images)
After clicking an image in the dialog, Facebook opens a Photo Viewer. The viewer shows the image at full resolution. Extract ALL images in the viewer:
```javascript
Array.from(document.querySelectorAll('img'))
  .filter(function(img) {
    return img.naturalWidth > 200 &&
           img.getBoundingClientRect().width > 50 &&
           !img.src.includes('static.xx.fbcdn') &&
           !img.src.startsWith('data:');
  })
  .map(function(img) { return img.src; })
```
**Navigate with the div button, NOT ArrowRight:**
```javascript
// Click "Next photo" — use div[aria-label], not keyboard
var next = document.querySelector('div[aria-label="Next photo"]') ||
           Array.from(document.querySelectorAll('button')).find(function(b) {
             return (b.getAttribute('aria-label')||'').includes('Next photo');
           });
if (next && !next.disabled) { next.click(); }
// ❌ ArrowRight key does NOT work in CDP browser
```
**Repeat until Next is disabled or missing.** Collect unique URLs by filename (part before `?`). A post with "Previous photo" AND "Next photo" buttons visible typically has 2+ images. If both show after collecting once and Next is still clickable, continue the loop.
```javascript
var base = url.split('?')[0]; // dedupe by filename
```

**⚠️ Keep the EXACT URLs** from `img.src` — do NOT strip query parameters, do NOT run the upgrade regex. The Facebook CDN requires the signed parameters (`_nc_ohc=`, `oh=`, `oe=`) for access. Stripped/truncated URLs return "Bad URL hash".

## Django Admin Image Injection

**⚠️ CRITICAL — Use COMPLETE image URLs.** Facebook CDN image URLs contain signed query parameters (`_nc_ohc=`, `oh=`, `oe=`) that are REQUIRED for access. Stripping, truncating, or regex-cleaning these URLs results in **"Bad URL hash"** errors from the CDN. Use the EXACT `img.src` value from the photo viewer — do NOT modify or strip query parameters.

```javascript
(async () => {
  // Use COMPLETE URLs from photo viewer — no stripping, no truncation
  const urls = [
    "https://scontent-hel3-1.xx.fbcdn.net/v/t39.30808-6/709589984_1492116309378117_806867068208643213_n.jpg?stp=cp6_dst-jpg_s1080x2048_tt6&_nc_cat=100&ccb=1-7&_nc_sid=aa7b47&_nc_ohc=-ABC1234Q7kNvwFDQyxK&_nc_oc=AdoMwHuTeo81...&_nc_zt=23&_nc_ht=scontent-hel3-1.xx&_nc_gid=XYZ&_nc_ss=7b2a8&oh=00_Af...&oe=6A22040C",
    // ... more complete URLs
  ];
  const images = [];
  for (const url of urls) {
    try {
      const blob = await fetch(url).then(r => r.blob());
      const dataUrl = await new Promise((res, rej) => {
        const reader = new FileReader();
        reader.onload = () => res(reader.result);
        reader.onerror = rej;
        reader.readAsDataURL(blob);
      });
      images.push({ data_url: dataUrl });
    } catch(e) { console.error('img fail', url.substring(0, 80), e.message); }
  }
  document.getElementById('images_payload').value = JSON.stringify(images);
  document.title = 'IMAGES_SET: ' + images.length + '/' + urls.length;
})();
```

Wait 5-10s, then verify: `document.title` shows `IMAGES_SET: N/M` AND check `document.getElementById('images_payload').value.length > 200` (real base64 images produce payloads of thousands of chars). A payload of ~200 chars with "data:text/plain;base64,QmFkIFVSTCBoYXNo" means ALL images failed with "Bad URL hash" — your URLs are incomplete or stripped.

**Critical:** Each entry MUST be `{"data_url": "..."}` — NOT a plain string. Plain strings cause `AttributeError: 'str' object has no attribute 'get'`.

## Django Admin Form Filling

**Fill EVERY field the Facebook post mentions.** The 5 required fields (Brand, Model, Condition, Movement, Price) are minimum. If the post mentions diameter, case material, bracelet, water resistance, display type, year — fill them all. Use `.value` + `dispatchEvent(new Event('change'))` for all fields.

**Brand — Direct Injection via ID Mapping (PRIMARY method):**
```javascript
// One call, instant. Scrape the brand list page once to build this mapping.
var BRAND_IDS = {"Certina":28,"Spinnaker":27,"Atlantic":26,"Orient":25,"Cauny":24,"Doxa":23,"Seconda":22,"Fossil":21,"Maurice Lacroix":20,"Bischoff":19,"Longines":18,"Hamilton":17,"Zenith":16,"Seiko":15,"Tudor":14,"Citizen":13,"Tissot":12,"Poljot":11,"Cartier":10,"Le Duc":9,"Racheta":8,"Omega":7,"TITUS Geneve":6,"Glashutte":5,"Rotary":4,"Rolex":3,"Casio":2,"Aerowatch":1};

var brandId = BRAND_IDS["Spinnaker"];  // 27
var select = document.getElementById('id_brand');
var opt = document.createElement('option');
opt.value = brandId; opt.textContent = 'Spinnaker'; opt.selected = true;
select.appendChild(opt);
select.value = brandId;
select.dispatchEvent(new Event('change', {bubbles: true}));
document.querySelector('#select2-id_brand-container').textContent = 'Spinnaker';
// Verify: document.getElementById('id_brand').value === brandId
```

**Brand — Select2 (FALLBACK only, for brands NOT in the mapping):**
Use mousedown/mouseup/click dispatchEvents on the Select2 container, NOT `browser_type`:
```javascript
var c = document.querySelector('#select2-id_brand-container');
['mousedown','mouseup','click','focus'].forEach(e => c.dispatchEvent(new MouseEvent(e, {bubbles: true})));
// Wait 2s, then type into .select2-search__field via JS, wait 3s, click li[role=option]
```

**All other fields:** Set `.value` + dispatch `change` event. This works for text inputs, `<select>`, and `spinbutton`.
```javascript
document.getElementById('id_model_name').value = 'Ds Podium Chronograph';
document.getElementById('id_condition').value = 'good'; document.getElementById('id_condition').dispatchEvent(new Event('change'));
document.getElementById('id_movement').value = 'quartz'; document.getElementById('id_movement').dispatchEvent(new Event('change'));
document.getElementById('id_price').value = '1200';
// Optional — fill if post mentions:
document.getElementById('id_case_diameter_mm').value = '44.5';
document.getElementById('id_case_material').value = 'steel'; document.getElementById('id_case_material').dispatchEvent(new Event('change'));
document.getElementById('id_bracelet_material').value = 'steel'; document.getElementById('id_bracelet_material').dispatchEvent(new Event('change'));
document.getElementById('id_type').value = 'men'; document.getElementById('id_type').dispatchEvent(new Event('change'));
// ... etc for waterRes, displayMat, displayColor, displayType, displaySize, year, currency
```

**Submit:** `document.querySelector('input[name="_addanother"]').click()` via JS eval.
**Verify:** Two green banners — "X imagini salvate..." AND 'The watch "Brand Model" was added successfully...'

## Duplicate Check

Navigate to `https://site.com/admin/model/?q=<brand+model>`. If results exist, skip. Post IDs from Facebook are unreliable — search by brand+model name instead.

## Extracting Post IDs and Navigating to Posts

**Post IDs ARE extractable.** Two methods, in order of reliability:

### Method 1: Photo links with `set=gm.PID` (most reliable)
Scroll the feed to where watch posts appear, then extract post IDs from photo links:
```javascript
var ids = new Set();
document.querySelectorAll('a[href*="set=gm."]').forEach(function(a) {
  var m = a.href.match(/set=gm\.(\d+)/);
  if (m) ids.add(m[1]);
});
// Returns: ["2044071959794786", ...]
```
These `gm.NNN` values ARE group post IDs. Use them to navigate directly.

### Method 2: Timestamp links with `/posts/` (works for some posts)
For admin/featured posts, timestamp links below the author name contain `/posts/ID/` in their `href`:
```javascript
var ids = new Set();
document.querySelectorAll('a[href*="/posts/"]').forEach(function(a) {
  var m = a.href.match(/\/posts\/(\d+)/);
  if (m) ids.add(m[1]);
});
```
**Caveat:** Regular (non-admin) posts may render as empty `[role="article"]` skeletons with no links — Facebook's React lazy loading. If method 2 returns nothing, use method 1. Detailed reference: `references/post-id-extraction.md`.

### Direct navigation (preferred extraction method)
Once you have a post ID, navigate directly to the post page to open it in a dialog:
```
https://www.facebook.com/groups/vanzareceasuri/posts/POST_ID/
```
The post opens as a `[role="dialog"]` with full text content and images. This is the PRIMARY extraction method — more reliable than clicking links in the feed.

## CDP Python WebSocket Workaround (when browser_navigate/snapshot fail)

When `browser_navigate` and `browser_snapshot` fail with `'utf-8' codec can't decode byte 0xcf` encoding error (caused by Facebook CDN URLs with signed params entering the browser context), use direct CDP WebSocket calls from Python instead.

### How to connect
```python
import json, asyncio, websockets, urllib.request

async def main():
    resp = urllib.request.urlopen('http://192.168.65.254:9222/json/list')
    tabs = json.loads(resp.read())
    # Find the Facebook tab
    fb_tab = [t for t in tabs if 'facebook.com' in t.get('url','')][0]
    ws_url = fb_tab['webSocketDebuggerUrl']
    
    async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
        # Navigate via window.location (avoids encoding issue)
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 
            'params': {'expression': "window.location.replace('https://...'); 'ok'"}}))
        r = await asyncio.wait_for(ws.recv(), timeout=10)
        
        # Wait for page load
        await asyncio.sleep(10)
        
        # Execute JS
        await ws.send(json.dumps({'id': 2, 'method': 'Runtime.evaluate',
            'params': {'expression': 'document.title'}}))
        r = await asyncio.wait_for(ws.recv(), timeout=10)
        data = json.loads(r)
        print(data['result']['result']['value'])
```

### Key rules
- Use `ws_url` from the tab's `webSocketDebuggerUrl` field (NOT the HTTP endpoint)
- Always `await asyncio.wait_for(ws.recv(), timeout=10)` after each send
- Navigate with `window.location.replace()` via Runtime.evaluate to avoid the encoding bug
- `browser_console` still works even when `browser_navigate`/`browser_snapshot` fail — use it as fallback
- After navigating away from Facebook (to any non-FB URL), `browser_navigate`/`browser_snapshot` work again

## Extracting Images from Photo Viewer

### `set=gm.` Photo Links — Opens Carousel (may get stuck)

Links with `set=gm.<POST_ID>` open a photo viewer carousel. However, the "Next photo" button may NOT advance — the carousel gets stuck on the first image. This is a known CDP issue.

**Workaround:** After clicking a `set=gm.` link and opening the photo viewer:
1. Collect the current image
2. Check if "Next photo" button exists and is NOT disabled
3. Click it and wait 3s
4. If the same image URL appears (same filename before `?`), the carousel is stuck — stop and move on
5. If it advances, collect until "Next" is disabled or missing

### `set=pcb.` Photo Links — Opens Single Photo with Carousel

Links with `set=pcb.<PHOTO_SET_ID>` (found in buy/sell feed) open a single photo page that DOES have a working "Next" button carousel. These are more reliable for multi-image collection.

**Extraction pattern:**
```javascript
// On the photo page, collect current image then click Next
var urls = []; var seen = new Set();
function collect() {
  var imgs = Array.from(document.querySelectorAll('img')).filter(function(i) {
    return i.naturalWidth > 400 && i.getBoundingClientRect().width > 50 &&
           !i.src.includes('static.xx.fbcdn') && !i.src.startsWith('data:');
  });
  if (imgs.length > 0) {
    var base = imgs[0].src.split('?')[0].split('/').pop();
    if (!seen.has(base)) { seen.add(base); urls.push(imgs[0].src); }
  }
  var next = document.querySelector('div[aria-label="Next photo"]') ||
             Array.from(document.querySelectorAll('button')).find(function(b) {
               return (b.getAttribute('aria-label')||'').includes('Next');
             });
  if (next && !next.disabled) { next.click(); return true; }
  return false;
}
// Call collect() repeatedly with 3s waits until it returns false
```

### From the Photo Viewer (primary method — full-size images)
After clicking an image in the dialog, Facebook opens a Photo Viewer. The viewer shows the image at full resolution. Extract ALL images in the viewer:
```javascript
Array.from(document.querySelectorAll('img'))
  .filter(function(img) {
    return img.naturalWidth > 200 &&
           img.getBoundingClientRect().width > 50 &&
           !img.src.includes('static.xx.fbcdn') &&
           !img.src.startsWith('data:');
  })
  .map(function(img) { return img.src; })
```

## Photo Link Types: `set=pcb.` vs `set=gm.`

Facebook buy/sell feed has two distinct photo link formats with different carousel behavior:

### `set=pcb.<PHOTO_SET_ID>` — Multi-image carousel (WORKS)
Links like `facebook.com/photo/?fbid=123&set=pcb.456` open a photo viewer with a WORKING "Next photo" carousel. The Next button (`div[aria-label="Next photo"]` with class `x1qjc9v5`) advances correctly through all images.

### `set=gm.<POST_ID>` — Single photo (CAROUSEL GETS STUCK)
Links like `facebook.com/photo/?fbid=123&set=gm.456` open a photo viewer where the "Next photo" button exists but does NOT advance — it stays on the same image. Only 1 image collectible. **Do NOT use `set=gm.` links for image collection.**

### How to find `set=pcb.` links in the buy/sell feed:
```javascript
var links = document.querySelectorAll('a[href*="/photo/"]');
var pcbIds = new Set();
links.forEach(l => {
  const href = l.href || l.getAttribute('href') || '';
  const m = href.match(/set=pcb\.(\d+)/);
  if (m) pcbIds.add(m[1]);
});
```

### Carousel collection pattern (pcb links only):
```javascript
var urls = []; var seen = new Set();
for (var step = 0; step < 15; step++) {
  // Collect current largest image
  var imgs = Array.from(document.querySelectorAll('img')).filter(function(i) {
    return i.naturalWidth > 400 && i.getBoundingClientRect().width > 50 &&
           !i.src.includes('static.xx.fbcdn') && !i.src.startsWith('data:');
  });
  imgs.sort((a,b) => b.naturalWidth - a.naturalWidth);
  if (imgs.length > 0) {
    var base = imgs[0].src.split('?')[0].split('/').pop();
    if (!seen.has(base)) { seen.add(base); urls.push(imgs[0].src); }
  }
  // Click Next — MUST use the visible button with class x1qjc9v5
  var btns = document.querySelectorAll('div[aria-label="Next photo"]');
  var clicked = false;
  for (var i = 0; i < btns.length; i++) {
    if (btns[i].getBoundingClientRect().width > 0 && btns[i].className.indexOf('x1qjc9v5') > -1) {
      btns[i].click(); clicked = true; break;
    }
  }
  if (!clicked) break; // No more Next buttons = all images collected
  await new Promise(r => setTimeout(r, 3000)); // Wait 3s between images
}
```

**⚠️ IMPORTANT:** Facebook's virtualized list removes off-screen posts. After scrolling past a post, its `set=pcb.` links disappear from DOM. Collect image URLs from the feed page BEFORE scrolling past, or navigate directly to the photo page using the `set=pcb.` ID.

## Form Submission: Complete Fill + Inject + Submit in ONE Pass

When filling the Django admin form, ALL steps must happen in a single pass without intermediate navigation. Any navigation (e.g., to Facebook to collect images) clears the form state.

### Critical: Re-inject everything after ANY page navigation
- `images_payload` clears on page re-render
- Brand selection via direct injection clears if Select2 search is used
- All field values reset after `Page.navigate` to another site

### Correct order (no navigation between steps):
1. Navigate to admin add-watch form
2. Fill brand (direct injection)
3. Fill all text fields
4. Inject images (fetch + encode + set `#images_payload`)
5. Submit immediately (do NOT navigate away between steps)

### Submit button click pattern:
```javascript
// Use mousedown+mouseup+click for reliable submission
var btn = document.querySelector('input[name="_addanother"]');
btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
btn.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
```

## What DOESN'T Work on Facebook

- **Individual post pages for data extraction:** Navigating to `/groups/vanzareceasuri/posts/ID/` takes 10+ sec, shows loading skeletons, and the `[role="dialog"]` shows Facebook notifications instead of post content. Extract ALL data from the feed page, not individual post pages.
- **Timestamp link OPENING a dialog:** Clicking "about an hour ago" links does not open the post dialog in the CDP browser. The links DO contain post IDs in their `href` (see extraction method 2 above), but clicking them has no effect.
- **Author name click:** Navigates to profile, not post. Do NOT click author names.
- **Group search (`/search/?q=`):** Do NOT use it — the user prefers scrolling the feed. Search returns stale/mixed results and wastes time.
- **`mbasic.facebook.com`:** Redirects to `www.facebook.com` with `?__mmr=1&_rdr`. Cannot be used for plain-HTML scraping.
- **`browser-use` CLI:** Unnecessary — built-in tools already control the CDP browser correctly.
- **`set=gm.` photo links for multi-image collection:** Carousel gets stuck on first image. Use `set=pcb.` links instead.

## Extracting Post Text from the Feed

Facebook's DOM structure makes it impossible to walk up from a link to find the post text container. The `innerText` of ancestor divs either returns the entire page text or nothing useful. Instead, use TreeWalker on `[role="feed"]` to get ALL post text, then identify individual posts by their position in the text:

```javascript
const f = document.querySelector('[role="feed"]') || document.body;
const w = document.createTreeWalker(f, NodeFilter.SHOW_TEXT, {
  acceptNode: n => n.textContent.trim().length > 2 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP
});
let t = ''; let n;
while (n = w.nextNode()) t += n.textContent;
// t contains ALL posts' text: seller names, descriptions, prices, locations
```

**Individual post identification:** Once you have a post ID (from `set=gm.` photo links), find its position in the feed text by searching for the seller name or unique text fragments. The posts appear in the same order in the DOM and in the extracted text.

**Do NOT try:** `link.parentElement.parentElement... innerText` — this returns page-level text, not post-specific text.

## Pitfalls

- **Feed is sparse — keep scrolling:** The buy_sell_discussion page only loads a few posts at a time. Facebook's virtualized list removes off-screen articles from the DOM. Scroll repeatedly with `window.scrollBy(0, 2000)` via eval, waiting 2-3s between scrolls for content to load. Collect post data as you scroll — don't try to scroll back up (content gets removed).
- **Do NOT use search:** The user explicitly prefers scrolling the feed over using the group search feature. Searching wastes time.
- **Use COMPLETE image URLs:** Facebook CDN URLs have signed params (`_nc_ohc=`, `oh=`, `oe=`). Stripping them causes "Bad URL hash" failures. Always use the exact `img.src` value from the photo viewer.
- **Verify image payload size:** A successful injection produces `images_payload.value.length` in the thousands (base64 images). A value of ~200 chars with "data:text/plain;base64,QmFkIFVSTCBoYXNo" means ALL images failed. Re-extract URLs from Facebook and retry.
- **Images lost on re-render:** Re-inject if validation error forces form re-render.
- **Select2 brand:** Use direct injection (inject `<option>` + set `.value` + dispatch `change` + update container text). This is instant and reliable. Only use the Select2 click-type-click search as fallback for unknown brands NOT in the brand ID mapping.
- **`browser_type`:** NEVER use for any form field — it types into the wrong element (usually the Random ID field). Always use JS `.value =` + `dispatchEvent('change')` instead.
- **Currency values:** Use `"RON"` / `"EUR"` (value attr), NOT display text (`"Lei"` / `"Euro"`).
- **Dialog image links in snapshot:** Show as "May be an image of..." — click them to open the Photo Viewer, then use JS eval to get actual `src` URLs.
- **Feed text extraction scope:** Always use `[role="feed"]` for feed text — `document.body.innerText` includes sidebar/recommendations/noise. For individual post pages, scope to `[role="dialog"]` if one opened.
