---
name: fb-find-posts
description: Invoke at the start of each watch loop to discover the next qualifying watch-sale post (and its post ID) in the Facebook group feed.
---

# fb-find-posts

Discover the next qualifying watch-sale post in the FB group feed and pick its post ID.

**Tool:** The FB tab must be active. Use `browser_console` (synchronous JS only) or `browser-use` `js()`.
**Do NOT scroll with `browser_scroll` or browser-use's `scroll(x, y)` helper** — see
"Fallback: Limited Scrolling" for why and what to use instead.

## Harvest one feed read as a batch (anti-detection)

Each page load / navigation is what FB rate-detects — not mouse realism (see
`watch-troubleshooting` → Bot-Friction Symptoms for why). So minimise navigations by
treating one feed read as a batch, not a single post:

- **Read the already-loaded HTML/DOM before synthesising any scroll or click.** The primary
  method below needs zero interaction — always exhaust it first.
- **Extract EVERY qualifying post in that one read and cache the durable parts** — post IDs
  and text do not expire, so collect them all, then work through them (dedup-check + extract
  + import) without re-navigating the feed. This drops feed navigations from one-per-watch to
  one-per-batch.
- This does **not** violate iron rule #1 ("one watch at a time"). Only the *signed image
  URLs* expire, so those are still fetched per-watch in `fb-extract-post`, right before
  import — never pre-collected. You batch durable metadata, not images.
- When you must interact, pace it like a human (Fallback below); on friction, back off per
  the graduated ladder in `watch-troubleshooting` rather than retrying harder.

## Primary Method: Extract from Loaded Feed HTML

**Extract from the page HTML first** before scrolling — it needs zero interaction.

Two limits to know before you trust an empty result (both hit on 2026-07-17c):

- This regex reads `"message":{"text":"` out of the **embedded initial JSON**, so it only
  sees posts present at first render. Posts loaded later *by scrolling* exist only in the
  DOM and will NOT appear here — a feed full of fresh posts can still return 2 stale texts.
  Once you have scrolled, read text per-post from the DOM instead (see DOM Reading JS).
- An empty/stale result means "nothing in the initial payload", **not** "group exhausted".
  Scroll (correctly — see Fallback) before concluding anything.

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

The relevant regexes on `document.documentElement.outerHTML`:
- Post texts: regex `"message":{"text":"..."`
- Post IDs: regex `vanzareceasuri/posts/ID` or `vanzareceasuri/permalink/ID`
- Commerce listing IDs: regex `commerce/listing/ID`

## Post ID Sources (priority order)

1. **Commerce listing links** (`a[href*="commerce/listing/"]`) — PREFERRED. Navigate to `/commerce/listing/ID/`
2. **Photo links with `set=pcb.ID`** (buy/sell feed) — Works with photo viewer carousel
3. **Photo links with `set=gm.ID`** — May have stuck carousel, less reliable

## Qualifying Filter (per post)

Collect post data, then filter. Proceed only with posts that PASS all filters:
- Price >= 100 RON (or >= 20 EUR/$)
- Brand + model mentioned in post body
- Has visible images
- NOT replica/AAA+, NOT bulk, NOT non-watch item
- NOT Vinted invite links, NOT ads
- Skip cars and bulk lots

## Fallback: Limited Scrolling

Only scroll if the loaded HTML has no qualifying posts. **Pace it like a human** — vary the
wait (don't use one fixed interval), scroll one viewport at a time, and never burst-scroll.

**Scroll with `js('window.scrollBy(0, 1400)')`, never `scroll(x, y)` / `browser_scroll`.**
On browser-use 3.0, `scroll(0, 900)` moved the page *upward* (scrollY 12018 → 11718 → 11418)
and never advanced the feed. That silent failure is what produced the false "group exhausted"
verdict on 2026-07-17b; the very next session pulled 5 importable watches out of the same
feed using `window.scrollBy` (height 18939 → 28341). **The infinite feed does work.**

`js()` is synchronous, so drive the loop from Python:

```python
for i in range(10):                       # 3 is too few — real posts appeared at i=4..7
    js('window.scrollBy(0, 1400); "ok"')
    time.sleep(random.uniform(3, 6))      # jitter; fixed intervals read as a bot
    r = json.loads(js(PROBE))             # DOM Reading JS below
    # cache every new post ID + text as you go (virtualization eats them — see Pitfalls)
    if new_qualifying_found: break
```

**Diagnose a stall before blaming FB.** Log `document.body.scrollHeight` and `window.scrollY`
each pass:

| Symptom | Meaning |
|---|---|
| height grows (18939 → 28341) | scrolling works — keep going |
| height static, scrollY **not increasing** | YOUR scroll is broken, not FB. Fix the call |
| height static, scrollY increasing, no new posts | genuine end-of-feed or throttle → backoff ladder |
| height tiny (~2300) + `innerText` ~1KB right after `goto_url` | page still hydrating — wait 12–20s and re-read; do NOT scroll an empty document |

After ~10 fruitless scrolls → ONE main-group → buy/sell round-trip, then re-extract.

**Do not machine-gun the refresh.** Rapid identical navigation is itself a bot signal and
tends to make FB serve *less*, not more (observed: 4 back-to-back cycles kept returning the
same 3 posts). One paced main↔buy/sell round-trip per stall; on continued friction follow
the graduated backoff ladder in `watch-troubleshooting` (pause → one gentle re-read → stop
and report "exhausted for now"). Never escalate to more/faster navigation.

### DOM Reading JS (synchronous, keep under 3KB)

**Iterate `document.querySelector('[role="feed"]').children` — NOT `[role="article"]`.**
On the buy/sell feed `[role="article"]` matched only 2 nodes while the feed had 38 children
with 12+ real posts. Per-child gives you `{id, text, images}` already grouped by post, which
beats a flat text blob — you can filter and cache in one pass. Strip the repeated `Facebook`
branding noise: `txt.replace(/(Facebook\n?)+/g,'')`.

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

## User Preference

Never use the group search feature (`/search/?q=`) to find posts — extract/scroll the feed instead.

## Pitfalls

- **Scrolling fails to load more posts:** navigating between the main group and buy/sell refreshes the feed.
- **Cross-origin proxy iframe:** the buy/sell feed can load through `fbsbx.com/maw_proxy_page`; its DOM is invisible to JS eval on the parent page. Symptom: repeated "Facebook" branding text with no post content. Workaround: use the main group URL (`/groups/vanzareceasuri/`) instead.
- **Virtualized list:** Facebook removes off-screen posts from the DOM — `set=pcb.` links disappear after you scroll past. Collect post data/IDs as you go; don't scroll back up.
  **Recovery when you cached an ID but lost its text:** don't re-scroll hunting for it. Post
  IDs are durable — open `https://www.facebook.com/groups/vanzareceasuri/posts/<ID>/`
  directly (per `fb-extract-post` Method C, incl. its 15s + set-verification guard). On
  2026-07-17c this rescued 6 IDs captured by ID-only during an early scroll pass, and
  supplied the 5th watch after the live feed had gone sparse — cached IDs outlive the feed.
- **A sparse feed late in a session is normal.** Work your cached IDs instead of re-navigating;
  each extra feed load deepens the throttle for zero new posts.
- **Feed text scope:** scope feed text reads to `[role="feed"]` — `document.body.innerText` includes sidebar noise.

## Next

Once a post ID is chosen → run the duplicate check (see `admin-import-watch`), then invoke `fb-extract-post`.
