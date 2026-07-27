# Feed DOM reference (discovery fallback)

`find-posts.py` encodes everything here. **Read this only when that script fails** — when
it returns 0 candidates on a feed you can see has posts, when scrolling stalls, or when you
must drive the feed by hand. Nothing here is needed on the happy path.

## Post ID sources (priority order)

1. **Commerce listing links** (`a[href*="commerce/listing/"]`) — navigate to `/commerce/listing/ID/`
2. **Photo links with `set=pcb.ID`** (buy/sell feed) — works with the photo-viewer carousel
3. **Photo links with `set=gm.ID`** — carousel gets stuck; unreliable for image collection

**Never parse the timestamp/permalink line for an ID.** FB scrambles that zone by interleaving
single-character `aria-hidden="true"` decoy spans and reordering them with CSS `order`. A raw
text read yields garbage like `p o o s t n S r e d l f 4 7 u : 4 …`, and because CSS reorders
the *visible* characters while DOM order stays scrambled, it is unrecoverable even after
removing the decoys. The post **body** (brand/model/price) is NOT obfuscated and reads clean.
Every reliable ID comes from an image or listing link.

## Iterate `[role="feed"].children`, not `[role="article"]`

On the buy/sell feed `[role="article"]` matched only 2 nodes while the feed had 38 children
with 12+ real posts. Per-child iteration also gives you `{id, text, images}` already grouped
by post. Strip the repeated branding noise: `txt.replace(/(Facebook\n?)+/g,'')`, and scope
text reads to `[role="feed"]` — `document.body.innerText` drags in sidebar noise.

```javascript
(() => {
  const f = document.querySelector('[role="feed"]') || document.body;
  const isHidden = el => { for (let e = el; e && e !== f; e = e.parentElement)
    if (e.getAttribute && e.getAttribute('aria-hidden') === 'true') return true; return false; };
  const w = document.createTreeWalker(f, NodeFilter.SHOW_TEXT, {
    acceptNode: n => (n.textContent.trim().length > 2 && !isHidden(n.parentElement))
      ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP
  });
  let t = ''; let n;
  while (n = w.nextNode()) t += n.textContent;
  const ids = new Set();
  document.querySelectorAll('a[href*="/photo/"]').forEach(l => {
    const m = (l.href || '').match(/set=pcb\.(\d+)/) || (l.href || '').match(/set=gm\.(\d+)/);
    if (m) ids.add(m[1]);
  });
  document.querySelectorAll('a[href*="commerce/listing/"]').forEach(l => {
    const m = (l.href || '').match(/commerce\/listing\/(\d+)/);
    if (m) ids.add('listing:' + m[1]);
  });
  return JSON.stringify({ids: [...ids], textLen: t.length, text: t.substring(0, 6000)});
})()
```

## Initial-payload extraction (zero interaction)

`"message":{"text":"…"}` in `document.documentElement.outerHTML` yields post texts from the
**embedded initial JSON**. Two limits: it only sees posts present at first render (anything
loaded by scrolling exists only in the DOM), and an empty result means "nothing in the initial
payload", **not** "group exhausted".

## Scrolling

**Use `js('window.scrollBy(0, 1400)')`, never `scroll(x, y)` / `browser_scroll`.** On
browser-use 3.0, `scroll(0, 900)` moved the page *upward* (scrollY 12018 → 11718 → 11418) and
never advanced the feed. That silent failure produced a false "group exhausted" verdict on
2026-07-17b; the next session pulled 5 importable watches out of the same feed with
`window.scrollBy` (height 18939 → 28341). **The infinite feed does work.**

Pace it like a human: one viewport at a time, jittered 3–6s waits, never burst-scroll. Log
`document.body.scrollHeight` and `window.scrollY` each pass and diagnose before blaming FB:

| Symptom | Meaning |
|---|---|
| height grows (18939 → 28341) | scrolling works — keep going |
| height static, scrollY **not increasing** | YOUR scroll is broken, not FB. Fix the call |
| height static, scrollY increasing, no new posts | genuine end-of-feed or throttle → backoff ladder |
| height tiny (~2300) + `innerText` ~1KB right after `goto_url` | still hydrating — wait 12–20s, do NOT scroll an empty document |

After ~10 fruitless scrolls → ONE main-group → buy/sell round-trip, then re-extract. **Do not
machine-gun the refresh** — rapid identical navigation is itself a bot signal and makes FB
serve *less* (observed: 4 back-to-back cycles returning the same 3 posts). On continued
friction follow the graduated backoff ladder in `watch-troubleshooting`. Never escalate to
more or faster navigation.

## Recovery: a qualifying post with NO photo/permalink link

Some posts (video-first, or any post whose media hasn't lazy-loaded) render a feed child with
body text and a price but **zero** `set=pcb.`/`commerce/listing/` links, so no ID is
recoverable. This silently loses good listings — on 2026-07-24 it cost a ~7500 € Rolex
Submariner. Force-hydrate the media before giving up (`find-posts.py` does this automatically
for up to 2 link-less priced posts per pass):

```python
js(f'document.querySelector(\'[role="feed"]\').children[{idx}].scrollIntoView({{block:"center"}}); "c"')
time.sleep(4)                       # let lazy media / video poster load
# re-read that child's set=pcb.<ID> link
```

Retry once or twice. If no `set=pcb.` link appears, the ID is currently unreachable — record a
one-line note (author + title + price) and move on. Never decode the obfuscated timestamp.

## Pitfalls

- **Virtualized list:** FB removes off-screen posts from the DOM — `set=pcb.` links disappear
  after you scroll past. Collect IDs as you go; don't scroll back up. If you cached an ID but
  lost its text, don't re-scroll: post IDs are durable, so open
  `https://www.facebook.com/groups/vanzareceasuri/posts/<ID>/` directly (Method C in
  `post-extraction.md`). On 2026-07-17c this rescued 6 ID-only captures.
- **Cross-origin proxy iframe:** the buy/sell feed can load through `fbsbx.com/maw_proxy_page`,
  whose DOM is invisible to JS eval on the parent. Symptom: repeated "Facebook" branding text
  with no post content. Use the main group URL instead.
- **A sparse feed late in a session is normal.** Work your cached candidates rather than
  re-navigating; each extra feed load deepens the throttle for zero new posts.
- **Never use group search** (`/search/?q=`) to find posts — user preference; scroll the feed.
