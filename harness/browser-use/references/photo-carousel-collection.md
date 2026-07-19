# Facebook Photo Carousel Collection (2026-06-18)

## Two types of photo links in buy/sell feed

### `set=pcb.<ID>` — Multi-image carousel (WORKS)
- URL format: `facebook.com/photo/?fbid=<FBID>&set=pcb.<PHOTO_SET_ID>`
- Opens photo viewer with working "Next photo" carousel
- Can collect 4-12 images per post
- **Use this type for image collection**

### `set=gm.<POST_ID>` — Single photo (BROKEN carousel)
- URL format: `facebook.com/photo/?fbid=<FBID>&set=gm.<POST_ID>`
- Opens photo viewer with "Next photo" button visible but stuck
- Only 1 image collectible
- **Do NOT use for multi-image collection**

## Carousel collection pattern

```python
# Via CDP Python websocket (when browser_console has encoding issues)
for step in range(15):
    # Collect current largest image
    js = """(() => {
        var imgs = Array.from(document.querySelectorAll('img')).filter(function(i) {
            return i.naturalWidth > 400 && i.getBoundingClientRect().width > 50 &&
                   i.src.indexOf('static.xx.fbcdn') === -1 && i.src.indexOf('data:') !== 0;
        });
        if (imgs.length === 0) return '';
        imgs.sort(function(a,b) { return b.naturalWidth - a.naturalWidth; });
        return imgs[0].src;
    })()"""
    # ... execute, add to list if new ...
    
    # Click Next — MUST use visible button with class x1qjc9v5
    js_next = """(() => {
        var btns = document.querySelectorAll('div[aria-label="Next photo"]');
        for (var i = 0; i < btns.length; i++) {
            if (btns[i].getBoundingClientRect().width > 0 && btns[i].className.indexOf('x1qjc9v5') > -1) {
                btns[i].click(); return 'clicked';
            }
        }
        return 'done';
    })()"""
    # ... if 'done', break ...
    time.sleep(3)
```

## Key details
- Facebook's virtualized list removes off-screen posts — collect pcb IDs before scrolling past
- Wait 3s between carousel advances (images load asynchronously)
- Deduplicate by filename (part before `?`)
- Typical post has 4-12 images
