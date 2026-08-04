#!/usr/bin/env python3
# =============================================================================
# import-post.py — consolidated ONE-SHOT importer for a single FB watch post.
#
# Runs the entire per-watch flow in a single browser-use process, replacing the
# ~8 hand-orchestrated calls of the find/extract/import/verify skills:
#   post page -> gate on pcb.<ID> -> capture video permalink (if any) -> carousel images
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
#   POST_ID       numeric FB post ID (group post — gated on its pcb photo set)
#   LISTING_ID    numeric commerce-listing ID instead, for find-posts.py candidates
#                 with kind:"listing". Those have no pcb set; the listing page holds
#                 every image in the DOM at once, so there is no carousel to walk.
#   PROJECT_ROOT  repo root (default: the Mac path below)
#   ADMIN_TAB     targetId of the admin add-watch tab (auto-found if omitted)
#   PHOTO_TAB     targetId of a scratch FB tab for the photo viewer (auto/created)
#   OVERRIDES     JSON object of field overrides merged over inference (authoritative)
#   DRY_RUN       "1" = extract + infer + print, do NOT import (force a review pass)
#   CONFIRM       "1" = proceed past the REVIEW gate (see below)
#
# Do NOT run a DRY_RUN pass by default — it doubles the browser work and the
# output on posts that need no supervision. The script judges its own confidence
# and stops on its own when it should: if the brand is new, the model/price did
# not infer, fewer than 2 images came back, or the description is thin, it emits
# REVIEW: and imports NOTHING. Fix it with OVERRIDES and re-run with CONFIRM=1.
# Everything else imports in one pass.
#
# Emits marker lines the operator/parent can parse:
#   EXTRACT: {...}   SKIP: {...}   INFER: {...}   REVIEW: {...}
#   NEW_BRAND: {...} RESULT: {...} ERROR: {...}
#
# Field inference mirrors .claude/skills/fb-extract-post/SKILL.md — keep in sync.
# A NEW brand is created in the DB and injected at runtime, but the source files
# (BRAND_IDS in import-watch.js + references/brand-ids.md) must still be updated
# by hand afterwards — watch for the NEW_BRAND: line and sync + commit.
# =============================================================================
import os, re, json, time, random, sys

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", "/Users/stelian/.hermes/proiecte/3ceasuri")
# This file is piped to browser-use on stdin, so there is no __file__ to hang a
# relative import off — locate the sibling module through PROJECT_ROOT instead.
sys.path.insert(0, os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts"))
import infer_fields
POST_ID    = os.environ.get("POST_ID", "").strip()
LISTING_ID = os.environ.get("LISTING_ID", "").strip()
# find-posts.py emits kind:"listing" for commerce listings, which have no pcb photo set and
# so cannot be gated or carousel-collected like a group post. They take a different route to
# the same inference/import pipeline: LISTING_ID instead of POST_ID.
IS_LISTING = bool(LISTING_ID) and not POST_ID
if IS_LISTING:
    POST_ID = LISTING_ID
OVERRIDES = json.loads(os.environ.get("OVERRIDES", "{}"))
DRY_RUN   = os.environ.get("DRY_RUN", "") == "1"
CONFIRM   = os.environ.get("CONFIRM", "") == "1"   # proceed past the REVIEW gate
SKIP_PROMPT = os.environ.get("SKIP_PROMPT", "") == "1"  # import on the regex baseline
HARNESS   = os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts/import-watch.js")
SOURCE_URL = (("https://www.facebook.com/commerce/listing/%s/" % POST_ID) if IS_LISTING
              else ("https://www.facebook.com/groups/vanzareceasuri/posts/%s/" % POST_ID))

def emit(tag, obj): print(tag + ": " + json.dumps(obj, ensure_ascii=False))
def die(msg):       emit("ERROR", {"post_id": POST_ID, "msg": msg}); raise SystemExit(1)

if not POST_ID or not POST_ID.isdigit():
    die("set POST_ID (group post) or LISTING_ID (commerce listing) to a numeric FB id")

def _norm(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower().strip()

# --- dedup: read admin result rows for a ?q= query (own site, no rate limit) -
_ROWS_JS = ("(() => {const g=(tr,c)=>{const e=tr.querySelector('td.field-'+c);return e?(e.innerText||'').trim():'';};"
            "return JSON.stringify([...document.querySelectorAll('#result_list tbody tr')].map(tr=>"
            "({brand:g(tr,'brand'),model:g(tr,'model_name'),fbid:g(tr,'facebook_listing_id')})));})()")

def admin_rows(query, return_to):
    """Query the watch admin by ?q=, return [{brand,model,fbid}], restore return_to tab."""
    t = new_tab("https://3ceasuri.ro/admin/watches/watch/?q=%s" % query)
    t = t["targetId"] if isinstance(t, dict) else t
    time.sleep(3)
    try:
        rows = json.loads(js(_ROWS_JS))
    except Exception:
        rows = []
    close_tab(t)
    switch_tab(return_to)
    return rows

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

# --- 0. dedup Stage 1: exact facebook_listing_id (skip before any FB work) ---
if admin_rows(POST_ID, PHOTO_TAB):
    emit("SKIP", {"post_id": POST_ID, "reason": "already imported (facebook_listing_id match)"})
    raise SystemExit(0)

# --- 1L. commerce listing: every image is in the DOM at once, no carousel ----
if IS_LISTING:
    switch_tab(PHOTO_TAB)
    goto_url(SOURCE_URL)
    LISTING_JS = ('(() => {const seen={},urls=[];'
                  'document.querySelectorAll("img").forEach(i=>{'
                  'if(i.src&&i.src.indexOf("scontent")>-1&&i.naturalWidth>200){'
                  'const b=i.src.split("?")[0]; if(!seen[b]){seen[b]=1;urls.push(i.src);}}});'
                  'let aId=null,aName=null;'
                  'document.querySelectorAll(\'a[href*="/user/"],a[href*="profile.php?id="]\').forEach(a=>{'
                  'const h=a.href||""; if(!aId){const m=h.match(/\\/user\\/(\\d+)/)||h.match(/profile\\.php\\?id=(\\d+)/);'
                  'if(m)aId=m[1];} const tx=((a.innerText||"").trim().replace(/\\s+/g," "));'
                  'if(tx&&!aName)aName=tx;});'
                  'const m=document.querySelector(\'[role="main"]\')||document.body;'
                  'const txt=(m.innerText||"").replace(/(Facebook\\n?)+/g,"");'
                  'return JSON.stringify({urls:urls,txt:txt.substring(0,1200),authorId:aId,authorName:aName});})()')
    info, images = None, []
    for _ in range(4):                   # listing pages hydrate like post pages do
        time.sleep(5)
        try:
            info = json.loads(js(LISTING_JS))
        except Exception:
            continue
        images = info.get("urls") or []
        if images:
            break
    if not info or not images:
        die("commerce listing %s surfaced no scontent images (removed, or still hydrating)" % POST_ID)
    info["firstIsVideo"] = False         # listings lead with photos, not reels

    def _clean_listing(t):
        """A commerce listing page wraps the seller's text in UI chrome. Inference must
        NOT see it: on 2026-07-27 'Joined in 2011' (when the SELLER joined Facebook) was
        read as the watch's year. Keep only the block after 'Details'."""
        body = t
        m = re.search(r"\n\s*Details\s*\n", body)
        if m:
            body = body[m.end():]
        for marker in ("Seller information", "Seller details", "Location is approximate",
                       "Related searches", "Message Seller", "Learn more about",
                       "Joined ", "In stock"):
            i = body.find(marker)
            if i > 20:                   # keep the marker only if real text precedes it
                body = body[:i]
        body = "\n".join(ln for ln in body.splitlines() if ln.strip()).strip(" ·\t\n")
        return body if len(body.strip()) >= 20 else t

    text = _clean_listing(info["txt"])
    info["txt"] = text
    hit = SOURCE_URL
    emit("EXTRACT", {"post_id": POST_ID, "kind": "listing", "hit": hit, "images": len(images),
                     "chars": len(text), "author_id": info.get("authorId"),
                     "author_name": info.get("authorName")})

# --- 1. open post page, gate on the post's own photo set --------------------
if not IS_LISTING:
  switch_tab(PHOTO_TAB)
  goto_url(SOURCE_URL)
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
     # post author: first /user/<id> link in the post container = the poster (header link)
     # the poster has TWO /user/ links: the avatar (no text) then the name (text). Take the
     # id from the first, the name from the first one that actually has text.
     ' const aus=[...cont.querySelectorAll(\'a[href*="/user/"]\')]; let aId=null,aName=null;'
     ' for(const a of aus){ if(!aId){const m=(a.href||"").match(/\\/user\\/(\\d+)/); if(m)aId=m[1];}'
     ' const tx=((a.innerText||"").trim().replace(/\\s+/g," ")); if(tx&&!aName)aName=tx; }'
     # video-first: a <video>/scrubber that precedes the first photo in DOM order
     ' const nodes=[...cont.querySelectorAll(\'video,[aria-label*="Play"],a[href*="/photo/"]\')];'
     ' let firstIsVideo=false; for(const n of nodes){ const isVid=(n.tagName==="VIDEO")||'
     '((n.getAttribute&&(n.getAttribute("aria-label")||"").indexOf("Play")>-1)); '
     ' const isPhoto=n.tagName==="A"; if(isVid){firstIsVideo=true;break;} if(isPhoto){break;} }'
     # video permalink: FB serves the clip itself from a blob: MSE url, which is
     # worthless once the tab closes — the durable reference is the /videos/, /reel/
     # or /watch/?v= link FB renders alongside it. Only accept an http(s) <video src>.
     ' let vurl=null;'
     ' const vl=[...cont.querySelectorAll(\'a[href*="/videos/"],a[href*="/reel/"],a[href*="/watch/?v="]\')];'
     ' if(vl.length) vurl=vl[0].href.split("?")[0].indexOf("/watch")>-1 ? vl[0].href : vl[0].href.split("?")[0];'
     ' if(!vurl){ const v=cont.querySelector("video[src]"); '
     ' if(v&&/^https?:/.test(v.getAttribute("src")||"")) vurl=v.getAttribute("src"); }'
     ' const d=document.querySelector(\'div[role="dialog"]\')||cont;'
     ' let txt=(d.innerText||"").replace(/(Facebook\\n?)+/g,"");'
     ' return JSON.stringify({firstIsVideo, videoUrl:vurl, txt:txt.substring(0,1200), authorId:aId, authorName:aName}); })()' % POST_ID))
  text = info["txt"]
  emit("EXTRACT", {"post_id": POST_ID, "hit": hit, "video_first": info["firstIsVideo"],
                   "video_url": info.get("videoUrl"), "chars": len(text),
                   "author_id": info.get("authorId"), "author_name": info.get("authorName")})

# --- 1b. blocklisted sellers: never import (user directive) ------------------
_BLOCK = {}
try:
    _bl = json.load(open(os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/references/seller-blocklist.json")))
    _BLOCK = {a["id"]: a.get("name") for a in _bl.get("authors", [])}
except Exception:
    pass
if info.get("authorId") and info["authorId"] in _BLOCK:
    emit("SKIP", {"post_id": POST_ID, "reason": "blocklisted seller",
                  "author_id": info["authorId"], "author_name": _BLOCK.get(info["authorId"])})
    raise SystemExit(0)

# --- 2. video posts are imported, not skipped (user directive 2026-08-04) ----
# The clip is saved to Watch.video_url; the photos still come from the pcb carousel
# below, and a post with no usable photos is caught by the <2-images review gate.
VIDEO_URL = OVERRIDES.get("videoUrl") or info.get("videoUrl")
if info["firstIsVideo"]:
    emit("VIDEO", {"post_id": POST_ID, "video_url": VIDEO_URL,
                   "note": "video-first post; importing with video_url" if VIDEO_URL
                           else "video-first post but no durable video permalink found"})

# --- 3. collect images via the pcb carousel ---------------------------------
if not IS_LISTING:
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
# No default: an unstated gender used to fall through to "men", which
# invented data for every listing that simply did not mention it.
data["gender"] = first([(r"dama|femei|lady|women", "women"), (r"unisex", "unisex"),
                        (r"copii|kids", "kids"), (r"bărbat|barbat|bărbăt|barbat|\bmen\b", "men")])
# Style is independent of gender — a men's diver is both.
data["style"] = first([(r"smartwatch|smart watch|\bsmart\b", "smart"),
                       (r"diver|scafandru|scufundar|\bsub\b\s*\d{3}", "diver"),
                       (r"cronograf|chronograph|chrono", "chronograph"),
                       (r"sport|sportiv", "sport"),
                       (r"elegant|dress|clasic", "dress")])
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

def derive_from_brand(bname):
    """Locate the brand's line -> (body_start, model). The real post body starts at
    the brand line (everything above it is the author/timestamp preamble), and the
    model is that same line with the brand words stripped off the front."""
    if not bname:
        return 0, None
    nb, bwords = _norm(bname), set(_norm(bname).split())
    for i, line in enumerate(lines):
        if nb in _norm(line):
            words = line.split()
            while words and _norm(words[0]).strip(".-–·:") in bwords:
                words.pop(0)
            mdl = " ".join(words).strip(" .-–·:")[:80]
            return i, (mdl or None)
    return 0, None

body_start, _model = derive_from_brand(brand)
if _model: data["model"] = _model

data["images"]     = images
# description: real body only — drop the author/timestamp preamble and trailing FB UI noise
_NOISE = ("see translation", "see more", "vezi mai mult", "rate this translation",
          "no comments yet", "be the first to comment", "write a public comment")
def _is_noise(ln):
    n = _norm(ln.strip())
    return any(n.startswith(x) for x in _NOISE)
def _build_desc(bs):
    body = [ln for ln in lines[bs:] if not _is_noise(ln)]
    while body and not body[-1].strip(): body.pop()     # trim trailing blank lines
    return "\n".join(body).strip()
data["description"] = _build_desc(body_start) or text.strip()
data["sourceUrl"]  = SOURCE_URL
data["fbListingId"] = POST_ID
if VIDEO_URL: data["videoUrl"] = VIDEO_URL
if info.get("authorId"):   data["fbAuthorId"]   = info["authorId"]
if info.get("authorName"): data["fbAuthorName"] = info["authorName"]
# A filled contract is AUTHORITATIVE, including about what the post does NOT say: a
# contract field the answer left out is cleared, instead of keeping the regex guess.
# That guess is not harmless — the Tissot listing (1038189799074673) never states a
# case material and the regex still proposed `steel`.
# `is_wristwatch` is required by the contract and never null, so its presence is what
# distinguishes a full answer from a targeted OVERRIDES fix, which still merges.
IS_CONTRACT = "is_wristwatch" in OVERRIDES
if IS_CONTRACT:
    for _f in infer_fields.SCHEMA_FIELDS:
        if _f not in OVERRIDES:
            data.pop(_f, None)
data.update({k: v for k, v in OVERRIDES.items() if k != "force"})   # overrides win
# An override-supplied brand (every NEW brand comes this way) wasn't known when the brand
# line was located above, so BOTH the model and the description were derived from the wrong
# offset — the model not at all, and the scrambled author/timestamp preamble leaking into the
# description. Redo both against the final brand, without overwriting anything the caller set.
# Skipped for a contract answer: re-deriving would put back exactly what it just cleared.
if data.get("brand") and not IS_CONTRACT:
    _bs, _mdl = derive_from_brand(data["brand"])
    if _mdl and "model" not in OVERRIDES and not data.get("model"):
        data["model"] = _mdl
    if "description" not in OVERRIDES and _bs > body_start:
        data["description"] = _build_desc(_bs) or data["description"]

# --- 3b. the extraction contract --------------------------------------------
# The regexes above are the baseline and they are reliably wrong on the same
# fields (model, reference, movement). The agent driving the session does the real
# inference, so emit the contract for it to fill and validate what comes back.
# `is_wristwatch` / `is_bulk_lot` are the judgement calls the objective filters
# keep missing (pendulum clocks with no clock keyword, "400 lei amandoua" bundles).
problems = infer_fields.validate(OVERRIDES)
if problems:
    die("OVERRIDES are not valid DB values: " + "; ".join(problems))

if OVERRIDES.get("is_wristwatch") is False and not CONFIRM:
    emit("SKIP", {"post_id": POST_ID, "reason": "not a wristwatch; pass CONFIRM=1 to import anyway"})
    raise SystemExit(0)
if OVERRIDES.get("is_bulk_lot") is True and not CONFIRM:
    emit("SKIP", {"post_id": POST_ID, "reason": "bulk lot - one price, several watches; pass CONFIRM=1 to import anyway"})
    raise SystemExit(0)
for _k in ("is_wristwatch", "is_bulk_lot", "notes"):   # contract-only, not form fields
    data.pop(_k, None)

emit("INFER", {k: (v if k != "images" else len(v)) for k, v in data.items()})

# First pass with no OVERRIDES: stop here and hand the contract out to be filled.
# The regex baseline below it is only a starting point — importing on it is what
# produced four hand-fixed records on 2026-08-04. This costs a second browser-use
# call per watch, which the carousel needs anyway (FB image URLs expire in-session).
# SKIP_PROMPT=1 imports on the regex baseline when the post is trivially simple.
if not OVERRIDES and not SKIP_PROMPT and not DRY_RUN:
    emit("EXTRACT_PROMPT", {"post_id": POST_ID,
                            "prompt": infer_fields.build_prompt(text, brand_ids.keys()),
                            "rerun": "POST_ID=%s CONFIRM=1 OVERRIDES='{...}' browser-use < .../import-post.py" % POST_ID})
    raise SystemExit(0)

# --- 4a. confidence gate: halt for review ONLY when inference is weak --------
# Replaces the old "always DRY_RUN first, then import" double pass, which paid
# for a second full browser round-trip on every post including the obvious ones.
# A confident post imports in a single pass; a doubtful one stops here, before
# any DB write, and asks for OVERRIDES + CONFIRM=1.
review = []
if not data.get("brand"):                   review.append("brand not inferred")
elif data["brand"] not in brand_ids:        review.append("NEW brand '%s' — will be created in the DB" % data["brand"])
if not data.get("model"):                   review.append("model not inferred")
if data.get("price") is None:               review.append("price not inferred")
# movement is NOT optional in the DB, so the harness fills the gap with 'quartz'. That
# guess silently mislabelled a 1970s Poljot on 2026-08-04 — a post that never states its
# movement must be judged, not defaulted.
if not data.get("movement"):                review.append("movement not stated in the post (harness would default it to quartz)")
if len(images) < 2:                         review.append("only %d image(s) collected" % len(images))
if len((data.get("description") or "").strip()) < 40:
                                            review.append("description looks thin (%d chars)" % len((data.get("description") or "").strip()))
if review and not CONFIRM and not DRY_RUN:
    emit("REVIEW", {"post_id": POST_ID, "reasons": review, "images": len(images),
                    "inferred": {k: (v if k != "images" else len(v)) for k, v in data.items()},
                    "rerun": "POST_ID=%s CONFIRM=1 OVERRIDES='{...}' browser-use < .../import-post.py" % POST_ID})
    raise SystemExit(0)

# Hard requirements — CONFIRM cannot wave these through, the form would reject them.
if not data.get("brand"): die("could not infer brand; pass OVERRIDES {\"brand\":\"...\"}")
if not data.get("model"): die("could not infer model; pass OVERRIDES {\"model\":\"...\"}")
if data.get("price") is None: die("could not infer price; pass OVERRIDES {\"price\":N,\"currency\":\"RON|EUR\"}")

# --- 4b. dedup Stage 2: the same watch reposted under a NEW post id ----------
# Verified live on 2026-07-27, and the original author+brand+model rule turned out to be
# dead code: the admin changelist renders the BRAND cell as empty text (confirmed against a
# record whose brand id is definitely set), so `brand match AND model match` was never true.
# A known Helfer repost sailed straight through it. Two independent lookups now, matching on
# MODEL, with brand used only to *veto* — plus a REVIEW when the evidence is weak, so a
# generic model name can neither silently skip a new watch nor silently import a duplicate.
author_id = data.get("fbAuthorId")
my_model, my_brand = _norm(data.get("model")), _norm(data.get("brand"))

def _distinctive(m):
    """Distinctive enough that an exact match means 'same watch', not 'same word'."""
    return len(m) >= 8 and (any(c.isdigit() for c in m) or len(m.split()) >= 2)

hits = []
if author_id:
    hits += [(r, "author") for r in admin_rows(author_id, ADMIN_TAB)]
if data.get("model"):
    import urllib.parse
    hits += [(r, "model") for r in admin_rows(urllib.parse.quote(data["model"]), ADMIN_TAB)]

for row, via in hits:
    if _norm(row.get("model")) != my_model or not my_model:
        continue
    row_brand = _norm(row.get("brand"))
    if row_brand and row_brand != my_brand:
        continue                       # genuinely a different brand — not a repost
    if row.get("fbid") == POST_ID:
        continue                       # that's this very post
    strong = (via == "author") or _distinctive(my_model)
    detail = {"post_id": POST_ID, "author_id": author_id, "author_name": data.get("fbAuthorName"),
              "matched_via": via, "brand_confirmed": bool(row_brand),
              "match": {"brand": data.get("brand"), "model": data.get("model"),
                        "existing_fb_id": row.get("fbid")}}
    if strong:
        emit("SKIP", dict(detail, reason="repost (%s match)" % ("author+model" if via == "author" else "model")))
        raise SystemExit(0)
    if not CONFIRM:
        emit("REVIEW", dict(detail, reasons=["possible repost: model '%s' already on the site, "
                                             "but the name is generic and the brand could not be "
                                             "confirmed — check, then CONFIRM=1 to import anyway"
                                             % data.get("model")]))
        raise SystemExit(0)

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
        'ref:g("id_reference_number"),diameter:g("id_case_diameter_mm"),fbId:g("id_facebook_listing_id"),'
        'videoUrl:g("id_video_url"),'
        'authorId:g("id_facebook_author_id"),authorName:g("id_facebook_author_name"),imgs});})()'))

# The "added successfully" banner is flaky on multi-image saves; a readback that found the
# record by its own fbId is authoritative proof the add committed. Accept either signal.
readback_ok = bool(readback and str(readback.get("fbId")) == str(POST_ID))
ok = bool(banners.get("images_ok") and (banners.get("added_ok") or readback_ok))
emit("RESULT", {"post_id": POST_ID, "ok": bool(ok), "banners": banners, "readback_ok": readback_ok,
                "expected_images": len(images), "readback": readback,
                "new_brand": ({"name": data["brand"], "id": new_brand_id} if new_brand_id else None),
                "state_entry": {"id": POST_ID, "brand": data["brand"], "model": data["model"],
                                "price": data["price"], "currency": data["currency"], "images": len(images),
                                "video_url": data.get("videoUrl"),
                                "author_id": data.get("fbAuthorId"), "author_name": data.get("fbAuthorName")}})
