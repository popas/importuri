#!/usr/bin/env python3
"""Reading olx.ro — the API, the param map, and the photo URLs.

OLX rejects a plain HTTP GET with 403 (bot protection), but its own JSON API
answers normally from a page already on olx.ro. So every call here is a `fetch()`
executed in the page context, which carries the cookies and headers the site
expects. That is the whole reason the OLX scripts need a browser at all: there is
no DOM scraping, no scrolling and no carousel.

Two endpoints do everything:
    /api/v1/offers/?category_id=&offset=&limit=&sort_by=created_at:desc
    /api/v1/offers/<id>/

An ad carries seller-declared structured `params` (state, brand, material,
display, water resistance, gender, style, price) which map onto the DB enums
directly — the guessing the Facebook importer has to do from free text is
unnecessary here, and PARAM_MAP below is deliberately conservative about the
cases where OLX's vocabulary does not line up with ours.

Like admin_import, this is imported by browser-use payloads and takes the CDP
helpers through `bind(globals())`.
"""

import json
import re
import time

# The two categories we import from.
CATEGORY_SMARTWATCH = 1943   # /electronice-si-electrocasnice/.../smartwatch-uri/
CATEGORY_WATCHES = 1677      # /moda-frumusete/ceasuri/

CATEGORY_URL = {
    CATEGORY_SMARTWATCH: ("https://www.olx.ro/electronice-si-electrocasnice/"
                          "gadgets-wearables-si-camere-foto-video/smartwatch-uri/"),
    CATEGORY_WATCHES: "https://www.olx.ro/moda-frumusete/ceasuri/",
}


class Bound:
    def __init__(self, g):
        self.js = g["js"]
        self.new_tab = g["new_tab"]
        self.close_tab = g["close_tab"]
        self.switch_tab = g["switch_tab"]
        self.goto_url = g["goto_url"]
        self.list_tabs = g["list_tabs"]


def bind(g):
    return Bound(g)


# --- the tab ----------------------------------------------------------------
def ensure_tab(bu, url=None, tabs=None):
    """Return a tab sitting on olx.ro, creating or steering one if needed.

    Same-origin is not cosmetic here: a fetch issued from any other origin gets
    the 403 that plain curl gets.
    """
    url = url or "https://www.olx.ro/"
    tabs = tabs if tabs is not None else bu.list_tabs()
    for t in tabs:
        if "olx.ro" in (t.get("url") or "").lower():
            bu.switch_tab(t["targetId"])
            return t["targetId"]
    r = bu.new_tab(url)
    tab = r["targetId"] if isinstance(r, dict) else r
    time.sleep(8)
    bu.switch_tab(tab)
    return tab


# --- the API ----------------------------------------------------------------
def _fetch_json(bu, path):
    """GET `path` from the page context and parse it. Returns None on failure."""
    expr = ('(async () => { try { const r = await fetch(%s, {headers:{Accept:"application/json"}});'
            ' const t = await r.text();'
            ' return JSON.stringify({status:r.status, body:t}); }'
            ' catch(e) { return JSON.stringify({status:0, body:"", err:String(e)}); } })()'
            % json.dumps(path))
    try:
        env = json.loads(bu.js(expr))
    except Exception:
        return None
    if env.get("status") != 200:
        return None
    try:
        return json.loads(env.get("body") or "")
    except Exception:
        return None


def search(bu, category_id, offset=0, limit=40, price_from=None, sort="created_at:desc"):
    """One page of a category. Returns (offers, total) — ([], None) on failure.

    `price_from` is a server-side hint only; the caller re-applies the floor,
    because the API accepts the parameter without its effect being confirmed.
    """
    path = ("/api/v1/offers/?offset=%d&limit=%d&category_id=%d&sort_by=%s"
            % (offset, limit, category_id, sort.replace(":", "%3A")))
    if price_from:
        path += "&filter_float_price%%3Afrom=%d" % price_from
    d = _fetch_json(bu, path)
    if not d:
        return [], None
    meta = d.get("metadata") or {}
    return (d.get("data") or []), meta.get("total_elements")


def offer(bu, ad_id):
    """One ad in full, or None if it is gone."""
    d = _fetch_json(bu, "/api/v1/offers/%s/" % ad_id)
    return (d or {}).get("data")


# --- photos ------------------------------------------------------------------
def photo_urls(ad, width=1000, height=1000):
    """Full-size photo URLs for an ad.

    OLX hands back a templated link — `.../image;s={width}x{height}` — which is
    unsigned and durable, unlike Facebook's signed CDN urls. Rewriting the
    template is the intended use, not URL tampering.
    """
    out = []
    for p in (ad.get("photos") or []):
        link = p.get("link") or ""
        if not link:
            continue
        out.append(link.replace("{width}", str(width)).replace("{height}", str(height)))
    return out


def download_photos(bu, urls, dest_dir):
    """Save an ad's photos to disk. Returns (paths, failed_count).

    Fetched in the page context rather than with urllib: the CDN is a different
    host from olx.ro, but going through the page keeps one code path and one set
    of headers for everything this importer reads.

    They go to disk rather than being handed on as URLs because the extraction
    contract is answered minutes later in another process — a path still resolves,
    and reading photos is how the model name gets decided at all.
    """
    import base64
    import os

    os.makedirs(dest_dir, exist_ok=True)
    paths, failed = [], 0
    for i, url in enumerate(urls, 1):
        try:
            b64 = bu.js("(async () => { const r = await fetch(%s); const b = await r.blob();"
                        " return await new Promise(res => { const fr = new FileReader();"
                        " fr.onloadend = () => res(String(fr.result).split(',')[1]);"
                        " fr.readAsDataURL(b); }); })()" % json.dumps(url))
            if not b64 or len(b64) < 500:
                failed += 1
                continue
            path = os.path.join(dest_dir, "%02d.jpg" % i)
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
            paths.append(path)
        except Exception:
            failed += 1
    return paths, failed


# --- text --------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")


def clean_description(html):
    """OLX descriptions are HTML with <br /> line breaks. Keep the breaks."""
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = _TAG_RE.sub("", text)
    for ent, ch in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                    ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(ent, ch)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(ln.rstrip() for ln in text.splitlines()).strip()


# --- params -> DB enums ------------------------------------------------------
# Keyed on OLX's own param key, then on the value key (falling back to the
# label, normalized). Anything unrecognised stays null and the extraction
# contract answers it — a wrong enum is worse than an empty field.
PARAM_MAP = {
    "state": ("condition", {
        "new": "new",
        "nou": "new",
        "nou-cu-eticheta": "new",
        "nou-fara-eticheta": "new",
        "purtat-o-singura-data": "excellent",
        "in-conditii-bune": "good",
        "used": "good",
        "utilizat": "good",
        "defect": "broken",
    }),
    "material_carcasa": ("caseMat", {
        "otel_inoxidabil": "steel",
        "otel-inoxidabil": "steel",
        "otel": "steel",
        "aur": "gold",
        "argint": "silver",
        "titan": "titanium",
        "ceramica": "ceramic",
        "aluminiu": "aluminium",
        "plastic": "plastic",
        "cauciuc": "plastic",
        "lemn": "wood",
        "carbon": "carbon",
    }),
    "material_bratara": ("braceletMat", {
        "otel_inoxidabil": "steel",
        "otel-inoxidabil": "steel",
        "otel": "steel",
        "piele": "leather",
        "cauciuc": "rubber",
        "silicon": "rubber",
        "textil": "nylon",
        "nylon": "nylon",
        "aur": "gold",
        "argint": "silver",
        "titan": "titanium",
        "plastic": "plastic",
    }),
    "afisaj": ("displayType", {
        "analogic": "analog",
        "analog": "analog",
        "digital": "digital",
        "analogic_digital": "analog_digital",
        "analogic-digital": "analog_digital",
        "analogic-si-digital": "analog_digital",
        "smart": "smart",
    }),
    "pentru": ("gender", {
        "barbati": "men",
        "femei": "women",
        "unisex": "unisex",
        "copii": "kids",
        "baieti": "kids",
        "fete": "kids",
    }),
    "stil": ("style", {
        "sport": "sport",
        "elegant": "dress",
        "casual": None,          # no DB equivalent — the contract decides
        "clasic": "dress",
    }),
}

# Water resistance is a depth rating, not an enum we mirror: any ATM/metre figure
# means yes, and only an explicit "nu" means no.
_WR_NO = ("nu", "no", "fara", "nu-este-rezistent")


def _norm_key(v):
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", v or "") if not unicodedata.combining(c))
    return s.lower().strip().replace(" ", "-")


def param_values(ad):
    """{param key: {"key":…, "label":…, "raw": value}} for an ad."""
    out = {}
    for p in (ad.get("params") or []):
        v = p.get("value")
        if isinstance(v, dict):
            out[p.get("key")] = {"key": v.get("key"), "label": v.get("label"), "raw": v}
        else:
            out[p.get("key")] = {"key": None, "label": v, "raw": v}
    return out


def map_params(ad):
    """OLX structured params -> DB field values. Unknown values are omitted.

    Deliberately NOT mapped: `culoare_carcasa`. It is the colour of the CASE,
    while our `displayColor` means the dial — reading one as the other would put
    a confident wrong value on every ad that sets it.
    """
    vals = param_values(ad)
    data = {}

    for pkey, (field, table) in PARAM_MAP.items():
        if pkey not in vals:
            continue
        v = vals[pkey]
        hit = table.get(_norm_key(v.get("key"))) or table.get(_norm_key(v.get("label")))
        if hit:
            data[field] = hit

    if "rezistenta_la_apa" in vals:
        v = vals["rezistenta_la_apa"]
        token = _norm_key(v.get("key")) or _norm_key(v.get("label"))
        if token:
            data["waterRes"] = ("water_resistant_no" if token in _WR_NO
                                else "water_resistant_yes")

    price = (vals.get("price") or {}).get("raw") or {}
    if isinstance(price, dict) and price.get("value") is not None:
        data["price"] = price["value"]
        data["currency"] = price.get("currency") or "RON"
        if price.get("negotiable"):
            data["priceNote"] = "negociabil"

    return data


def brand_param(ad):
    """The seller-declared brand label, if the category has that param."""
    v = param_values(ad).get("brand") or {}
    return v.get("label") or None


def location_str(ad):
    loc = ad.get("location") or {}
    city = (loc.get("city") or {}).get("name")
    region = (loc.get("region") or {}).get("name")
    if city and region and region != city:
        return "%s, %s" % (city, region)
    return city or region or ""


def seller(ad):
    u = ad.get("user") or {}
    return {"id": str(u.get("id")) if u.get("id") else None,
            "name": u.get("name") or None,
            "business": bool(ad.get("business"))}
