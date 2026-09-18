# 3ceasuri Import Workflow (2026-06-18 session)

## Proven Flow (1 watch imported successfully)

### One-pass approach — NO navigation between fill and submit

```
1. Navigate to admin: /admin/watches/watch/add/
2. Fill brand via direct injection (Brand=ID)
3. Fill model, condition, movement, price, currency, type, description, source_url, fb_listing_id, diameter
4. Inject images one at a time (fetch FB CDN URL → blob → base64 → images_payload)
5. Submit (Save and add another) — do NOT navigate away between steps
```

### Brand ID Mapping (29 brands)
Certina:28, Spinnaker:27, Atlantic:26, Orient:25, Cauny:24, Doxa:23, Seconda:22, Fossil:21, Maurice Lacroix:20, Bischoff:19, Longines:18, Hamilton:17, Zenith:16, Seiko:15, Tudor:14, Citizen:13, Tissot:12, Poljot:11, Cartier:10, Le Duc:9, Racheta:8, Omega:7, TITUS Geneve:6, Glashutte:5, Rotary:4, Rolex:3, Casio:2, Aerowatch:1

### Image injection pattern (works via CDP websocket Python)
```python
for i, url in enumerate(images):
    js = '(async () => { const url = ' + json.dumps(url) + '; const resp = await fetch(url); const blob = await resp.blob(); const dataUrl = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob); }); const existing = JSON.parse(document.getElementById("images_payload").value || "[]"); existing.push({data_url: dataUrl}); document.getElementById("images_payload").value = JSON.stringify(existing); return "ok"; })()'
    await ws.send(json.dumps({'id': 100+i, 'method': 'Runtime.evaluate', 'params': {'expression': js, 'awaitPromise': True}}))
    r = await asyncio.wait_for(ws.recv(), timeout=30)
```

### Submit button click pattern
```javascript
var btn = document.querySelector('input[name="_addanother"]');
btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
btn.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
```

### Verification
```javascript
var text = document.body.innerText;
var hasImages = text.indexOf('imagini salvate') > -1;
var hasAdded = text.indexOf('added successfully') > -1;
```

## Facebook Posts Found (June 18, 2026)
- Longines Spirit Pilot Chronometer 40mm — 800 RON — 12 images — POSTED ✅
- Rolex Oyster Perpetual Datejust 1601 — RON 21,000 — photo links: set=g.978581759677150 (4 images)
- Orient Multicalendar Automatic Japan Made — Costi Schiverniuc
- Doxa original — 500 lei — Sile Variante
- Poljot USSR — 80 EUR — Timofeevich Vasilovich
- Citizen Red Arrows Royal Air Force — $3,000 — post ID 2060433074825341

## Pitfalls from this session
1. Navigating to Facebook clears ALL form state — must refill + re-inject after any nav
2. Select2 brand search CLEARS the value — use direct injection instead
3. `set=gm.` photo carousel stuck on 1 image — use `set=pcb.` links
4. browser_navigate fails with 'utf-8' codec error after FB CDN content — workaround: navigate to 3ceasuri.ro first
5. Expression size limit ~3KB — inject images one at a time, not in batch
