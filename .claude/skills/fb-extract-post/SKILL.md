---
name: fb-extract-post
description: Invoke after a qualifying post ID is chosen and the duplicate check has passed — extracts all fields and ALL image URLs from that ONE post, then hands them to admin-import-watch.
---

# fb-extract-post

Extract every field and EVERY image URL from one already-selected FB post. Try methods in
order: **A (commerce listing page) → B (feed HTML you already extracted) → C (individual post
page, last resort).** `$PROJECT_ROOT` / `$CDP_HOST` are defined in `watch-session-setup`.

## Method A: Commerce listing page (PREFERRED)

Navigate to `https://www.facebook.com/commerce/listing/LISTING_ID/`

**Why preferred:** All images are in the DOM simultaneously — no Next button, no carousel,
no stuck viewer. The page shows 5 thumbnails (Thumbnail 0-4) plus the main image, all in the
DOM simultaneously — do NOT click through them. The `img[src*="scontent"]` with `naturalWidth > 200` filter catches them all.

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

## Method B: Feed HTML text (no navigation)

If the post has no commerce listing, use the post text already captured by the feed-HTML
extraction during discovery (`fb-find-posts`); collect images via the photo-viewer carousel below using the post's `set=pcb.` photo link.

### Photo-viewer carousel collection (`set=pcb.` vs `set=gm.`)

- `set=pcb.<PHOTO_SET_ID>` opens a photo viewer with a WORKING "Next photo" carousel
  (`div[aria-label="Next photo"]` with class `x1qjc9v5`).
- `set=gm.<POST_ID>` opens a viewer whose Next button does NOT advance — carousel gets
  stuck on the first image; do NOT use `set=gm.` links for image collection.

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

- ArrowRight key does NOT work in the CDP browser — click the div button.
- On some pages the Next control appears as `[aria-label="View next image"]` or a button whose aria-label includes "Next".
- Dedupe collected URLs by filename (part before `?`).

## Method C: Individual post page (LAST RESORT)

Navigate to `https://www.facebook.com/groups/vanzareceasuri/posts/POST_ID/`, wait 8-10
seconds. Pages are slow and may show notifications instead of content — if the dialog shows
notifications, go back and use Method B. If content loads, click an image to open the photo viewer and collect via the carousel above.

## NEVER modify image URLs

Facebook CDN URLs carry signed params (`_nc_ohc=`, `oh=`, `oe=`) that are REQUIRED.
Stripping, truncating, or regex-"upgrading" them returns "Bad URL hash". Use the EXACT
`img.src`. FB CDN URLs also expire within hours — extract and import within the same session, re-extract fresh URLs on retry.

## Data to Extract

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

## Pitfalls

- Individual post pages are slow (8-10s) and often show notifications instead of content.
- `document.title` is blocked for values containing signed query params — read image URLs directly from `img.src` in the DOM, never via `document.title`.
- Timestamp links ("about an hour ago") do NOT open dialogs in the CDP browser (their hrefs still carry post IDs); clicking an author name navigates to the profile, not the post.
- `set=gm.` carousels get stuck; `set=pcb.` carousels work.

## Next

Pass the extracted raw fields + complete image URLs to `admin-import-watch`. Do NOT pre-format the description — pass the raw FB post text (the harness formats it).
