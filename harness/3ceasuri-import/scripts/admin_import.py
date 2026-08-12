#!/usr/bin/env python3
"""The 3ceasuri admin half of an import — everything that does not care where the
listing came from.

Facebook and OLX differ entirely in how a listing is found and read, and not at
all in what happens afterwards: look the id up in the admin, make sure the brand
exists, inject the harness, submit, check the banners, read the record back. That
second half lived inside `import-post.py` until OLX arrived and would have been
copied into four more scripts.

This module is imported by browser-use *payloads*, which run with the CDP helpers
(`js`, `new_tab`, `close_tab`, `switch_tab`, `goto_url`) as globals rather than
importable names. So every function here takes a `bu` object carrying them —
build it with `bind(globals())` at the top of a payload:

    import admin_import
    A = admin_import.bind(globals())
    A.admin_rows("307673714", return_to=PHOTO_TAB)

Nothing in here emits marker lines; the calling script owns its own output.
"""

import json
import re
import time
import unicodedata
import urllib.parse


class Bound:
    """The CDP helpers of a browser-use payload, passed around as one object."""

    def __init__(self, g):
        self.js = g["js"]
        self.new_tab = g["new_tab"]
        self.close_tab = g["close_tab"]
        self.switch_tab = g["switch_tab"]
        self.goto_url = g["goto_url"]
        self.list_tabs = g["list_tabs"]


def bind(g):
    return Bound(g)


ADMIN = "https://3ceasuri.ro/admin"


def norm(s):
    """Diacritic-insensitive lowercase — 'Helfer Genève' and 'Helfer Geneve' match."""
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c)).lower().strip()


def _target(t):
    return t["targetId"] if isinstance(t, dict) else t


# --- județ / localitate ------------------------------------------------------
# OLX answers these as structured fields (see olx_api._split_location); Facebook
# has no geo at all, so the only source there is the free-text `location` the
# contract filled. Same spelling table both sides, so the two importers cannot
# drift into writing "Iasi" and "Iași" as different counties.
COUNTY_SPELLING = {
    "Arges": "Argeș", "Bacau": "Bacău", "Bistrita-Nasaud": "Bistrița-Năsăud",
    "Botosani": "Botoșani", "Braila": "Brăila", "Brasov": "Brașov",
    "Bucuresti": "București", "Buzau": "Buzău", "Caras-Severin": "Caraș-Severin",
    "Calarasi": "Călărași", "Constanta": "Constanța", "Dambovita": "Dâmbovița",
    "Galati": "Galați", "Ialomita": "Ialomița", "Iasi": "Iași",
    "Maramures": "Maramureș", "Mehedinti": "Mehedinți", "Mures": "Mureș",
    "Neamt": "Neamț", "Salaj": "Sălaj", "Timis": "Timiș", "Valcea": "Vâlcea",
}

# A bare city name only yields a județ when the city IS one — a county seat or the
# capital. Anything else stays countyless rather than guessed: a wrong județ on a
# public listing is worse than an empty one.
COUNTY_SEATS = {
    "bucuresti": ("București", "București"),
    "constanta": ("Constanța", "Constanța"),
    "bacau": ("Bacău", "Bacău"),
    "suceava": ("Suceava", "Suceava"),
    "iasi": ("Iași", "Iași"),
    "brasov": ("Brașov", "Brașov"),
    "galati": ("Galați", "Galați"),
    "braila": ("Brăila", "Brăila"),
    "sibiu": ("Sibiu", "Sibiu"),
    "arad": ("Arad", "Arad"),
    "botosani": ("Botoșani", "Botoșani"),
    "buzau": ("Buzău", "Buzău"),
    "vaslui": ("Vaslui", "Vaslui"),
    "tulcea": ("Tulcea", "Tulcea"),
    "covasna": ("Covasna", "Covasna"),
    "cluj-napoca": ("Cluj", "Cluj-Napoca"),
    "timisoara": ("Timiș", "Timișoara"),
    "ploiesti": ("Prahova", "Ploiești"),
    "craiova": ("Dolj", "Craiova"),
    "oradea": ("Bihor", "Oradea"),
}

# Free text after "Locație:" often ends in a country, which is not a județ.
_NOT_A_COUNTY = {"romania"}


def split_location(text):
    """(county, city) from a free-text location. Either half may be ''.

    "Florești, Cluj" -> ("Cluj", "Florești"); "București, România" -> the country is
    dropped and the capital recognised; "Comuna Necunoscuta" -> ("", "Comuna
    Necunoscuta"), because inventing a județ for an unknown commune is worse than
    leaving the column empty.
    """
    parts = [p.strip() for p in (text or "").split(",") if p.strip()]
    parts = [p for p in parts if norm(p) not in _NOT_A_COUNTY]
    if not parts:
        return "", ""
    if len(parts) == 1:
        seat = COUNTY_SEATS.get(norm(parts[0]))
        return seat if seat else ("", parts[0])
    city, county = parts[0], parts[-1]
    return COUNTY_SPELLING.get(county, county), city


# --- changelist reads --------------------------------------------------------
# The provenance columns were renamed on 2026-08-09 (facebook_listing_id ->
# external_listing_id). Read whichever cell the deployed admin renders, so a
# readback is not blank while the deploy is in flight.
_ROWS_JS = ("(() => {const g=(tr,c)=>{const e=tr.querySelector('td.field-'+c);return e?(e.innerText||'').trim():'';};"
            "const any=(tr,cs)=>{for(const c of cs){const v=g(tr,c); if(v) return v;} return '';};"
            "return JSON.stringify([...document.querySelectorAll('#result_list tbody tr')].map(tr=>"
            "({brand:g(tr,'brand'),model:g(tr,'model_name'),"
            "extid:any(tr,['external_listing_id','facebook_listing_id']),"
            "seller:any(tr,['seller_name','facebook_author_name'])})));})()")

_PAGINATOR_JS = '(() => {const p=document.querySelector(".paginator");return p?(p.innerText||"").trim():"";})()'


def admin_rows(bu, query, return_to=None):
    """Query the watch changelist by ?q=, return [{brand,model,extid,seller}].

    Runs in a scratch tab and restores `return_to` — the caller's tab keeps its
    page. Our own site, so there is no rate-limit concern about querying often.
    """
    t = _target(bu.new_tab("%s/watches/watch/?q=%s" % (ADMIN, urllib.parse.quote(str(query)))))
    time.sleep(3)
    try:
        rows = json.loads(bu.js(_ROWS_JS))
    except Exception:
        rows = []
    bu.close_tab(t)
    if return_to:
        bu.switch_tab(return_to)
    return rows


def admin_count(bu, query=None):
    """Row count for a ?q= (or the whole changelist when query is None).

    Over 100 rows the paginator also renders page LINKS ("1 2\\n107 watchs"), so
    the first number is a page number, not a count — read the one that sits right
    before "watch".
    """
    url = "%s/watches/watch/" % ADMIN
    if query is not None:
        url += "?q=" + urllib.parse.quote(str(query))
    bu.goto_url(url)
    time.sleep(2.5)
    try:
        txt = bu.js(_PAGINATOR_JS) or ""
        m = re.search(r"(\d[\d,.]*)\s*watch", txt, re.I) or re.search(r"(\d[\d,.]*)(?!.*\d)", txt, re.S)
        return int(re.sub(r"[,.]", "", m.group(1))) if m else None
    except Exception:
        return None


def already_imported(bu, listing_id, return_to=None):
    """Stage-1 dedup: has this exact listing id been imported already?"""
    return bool(admin_rows(bu, listing_id, return_to=return_to))


def distinctive(model):
    """Distinctive enough that an exact match means 'same watch', not 'same word'."""
    m = norm(model)
    return len(m) >= 8 and (any(c.isdigit() for c in m) or len(m.split()) >= 2)


def find_repost(bu, data, listing_id, return_to=None):
    """Stage-2 dedup: the same watch relisted under a NEW listing id.

    Two independent lookups — by seller and by model — matching on MODEL, with
    brand used only to VETO (the changelist renders the brand cell empty often
    enough that requiring it match would make this dead code, which is exactly
    what happened to the original author+brand+model rule).

    Returns None, or {"strong": bool, ...detail}: a strong hit is a skip, a weak
    one is a REVIEW so a generic model name can neither silently skip a new watch
    nor silently import a duplicate.
    """
    my_model, my_brand = norm(data.get("model")), norm(data.get("brand"))
    if not my_model:
        return None
    seller_id = data.get("sellerId")

    hits = []
    if seller_id:
        hits += [(r, "seller") for r in admin_rows(bu, seller_id, return_to=return_to)]
    hits += [(r, "model") for r in admin_rows(bu, data["model"], return_to=return_to)]

    for row, via in hits:
        if norm(row.get("model")) != my_model:
            continue
        row_brand = norm(row.get("brand"))
        if row_brand and row_brand != my_brand:
            continue                        # genuinely a different brand — not a repost
        if str(row.get("extid") or "") == str(listing_id):
            continue                        # that's this very listing
        return {"strong": (via == "seller") or distinctive(my_model),
                "matched_via": via, "brand_confirmed": bool(row_brand),
                "match": {"brand": data.get("brand"), "model": data.get("model"),
                          "existing_listing_id": row.get("extid")}}
    return None


# --- brands ------------------------------------------------------------------
def load_brand_ids(harness_path):
    """The BRAND_IDS map the harness ships with — the local cache of brand->id."""
    return json.loads(re.search(r"window\.BRAND_IDS\s*=\s*(\{.*?\});",
                                open(harness_path).read()).group(1))


def match_brand(text, brand_ids):
    """Longest known brand name occurring in `text`, diacritic-insensitive."""
    low = norm(text)
    for name in sorted(brand_ids, key=len, reverse=True):
        if re.search(r"\b" + re.escape(norm(name)) + r"\b", low):
            return name
    return None


def _lookup_brand(bu, name):
    """Find a brand by NAME on the changelist.

    The admin's search box covers the name, NOT the slug — looking a freshly
    created brand up by its slug is what made 'Buchner & Bovalier' and
    'Fără marcă' die with 'failed to create/find brand' after the row had
    already been written.
    """
    bu.goto_url("%s/watches/brand/?q=%s" % (ADMIN, urllib.parse.quote(name)))
    time.sleep(3)
    rows = json.loads(bu.js('(() => JSON.stringify([...document.querySelectorAll('
                            '\'#result_list tbody tr a[href*="/change/"]\')].map(a=>('
                            '{name:(a.innerText||"").trim(),'
                            'id:(a.href.match(/brand\\/(\\d+)\\/change/)||[])[1]}))))()'))
    for r in rows:
        if r.get("id") and norm(r["name"]) == norm(name):
            return int(r["id"])
    return None


def ensure_brand(bu, name, brand_ids):
    """Return (brand_id_or_None, info). None means it was already in BRAND_IDS.

    `info` is the NEW_BRAND payload for the caller to emit: a brand missing from
    BRAND_IDS is not necessarily missing from the DB — the map is a local cache
    and drifts. Look before creating, or you get a second row with a mangled slug
    ('f-r-marc' next to 'fara-marca').
    """
    if name in brand_ids:
        return None, None

    bt = _target(bu.new_tab("%s/watches/brand/" % ADMIN))
    time.sleep(3)
    try:
        existing = _lookup_brand(bu, name)
        if existing:
            return existing, {"name": name, "id": existing, "created": False,
                              "action": "already on the site but MISSING from BRAND_IDS — add it to "
                                        "import-watch.js AND references/brand-ids.md, then commit"}

        bu.goto_url("%s/watches/brand/add/" % ADMIN)
        time.sleep(4)
        slug = re.sub(r"[^a-z0-9]+", "-", norm(name)).strip("-")
        bu.js('(() => {const n=document.getElementById("id_name"),s=document.getElementById("id_slug");'
              'n.value=%s;n.dispatchEvent(new Event("input",{bubbles:true}));'
              'if(s){s.value=%s;s.dispatchEvent(new Event("input",{bubbles:true}));}'
              'const b=document.querySelector("input[name=_save]");b?b.click():document.querySelector("form").submit();'
              'return "ok";})()' % (json.dumps(name), json.dumps(slug)))
        time.sleep(4)
        created = _lookup_brand(bu, name)
        if not created:
            raise RuntimeError("failed to create/find brand %s" % name)
        return created, {"name": name, "id": created, "created": True,
                         "action": "ADD to BRAND_IDS in import-watch.js AND references/brand-ids.md, then commit"}
    finally:
        bu.close_tab(bt)


# --- the add form ------------------------------------------------------------
def find_admin_tab(bu, tabs=None):
    """Locate the add-watch tab, steering a stale admin tab back to it.

    The previous run's readback leaves the tab on the saved record's change page,
    so after every import there is an admin tab but no *add* tab.
    """
    tabs = tabs if tabs is not None else bu.list_tabs()

    def find(pred):
        for t in tabs:
            if pred((t.get("url") or "").lower()):
                return t["targetId"]
        return None

    tab = find(lambda u: "/watches/watch/add" in u)
    if tab:
        return tab
    tab = find(lambda u: "3ceasuri.ro/admin" in u)
    if tab:
        bu.switch_tab(tab)
        bu.goto_url("%s/watches/watch/add/" % ADMIN)
        time.sleep(4)
    return tab


def inject_harness(bu, harness_path, brand_name=None, brand_id=None):
    """Inject import-watch.js into the current tab. Lost on every navigation."""
    src = open(harness_path).read()
    ok = bu.js("(() => { const s=document.createElement('script'); s.textContent="
               + json.dumps(src) + "; document.head.appendChild(s); "
               "return window.importWatch ? 'OK':'NO_FUNC'; })()")
    if ok != "OK":
        raise RuntimeError("harness injection failed")
    if brand_id is not None and brand_name:
        bu.js('(() => { window.BRAND_IDS[%s]=%d; return "ok"; })()'
              % (json.dumps(brand_name), brand_id))


def submit(bu, data, image_count):
    """Call importWatch() and wait it out.

    The call reliably raises 'Inspected target navigated/closed' or times out —
    that is the *normal* path, because a successful submit navigates the page out
    from under CDP. Verify by page content afterwards, never by return value.
    """
    call = ("(async () => { try { await importWatch("
            + json.dumps(data, ensure_ascii=False)
            + "); return 'OK'; } catch(e){ return 'ERR:'+e.message; } })()")
    try:
        bu.js(call)
    except Exception:
        pass
    time.sleep(20 + max(0, image_count - 5) * 2)


_BANNERS_JS = ('(() => {const t=document.body.innerText;return JSON.stringify({'
               'images_ok:t.includes("imagini salvate"),'
               'added_ok:t.includes("added successfully")||t.includes("adăugat cu succes")});})()')

_CHANGE_LINK_JS = ('(() => {const a=document.querySelector(\'#result_list tbody tr a[href*="/change/"]\');'
                   'return JSON.stringify({url:a?a.href:null});})()')

_READBACK_JS = ('(() => {const g=id=>{const e=document.getElementById(id);'
                'return e?(e.tagName==="SELECT"?(e.options[e.selectedIndex]||{}).value:e.value):null;};'
                'const any=ids=>{for(const i of ids){const v=g(i); if(v!==null) return v;} return null;};'
                'const imgs=document.querySelectorAll(\'.field-image img,[id*="images-group"] img,img[src*="/media/"]\').length;'
                'return JSON.stringify({brandId:g("id_brand"),price:g("id_price"),currency:g("id_currency"),'
                'ref:g("id_reference_number"),diameter:g("id_case_diameter_mm"),'
                'source:g("id_source"),'
                'extId:any(["id_external_listing_id","id_facebook_listing_id"]),'
                'sellerId:any(["id_seller_id","id_facebook_author_id"]),'
                'sellerName:any(["id_seller_name","id_facebook_author_name"]),'
                'videoUrl:g("id_video_url"),imgs});})()')


def verify(bu, listing_id):
    """Check both banners, then read the saved record back (saved != correct).

    Returns (ok, banners, readback). The "added successfully" banner is flaky on
    multi-image saves, so a readback that found the record by its own listing id
    is accepted as equivalent proof the add committed.
    """
    banners = json.loads(bu.js(_BANNERS_JS))
    chg = json.loads(bu.js(_CHANGE_LINK_JS))
    if not chg.get("url"):
        bu.goto_url("%s/watches/watch/?q=%s" % (ADMIN, urllib.parse.quote(str(listing_id))))
        time.sleep(3)
        chg = json.loads(bu.js(_CHANGE_LINK_JS))

    readback = None
    if chg.get("url"):
        bu.goto_url(chg["url"])
        time.sleep(4)
        readback = json.loads(bu.js(_READBACK_JS))

    readback_ok = bool(readback and str(readback.get("extId")) == str(listing_id))
    ok = bool(banners.get("images_ok") and (banners.get("added_ok") or readback_ok))
    return ok, banners, readback, readback_ok
