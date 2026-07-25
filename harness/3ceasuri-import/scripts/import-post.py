#!/usr/bin/env python3
# =============================================================================
# import-post.py — consolidated ONE-SHOT importer for a single FB watch post.
#
# Runs the entire per-watch flow in a single browser-use process, replacing the
# ~8 hand-orchestrated calls of the find/extract/import/verify skills:
#   post page -> gate on pcb.<ID> -> SKIP if video-first (ad) -> carousel images
#   -> infer fields (RO->enum + defaults, plating rule) -> ensure brand
#   -> inject harness -> importWatch() -> verify banners -> read back the record.
#
# It is a browser-use *payload*: pipe it on stdin, NOT `python3 import-post.py`.
#   export BU_CDP_URL="http://127.0.0.1:9222"
#   POST_ID=2080773889457926 ADMIN_TAB=<id> PHOTO_TAB=<id> \
#     OVERRIDES='{"model":"Crystal Automatic","caseMat":"steel"}' \
#     browser-use < harness/3ceasuri-import/scripts/import-post.py
#
# Env:
#   POST_ID       (required) numeric FB post ID
#   PROJECT_ROOT  repo root (default: the Mac path below)
#   ADMIN_TAB     targetId of the admin add-watch tab (auto-found if omitted)
#   PHOTO_TAB     targetId of a scratch FB tab for the photo viewer (auto/created)
#   OVERRIDES     JSON object of field overrides merged over inference (authoritative)
#   DRY_RUN       "1" = extract + infer + print, do NOT import (review first)
#
# Emits marker lines the operator/parent can parse:
#   EXTRACT: {...}   SKIP: {...}   INFER: {...}   NEW_BRAND: {...}
#   RESULT: {...}    ERROR: {...}
#
# Field inference mirrors .claude/skills/fb-extract-post/SKILL.md — keep in sync.
# A NEW brand is created in the DB and injected at runtime, but the source files
# (BRAND_IDS in import-watch.js + references/brand-ids.md) must still be updated
# by hand afterwards — watch for the NEW_BRAND: line and sync + commit.
# =============================================================================
import os, re, json, time, random

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", "/Users/stelian/.hermes/proiecte/3ceasuri")
POST_ID   = os.environ.get("POST_ID", "").strip()
OVERRIDES = json.loads(os.environ.get("OVERRIDES", "{}"))
DRY_RUN   = os.environ.get("DRY_RUN", "") == "1"
HARNESS   = os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts/import-watch.js")

def emit(tag, obj): print(tag + ": " + json.dumps(obj, ensure_ascii=False))
def die(msg):       emit("ERROR", {"post_id": POST_ID, "msg": msg}); raise SystemExit(1)

if not POST_ID or not POST_ID.isdigit():
    die("POST_ID env var must be a numeric FB post ID")

# --- resolve tabs -----------------------------------------------------------
tabs = list_tabs()
def find_tab(pred):
    for t in tabs:
        if pred((t.get("url") or "").lower(), (t.get("title") or "").lower()):
            return t["targetId"]
    return None

ADMIN_TAB = os.environ.get("ADMIN_TAB") or find_tab(lambda u, t: "/watches/watch/add" in u)
if not ADMIN_TAB:
    die("no admin add-watch tab found; open https://3ceasuri.ro/admin/watches/watch/add/ or pass ADMIN_TAB")
PHOTO_TAB = os.environ.get("PHOTO_TAB") or find_tab(lambda u, t: "facebook.com" in u and "/groups/" not in u)
if not PHOTO_TAB:
    PHOTO_TAB = new_tab("https://www.facebook.com/")["targetId"] if isinstance(new_tab("https://www.facebook.com/"), dict) else None
    tabs = list_tabs()
    PHOTO_TAB = PHOTO_TAB or find_tab(lambda u, t: "facebook.com" in u)

# --- 1. open post page, gate on the post's own photo set --------------------
switch_tab(PHOTO_TAB)
goto_url("https://www.facebook.com/groups/vanzareceasuri/posts/%s/" % POST_ID)
hit = None
for _ in range(4):                       # ~15s+ ; renders home feed first, gate on pcb.<ID>
    time.sleep(5)
    r = js(('(() => { let h=null; document.querySelectorAll(\'a[href*="/photo/"]\').forEach(l=>{'
            'if((l.href||"").indexOf("pcb.%s")>-1) h=l.href.split("&__cft__")[0];}); '
            'return JSON.stringify({hit:h}); })()') % POST_ID)
    hit = json.loads(r).get("hit")
    if hit: break
if not hit:
    die("post %s never surfaced its pcb photo set (private/removed, or still hydrating)" % POST_ID)

# expand "See more" and read the post body text
js('(() => { const d=document.querySelector(\'div[role="dialog"]\')||document.body;'
   ' d.querySelectorAll(\'div[role="button"],span\').forEach(b=>{const t=(b.innerText||"").trim();'
   ' if(t==="See more"||t==="Vezi mai mult"){b.click();}}); return "ok"; })()')
time.sleep(1)
info = json.loads(js(
   '(() => { const link=[...document.querySelectorAll(\'a[href*="/photo/"]\')]'
   '.find(l=>(l.href||"").indexOf("pcb.%s")>-1);'
   ' const cont=(link&&(link.closest(\'[role="article"]\')||link.closest(\'div[role="dialog"]\')))||document.body;'
   # video-first: a <video>/scrubber that precedes the first photo in DOM order
   ' const nodes=[...cont.querySelectorAll(\'video,[aria-label*="Play"],a[href*="/photo/"]\')];'
   ' let firstIsVideo=false; for(const n of nodes){ const isVid=(n.tagName==="VIDEO")||'
   '((n.getAttribute&&(n.getAttribute("aria-label")||"").indexOf("Play")>-1)); '
   ' const isPhoto=n.tagName==="A"; if(isVid){firstIsVideo=true;break;} if(isPhoto){break;} }'
   ' const d=document.querySelector(\'div[role="dialog"]\')||cont;'
   ' let txt=(d.innerText||"").replace(/(Facebook\\n?)+/g,"");'
   ' return JSON.stringify({firstIsVideo, txt:txt.substring(0,1200)}); })()' % POST_ID))
text = info["txt"]
emit("EXTRACT", {"post_id": POST_ID, "hit": hit, "video_first": info["firstIsVideo"], "chars": len(text)})

# --- 2. skip video-first posts (ad heuristic) -------------------------------
if info["firstIsVideo"] and OVERRIDES.get("force") is not True:
    emit("SKIP", {"post_id": POST_ID, "reason": "video-first post (ad); pass OVERRIDES {\"force\":true} to import anyway"})
    raise SystemExit(0)

# --- 3. collect images via the pcb carousel ---------------------------------
switch_tab(PHOTO_TAB)
goto_url(hit)
time.sleep(8)
COLLECT = ('(() => {var imgs=Array.from(document.querySelectorAll("img")).filter(i=>i.naturalWidth>400'
           '&&i.getBoundingClientRect().width>50&&!i.src.includes("static.xx.fbcdn")&&!i.src.startsWith("data:"));'
           'imgs.sort((a,b)=>b.naturalWidth-a.naturalWidth);return imgs.length?imgs[0].src:"";})()')
NEXT = ('(() => {var b=document.querySelectorAll(\'div[aria-label="Next photo"]\');'
        'for(var i=0;i<b.length;i++){if(b[i].getBoundingClientRect().width>0&&b[i].className.indexOf("x1qjc9v5")>-1)'
        '{b[i].click();return "c";}}return "x";})()')
images, seen = [], set()
for _ in range(15):
    s = js(COLLECT)
    if s:
        base = s.split("?")[0].split("/")[-1]
        if base not in seen:
            seen.add(base); images.append(s)
    if js(NEXT) == "x": break
    time.sleep(2.5 + random.random() * 2.5)
same = js('(() => location.href.indexOf("pcb.%s")>-1?"same-set":location.href)()' % POST_ID)
if same != "same-set":
    die("carousel drifted off the post's photo set (%s) — images may be contaminated" % same)
if not images:
    die("collected 0 images for post %s" % POST_ID)

# --- 4. infer fields (RO->enum + defaults; see fb-extract-post SKILL) --------
low = text.lower()
def first(patterns, default=None):
    for pat, val in patterns:
        if re.search(pat, low): return val
    return default

data = {}
data["condition"] = first([(r"\bnou\b", "new"),
                           (r"ca nou|excelent|impecabil|foarte îngrijit|foarte ingrijit", "excellent"),
                           (r"defect|nefuncțional|nefunctional", "broken"),
                           (r"acceptabil|uzat", "fair"),
                           (r"\bbun\b|folosit", "good")], "good")
mv = first([(r"automat|automatic", "automatic"),
            (r"quartz|baterie", "quartz"),
            (r"mecanic|manual|cheiț|cheit|întoarcere manual|intoarcere manual", "manual")])
if mv: data["movement"] = mv
# case material — plating is a coating, NOT the case metal
if re.search(r"aur masiv|solid gold|18k|14k", low):            data["caseMat"] = "gold"
elif re.search(r"titan|titanium", low):                        data["caseMat"] = "titanium"
else:                                                          data["caseMat"] = "steel"  # incl. plated/AU\d+/dublé
bm = first([(r"piele|leather", "leather"), (r"cauciuc|rubber", "rubber"),
            (r"nylon|textil", "nylon"), (r"brățar|bratar|metal|otel|inox", "steel")])
if bm: data["braceletMat"] = bm
data["type"] = first([(r"dama|femei|lady|women", "women"), (r"unisex", "unisex"),
                      (r"copii|kids", "kids"), (r"bărbat|barbat|bărbăt|barbat|\bmen\b", "men")], "men")
dm = first([(r"safir|sapphire", "sapphire"), (r"cristal mineral|mineral", "mineral"),
            (r"acrilic|plexi|acrylic", "acrylic")])
if dm: data["displayMat"] = dm
wr = first([(r"rezistent la ap|water resist|\bwr\b|\d+\s*atm|\d{2,4}\s*m\b", "water_resistant_yes")])
if wr: data["waterRes"] = wr

m = re.search(r"(\d{2}(?:[.,]\d)?)\s*mm", low)
if m: data["diameter"] = float(m.group(1).replace(",", "."))
m = re.search(r"(?:ref(?:erin[țt]a)?\.?\s*[:\-]?\s*(?:este\s*)?)([A-Z0-9][A-Z0-9\-\/ ]{2,20}[A-Z0-9])", text, re.I)
if m: data["reference"] = m.group(1).strip()
m = re.search(r"(?:\+?40[\s.]?|0)7\d{2}[\s.]?\d{3}[\s.]?\d{3}", text)
if m: data["phone"] = m.group(0)
m = re.search(r"\b((?:19|20)\d{2})(?:\s*[-–]\s*((?:19|20)\d{2}))?\b", text)
if m: data["year"] = m.group(1) + ("-" + m.group(2) if m.group(2) else "")

# price + currency (bare number => RON)
m = re.search(r"(\d[\d.\s]{1,7})\s*(euro|eur|€|lei|ron)?", low)
price, cur = None, "RON"
pm = re.search(r"(?:pre[țt]\s*[:\-]?\s*)?(\d[\d.\s]{1,6})\s*(euro|eur|€|lei|ron)", low)
if pm:
    price = int(re.sub(r"[.\s]", "", pm.group(1)))
    cur = "EUR" if pm.group(2) in ("euro", "eur", "€") else "RON"
else:
    pm = re.search(r"pre[țt]\s*[:\-]?\s*(\d[\d.\s]{1,6})", low)
    if pm: price = int(re.sub(r"[.\s]", "", pm.group(1)))
if price is not None: data["price"] = price
data["currency"] = cur

# brand — match a known BRAND_IDS key present in the text (diacritic-insensitive:
# a post's "Helfer Genève" must still resolve to BRAND_IDS "Helfer Geneve")
def _norm(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()
lown = _norm(text)
brand_ids = json.loads(re.search(r"window\.BRAND_IDS\s*=\s*(\{.*?\});", open(HARNESS).read()).group(1))
brand = None
for name in sorted(brand_ids, key=len, reverse=True):
    if re.search(r"\b" + re.escape(_norm(name)) + r"\b", lown):
        brand = name; break
if brand: data["brand"] = brand
# model — descriptive remainder of the brand's line, brand words stripped off the front.
# Also mark where the real body starts (the brand line) so the description can drop the
# author/timestamp preamble (which includes the aria-hidden obfuscation garbage).
lines = text.splitlines()
body_start = 0
if brand:
    bwords = set(_norm(brand).split())
    for i, line in enumerate(lines):
        if _norm(brand) in _norm(line):
            body_start = i
            words = line.split()
            while words and _norm(words[0]).strip(".-–·:") in bwords:
                words.pop(0)
            model = " ".join(words).strip(" .-–·:")
            if model: data["model"] = model[:80]
            break

data["images"]     = images
# description: real body only — drop the author/timestamp preamble and trailing FB UI noise
_NOISE = ("see translation", "see more", "vezi mai mult", "rate this translation",
          "no comments yet", "be the first to comment", "write a public comment")
def _is_noise(ln):
    n = _norm(ln.strip())
    return any(n.startswith(x) for x in _NOISE)
_body = [ln for ln in lines[body_start:] if not _is_noise(ln)]
while _body and not _body[-1].strip(): _body.pop()      # trim trailing blank lines
data["description"] = "\n".join(_body).strip() or text.strip()
data["sourceUrl"]  = "https://www.facebook.com/groups/vanzareceasuri/posts/%s/" % POST_ID
data["fbListingId"] = POST_ID
data.update({k: v for k, v in OVERRIDES.items() if k != "force"})   # overrides win
emit("INFER", {k: (v if k != "images" else len(v)) for k, v in data.items()})

if not data.get("brand"): die("could not infer brand; pass OVERRIDES {\"brand\":\"...\"}")
if not data.get("model"): die("could not infer model; pass OVERRIDES {\"model\":\"...\"}")
if data.get("price") is None: die("could not infer price; pass OVERRIDES {\"price\":N,\"currency\":\"RON|EUR\"}")

# --- 5. ensure brand exists (create + flag if new) --------------------------
new_brand_id = None
if data["brand"] not in brand_ids:
    bt = new_tab("https://3ceasuri.ro/admin/watches/brand/add/")
    bt = bt["targetId"] if isinstance(bt, dict) else bt
    time.sleep(4)
    slug = re.sub(r"[^a-z0-9]+", "-", data["brand"].lower()).strip("-")
    js('(() => {const n=document.getElementById("id_name"),s=document.getElementById("id_slug");'
       'n.value=%s;n.dispatchEvent(new Event("input",{bubbles:true}));'
       'if(s){s.value=%s;s.dispatchEvent(new Event("input",{bubbles:true}));}'
       'const b=document.querySelector("input[name=_save]");b?b.click():document.querySelector("form").submit();'
       'return "ok";})()' % (json.dumps(data["brand"]), json.dumps(slug)))
    time.sleep(4)
    goto_url("https://3ceasuri.ro/admin/watches/brand/?q=" + slug)
    time.sleep(3)
    row = json.loads(js('(() => {const a=document.querySelector(\'#result_list tbody tr a[href*="/change/"]\');'
                        'const m=a&&a.href.match(/brand\\/(\\d+)\\/change/);return JSON.stringify({id:m?m[1]:null});})()'))
    close_tab(bt)
    if not row["id"]: die("failed to create/find brand %s" % data["brand"])
    new_brand_id = int(row["id"])
    emit("NEW_BRAND", {"name": data["brand"], "id": new_brand_id,
                       "action": "ADD to BRAND_IDS in import-watch.js AND references/brand-ids.md, then commit"})

# --- 6. inject harness (+ runtime brand id if new) --------------------------
switch_tab(ADMIN_TAB)
inject = ("(() => { const s=document.createElement('script'); s.textContent="
          + json.dumps(open(HARNESS).read()) + "; document.head.appendChild(s); "
          "return window.importWatch ? 'OK':'NO_FUNC'; })()")
if js(inject) != "OK": die("harness injection failed")
if new_brand_id is not None:
    js('(() => { window.BRAND_IDS[%s]=%d; return "ok"; })()' % (json.dumps(data["brand"]), new_brand_id))

if DRY_RUN:
    emit("RESULT", {"post_id": POST_ID, "dry_run": True, "images": len(images),
                    "would_import": {k: (v if k != "images" else len(v)) for k, v in data.items()}})
    raise SystemExit(0)

# --- 7. importWatch (expect the navigation exception = success in progress) --
call = "(async () => { try { await importWatch(" + json.dumps(data, ensure_ascii=False) + "); return 'OK'; } catch(e){ return 'ERR:'+e.message; } })()"
try:
    js(call)
except Exception as e:
    pass   # 'Inspected target navigated/closed' / timeout is the normal path
time.sleep(20 + max(0, len(images) - 5) * 2)

# --- 8. verify banners, then read the record back (saved != correct) --------
banners = json.loads(js('(() => {const t=document.body.innerText;return JSON.stringify({'
                        'images_ok:t.includes("imagini salvate"),'
                        'added_ok:t.includes("added successfully")||t.includes("adăugat cu succes")});})()'))
readback = None
chg = json.loads(js('(() => {const a=document.querySelector(\'#result_list tbody tr a[href*="/change/"]\');'
                    'return JSON.stringify({url:a?a.href:null});})()'))
if not (chg.get("url")):
    goto_url("https://3ceasuri.ro/admin/watches/watch/?q=" + POST_ID); time.sleep(3)
    chg = json.loads(js('(() => {const a=document.querySelector(\'#result_list tbody tr a[href*="/change/"]\');'
                        'return JSON.stringify({url:a?a.href:null});})()'))
if chg.get("url"):
    goto_url(chg["url"]); time.sleep(4)
    readback = json.loads(js(
        '(() => {const g=id=>{const e=document.getElementById(id);'
        'return e?(e.tagName==="SELECT"?(e.options[e.selectedIndex]||{}).value:e.value):null;};'
        'const imgs=document.querySelectorAll(\'.field-image img,[id*="images-group"] img,img[src*="/media/"]\').length;'
        'return JSON.stringify({brandId:g("id_brand"),price:g("id_price"),currency:g("id_currency"),'
        'ref:g("id_reference_number"),diameter:g("id_case_diameter_mm"),fbId:g("id_facebook_listing_id"),imgs});})()'))

ok = banners.get("images_ok") and banners.get("added_ok")
emit("RESULT", {"post_id": POST_ID, "ok": bool(ok), "banners": banners,
                "expected_images": len(images), "readback": readback,
                "new_brand": ({"name": data["brand"], "id": new_brand_id} if new_brand_id else None),
                "state_entry": {"id": POST_ID, "brand": data["brand"], "model": data["model"],
                                "price": data["price"], "currency": data["currency"], "images": len(images)}})
