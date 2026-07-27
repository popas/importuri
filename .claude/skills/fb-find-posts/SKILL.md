---
name: fb-find-posts
description: Invoke ONCE per session (not once per watch) to discover qualifying watch-sale posts in the Facebook group feed — runs find-posts.py and triages the candidates it returns.
---

# fb-find-posts

Discovery runs as **one script call per session**, not a hand-driven scroll loop. The FB tab
must exist (`watch-session-setup`); `$PROJECT_ROOT` / `$CDP_HOST` are defined there.

```bash
export BU_CDP_URL="http://$CDP_HOST"
MAX_CANDIDATES=8 browser-use < $PROJECT_ROOT/harness/3ceasuri-import/scripts/find-posts.py
```

It hydrates the feed, iterates `[role="feed"]` children, applies the objective filters, scrolls
with human pacing and stall diagnosis, force-hydrates link-less posts, runs **Stage-1 admin
dedup on every candidate**, writes the full records to
`harness/3ceasuri-import/.candidates.json`, and prints two lines:

```
CANDIDATES: [{"id","kind","price","cur","brand","new_brand","author","snip"}, …]
STATS: {"candidates","seen","scrolls","dropped":{…},"admin_total","notes"}
```

Rejects are reported as **counts**, not entries — a feed full of ads costs you nothing.

## What the script decides vs what YOU decide

It applies only filters a regex gets right every time: video-first ads, blocklisted sellers,
missing price, price under the floor (100 RON / 20 EUR), explicit replica wording, wall clocks,
and already-imported post ids.

**The judgement calls stay with you.** Read each `snip` and drop candidates that are:

- bulk lots, trade-only bundles, or "collection" posts (one price, many watches)
- not a wristwatch, despite passing the wall-clock regex
- missing a real brand **or** model in the body text
- Vinted invite links, promoted ads, group-admin announcements
- cars, parts, straps, or anything that isn't the watch itself

`brand: null` / `new_brand: true` means no known brand matched — usually a genuinely new brand
(fine, the importer will flag it), sometimes a sign the post isn't a watch at all. Judge from
the snippet.

## Then

Work the surviving ids **one at a time** through `admin-import-watch`. The candidates file
holds the full post text, so a `/clear`ed context can resume from it without re-scraping —
re-running discovery costs a feed navigation and deepens FB throttling, so don't.

Post IDs are durable; only signed image URLs expire, and those are fetched per-watch at import
time. `kind: "listing"` candidates are commerce listings — import them with
`LISTING_ID=<id>` instead of `POST_ID=<id>`; the rest of the flow is identical.

If a sweep returns 0 candidates on a feed that clearly has posts, re-run it with
`DEBUG_DROPS=1` to see `DROPPED: [{id,why,snip}]` and confirm the filters aren't eating good
watches, rather than guessing from the counts.

## When it fails

0 candidates on a feed that visibly has posts, a stall, or an unreadable feed →
`harness/3ceasuri-import/references/feed-dom.md` (post-ID sources, scroll diagnosis table,
virtualization, proxy-iframe workaround, obfuscated timestamp zone). Persistent friction →
`watch-troubleshooting` and its backoff ladder. Never scroll with `scroll(x, y)` /
`browser_scroll`, and never use group search — both are explained there.
