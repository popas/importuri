# Cross-Site Automation: Facebook → Django Admin

Pattern for extracting data/posts from Facebook and publishing to a Django admin panel.

## Workflow

1. **Open both sites in separate tabs** using `browser-use tab new`
2. **Extract data** from the Facebook tab (images, text, price, location)
3. **Switch to Django admin tab**, fill form via JS injection
4. **Submit**, verify success, repeat with blank form ("Save and add another")

## Django Admin Image Injection

Many Django admin sites store uploaded images in a hidden `#images_payload` field as JSON:

```javascript
// Images MUST be objects {"data_url": "data:image/..."}, NOT plain strings
const images = [];
for (const url of fbImageUrls) {
  const blob = await fetch(url).then(r => r.blob());
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
  images.push({ data_url: dataUrl });
}
document.getElementById("images_payload").value = JSON.stringify(images);
```

**Why this works**: The Django tab can fetch Facebook CDN images via CORS (returns HTTP 200). Fetching from the sandbox (curl/wget) will fail — Facebook CDN blocks non-browser egress.

## Django Admin Post-Save Verification

After clicking "Save and add another", check for TWO success banners:
- Imagini salvate: "X imagini salvate și asociate cu ceasul."
- Watch added: 'The watch "Brand Model" was added successfully. You may add another watch below.'

## Duplicate Check Pattern

Before adding, open a new tab to check for duplicates:

```bash
browser-use tab new "https://site.com/admin/app/model/?q=POST_ID"
# Check page content — if 0 results, safe to proceed
# Then: browser-use tab close <index> && browser-use tab switch <form-tab>
```

## Facebook DOM Scraping Pitfalls (2026-05-31)

### Desktop Facebook group feed: anti-scraping blocks DOM extraction

Facebook's desktop group feed aggressively defends against scraping:

1. **Posts render as skeleton/loading states** — `[role=article]` elements exist in DOM but contain no text/links. Text visible on screen is rendered via React hydration that never populates `a[href]` attributes during the scraping window.
2. **Post text is obfuscated as individual character spans** — timestamps like "3 hours ago" render as `<span>r</span><span>S</span><span>t</span>` etc. These are images of letters, not text. `innerText` returns the concatenated characters, not useful data.
3. **`set=pcb.` pattern returns empty** — The photo links containing post IDs are never populated in the DOM due to lazy-loading. Repeated scrolling (30+ times) + long waits (8s) still yields empty results.
4. **"Buy and sell" tab shows marketplace listings**, not regular posts — links use `commerce/listing/<ID>` format, not `/vanzareceasuri/posts/POST_ID/`.
5. **All article elements may be loading skeletons** — Even after aggressive scrolling, `[role=article]` count stays at ~5 with `innerText.length === 0`.

### Workaround: Use m.facebook.com

The mobile site serves simpler HTML with real `a[href]` attributes:

```bash
browser-use --cdp-url "<ws-url>" tab new "https://m.facebook.com/groups/<group-slug>/"
# Then extract post IDs from real hrefs:
browser-use --cdp-url "<ws-url>" eval 'Array.from(document.querySelectorAll("a[href]")).map(a => (a.href||"").match(/posts\/(\d+)/)).filter(Boolean).map(m=>m[1])'
```

**Status: proposed but untested in session.** Try this before wasting time on desktop FB DOM scraping.

### NEVER use built-in browser tools on same CDP as browser-use

If `browser-use --cdp-url <ws>` manages tabs, **do not call `browser_navigate`** — it targets the Hermes layer's active tab (not the browser-use controlled tab), which can replace the URL on the wrong tab (e.g., overwriting the admin form tab with Facebook). After this happens, you must re-open the admin form in a new tab. Use `browser-use tab switch + eval` for everything on the shared CDP.

### Tool Isolation: built-in vs browser-use CLI (Session 2026-05-31)

The Hermes built-in browser tools and `browser-use --cdp-url` CLI share the same CDP browser but track DIFFERENT active tabs. Mixing them causes catastrophic navigation errors:

- `browser_navigate` targets the Hermes layer's "active" tab (not necessarily the browser-use selected tab)
- `browser_console` eval also targets the Hermes active tab
- Result: your admin form tab silently gets replaced with Facebook content

**Use one tool set exclusively:**
- Multi-tab workflow: `browser-use --cdp-url <ws>` CLI for everything
- Single-tab workflow: built-in tools only

**Recovery:** If admin form tab gets overwritten: `browser-use tab close <damaged>` then `browser-use tab new <admin-url>`.

## Form Submission Pattern (2026-06-18)

### Complete fill + inject + submit in ONE pass

Any navigation between filling steps clears the form state. The correct flow:

1. Navigate to admin add-watch form
2. Fill brand via direct injection (Longines=18, Rolex=3, etc.)
3. Fill all text fields (`.value` + `dispatchEvent('change')`)
4. Inject images (fetch from FB CDN → base64 → `#images_payload`)
5. Submit immediately — do NOT navigate between steps

### Submit button click (reliable pattern):
```javascript
var btn = document.querySelector('input[name="_addanother"]');
btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
btn.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
```

### Brand direct injection (proven working):
```javascript
var brandId = 18; // Longines
var select = document.getElementById('id_brand');
var opt = document.createElement('option');
opt.value = brandId; opt.textContent = 'Longines'; opt.selected = true;
select.appendChild(opt);
select.value = brandId;
select.dispatchEvent(new Event('change', {bubbles: true}));
document.querySelector('#select2-id_brand-container').textContent = 'Longines';
```

### Image injection (one at a time to avoid expression size limits):
```javascript
// For each image URL:
var js = '(async () => { const url = ' + json.dumps(url) + '; const resp = await fetch(url); const blob = await resp.blob(); const dataUrl = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob); }); const existing = JSON.parse(document.getElementById("images_payload").value || "[]"); existing.push({data_url: dataUrl}); document.getElementById("images_payload").value = JSON.stringify(existing); return "ok"; })()'
```

### Verification after submit:
```javascript
var text = document.body.innerText;
var hasImages = text.indexOf('imagini salvate') > -1;
var hasAdded = text.indexOf('added successfully') > -1;
```

## Common Pitfalls

- **Images lost on ANY navigation**: `#images_payload` resets when navigating to Facebook and back. ALWAYS collect images AFTER navigating to admin, inject, then submit in one pass.
- **Select2 dropdowns**: Standard `<select>` manipulation works for direct injection. Do NOT use Select2 search method — it clears the value.
- **Currency/option values**: Always use the `value` attribute, not display text (e.g., `"RON"` not `"Lei"`).
- **Form field IDs**: Verify IDs match exactly (e.g., `id_type` not `id_watch_type`).
- **`set=gm.` photo links**: Carousel stuck on 1 image. Use `set=pcb.` links for multi-image collection.
- **Expression size limit**: `browser_console` has ~3KB limit. Inject images one at a time, not in a batch loop.
