#!/usr/bin/env python3
# =============================================================================
# olx-import-watch.py — one-shot importer for a single OLX classic-watch ad.
#
# The OLX counterpart of import-post.py, for category 1677 (moda/ceasuri). It
# runs the whole per-watch flow in one browser-use process:
#   dedup -> GET /api/v1/offers/<id>/ -> blocklist -> map OLX params to DB enums
#   -> download photos -> EXTRACT_PROMPT (pass 1, writes NOTHING)
#   ... you fill the contract ...
#   -> validate -> repost dedup -> ensure brand -> inject harness -> importWatch
#   -> verify both banners -> read the record back (pass 2)
#
# It is a browser-use *payload*: pipe it on stdin, NOT `python3 <this>`.
#   export BU_CDP_URL="http://127.0.0.1:9222"
#   AD_ID=266008409 browser-use < .../olx-import-watch.py                 # pass 1
#   AD_ID=266008409 CONFIRM=1 OVERRIDES='{...}' browser-use < .../olx-import-watch.py
#
# Env:
#   AD_ID         numeric OLX ad id (the `id` from olx-find-watches.py)
#   PROJECT_ROOT  repo root (default: the Mac path below)
#   OVERRIDES     JSON object — the filled extraction contract, authoritative
#   CONFIRM       "1" = proceed past the REVIEW/SKIP gates
#   DRY_RUN       "1" = everything except the DB write
#   SKIP_PROMPT   "1" = import on the OLX params alone, no contract pass
#
# Emits: EXTRACT: SKIP: EXTRACT_PROMPT: INFER: REVIEW: NEW_BRAND: RESULT: ERROR:
#
# TWO PASSES, because YOU do the inference. OLX's structured params answer
# condition, case material, gender, style and price outright — what they never
# answer is which watch this is. The model, the movement and the reference come
# off the dial, the caseback and the era, and that is what pass 1 hands you.
#
# A filled contract is AUTHORITATIVE, including about what the ad does NOT say: a
# contract field left out of the answer is CLEARED, not kept from the OLX params.
# Restate what the "Known from OLX" block shows you.
# =============================================================================
import os, re, json, time, sys

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", "/Users/stelian/.hermes/proiecte/3ceasuri")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts"))
import olx_api, admin_import, infer_fields

AD_ID       = os.environ.get("AD_ID", "").strip()
OVERRIDES   = json.loads(os.environ.get("OVERRIDES", "{}"))
CONFIRM     = os.environ.get("CONFIRM", "") == "1"
DRY_RUN     = os.environ.get("DRY_RUN", "") == "1"
SKIP_PROMPT = os.environ.get("SKIP_PROMPT", "") == "1"
HARNESS     = os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts/import-watch.js")
PHOTO_DIR   = os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/.photos", "olx-%s" % AD_ID)

def emit(tag, obj): print(tag + ": " + json.dumps(obj, ensure_ascii=False))
def die(msg):       emit("ERROR", {"ad_id": AD_ID, "msg": msg}); raise SystemExit(1)

if not AD_ID or not AD_ID.isdigit():
    die("set AD_ID to a numeric OLX ad id")

bu = olx_api.bind(globals())
A  = admin_import.bind(globals())

# --- resolve tabs -----------------------------------------------------------
tabs = list_tabs()
ADMIN_TAB = os.environ.get("ADMIN_TAB") or admin_import.find_admin_tab(A, tabs)
if not ADMIN_TAB:
    die("no admin tab found; open https://3ceasuri.ro/admin/watches/watch/add/ or pass ADMIN_TAB")
OLX_TAB = olx_api.ensure_tab(bu, olx_api.CATEGORY_URL[olx_api.CATEGORY_WATCHES], tabs)

# --- 0. dedup Stage 1: exact listing id -------------------------------------
if admin_import.already_imported(A, AD_ID, return_to=OLX_TAB):
    emit("SKIP", {"ad_id": AD_ID, "reason": "already imported (external_listing_id match)"})
    raise SystemExit(0)

# --- 1. read the ad ---------------------------------------------------------
switch_tab(OLX_TAB)
ad = olx_api.offer(bu, AD_ID)
if not ad:
    die("OLX ad %s did not load — removed, expired, or the bot check is in the way" % AD_ID)
if ad.get("status") != "active":
    emit("SKIP", {"ad_id": AD_ID, "reason": "ad is not active (status=%s)" % ad.get("status")})
    raise SystemExit(0)

seller = olx_api.seller(ad)
try:
    _bl = json.load(open(os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/references/seller-blocklist.json")))
    _block = {str(s["id"]): s.get("name") for s in _bl.get("olx_sellers", [])}
except Exception:
    _block = {}
if seller["id"] and seller["id"] in _block:
    emit("SKIP", {"ad_id": AD_ID, "reason": "blocklisted seller",
                  "seller_id": seller["id"], "seller_name": _block.get(seller["id"])})
    raise SystemExit(0)

title = ad.get("title") or ""
description = olx_api.clean_description(ad.get("description"))
text = (title + "\n\n" + description).strip()
images = olx_api.photo_urls(ad)
SOURCE_URL = ad.get("url") or "https://www.olx.ro/d/oferta/-ID%s.html" % AD_ID

emit("EXTRACT", {"ad_id": AD_ID, "title": title[:100], "images": len(images),
                 "chars": len(text), "seller_id": seller["id"],
                 "seller_name": seller["name"], "business": seller["business"],
                 "city": olx_api.location_str(ad)})

# --- 2. what OLX already answers -------------------------------------------
brand_ids = admin_import.load_brand_ids(HARNESS)
mapped = olx_api.map_params(ad)

brand_label = olx_api.brand_param(ad)
brand = (admin_import.match_brand(brand_label, brand_ids) if brand_label else None) \
        or admin_import.match_brand(title, brand_ids) \
        or admin_import.match_brand(description, brand_ids) \
        or (brand_label or None)

data = dict(mapped)
if brand:
    data["brand"] = brand
data["description"] = description

# what the params never carry: size, reference, era. Baseline only — the contract
# overrules all three, and reliably has to (a reference truncated at the first dot
# is worse than an empty field).
m = re.search(r"(\d{2}(?:[.,]\d)?)\s*mm", text, re.I)
if m:
    data["diameter"] = float(m.group(1).replace(",", "."))
# "referință" ends in ț+ă, so the old `erin[țt]a` never matched the whole word and
# the capture started mid-word — a Rolex ad yielded reference "erin" on 2026-08-09.
# A reference also always carries a digit; without that check the capture happily
# swallows the next ordinary word.
m = re.search(r"(?:ref(?:erin[țt][ăa])?\.?\s*(?:nr\.?)?\s*[:\-]?\s*(?:este\s*)?)"
              r"([A-Z0-9][A-Z0-9\-\./ ]{2,20}[A-Z0-9])", text, re.I)
if m and any(c.isdigit() for c in m.group(1)):
    data["reference"] = m.group(1).strip(" .")
m = re.search(r"\b((?:19|20)\d{2})\b", text)
if m:
    data["year"] = int(m.group(1))
mv = None
low = text.lower()
for pat, val in ((r"automat|automatic", "automatic"),
                 (r"quartz|baterie", "quartz"),
                 (r"mecanic|manual|cheiț|cheit|remontoar", "manual")):
    if re.search(pat, low):
        mv = val
        break
if mv:
    data["movement"] = mv

known = {k: v for k, v in data.items()
         if k in infer_fields.SCHEMA_FIELDS and k != "description"}

# --- 3. pass 1: hand the contract out --------------------------------------
if not OVERRIDES and not SKIP_PROMPT and not DRY_RUN:
    photos, failed = olx_api.download_photos(bu, images, PHOTO_DIR)
    # The phone is masked in the JSON and only rendered on click, so it costs a page
    # navigation — do it once here and show it with the contract. SOURCE_URL always
    # comes from the API: a hand-built /d/oferta/ slug lands on an unrelated ad.
    phone, phone_status = olx_api.reveal_phone(bu, SOURCE_URL)
    if phone:
        known["phone"] = phone
    emit("EXTRACT_PROMPT", {
        "ad_id": AD_ID,
        "prompt": infer_fields.build_prompt(text, brand_ids.keys(), profile="classic",
                                            known=known, source_noun="OLX ad"),
        "photos": photos, "photos_failed": failed, "phone_status": phone_status,
        "rerun": "AD_ID=%s CONFIRM=1 OVERRIDES='{...}' browser-use < .../olx-import-watch.py" % AD_ID})
    raise SystemExit(0)

# --- 4. the filled contract is authoritative --------------------------------
problems = infer_fields.validate(OVERRIDES)
if problems:
    die("OVERRIDES are not valid DB values: " + "; ".join(problems))

IS_CONTRACT = "is_wristwatch" in OVERRIDES
if IS_CONTRACT:
    for f in infer_fields.SCHEMA_FIELDS:
        if f not in OVERRIDES:
            data.pop(f, None)
data.update({k: v for k, v in OVERRIDES.items() if k != "force"})

# A wall clock IS imported (category="wall", since 2026-08-09). Pocket, mantel,
# table and alarm clocks are not: is_wristwatch false with no category skips.
if (OVERRIDES.get("is_wristwatch") is False
        and OVERRIDES.get("category") != "wall" and not CONFIRM):
    emit("SKIP", {"ad_id": AD_ID,
                  "reason": "not a wristwatch and not a wall clock; pass CONFIRM=1 to import anyway",
                  "notes": OVERRIDES.get("notes")})
    raise SystemExit(0)
if OVERRIDES.get("is_bulk_lot") is True and not CONFIRM:
    emit("SKIP", {"ad_id": AD_ID, "reason": "bulk lot — one price, several watches; "
                                            "pass CONFIRM=1 to import anyway"})
    raise SystemExit(0)
for k in ("is_wristwatch", "is_bulk_lot", "notes"):     # contract-only, not form fields
    data.pop(k, None)
data.setdefault("category", "wrist")

# --- 5. provenance ----------------------------------------------------------
# The seller's city and phone are OLX metadata, not claims in the ad text — an
# answer that omits them is silent, not authoritative, so they are restored rather
# than cleared. The phone costs a page navigation (it is masked until clicked), so
# it is only fetched when the contract did not already carry it.
if not data.get("location"):
    data["location"] = olx_api.location_str(ad)
if not data.get("phone"):
    data["phone"] = olx_api.reveal_phone(bu, SOURCE_URL)[0] or None
data["images"] = images
data["sourceUrl"] = SOURCE_URL
data["source"] = "olx"
data["externalId"] = AD_ID
if seller["id"]:
    data["sellerId"] = seller["id"]
if seller["name"]:
    data["sellerName"] = seller["name"]

emit("INFER", {k: (v if k != "images" else len(v)) for k, v in data.items()})

# --- 6. confidence gate -----------------------------------------------------
review = []
if not data.get("brand"):                    review.append("brand not inferred")
elif data["brand"] not in brand_ids:         review.append("NEW brand '%s' — will be created in the DB" % data["brand"])
if not data.get("model"):                    review.append("model not inferred")
if data.get("price") is None:                review.append("price not inferred")
# movement is NOT optional in the DB, so the harness fills the gap with 'quartz'.
# That guess mislabelled a 1970s Poljot once already — an ad that never states its
# movement must be judged, not defaulted.
if not data.get("movement"):                 review.append("movement not stated in the ad "
                                                           "(harness would default it to quartz)")
if data.get("movement") == "smart":          review.append("this is a smartwatch — import it with "
                                                           "olx-import-smartwatch.py instead")
if data.get("category") == "wall" and not data.get("caseMat"):
                                             review.append("wall clock without a case material "
                                                           "(usually wood)")
if len(images) < 2:                          review.append("only %d image(s) on the ad" % len(images))
if len((data.get("description") or "").strip()) < 40:
                                             review.append("description looks thin (%d chars)"
                                                           % len((data.get("description") or "").strip()))
if review and not CONFIRM and not DRY_RUN:
    emit("REVIEW", {"ad_id": AD_ID, "reasons": review, "images": len(images),
                    "inferred": {k: (v if k != "images" else len(v)) for k, v in data.items()},
                    "rerun": "AD_ID=%s CONFIRM=1 OVERRIDES='{...}' browser-use < .../olx-import-watch.py" % AD_ID})
    raise SystemExit(0)

# Hard requirements — CONFIRM cannot wave these through, the form would reject them.
if not data.get("brand"): die('could not infer brand; pass OVERRIDES {"brand":"..."}')
if not data.get("model"): die('could not infer model; pass OVERRIDES {"model":"..."}')
if data.get("price") is None: die('could not infer price; pass OVERRIDES {"price":N,"currency":"RON|EUR"}')

# --- 7. dedup Stage 2: the same watch relisted under a new ad id ------------
repost = admin_import.find_repost(A, data, AD_ID, return_to=ADMIN_TAB)
if repost:
    detail = dict(repost, ad_id=AD_ID, seller_id=seller["id"], seller_name=seller["name"])
    if repost["strong"]:
        emit("SKIP", dict(detail, reason="repost (%s match)" % repost["matched_via"]))
        raise SystemExit(0)
    if not CONFIRM:
        emit("REVIEW", dict(detail, reasons=[
            "possible repost: model '%s' is already on the site, but the name is generic "
            "and the brand could not be confirmed — check, then CONFIRM=1 to import anyway"
            % data.get("model")]))
        raise SystemExit(0)

# --- 8. ensure the brand exists ---------------------------------------------
switch_tab(ADMIN_TAB)
try:
    new_brand_id, new_brand_info = admin_import.ensure_brand(A, data["brand"], brand_ids)
except RuntimeError as e:
    die(str(e))
if new_brand_info:
    emit("NEW_BRAND", new_brand_info)

# --- 9. inject + import -----------------------------------------------------
ADMIN_TAB = admin_import.find_admin_tab(A) or ADMIN_TAB
switch_tab(ADMIN_TAB)
try:
    admin_import.inject_harness(A, HARNESS, data["brand"], new_brand_id)
except RuntimeError as e:
    die(str(e))

if DRY_RUN:
    emit("RESULT", {"ad_id": AD_ID, "dry_run": True, "images": len(images),
                    "would_import": {k: (v if k != "images" else len(v)) for k, v in data.items()}})
    raise SystemExit(0)

admin_import.submit(A, data, len(images))

# --- 10. verify -------------------------------------------------------------
ok, banners, readback, readback_ok = admin_import.verify(A, AD_ID)
emit("RESULT", {"ad_id": AD_ID, "ok": bool(ok), "banners": banners,
                "readback_ok": readback_ok, "expected_images": len(images),
                "readback": readback,
                "new_brand": ({"name": data["brand"], "id": new_brand_id} if new_brand_id else None),
                "state_entry": {"source": "olx", "id": AD_ID, "url": SOURCE_URL,
                                "brand": data["brand"], "model": data["model"],
                                "price": data["price"], "currency": data.get("currency"),
                                "images": len(images), "category": data.get("category"),
                                "seller_id": seller["id"], "seller_name": seller["name"],
                                "business": seller["business"]}})
