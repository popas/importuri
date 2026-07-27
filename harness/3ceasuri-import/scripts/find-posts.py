#!/usr/bin/env python3
# =============================================================================
# find-posts.py — consolidated ONE-SHOT discovery for the FB group feed.
#
# The discovery half of what import-post.py does for a single post: it runs the
# whole find loop inside ONE browser-use process instead of ~10-40 hand-driven
# js() round-trips that each dumped multi-KB feed text into the conversation.
#   hydrate -> probe [role="feed"] children -> objective filters -> jittered
#   scroll with stall diagnosis -> force-hydrate link-less posts -> batched
#   Stage-1 admin dedup -> emit ONE compact CANDIDATES: line + write them to disk.
#
# It is a browser-use *payload*: pipe it on stdin, NOT `python3 find-posts.py`.
#   export BU_CDP_URL="http://127.0.0.1:9222"
#   MAX_CANDIDATES=8 browser-use < harness/3ceasuri-import/scripts/find-posts.py
#
# Env:
#   PROJECT_ROOT    repo root (default: the Mac path below)
#   GROUP_URL       feed to read (default: the vanzareceasuri main group)
#   FEED_TAB        targetId of the FB group tab (auto-found/created if omitted)
#   MAX_CANDIDATES  stop once this many qualify (default 8)
#   MAX_SCROLLS     scroll passes before giving up (default 10)
#   MIN_RON/MIN_EUR price floors (default 100 RON / 20 EUR)
#   SNIPPET         chars of post text per emitted candidate (default 180)
#   NO_DEDUP=1      skip the admin Stage-1 dedup pass
#   DEBUG_DROPS=1   also emit DROPPED: [{id,why,snip}] — use when a sweep returns
#                   0 candidates, to check the filters aren't eating good watches
#   OUT             candidates file (default harness/3ceasuri-import/.candidates.json)
#
# Emits marker lines the operator/parent can parse:
#   CANDIDATES: [...]   STATS: {...}   ERROR: {...}
#
# WHAT THIS SCRIPT DECIDES vs WHAT YOU DECIDE
#   It applies only *objective* filters — ones a regex can get right every time:
#   video-first ads, blocklisted sellers, missing price, price under the floor,
#   explicit replica wording, wall clocks, already-imported ids. Everything
#   requiring judgement (is this really a watch? a bulk lot? a real brand+model?)
#   stays with you: read the emitted snippets and pick. Dropped posts are
#   reported as COUNTS, not entries, so rejects cost you almost no context.
#
# The full text of every candidate is written to OUT, so a later /clear'd
# context can import from the file without re-scraping the feed.
# =============================================================================
import os, re, json, time, random

PROJECT_ROOT   = os.environ.get("PROJECT_ROOT", "/Users/stelian/.hermes/proiecte/3ceasuri")
GROUP_URL      = os.environ.get("GROUP_URL", "https://www.facebook.com/groups/vanzareceasuri/")
MAX_CANDIDATES = int(os.environ.get("MAX_CANDIDATES", "8"))
MAX_SCROLLS    = int(os.environ.get("MAX_SCROLLS", "10"))
MIN_RON        = int(os.environ.get("MIN_RON", "100"))
MIN_EUR        = int(os.environ.get("MIN_EUR", "20"))
SNIPPET        = int(os.environ.get("SNIPPET", "180"))
NO_DEDUP       = os.environ.get("NO_DEDUP", "") == "1"
DEBUG_DROPS    = os.environ.get("DEBUG_DROPS", "") == "1"   # also emit WHAT was rejected
HARNESS        = os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts/import-watch.js")
OUT            = os.environ.get("OUT", os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/.candidates.json"))

def emit(tag, obj): print(tag + ": " + json.dumps(obj, ensure_ascii=False))
def die(msg):       emit("ERROR", {"msg": msg}); raise SystemExit(1)

def _norm(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower().strip()

# --- blocklisted sellers (same file import-post.py enforces) -----------------
BLOCK = {}
try:
    _bl = json.load(open(os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/references/seller-blocklist.json")))
    BLOCK = {a["id"]: a.get("name") for a in _bl.get("authors", [])}
except Exception:
    pass

# --- known brands, for a cheap brand hint on each candidate -----------------
try:
    BRAND_IDS = json.loads(re.search(r"window\.BRAND_IDS\s*=\s*(\{.*?\});", open(HARNESS).read()).group(1))
except Exception:
    BRAND_IDS = {}
BRANDS_BY_LEN = sorted(BRAND_IDS, key=len, reverse=True)

# --- resolve the feed tab ---------------------------------------------------
tabs = list_tabs()
def find_tab(pred):
    for t in tabs:
        if pred((t.get("url") or "").lower(), (t.get("title") or "").lower()):
            return t["targetId"]
    return None

# A group *post* page (/groups/<g>/posts/<id>/) also matches "/groups/" but has no feed —
# left-over post tabs from a previous session would otherwise be picked as the feed.
def _is_feed(u):
    return ("facebook.com" in u and "/groups/" in u
            and not any(x in u for x in ("/posts/", "/user/", "/photo", "/permalink/")))

FEED_TAB = os.environ.get("FEED_TAB") or find_tab(lambda u, t: _is_feed(u))
if not FEED_TAB:
    r = new_tab(GROUP_URL)
    FEED_TAB = r["targetId"] if isinstance(r, dict) else r
    time.sleep(8)
switch_tab(FEED_TAB)
if "/groups/" not in (js('(() => location.href)()') or ""):
    goto_url(GROUP_URL); time.sleep(8)

# --- the probe: one compact record per feed child ---------------------------
# Iterates [role="feed"].children (NOT [role="article"] — that matches ~2 nodes
# on the buy/sell feed). Text is read through a TreeWalker that skips
# aria-hidden nodes, so FB's scrambled author/timestamp decoys stay out of it.
PROBE = r'''(() => {
 const f=document.querySelector('[role="feed"]');
 const meta={h:document.body.scrollHeight,y:Math.round(window.scrollY)};
 if(!f) return JSON.stringify(Object.assign(meta,{ok:false,n:0,items:[]}));
 const kids=[...f.children], out=[];
 kids.forEach((c,i)=>{
  const nodes=[...c.querySelectorAll('video,[aria-label*="Play"],a[href*="/photo/"]')];
  let vf=false;
  for(const n of nodes){
   const isVid=(n.tagName==="VIDEO")||(((n.getAttribute&&n.getAttribute("aria-label"))||"").indexOf("Play")>-1);
   if(isVid){vf=true;break;}
   if(n.tagName==="A")break;
  }
  let id=null,lid=null,au=null;
  c.querySelectorAll('a[href*="/photo/"]').forEach(l=>{
   if(!id){const m=(l.href||"").match(/set=pcb\.(\d+)/);if(m)id=m[1];}});
  c.querySelectorAll('a[href*="commerce/listing/"]').forEach(l=>{
   if(!lid){const m=(l.href||"").match(/commerce\/listing\/(\d+)/);if(m)lid=m[1];}});
  c.querySelectorAll('a[href*="/user/"]').forEach(a=>{
   if(!au){const m=(a.href||"").match(/\/user\/(\d+)/);if(m)au=m[1];}});
  const hid=el=>{for(let e=el;e&&e!==c;e=e.parentElement)
   if(e.getAttribute&&e.getAttribute("aria-hidden")==="true")return true;return false;};
  const w=document.createTreeWalker(c,NodeFilter.SHOW_TEXT,{acceptNode:n=>
   (n.textContent.trim().length>1&&!hid(n.parentElement))?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_SKIP});
  let t="",z;
  while(z=w.nextNode()) t+=z.textContent+" ";
  t=t.replace(/(Facebook\s*)+/g," ").replace(/\s+/g," ").trim();
  if(t.length>25||id||lid) out.push({i:i,id:id,lid:lid,vf:vf,au:au,txt:t.substring(0,700)});
 });
 return JSON.stringify(Object.assign(meta,{ok:true,n:kids.length,items:out}));
})()'''

HYDRATE = ('(() => {const f=document.querySelector(\'[role="feed"]\');const c=f&&f.children[%d];'
           'if(!c)return "x";c.scrollIntoView({block:"center"});return "c";})()')
CHILD_ID = ('(() => {const f=document.querySelector(\'[role="feed"]\');const c=f&&f.children[%d];'
            'if(!c)return "";let id="";c.querySelectorAll(\'a[href*="/photo/"]\').forEach(l=>{'
            'if(!id){const m=(l.href||"").match(/set=pcb\\.(\\d+)/);if(m)id=m[1];}});return id;})()')

def probe():
    try:
        return json.loads(js(PROBE))
    except Exception as e:
        return {"ok": False, "h": 0, "y": 0, "n": 0, "items": [], "err": str(e)}

# --- wait out hydration (an empty document is not an empty feed) ------------
p = probe()
for _ in range(5):
    if p.get("ok") and p.get("n", 0) > 3 and p.get("h", 0) > 3000:
        break
    time.sleep(5)
    p = probe()
if not p.get("ok"):
    die("no [role=\"feed\"] on %s — wrong page, or the cross-origin proxy iframe (use the main group URL)" % GROUP_URL)

# --- objective filters ------------------------------------------------------
REPLICA  = re.compile(r"\breplic|\baaa\+|\bclona|\bclone\b|homage", re.I)
# plural matters: a seller clearing stock writes "Ceasuri de perete", not "ceas de perete"
WALLCLK  = re.compile(r"ceas(?:uri)?\s+(?:de\s+)?(?:perete|mas[ăa]|birou|[șs]emineu)|pendul|wall clock", re.I)
# a price RANGE means more than one item is for sale — a bulk/stock post, not a listing
BULK     = re.compile(r"pre[țt]uri\s+(?:cuprinse|[iî]ntre)|\blot\s+de\s+\d|\bloturi\b|"
                      r"\d+\s*[-–]\s*\d+\s*(?:ron|lei|eur|euro|€)", re.I)
# Digits may group as 1.500 / 1 500, but NOT run across arbitrary whitespace — on
# 2026-07-27 the looser pattern welded a price onto a following phone number and
# produced 2500763 RON. Phone numbers are stripped before parsing for the same reason.
_NUM     = r"(\d{1,3}(?:[.,\s]\d{3})+|\d+)"
PRICE_RE = re.compile(_NUM + r"\s*(euro|eur|€|lei|ron)\b", re.I)
PRICE_LB = re.compile(r"pre[țt]\s*[:\-]?\s*" + _NUM, re.I)
PHONE_RE = re.compile(r"(?:\+?40[\s.]?|0)7\d{2}[\s.]?\d{3}[\s.]?\d{3}")
MAX_PLAUSIBLE = {"RON": 500000, "EUR": 100000}

def parse_price(text):
    """Return (amount, currency) or (None, None). A bare number counts only when
    labelled 'pret:' — otherwise years and phone numbers read as prices."""
    text = PHONE_RE.sub(" ", text)
    best = None
    for m in PRICE_RE.finditer(text):
        try:
            amt = int(re.sub(r"[.,\s]", "", m.group(1)))
        except ValueError:
            continue
        cur = "EUR" if m.group(2).lower() in ("euro", "eur", "€") else "RON"
        if amt <= 0 or amt > MAX_PLAUSIBLE[cur]:
            continue
        if best is None or amt > best[0]:
            best = (amt, cur)
    if best:
        return best
    m = PRICE_LB.search(text)
    if m:
        try:
            amt = int(re.sub(r"[.,\s]", "", m.group(1)))
            if 0 < amt <= MAX_PLAUSIBLE["RON"]:
                return amt, "RON"
        except ValueError:
            pass
    return None, None

BIG_CM = re.compile(r"(\d{2,3})\s*cm", re.I)

def is_furniture(text):
    """A wristwatch is never described in tens of centimetres — but a case diameter
    legitimately is (4 cm), so only a LARGE cm figure marks a wall/floor clock."""
    return any(int(m.group(1)) >= 15 for m in BIG_CM.finditer(text))

def brand_hint(text):
    n = _norm(text)
    for name in BRANDS_BY_LEN:
        if re.search(r"\b" + re.escape(_norm(name)) + r"\b", n):
            return name
    return None

seen_ids   = set()      # every id we have already judged (any verdict)
candidates = {}         # id -> record, survivors only
dropped    = {}         # reason -> count
samples    = []         # DEBUG_DROPS only: what was rejected and why
def drop(reason, it=None):
    dropped[reason] = dropped.get(reason, 0) + 1
    if DEBUG_DROPS:
        samples.append({"id": (it or {}).get("id") or (it or {}).get("lid"), "why": reason,
                        "snip": re.sub(r"\s+", " ", (it or {}).get("txt") or "")[:110]})

def consider(it):
    """Apply the objective filters to one probed feed child."""
    key = it.get("id") or (("listing:" + it["lid"]) if it.get("lid") else None)
    if not key or key in seen_ids:
        return
    seen_ids.add(key)
    txt = it.get("txt") or ""
    if it.get("vf"):
        drop("video_first", it); return
    if it.get("au") and it["au"] in BLOCK:
        drop("blocklisted_seller", it); return
    if REPLICA.search(txt):
        drop("replica", it); return
    if WALLCLK.search(txt) or is_furniture(txt):
        drop("not_wristwatch", it); return
    if BULK.search(txt):
        drop("bulk_or_price_range", it); return
    amt, cur = parse_price(txt)
    if amt is None:
        drop("no_price", it); return
    if (cur == "RON" and amt < MIN_RON) or (cur == "EUR" and amt < MIN_EUR):
        drop("price_below_floor", it); return
    b = brand_hint(txt)
    candidates[key] = {"id": it.get("id") or it.get("lid"),
                       "kind": "post" if it.get("id") else "listing",
                       "price": amt, "cur": cur, "brand": b,
                       "new_brand": b is None,
                       "author": it.get("au"), "text": txt}

def sweep(pr):
    """Judge every item in a probe, force-hydrating promising link-less posts.

    A post whose media has not lazy-loaded exposes no set=pcb. link, so its id is
    unrecoverable and the listing is silently lost (this cost a ~7500 EUR Rolex on
    2026-07-24). Scroll it into view and re-read before writing it off."""
    stuck = [it for it in pr.get("items", [])
             if not it.get("id") and not it.get("lid") and len(it.get("txt") or "") > 40
             and parse_price(it.get("txt") or "")[0] is not None]
    for it in stuck[:2]:
        try:
            if js(HYDRATE % it["i"]) != "c":
                continue
            time.sleep(4)
            got = (js(CHILD_ID % it["i"]) or "").strip()
            if got:
                it["id"] = got
            else:
                drop("no_id_after_hydrate", it)
        except Exception:
            drop("no_id_after_hydrate", it)
    for it in pr.get("items", []):
        consider(it)

sweep(p)

# --- paced scroll loop, with the stall diagnosis kept out of context --------
scrolls, stall, notes = 0, 0, []
last_h, last_y = p.get("h", 0), p.get("y", 0)
while len(candidates) < MAX_CANDIDATES and scrolls < MAX_SCROLLS:
    js('window.scrollBy(0, 1400); "ok"')
    time.sleep(random.uniform(3, 6))          # jitter — fixed intervals read as a bot
    scrolls += 1
    pr = probe()
    if not pr.get("ok"):
        continue
    sweep(pr)
    h, y = pr.get("h", 0), pr.get("y", 0)
    if h == last_h and y <= last_y:
        stall += 1
        if stall == 1:
            notes.append("scrollY not advancing at pass %d — scroll may be broken, not FB" % scrolls)
    elif h == last_h:
        stall += 1
    else:
        stall = 0
    last_h, last_y = h, y
    if stall >= 3:
        notes.append("feed stopped growing after %d passes — throttled or genuinely exhausted" % scrolls)
        break

# --- Stage-1 dedup: batch every candidate against the admin -----------------
# Our own site, so no FB-style rate concern. Clearing all ids up front means a
# throttled feed can't strand the loop mid-way.
admin_total = None
if candidates and not NO_DEDUP:
    r = new_tab("https://3ceasuri.ro/admin/watches/watch/")
    at = r["targetId"] if isinstance(r, dict) else r
    time.sleep(3)
    PAG = '(() => {const p=document.querySelector(".paginator");return p?(p.innerText||"").trim():"";})()'
    def count_for(url):
        goto_url(url); time.sleep(2.5)
        try:
            m = re.search(r"\d[\d,.]*", js(PAG) or "")
            return int(re.sub(r"[,.]", "", m.group(0))) if m else None
        except Exception:
            return None
    admin_total = count_for("https://3ceasuri.ro/admin/watches/watch/")
    for key in list(candidates):
        n = count_for("https://3ceasuri.ro/admin/watches/watch/?q=%s" % candidates[key]["id"])
        if n is None:
            candidates[key]["dedup"] = "unverified"   # never drop on a failed check
        elif n > 0:
            drop("already_imported", {"id": candidates[key]["id"], "txt": candidates[key]["text"]}); del candidates[key]
    close_tab(at)
    switch_tab(FEED_TAB)

# --- persist full records, emit compact ones --------------------------------
ordered = list(candidates.values())[:MAX_CANDIDATES]
try:
    with open(OUT, "w") as f:
        json.dump({"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "group": GROUP_URL,
                   "candidates": ordered}, f, ensure_ascii=False, indent=1)
except Exception as e:
    notes.append("could not write %s: %s" % (OUT, e))

emit("CANDIDATES", [{"id": c["id"], "kind": c["kind"], "price": c["price"], "cur": c["cur"],
                     "brand": c["brand"], "new_brand": c["new_brand"], "author": c["author"],
                     "snip": re.sub(r"\s+", " ", c["text"])[:SNIPPET]}
                    for c in ordered])
if DEBUG_DROPS:
    emit("DROPPED", samples)
emit("STATS", {"candidates": len(ordered), "seen": len(seen_ids), "scrolls": scrolls,
               "dropped": dropped, "admin_total": admin_total, "out": OUT,
               "notes": notes or None})
