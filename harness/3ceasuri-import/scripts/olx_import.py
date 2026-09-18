#!/usr/bin/env python3
# =============================================================================
# olx_import.py — the per-ad OLX import flow, shared by both profiles.
#
# olx-import-watch.py and olx-import-smartwatch.py were 95% identical: ~60 lines
# of real difference out of ~300. Every rule change had to be made twice and
# drift between them was a silent correctness bug, so the flow lives here once
# and the two payloads are wrappers that pick a profile.
#
# This module is NOT a browser-use payload. The payloads are; they call
#   olx_import.run("classic", globals())
# and `globals()` is what carries the CDP helpers (js, new_tab, close_tab,
# switch_tab, goto_url, list_tabs) that browser-use injects.
#
# The flow, in one process:
#   dedup -> GET /api/v1/offers/<id>/ -> blocklist -> map OLX params to DB enums
#   -> download photos -> EXTRACT_PROMPT (pass 1, writes NOTHING)
#   ... you fill the contract ...
#   -> validate -> repost dedup -> ensure brand -> inject harness -> importWatch
#   -> verify both banners -> read the record back (pass 2)
#
# Env:
#   AD_ID         numeric OLX ad id (the `id` from the matching discovery script)
#   PROJECT_ROOT  repo root (default: the Mac path below)
#   OVERRIDES     JSON object — the filled extraction contract, authoritative
#   CONFIRM       "1" = proceed past the REVIEW/SKIP gates
#   DRY_RUN       "1" = everything except the DB write
#   SKIP_PROMPT   "1" = import on the OLX params alone, no contract pass
#   FRESH         "1" = re-seed the contract draft even if one exists
#                       (it overwrites the model's answers -- say so on purpose)
#
# Emits: EXTRACT: SKIP: EXTRACT_PROMPT: INFER: REVIEW: NEW_BRAND: RESULT: ERROR:
#
# TWO PASSES, because YOU do the inference. OLX's structured params answer
# condition, materials, gender, style and price outright — what they never answer
# is which watch this is. For a classic watch the model, the movement and the
# reference come off the dial, the caseback and the era; for a smartwatch the
# model name and the generation come off the photos and the title. That is what
# pass 1 hands you.
#
# A filled contract is AUTHORITATIVE, including about what the ad does NOT say: a
# contract field left out of the answer is CLEARED, not kept from the OLX params.
# =============================================================================
import os
import re
import json
import sys

# --- the profile table -------------------------------------------------------
# Everything the classic and smart paths do differently, in one place. Anything
# not listed here is shared, and that is the point of the file.
PROFILES = {
    "classic": {
        "category_const": "CATEGORY_WATCHES",
        "script_name": "olx-import-watch.py",
        # classic also matches the brand in the body: a vintage seller often names
        # the brand only in the description, never in the title or the param.
        "brand_from_description": True,
        "forced": {},                     # nothing is forced
        "regex_baseline": True,           # diameter + reference + year + movement
        "misroute_check": False,          # the smart importer owns that gate
        "wall_clock_exempt": True,        # a wall clock IS imported, since 2026-08-09
        "not_a_watch_reason": "not a wristwatch and not a wall clock; "
                              "pass CONFIRM=1 to import anyway",
        "state_entry_category": True,
    },
    "smart": {
        "category_const": "CATEGORY_SMARTWATCH",
        "script_name": "olx-import-smartwatch.py",
        "brand_from_description": False,
        # A smartwatch listing is a smartwatch: these are not inferred, they are the
        # category. Leaving `movement` to the harness default would silently write
        # quartz.
        "forced": {"movement": "smart", "style": "smart",
                   "displayType": "smart", "category": "wrist"},
        "regex_baseline": False,          # only the diameter regex
        "misroute_check": True,
        "wall_clock_exempt": False,
        "not_a_watch_reason": "not a watch (accessory: strap/charger/case/box); "
                              "pass CONFIRM=1 to import anyway",
        "state_entry_category": False,
    },
}


def run(profile, g):
    """Import one OLX ad. `g` is the payload's globals(), carrying the CDP helpers.

    Returns None; exits through SystemExit exactly as the scripts always did.
    """
    conf = PROFILES.get(profile)
    if conf is None:
        raise ValueError("unknown profile %r (have: %s)" % (profile, ", ".join(sorted(PROFILES))))

    js         = g["js"]
    list_tabs  = g["list_tabs"]
    switch_tab = g["switch_tab"]

    PROJECT_ROOT = os.environ.get("PROJECT_ROOT", "/Users/stelian/.hermes/proiecte/3ceasuri")
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts"))
    import olx_api, admin_import, infer_fields, price_sanity, contract_draft

    AD_ID       = os.environ.get("AD_ID", "").strip()
    OVERRIDES   = json.loads(os.environ.get("OVERRIDES", "{}"))
    CONFIRM     = os.environ.get("CONFIRM", "") == "1"
    DRY_RUN     = os.environ.get("DRY_RUN", "") == "1"
    SKIP_PROMPT = os.environ.get("SKIP_PROMPT", "") == "1"
    HARNESS     = os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts/import-watch.js")
    PHOTO_DIR   = os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/.photos", "olx-%s" % AD_ID)

    def emit(tag, obj):
        print(tag + ": " + json.dumps(obj, ensure_ascii=False))

    def die(msg):
        emit("ERROR", {"ad_id": AD_ID, "msg": msg})
        raise SystemExit(1)

    RERUN = ("AD_ID=%s CONFIRM=1 OVERRIDES='{...}' browser-use < .../%s"
             % (AD_ID, conf["script_name"]))

    if not AD_ID or not AD_ID.isdigit():
        die("set AD_ID to a numeric OLX ad id")

    bu = olx_api.bind(g)
    A  = admin_import.bind(g)

    # --- resolve tabs --------------------------------------------------------
    tabs = list_tabs()
    ADMIN_TAB = os.environ.get("ADMIN_TAB") or admin_import.find_admin_tab(A, tabs)
    if not ADMIN_TAB:
        die("no admin tab found; open https://3ceasuri.ro/admin/watches/watch/add/ or pass ADMIN_TAB")
    OLX_TAB = olx_api.ensure_tab(
        bu, olx_api.CATEGORY_URL[getattr(olx_api, conf["category_const"])], tabs)

    # --- 0. dedup Stage 1: exact listing id ----------------------------------
    if admin_import.already_imported(A, AD_ID, return_to=OLX_TAB):
        emit("SKIP", {"ad_id": AD_ID, "reason": "already imported (external_listing_id match)"})
        raise SystemExit(0)

    # --- 1. read the ad ------------------------------------------------------
    switch_tab(OLX_TAB)
    ad = olx_api.offer(bu, AD_ID)
    if not ad:
        die("OLX ad %s did not load — removed, expired, or the bot check is in the way" % AD_ID)
    if ad.get("status") != "active":
        emit("SKIP", {"ad_id": AD_ID, "reason": "ad is not active (status=%s)" % ad.get("status")})
        raise SystemExit(0)

    seller = olx_api.seller(ad)
    try:
        _bl = json.load(open(os.path.join(PROJECT_ROOT,
                                          "harness/3ceasuri-import/references/seller-blocklist.json")))
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

    # --- 1c. suspiciously cheap = fake, never imported ------------------------
    # User directive 2026-08-09. This is a HARD skip, before the photos are even
    # fetched: CONFIRM does not wave it through, because the whole point is that the
    # listing looks fine apart from the price.
    _m = olx_api.map_params(ad)
    _cheap = price_sanity.implausible_price(_m.get("price"), _m.get("currency"),
                                            olx_api.brand_param(ad) or "", text)
    if _cheap and os.environ.get("ALLOW_CHEAP", "") != "1":
        emit("SKIP", {"ad_id": AD_ID, "reason": "suspiciously cheap — %s" % _cheap,
                      "price": _m.get("price"), "currency": _m.get("currency"),
                      "title": title[:80]})
        raise SystemExit(0)

    # --- 2. what OLX already answers -----------------------------------------
    brand_ids = admin_import.load_brand_ids(HARNESS)
    mapped = olx_api.map_params(ad)

    brand_label = olx_api.brand_param(ad)
    brand = (admin_import.match_brand(brand_label, brand_ids) if brand_label else None) \
            or admin_import.match_brand(title, brand_ids)
    if not brand and conf["brand_from_description"]:
        brand = admin_import.match_brand(description, brand_ids)
    brand = brand or (brand_label or None)

    data = dict(mapped)
    data.update(conf["forced"])
    if brand:
        data["brand"] = brand
    data["description"] = description

    # what the params never carry: size, and for a classic watch reference and era.
    # Baseline only — the contract overrules all three, and reliably has to (a
    # reference truncated at the first dot is worse than an empty field).
    m = re.search(r"(\d{2}(?:[.,]\d)?)\s*mm", text, re.I)
    if m:
        data["diameter"] = float(m.group(1).replace(",", "."))
    if conf["regex_baseline"]:
        # "referință" ends in ț+ă, so the old `erin[țt]a` never matched the whole word
        # and the capture started mid-word — a Rolex ad yielded reference "erin" on
        # 2026-08-09. A reference also always carries a digit; without that check the
        # capture happily swallows the next ordinary word.
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

    # --- 3. pass 1: hand the contract out ------------------------------------
    # A draft on disk means pass 1 already ran, so this is pass 2 even though no
    # OVERRIDES were passed -- that is the normal path now. Re-seeding on top of a
    # draft the model has already filled would silently destroy its answers, so it
    # takes an explicit FRESH=1.
    _draft_exists = (os.path.exists(contract_draft.draft_path(PROJECT_ROOT, AD_ID))
                     and os.environ.get("FRESH", "") != "1")
    if not OVERRIDES and not _draft_exists and not SKIP_PROMPT and not DRY_RUN:
        photos, failed = olx_api.download_photos(bu, images, PHOTO_DIR)
        # The phone is masked in the JSON and only rendered on click, so it costs a
        # page navigation — do it once here and show it with the contract. SOURCE_URL
        # always comes from the API: a hand-built /d/oferta/ slug lands on an
        # unrelated ad.
        phone, phone_status = olx_api.reveal_phone(bu, SOURCE_URL)
        if phone:
            known["phone"] = phone
        draft = contract_draft.build(data, profile)
        dpath = contract_draft.draft_path(PROJECT_ROOT, AD_ID)
        contract_draft.write(dpath, draft)
        emit("EXTRACT_PROMPT", {
            "ad_id": AD_ID,
            "draft": dpath,
            "todo": draft["_todo"],
            "prompt": infer_fields.build_prompt(text, brand_ids.keys(), profile=profile,
                                                known=known, source_noun="OLX ad",
                                                todo=draft["_todo"]),
            "photos": photos, "photos_failed": failed, "phone_status": phone_status,
            "rerun": "AD_ID=%s CONFIRM=1 browser-use < .../%s" % (AD_ID, conf["script_name"])})
        raise SystemExit(0)

    # --- 4. the filled contract is authoritative -----------------------------
    # The draft file is the contract. OVERRIDES stays supported and WINS, because a
    # human fixing one field from the shell should not have to edit the file.
    dpath = contract_draft.draft_path(PROJECT_ROOT, AD_ID)
    filled, problems = ({}, [])
    if os.path.exists(dpath):
        filled, problems = contract_draft.read(dpath, profile)
        if problems and not OVERRIDES:
            emit("REVIEW", {"ad_id": AD_ID, "draft": dpath,
                            "reasons": [{"code": "draft_invalid", "action": "fix",
                                         "message": p, "field": None} for p in problems]})
            raise SystemExit(0)
    if OVERRIDES:
        bad = infer_fields.validate(OVERRIDES)
        if bad:
            die("OVERRIDES are not valid DB values: " + "; ".join(bad))
        filled.update(OVERRIDES)

    # IS_CONTRACT is computed AFTER the merge on purpose: a human patching one field
    # with OVERRIDES='{"model":"X"}' on top of a full draft must still get the
    # full-contract clearing behaviour, and checking OVERRIDES alone would silently
    # downgrade it to a partial merge.
    IS_CONTRACT = bool(filled) and "is_wristwatch" in filled
    if IS_CONTRACT:
        for f in infer_fields.SCHEMA_FIELDS:
            if f not in filled:
                data.pop(f, None)
    data.update({k: v for k, v in filled.items() if k != "force"})

    if conf["misroute_check"]:
        # The category facts survive the clearing — a smartwatch stays a smartwatch
        # even when the answer forgets to restate them. An answer that actively
        # disagrees is a routing mistake, not a correction, so it stops instead.
        if data.get("movement") not in (None, "smart"):
            emit("REVIEW", {"ad_id": AD_ID, "reasons": [{
                "code": "misrouted_classic", "action": "skip", "field": "movement",
                "message": "movement=%r on the smartwatch importer — if this is a "
                           "mechanical/quartz watch, import it with olx-import-watch.py "
                           "instead" % data.get("movement")}]})
            if not CONFIRM:
                raise SystemExit(0)
    # setdefault is NOT enough here: the seeded draft carries every contract key, so
    # an unedited forced field arrives as an explicit None rather than being absent.
    # Restoring only on "key missing" would write movement=None for a smartwatch,
    # which is the silent-default failure this gate exists to prevent.
    for f, v in conf["forced"].items():
        if data.get(f) is None:
            data[f] = v

    # A wall clock IS imported (category="wall", since 2026-08-09). Pocket, mantel,
    # table and alarm clocks are not: is_wristwatch false with no category skips.
    _not_a_watch = filled.get("is_wristwatch") is False
    if _not_a_watch and conf["wall_clock_exempt"] and filled.get("category") == "wall":
        _not_a_watch = False
    if _not_a_watch and not CONFIRM:
        emit("SKIP", {"ad_id": AD_ID, "reason": conf["not_a_watch_reason"],
                      "notes": filled.get("notes")})
        raise SystemExit(0)
    if filled.get("is_bulk_lot") is True and not CONFIRM:
        emit("SKIP", {"ad_id": AD_ID, "reason": "bulk lot — one price, several watches; "
                                                "pass CONFIRM=1 to import anyway"})
        raise SystemExit(0)
    for k in ("is_wristwatch", "is_bulk_lot", "notes"):   # contract-only, not form fields
        data.pop(k, None)
    if data.get("category") is None:                     # same reason as the forced fields
        data["category"] = "wrist"

    # --- 5. provenance -------------------------------------------------------
    # The seller's city and phone are OLX metadata, not claims in the ad text — an
    # answer that omits them is silent, not authoritative, so they are restored rather
    # than cleared. The phone costs a page navigation (it is masked until clicked), so
    # it is only fetched when the contract did not already carry it.
    if not data.get("location"):
        data["location"] = olx_api.location_str(ad)
    data["county"] = olx_api.location_county(ad)
    data["city"] = olx_api.location_city(ad)
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

    # --- 6. confidence gate --------------------------------------------------
    # Each reason carries a code and an action. `fix` means the gate named exactly
    # what to supply and the answer is already in hand. `skip` means genuine doubt:
    # the runbook logs it and takes the next candidate. The agent never overrides a
    # gate — see §6 decision 5 in the determinism spec.
    review = []

    def _review(code, action, message, field=None):
        review.append({"code": code, "action": action, "message": message, "field": field})

    if not data.get("brand"):
        _review("brand_missing", "fix", "brand not inferred", "brand")
    elif data["brand"] not in brand_ids:
        _review("new_brand", "fix",
                "NEW brand '%s' — will be created in the DB" % data["brand"], "brand")
    if not data.get("model"):
        _review("model_missing", "fix", "model not inferred", "model")
    if data.get("price") is None:
        _review("price_missing", "fix", "price not inferred", "price")
    if profile == "classic":
        # movement is NOT optional in the DB, so the harness fills the gap with
        # 'quartz'. That guess mislabelled a 1970s Poljot once already — an ad that
        # never states its movement must be judged, not defaulted, and judging it
        # from nothing is exactly the doubt this gate exists to stop.
        if not data.get("movement"):
            _review("movement_missing", "skip",
                    "movement not stated in the ad (harness would default it to quartz)",
                    "movement")
        if data.get("movement") == "smart":
            _review("misrouted_smart", "skip",
                    "this is a smartwatch — import it with olx-import-smartwatch.py instead")
        if data.get("category") == "wall" and not data.get("caseMat"):
            _review("wall_no_material", "fix",
                    "wall clock without a case material (usually wood)", "caseMat")
    else:
        for f in ("connectivity", "compatibility"):
            if not data.get(f):
                _review("%s_missing" % f, "fix",
                        "smartwatch without %s (fill it in the draft)" % f, f)
    if len(images) < 2:
        _review("too_few_images", "skip", "only %d image(s) on the ad" % len(images))
    if len((data.get("description") or "").strip()) < 40:
        _review("thin_description", "skip",
                "description looks thin (%d chars)"
                % len((data.get("description") or "").strip()))
    if review and not CONFIRM and not DRY_RUN:
        emit("REVIEW", {"ad_id": AD_ID, "reasons": review, "images": len(images),
                        "inferred": {k: (v if k != "images" else len(v)) for k, v in data.items()},
                        "rerun": RERUN})
        raise SystemExit(0)

    # Hard requirements — CONFIRM cannot wave these through, the form would reject them.
    if not data.get("brand"):
        die('could not infer brand; pass OVERRIDES {"brand":"..."}')
    if not data.get("model"):
        die('could not infer model; pass OVERRIDES {"model":"..."}')
    if data.get("price") is None:
        die('could not infer price; pass OVERRIDES {"price":N,"currency":"RON|EUR"}')

    # --- 7. dedup Stage 2: the same watch relisted under a new ad id ---------
    repost = admin_import.find_repost(A, data, AD_ID, return_to=ADMIN_TAB)
    if repost:
        detail = dict(repost, ad_id=AD_ID, seller_id=seller["id"], seller_name=seller["name"])
        if repost["strong"]:
            emit("SKIP", dict(detail, reason="repost (%s match)" % repost["matched_via"]))
            raise SystemExit(0)
        if not CONFIRM:
            emit("REVIEW", dict(detail, reasons=[{
                "code": "weak_repost", "action": "skip", "field": None,
                "message": "possible repost: model '%s' is already on the site, but the "
                           "name is generic and the brand could not be confirmed"
                           % data.get("model")}]))
            raise SystemExit(0)

    # --- 8. ensure the brand exists ------------------------------------------
    switch_tab(ADMIN_TAB)
    try:
        new_brand_id, new_brand_info = admin_import.ensure_brand(A, data["brand"], brand_ids)
    except RuntimeError as e:
        die(str(e))
    if new_brand_info:
        emit("NEW_BRAND", new_brand_info)

    # --- 9. inject + import --------------------------------------------------
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

    # --- 10. verify ----------------------------------------------------------
    ok, banners, readback, readback_ok = admin_import.verify(A, AD_ID)
    state_entry = {"source": "olx", "id": AD_ID, "url": SOURCE_URL,
                   "brand": data["brand"], "model": data["model"],
                   "price": data["price"], "currency": data.get("currency"),
                   "images": len(images)}
    if conf["state_entry_category"]:
        state_entry["category"] = data.get("category")
    state_entry.update({"seller_id": seller["id"], "seller_name": seller["name"],
                        "business": seller["business"]})
    emit("RESULT", {"ad_id": AD_ID, "ok": bool(ok), "banners": banners,
                    "readback_ok": readback_ok, "expected_images": len(images),
                    "readback": readback,
                    "new_brand": ({"name": data["brand"], "id": new_brand_id} if new_brand_id else None),
                    "state_entry": state_entry})
