# Facebook Group Post ID Extraction — Reference

## Background

Facebook's CDP browser (Chromium DevTools Protocol) renders group feed posts with React lazy-loading. Articles visible on screen may contain readable text via `[role="feed"].innerText`, but DOM inspection reveals empty skeleton `[role="article"]` elements with no links for many regular posts.

## Method 1: Photo link `set=gm.PID` (most reliable)

Photo links in the feed have the pattern:
```
https://www.facebook.com/photo/?fbid=<FBID>&set=gm.<POST_ID>&idorvanity=<GROUP_ID>
```

The `set=gm.<NUMBER>` parameter contains the group post ID.

### Extraction JS
```javascript
var ids = new Set();
document.querySelectorAll('a[href*="set=gm."]').forEach(function(a) {
  var m = a.href.match(/set=gm\.(\d+)/);
  if (m) ids.add(m[1]);
});
// Returns: ["2044071959794786", "2044070439794938", ...]
```

### How to use the ID
Construct the post URL and navigate to it:
```
https://www.facebook.com/groups/vanzareceasuri/posts/POST_ID/
```

This opens the post in a `[role="dialog"]` overlay with full content and images.

### Why this works
- Photo links are ALWAYS rendered (unlike timestamp links which may be in empty skeleton articles)
- The `gm.` prefix stands for "group message" (Facebook internal naming)
- These IDs match the numeric range of timestamp link post IDs (confirmed: `2044094493125866`)

## Method 2: Timestamp link `/posts/` (limited)

Timestamp links below post author names contain `/posts/ID/` in their `href`:
```javascript
var ids = new Set();
document.querySelectorAll('a[href*="/posts/"]').forEach(function(a) {
  var m = a.href.match(/\/posts\/(\d+)/);
  if (m) ids.add(m[1]);
});
```

### Caveats
- Only works for admin/featured posts where articles are fully populated
- Regular posts render as empty `[role="article"]` skeletons with zero links
- The feed text is readable, but no link DOM nodes exist for method 2

## Why scrolling position matters

Facebook's virtualized list only keeps ~2-3 articles in the DOM at any scroll position. Posts above/below the viewport are removed.

**Strategy:** Scroll to where feed text shows watch posts, THEN immediately extract `set=gm.` IDs before scrolling further. Work position-by-position, processing posts as you find them.

## Method 3: `set=pcb.` Photo Links (buy/sell feed)

In the buy/sell feed (`/groups/978581759677150/buy_sell_discussion`), photo links use:
```
https://www.facebook.com/photo/?fbid=<FBID>&set=pcb.<PHOTO_SET_ID>&__cft__[0]=...
```

These open a single-photo page with a **working** "Next" button carousel (unlike `set=gm.` which gets stuck). Multiple images from the same post share the same `set=pcb.<PHOTO_SET_ID>` value.

**Extraction:**
```javascript
var links = document.querySelectorAll('a[href*="/photo/"]');
var pcbLinks = [];
links.forEach(function(l) {
  var href = l.href || '';
  var m = href.match(/set=pcb\.(\d+)/);
  if (m) pcbLinks.push({href: href.substring(0, 120), pcbId: m[1]});
});
// Group by pcbId to get all images per post
```

**Note:** `set=pcb.` IDs are NOT group post IDs — they're photo set IDs. To get the post ID, use the feed text extraction to find the seller name associated with a given `pcb.` group.

## Do NOT use

- `set=gm.` for multi-image collection — carousel gets stuck on first image in CDP
- `commerce/listing/ID` — these are marketplace listings, not group posts
- Group search (`/search/?q=`) — user explicitly prefers scrolling the feed
- DOM parent-walking to find post text — returns page-level text, not post-specific
