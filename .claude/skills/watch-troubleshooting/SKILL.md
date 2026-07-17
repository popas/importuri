---
name: watch-troubleshooting
description: Invoke ONLY when something fails during a watch-import session — UTF-8 codec crashes on FB, WebSocket drops, harness injection failures, image-injection errors, admin DB outages, or when applying the retry/rollback policy.
---

# Watch Troubleshooting

Failure modes and fallbacks only. `$PROJECT_ROOT` and `$CDP_HOST` are in `watch-session-setup`.

## Retry / Rollback Strategy

| Failure | Action |
|---------|--------|
| FB page fails to load | Retry once. If still failing, navigate to main group → back to buy/sell |
| Post content not loading (skeletons) | Wait 10s. If still loading, skip post |
| Image extraction fails (0 images) | Try alternate method (commerce vs group post). If both fail, skip watch |
| Duplicate check: already exists | Skip watch, update state |
| Harness injection fails | Retry once. If still failing, use manual field filling (see below) |
| importWatch timeout | Re-check page. Likely succeeded. Verify green banners |
| Import fails (no green banners) | Re-inject harness → re-inject images → retry. Max 2 retries |
| Admin DB down | Wait 30s, retry. If persistent, stop and report |
| WebSocket drops | Reconnect. Use short-lived connections per CDP call |
| `browser-use tab new` shows notifications | Don't use `tab new` for FB. Navigate existing tab with `window.location.href` |
| WS closes after navigation | Expected. Reconnect with a fresh `websockets.connect()` after page loads |

## UTF-8 Codec Crash on FB

Facebook CDN URLs with non-ASCII characters in signed params (e.g. `oh=00_Af...`) corrupt the CDP session. Symptoms:
- `browser_navigate` fails with `'utf-8' codec can't decode byte 0xcf in position 28`
- `browser_snapshot` fails with the same encoding error
- `browser_console` JS eval still works

**Workaround**: navigate via `window.location.replace()` through `browser_console` (e.g. `window.location.replace('https://www.facebook.com/groups/vanzareceasuri/')`). Or use the `browser-use` CLI — its `eval` works on FB pages even when `browser_console` fails with UTF-8 encoding errors. After navigating away from Facebook the encoding issue resolves and `browser_navigate`/`browser_snapshot` work again.

## FB Navigation Quirks

- `browser-use tab new` on FB shows notifications instead of content — navigate an EXISTING tab with `window.location.href` instead.
- Commerce listing pages often don't load even in navigated new tabs — use `browser-use eval` on an already-loaded tab, or extract from feed HTML instead.
- `mbasic.facebook.com` redirects to `www.facebook.com` (`?__mmr=1&_rdr`) — unusable for plain-HTML scraping.

## Bot-Friction Symptoms — what's really detected, and how to respond

Frozen/sparse feed, notification screens instead of content, or the same few posts on every
refresh are usually FB throttling agent-driven traffic — not a bug or an empty group. Two
facts shape the correct response.

**First, rule out your own tooling — "throttled" is over-diagnosed.** The 2026-07-17b session
declared the group exhausted when the real cause was browser-use's `scroll(x, y)` helper
paging the feed *upward*; the next session imported 5 watches from that same feed with
`js('window.scrollBy(0, 1400)')`. Before invoking the ladder, confirm all three:

1. `document.body.scrollHeight` is **not growing** across scrolls (if it grows, you are fine);
2. `window.scrollY` **is** increasing (if not, your scroll call is broken — fix that, not FB);
3. the page finished hydrating (height ~2300 + `innerText` ~1KB right after `goto_url` means
   still loading — wait 12–20s and re-read; scrolling an un-hydrated document does nothing).

Only when height is static, scrollY climbs, and the page is hydrated is it genuine friction.

**What FB can actually observe about THIS automation.** We do not simulate a mouse or type
into FB: our synthetic `.click()` and `window.location`/`goto_url` navigations produce
`isTrusted:false` events with no pointer trail at all. So the "human scroll cadence /
off-center clicks / typing rhythm" behavioural checks mostly do not apply to us. Our real
detection surface is the **rate and shape of traffic**, not mouse realism:
- navigations / page loads fired per minute,
- repeated identical navigation loops (main↔buy/sell hammering),
- little or no dwell time between actions,
- request volume against the feed/GraphQL endpoints.
Lever accordingly: **fewer page loads, more extracted per load, real dwell between them.**
(`fb-find-posts` harvests a whole feed read as one batch for exactly this reason.)

**Session trust is what carries us — protect it.** Attaching to the user's own logged-in
Chrome supplies the signals that actually matter: aged cookies, a residential IP, a real
User-Agent, real account history. That is why we reuse existing tabs and never spawn a
throwaway automation profile — a fresh profile discards every trust signal and looks exactly
like the datacenter bot the detection is built to catch.

**Graduated backoff on friction (do not escalate):**
1. First friction signal → PAUSE 30–60s, then gently retry ONCE by re-reading the DOM of an
   already-loaded page (no re-navigation).
2. Still stuck → one paced main↔buy/sell round-trip with a human dwell, then re-read.
3. Nothing new after two paced attempts → stop and report "group exhausted / throttled for
   now." More retries deepen the throttle.

**Before you stop, spend your cached post IDs.** A throttled *feed* does not block individual
post pages: on 2026-07-17c the feed went sparse at 4/5 watches, and the 5th came from an ID
cached earlier in the session, opened directly via `posts/<ID>/`. Exhaust cached IDs
(dedup-check → `fb-extract-post` Method C) before reporting exhaustion — and say which one
you hit, "feed throttled" and "no qualifying posts left" are different outcomes for the user.

**Do NOT forge detection signals.** FB's server-side checks include User-Agent validation,
TLS/JA3 fingerprinting, and IP reputation. The correct — and more robust — answer is to be a
genuine low-rate authenticated user, NOT to spoof a User-Agent, forge TLS fingerprints,
rotate proxies, or auto-solve challenges. Those are brittle, escalate the arms race, and are
out of scope for this runbook.

## Harness Injection Failure → Manual Field Filling

`browser_console` has an expression size limit. The full harness is too large for a single call and fails with "Invalid or unexpected token". When the harness can't be injected, fall back to manual field filling via smaller JS eval calls:
```javascript
// Step 1: set brand via direct <option> injection — see admin-import-watch
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

Keep each `browser_console` expression under ~3KB to avoid the size limit. Split into multiple calls if needed. For reliable submission you can also dispatch `mousedown`+`mouseup`+`click` MouseEvents on `input[name="_addanother"]`:
```javascript
var btn = document.querySelector('input[name="_addanother"]');
btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
btn.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
```

## Image Injection — One at a Time

Some FB CDN URLs cause `'utf-8' codec can't decode` errors when passed inside `browser_console` expressions — inject images ONE at a time in separate calls. For the first image, set `#images_payload.value` to a one-element array the same way. For each subsequent image, read the existing payload and push:

```javascript
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
```

**CRITICAL**: each payload entry MUST be `{"data_url": "..."}` — NOT a plain string. Plain strings cause `AttributeError: 'str' object has no attribute 'get'`.

## Raw CDP Python WebSocket Fallback (LAST RESORT)

```python
import json, asyncio, websockets, urllib.request

# Get tab WS URLs
tabs = json.loads(urllib.request.urlopen('http://$CDP_HOST/json').read())
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

- Use the tab's `webSocketDebuggerUrl` (not the HTTP endpoint).
- Always `await asyncio.wait_for(ws.recv(), timeout=...)` after each send.
- WebSocket connections drop after heavy page operations — use short-lived connections per CDP call, reconnect each time.
- Keep JS expressions short.
- Navigate via `Runtime.evaluate` + `window.location.replace()`.

## Admin DB Outages

Admin may return `OperationalError: failed to resolve host 'anunturi1-anunturi.h.aivencloud.com'` when PostgreSQL is unreachable — a server-side issue. A Django error page with traceback on the admin = DB down. Wait 30s and retry; if persistent, stop and report.
