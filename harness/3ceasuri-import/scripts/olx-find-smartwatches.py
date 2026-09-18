#!/usr/bin/env python3
# =============================================================================
# olx-find-smartwatches.py — discovery for OLX category 1943 (smartwatch-uri).
#
# OLX answers
# its own JSON API from a page already on olx.ro, so there is no feed to scroll,
# no hydration to wait out and no DOM lore. One paged API loop, objective
# filters, batched Stage-1 dedup, one CANDIDATES: line.
#
# It is a browser-use *payload*: pipe it on stdin, NOT `python3 <this>`.
#   export BU_CDP_URL="http://127.0.0.1:9222"
#   MAX_CANDIDATES=8 browser-use < harness/3ceasuri-import/scripts/olx-find-smartwatches.py
#
# Env:
#   PROJECT_ROOT    repo root (default: the Mac path below)
#   MAX_CANDIDATES  stop once this many qualify (default 8)
#   MAX_PAGES       API pages to walk before giving up (default 5, 40 ads each)
#   MIN_RON/MIN_EUR price floors (default 150 RON / 30 EUR — a real smartwatch
#                   under 150 lei is a strap, a clone, or a broken unit)
#   SNIPPET         chars of ad text per emitted candidate (default 180)
#   NO_DEDUP=1      skip the admin Stage-1 dedup pass
#   DEBUG_DROPS=1   also emit DROPPED: [{id,why,snip}]
#   OUT             candidates file (default .candidates-olx-smart.json)
#
# Emits: CANDIDATES: [...]   STATS: {...}   ERROR: {...}
#
# WHAT THIS SCRIPT DECIDES vs WHAT YOU DECIDE
#   Only objective filters — inactive ads, no price, price under the floor,
#   explicit replica wording, accessories (a strap is not a watch), blocklisted
#   sellers, already-imported ids. Everything requiring judgement (is this the
#   generation it claims? is it activation-locked? is the photo a stock render?)
#   stays with you: read the snippets and pick.
#
#   Business sellers are KEPT (user directive 2026-08-09) and flagged
#   `business: true` so you can triage shop stock by hand.
# =============================================================================
import os, re, json, time, sys

PROJECT_ROOT   = os.environ.get("PROJECT_ROOT", "/Users/stelian/.hermes/proiecte/3ceasuri")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts"))
import olx_api, admin_import, price_sanity

MAX_CANDIDATES = int(os.environ.get("MAX_CANDIDATES", "8"))
MAX_PAGES      = int(os.environ.get("MAX_PAGES", "5"))
MIN_RON        = int(os.environ.get("MIN_RON", "150"))
MIN_EUR        = int(os.environ.get("MIN_EUR", "30"))
SNIPPET        = int(os.environ.get("SNIPPET", "180"))
NO_DEDUP       = os.environ.get("NO_DEDUP", "") == "1"
DEBUG_DROPS    = os.environ.get("DEBUG_DROPS", "") == "1"
HARNESS        = os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts/import-watch.js")
OUT            = os.environ.get("OUT", os.path.join(PROJECT_ROOT,
                                "harness/3ceasuri-import/.candidates-olx-smart.json"))

def emit(tag, obj): print(tag + ": " + json.dumps(obj, ensure_ascii=False))
def die(msg):       emit("ERROR", {"msg": msg}); raise SystemExit(1)

bu = olx_api.bind(globals())
A  = admin_import.bind(globals())

# --- blocklisted sellers ----------------------------------------------------
BLOCK = {}
try:
    _bl = json.load(open(os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/references/seller-blocklist.json")))
    BLOCK = {str(s["id"]): s.get("name") for s in _bl.get("olx_sellers", [])}
except Exception:
    pass

try:
    BRAND_IDS = admin_import.load_brand_ids(HARNESS)
except Exception:
    BRAND_IDS = {}

# --- objective filters ------------------------------------------------------
REPLICA = re.compile(r"\breplic|\bclon|\bcopie\b|aaa\+|homage", re.I)
# A strap, a charger or an empty box is not a watch. Anchored on the phrasings
# that actually title such ads — "curea" alone would eat every ad that merely
# mentions the strap it comes with.
ACCESSORY = re.compile(
    r"^\s*(curea|curele|bratara|br[ăa][țt]ar[ăa]|husa|hus[ăa]|folie|incarcator|"
    r"[îi]nc[ăa]rc[ăa]tor|dock|stand|adaptor|carcasa|carcas[ăa]|protectie|protec[țt]ie)\b"
    r"|curea\s+(?:de\s+)?schimb|set\s+curele|doar\s+(?:cutia|curea|bratara|[îi]nc[ăa]rc[ăa]torul)|"
    r"folie\s+(?:de\s+)?protec|sticla\s+protec", re.I)
PHONE_RE = re.compile(r"(?:\+?40[\s.]?|0)7\d{2}[\s.]?\d{3}[\s.]?\d{3}")
# Stock ads: a plural title, or a seller quoting a price per model. Every signal is
# about watches specifically — a bare numeric range would kill any ad whose model
# number precedes its price ("Watch 4 Pro 48mm - 899 lei").
BULK_TITLE = re.compile(r"^\s*(ceasuri|smartwatch-uri|smartwatches)\b", re.I)
BULK = re.compile(r"pre[țt]uri\s+(?:cuprinse|[îi]ntre)|"
                  r"\blot(?:uri)?\s+(?:de\s+)?(?:ceas|smartwatch)|"
                  r"\bam[âa]ndou[ăa]\b|\bambele\s+ceasuri\b|"
                  r"pre[țt]\s+pe\s+bucat|\bbucata\s*[:\-]", re.I)
# A seller listing five watches quotes five prices. Only prices that could plausibly
# BE a watch count: shop ads pad their boilerplate with delivery and return fees, and
# counting those dropped a legitimate Amazfit on 2026-08-09 over "35 / 50 / 99 lei".
PRICE_MENTION = re.compile(r"\b(\d{2,6})\s*(?:lei|ron|eur|euro|€)\b", re.I)


def is_stock_listing(title, text):
    if BULK_TITLE.search(title) or BULK.search(text):
        return True
    quoted = {int(n) for n in PRICE_MENTION.findall(text)}
    return len([n for n in quoted if n >= MIN_RON]) >= 3
# A classic watch that wandered into the smartwatch category — flagged, not dropped.
CLASSIC_HINT = re.compile(r"\bautomat|\bmecanic|quartz\b|cronograf|vintage|"
                          r"\bcu\s+cheie\b|\bremontoar\b", re.I)

seen, candidates, dropped, samples = set(), {}, {}, []

def drop(reason, ad=None, snip=""):
    dropped[reason] = dropped.get(reason, 0) + 1
    if DEBUG_DROPS:
        samples.append({"id": (ad or {}).get("id"), "why": reason, "snip": snip[:110]})

def consider(ad):
    aid = str(ad.get("id") or "")
    if not aid or aid in seen:
        return
    seen.add(aid)

    title = ad.get("title") or ""
    desc  = olx_api.clean_description(ad.get("description"))
    text  = (title + "\n" + desc).strip()
    snip  = re.sub(r"\s+", " ", text)

    if ad.get("status") != "active":
        drop("not_active", ad, snip); return
    s = olx_api.seller(ad)
    if s["id"] and s["id"] in BLOCK:
        drop("blocklisted_seller", ad, snip); return
    if REPLICA.search(text):
        drop("replica", ad, snip); return
    if ACCESSORY.search(title):
        drop("accessory", ad, snip); return
    if is_stock_listing(title, text):
        drop("bulk_or_stock", ad, snip); return

    mapped = olx_api.map_params(ad)
    price, cur = mapped.get("price"), mapped.get("currency", "RON")
    if price is None:
        drop("no_price", ad, snip); return
    if (cur == "RON" and price < MIN_RON) or (cur == "EUR" and price < MIN_EUR):
        drop("price_below_floor", ad, snip); return

    # Never surface a suspiciously cheap listing (user directive 2026-08-09): a
    # replica seldom says "replica", the price is what gives it away.
    cheap = price_sanity.implausible_price(price, cur, olx_api.brand_param(ad), text)
    if cheap:
        drop("suspiciously_cheap", ad, snip); return

    brand_label = olx_api.brand_param(ad)
    brand = (admin_import.match_brand(brand_label, BRAND_IDS) if brand_label else None) \
            or admin_import.match_brand(title, BRAND_IDS)

    candidates[aid] = {
        "id": aid, "url": ad.get("url"), "title": title[:120],
        "price": price, "cur": cur,
        "brand": brand, "brand_label": brand_label,
        "new_brand": brand is None,
        "business": s["business"], "seller": s["id"], "seller_name": s["name"],
        "city": olx_api.location_str(ad),
        "photos": len(ad.get("photos") or []),
        "created": ad.get("created_time"),
        "looks_classic": bool(CLASSIC_HINT.search(text)),
        "text": PHONE_RE.sub("", text)[:1500],
        # The work queue lives in this file: the importer flips this to
        # imported/skipped/error, so "which watch is next" is a command and not
        # something the model has to remember across a context checkpoint.
        "status": "pending",
    }

# --- walk the category ------------------------------------------------------
olx_api.ensure_tab(bu, olx_api.CATEGORY_URL[olx_api.CATEGORY_SMARTWATCH])
total, pages = None, 0
for page in range(MAX_PAGES):
    offers, tot = olx_api.search(bu, olx_api.CATEGORY_SMARTWATCH,
                                 offset=page * 40, limit=40, price_from=MIN_RON)
    pages += 1
    if tot is not None:
        total = tot
    if not offers:
        if page == 0:
            die("OLX returned no offers for category 1943 — not logged in on olx.ro, "
                "blocked by the bot check, or the category id changed")
        break
    for ad in offers:
        consider(ad)
    if len(candidates) >= MAX_CANDIDATES:
        break
    time.sleep(1.5)

# --- Stage-1 dedup ----------------------------------------------------------
# One API page holds 40-50 ads, so checking every survivor before truncating meant
# ~50 admin page loads for the 8 candidates actually wanted. Check in order and
# stop at MAX_CANDIDATES confirmed survivors; the rest are never queried.
admin_total = None
ordered = list(candidates.values())
if candidates and not NO_DEDUP:
    at = new_tab("https://3ceasuri.ro/admin/watches/watch/")
    at = at["targetId"] if isinstance(at, dict) else at
    time.sleep(3)
    admin_total = admin_import.admin_count(A)
    kept = []
    for c in ordered:
        if len(kept) >= MAX_CANDIDATES:
            break
        n = admin_import.admin_count(A, c["id"])
        if n is None:
            c["dedup"] = "unverified"                    # never drop on a failed check
        elif n > 0:
            drop("already_imported", {"id": c["id"]}, c["title"]); continue
        kept.append(c)
    ordered = kept
    close_tab(at)
    olx_api.ensure_tab(bu)

ordered = ordered[:MAX_CANDIDATES]
try:
    with open(OUT, "w") as f:
        json.dump({"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": "olx",
                   "profile": "smart", "category": olx_api.CATEGORY_SMARTWATCH,
                   "candidates": ordered}, f, ensure_ascii=False, indent=1)
except Exception as e:
    emit("ERROR", {"msg": "could not write %s: %s" % (OUT, e)})

emit("CANDIDATES", [{k: c[k] for k in ("id", "price", "cur", "brand", "new_brand",
                                       "business", "seller_name", "photos", "looks_classic")}
                    | {"snip": re.sub(r"\s+", " ", c["text"])[:SNIPPET]}
                    for c in ordered])
if DEBUG_DROPS:
    emit("DROPPED", samples)
emit("STATS", {"candidates": len(ordered), "seen": len(seen), "pages": pages,
               "category_total": total, "dropped": dropped,
               "admin_total": admin_total, "out": OUT})
