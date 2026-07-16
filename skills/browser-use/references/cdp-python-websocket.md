# CDP Python WebSocket Fallback

When `browser_navigate`/`browser_snapshot` fail due to Facebook CDN encoding corruption, use direct CDP WebSocket calls from Python.

## Connection Setup

```python
import json, asyncio, websockets, urllib.request

async def main():
    # Get tab list
    resp = urllib.request.urlopen('http://192.168.65.254:9222/json/list')
    tabs = json.loads(resp.read())
    
    # Find the Facebook tab (filter out worker/static URLs)
    fb_tabs = [t for t in tabs if 'facebook.com' in t.get('url','') 
                and not t.get('url','').startswith('https://www.facebook.com/static')
                and not t.get('url','').startswith('https://www.fbsbx.com')]
    fb_tab = fb_tabs[0]
    
    ws_url = fb_tab['webSocketDebuggerUrl']
    async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
        # All CDP commands go through here
        ...
```

## Navigation (avoid encoding bug)

```python
# Navigate via Runtime.evaluate — avoids the UTF-8 encoding corruption
await ws.send(json.dumps({
    'id': 1,
    'method': 'Runtime.evaluate',
    'params': {'expression': "window.location.replace('https://www.facebook.com/...'); 'ok'"}
}))
r = await asyncio.wait_for(ws.recv(), timeout=10)
await asyncio.sleep(10)  # Wait for page load
```

## Page Navigation (Page.navigate method)

```python
# This also works but may trigger encoding issues if FB CDN content is already loaded
await ws.send(json.dumps({
    'id': 1,
    'method': 'Page.navigate',
    'params': {'url': 'https://www.facebook.com/groups/vanzareceasuri/'}
}))
r = await asyncio.wait_for(ws.recv(), timeout=10)
```

## JS Evaluation

```python
await ws.send(json.dumps({
    'id': 2,
    'method': 'Runtime.evaluate',
    'params': {'expression': 'document.title'}
}))
r = await asyncio.wait_for(ws.recv(), timeout=10)
data = json.loads(r)
value = data['result']['result']['value']
```

## Image Collection Loop (Photo Viewer)

```python
all_images = []
seen = set()

for step in range(15):
    # Collect current image
    await ws.send(json.dumps({
        'id': 100+step,
        'method': 'Runtime.evaluate',
        'params': {'expression': '''
            (() => {
                var imgs = Array.from(document.querySelectorAll('img')).filter(i => 
                    i.naturalWidth > 400 && 
                    i.getBoundingClientRect().width > 50 &&
                    !i.src.includes('static.xx.fbcdn') &&
                    !i.src.startsWith('data:')
                );
                if (imgs.length > 0) return imgs[0].src;
                return '';
            })()
        '''}
    }))
    r = await asyncio.wait_for(ws.recv(), timeout=10)
    data = json.loads(r)
    src = data.get('result',{}).get('result',{}).get('value','')
    if src:
        base = src.split('?')[0].split('/').pop()
        if base not in seen:
            seen.add(base)
            all_images.append(src)
    
    # Click Next
    await ws.send(json.dumps({
        'id': 200+step,
        'method': 'Runtime.evaluate',
        'params': {'expression': '''
            (() => {
                var next = document.querySelector('div[aria-label="Next photo"]') ||
                    Array.from(document.querySelectorAll('button')).find(b => 
                        (b.getAttribute('aria-label')||'').includes('Next'));
                if (next && !next.disabled) { next.click(); return 'clicked'; }
                return 'done';
            })()
        '''}
    }))
    r = await asyncio.wait_for(ws.recv(), timeout=10)
    data = json.loads(r)
    status = data.get('result',{}).get('result',{}).get('value','')
    if status == 'done':
        break
    await asyncio.sleep(3)
```

## Key Rules

1. Always use `asyncio.wait_for(ws.recv(), timeout=10)` — the CDP response is a JSON object
2. `window.location.replace()` via Runtime.evaluate is MORE reliable than `Page.navigate` for avoiding encoding issues
3. After navigating away from Facebook (to any non-FB URL like 3ceasuri.ro), `browser_navigate`/`browser_snapshot` work again
4. `browser_console` tool works even when `browser_navigate`/`browser_snapshot` fail — use it as first fallback
5. Filter out worker/static tabs: URLs starting with `https://www.facebook.com/static` or `https://www.fbsbx.com`
