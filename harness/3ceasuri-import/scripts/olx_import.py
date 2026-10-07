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
#   -> validate -> repost dedup -> import-json when the admin endpoints are
#   deployed (one POST; the server answers with what it saved), else ensure brand
#   -> inject harness -> importWatch -> verify both banners -> read the record
#   back (pass 2)
#
# Env:
#   AD_ID         numeric OLX ad id (the `id` from the matching discovery script)
#   PROJECT_ROOT  repo root (default: the Mac path below)
#   OVERRIDES     JSON object — the filled extraction contract, authoritative
#   CONFIRM       "1" = set on every pass 2. Waives ONLY the weak_repost review; it
#                       never waives not_a_watch, bulk_lot, the misroute or the
#                       confidence gate, a cheap fake, or a missing brand/model/price
#   DRY_RUN       "1" = everything except the DB write
#   SKIP_PROMPT   "1" = import on the OLX params alone, no contract pass
#   FRESH         "1" = re-seed the contract draft even if one exists
#                       (it overwrites the model's answers -- say so on purpose)
#   API           "off" = never use the admin's JSON endpoints: the DOM path only
#   FORCE_IMAGE_UPLOAD "1" = import-json with the photos uploaded as files, not
#                       fetched by the server (tests the 422 fallback on purpose)
#
# Emits: EXTRACT: SKIP: EXTRACT_PROMPT: INFER: REVIEW: NEW_BRAND: NEW_MODEL: RESULT: ERROR: WARN:
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
import time

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
        "not_a_watch_reason": "not a wristwatch and not a wall clock",
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
        "not_a_watch_reason": "not a watch (accessory: strap/charger/case/box)",
        "state_entry_category": False,
    },
}



# The watch's condition, not its movement: "atât estetic cât și mecanic", "mecanic și
# estetic impecabil". Removed before the movement seed reads the text.
_CONDITION_MECANIC = re.compile(
    r"(?:estetic|vizual|optic)\w*\W+(?:\w+\W+){0,3}?mecanic\w*|"
    r"mecanic\w*\W+(?:\w+\W+){0,3}?(?:estetic|vizual|optic)\w*")

# --- the description stays the seller's (user directive 2026-10-04) ----------
# The 2026-10-03 "rewrite it, 400-1000 chars" rule produced listings in a third
# voice: "Vânzătorul precizează că funcționează foarte bine", "Fotografiile prezintă
# ceasul în cutie, iar în anunț sunt disponibile și alte imagini" — on a 178-char ad
# that said none of it that way. The listing text is the seller's own, lightly
# corrected, and these two checks are what keep it that way.

# Talking ABOUT the seller, the ad or the photos is never the author's voice. It is
# flagged even when the seller wrote it ("Fotografiile sunt reale") — user directive.
DESCRIPTION_META_RE = re.compile(
    r"\b(vanzat\w*|anunt\w*|fotografi\w*|imagin\w*|poz(a|e|ele|ei))\b")
# Words of ours that the seller never used. A light edit adds a handful (a brand the
# seller left out, a connective, "oțel" for "Stainless Steel"); a rewrite adds dozens
# (44-70 on the 2026-10-04 listings, at 11-41% of the text being the seller's).
DESCRIPTION_MAX_NEW_WORDS = 10
DESCRIPTION_MIN_SELLER_SHARE = 0.75


def _plain(text):
    """Lowercase, diacritics off: "Funcționează" and "functioneaza" are one word."""
    import unicodedata
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _words(text):
    return [w for w in re.findall(r"[a-z0-9]+", _plain(text)) if len(w) >= 3]


def _same_word(a, b):
    """Romanian inflects at the end (cutie/cutia, încărcător/încărcătorul), so two
    words match when they differ only in their last two letters."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return a == b or n >= max(3, min(len(a), len(b)) - 2)


def description_drift(description, source):
    """(words of ours the seller never used, share of the text that is the seller's)."""
    vocab = set(_words(source))
    words = _words(description)
    new = [w for w in words if not any(_same_word(w, v) for v in vocab)]
    return new, (1 - float(len(new)) / len(words)) if words else 1.0


def confidence_review(profile, data, images, brand_ids, seller_text=None, seller_title=None):
    """The confidence gate, as a pure function. Returns a list of reasons.

    Each reason carries a code and an action. `fix` means the gate named exactly
    what to supply and the answer is already in hand. `skip` means genuine doubt:
    the runbook logs it and takes the next candidate. The agent never overrides a
    gate — see §6 decision 5 in the determinism spec.

    It is out here, rather than inside run(), so the offline replay eval scores the
    SAME gate the importer runs instead of a copy of it that can drift.

    `seller_text` is the cleaned OLX description and `seller_title` the ad's title.
    The listing text is the seller's own, lightly corrected (user directive
    2026-10-04), so three things are a `fix`, each one edit away: the seeded text
    back untouched, a text that talks about the seller/ad/photos, and a text that is
    mostly not the seller's words.
    """
    review = []

    def _review(code, action, message, field=None):
        review.append({"code": code, "action": action, "message": message, "field": field})

    # A brand missing from BRAND_IDS is NOT a gate: no draft edit can make a new brand
    # old, so it was a "fix" that only CONFIRM=1 ever got past. ensure_brand() creates
    # it and NEW_BRAND: hands off to the new-brand procedure.
    if not data.get("brand"):
        _review("brand_missing", "fix", "brand not inferred", "brand")
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
    ours = data.get("description") or ""
    if seller_text and " ".join(ours.split()) == " ".join(seller_text.split()):
        _review("description_unedited", "fix",
                "description is the seller's text untouched - correct it lightly "
                "(diacritics, typos, punctuation) and drop price/contact, keeping their words",
                "description")
    elif seller_text:
        meta = sorted({m.group(0) for m in DESCRIPTION_META_RE.finditer(_plain(ours))})
        if meta:
            _review("description_meta", "fix",
                    "description talks about the seller/ad/photos (%s) - remove those "
                    "sentences; the text is the seller's own voice" % ", ".join(meta),
                    "description")
        new, share = description_drift(ours, "\n".join(
            [seller_title or "", seller_text] +
            [str(data.get(k) or "") for k in ("brand", "model", "variant", "reference")]))
        if len(new) > DESCRIPTION_MAX_NEW_WORDS and share < DESCRIPTION_MIN_SELLER_SHARE:
            _review("description_drifted", "fix",
                    "description is rewritten, only %d%% of it is the seller's words "
                    "(%d new: %s) - start again from their text and correct it lightly"
                    % (round(share * 100), len(new), " ".join(new[:12])),
                    "description")
    if len((data.get("description") or "").strip()) < 40:
        _review("thin_description", "skip",
                "description looks thin (%d chars)"
                % len((data.get("description") or "").strip()))
    return review


# --- import-json answers, as the DOM path's shapes -----------------------------
# history.jsonl, olx-step and the import-verify-state skill read ONE RESULT: shape,
# whichever path saved the watch. These turn the server's answer into it.
_READBACK_KEYS = ("brandId", "price", "currency", "ref", "diameter", "source", "extId",
                  "sellerId", "sellerName", "videoUrl", "desc", "imgs")


def readback_from_saved(resp):
    """A 201's `saved` as the change-form readback: strings like the form's inputs,
    and only the first 120 chars of the description (history.jsonl logs it)."""
    saved = resp.get("saved") or {}

    def s(k):
        return None if saved.get(k) is None else str(saved[k])
    brand_id = (resp.get("brand") or {}).get("id")
    return {"brandId": None if brand_id is None else str(brand_id),
            "price": s("price"), "currency": s("currency"), "ref": s("reference_number"),
            "diameter": s("case_diameter_mm"), "source": s("source"),
            "extId": s("external_listing_id"), "sellerId": s("seller_id"),
            "sellerName": s("seller_name"), "videoUrl": s("video_url"),
            "desc": (saved.get("description") or "")[:120], "imgs": resp.get("pictures")}


def readback_from_lookup(row, ad_id):
    """What a lookup/ row proves about a watch whose import-json answer was lost."""
    rb = dict.fromkeys(_READBACK_KEYS)
    rb.update({"source": row.get("source"), "extId": str(ad_id),
               "sellerId": row.get("seller_id"), "imgs": row.get("pictures")})
    return rb


# How many of the brand's models an unknown_model fix lists before "and N more".
MODELS_IN_FIX = 80


def server_reasons(errors, models=None):
    """import-json's 400 field errors as REVIEW reasons.

    `fix` only for a contract key, which the agent can answer with `finish`. An error
    on a field the harness fills (sourceUrl, sellerId, county...) or a non-field
    error has no answer there — a `fix` would loop on BAD_ANSWER — so it is `skip`.

    A model the brand does not have comes with `models`, the brand's list: that is an
    `unknown_model` fix with both ways out — a listed name, or new_model=true.
    """
    import site_api
    reasons = []
    for field, msgs in (errors or {}).items():
        text = "; ".join(str(m) for m in (msgs if isinstance(msgs, list) else [msgs]))
        if field == "model_name" and models is not None:
            shown = ", ".join(models[:MODELS_IN_FIX]) or "(none yet)"
            if len(models) > MODELS_IN_FIX:
                shown += " and %d more" % (len(models) - MODELS_IN_FIX)
            reasons.append({"code": "unknown_model", "action": "fix", "field": "model",
                            "message": "the site refused the model: %s. The brand's models: "
                                       "%s. Use one of them as `model` and put the rest of "
                                       "the name in `variant`; only for a line the brand "
                                       "really makes and the site lacks, keep it and answer "
                                       "new_model=true" % (text, shown)})
            continue
        key = site_api.from_model_field(field)
        reasons.append({"code": "server_invalid",
                        "action": "fix" if site_api.fixable(key) else "skip",
                        "field": key or (None if field == "__all__" else field),
                        "message": "the site refused %s: %s" % (key or field, text)})
    return reasons


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

    PROJECT_ROOT = os.environ.get("PROJECT_ROOT") or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../.."))
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts"))
    import olx_api, admin_import, infer_fields, price_sanity, contract_draft
    import candidates, site_api, photo_dedup

    AD_ID       = os.environ.get("AD_ID", "").strip()
    OVERRIDES   = json.loads(os.environ.get("OVERRIDES", "{}"))
    CONFIRM     = os.environ.get("CONFIRM", "") == "1"
    DRY_RUN     = os.environ.get("DRY_RUN", "") == "1"
    SKIP_PROMPT = os.environ.get("SKIP_PROMPT", "") == "1"
    HARNESS     = os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/scripts/import-watch.js")
    # PHOTO_ROOT exists for the offline tests: their fixtures carry REAL ad ids, and
    # writing stub photos to the real folders overwrote imported ads' photos with
    # 600-byte junk (found 2026-10-07, after the .contracts wipe of 2026-10-04).
    PHOTO_DIR   = os.path.join(os.environ.get("PHOTO_ROOT") or
                               os.path.join(PROJECT_ROOT, "harness/3ceasuri-import/.photos"),
                               "olx-%s" % AD_ID)
    # SHOP_CARDS exists for the offline tests, like PHOTO_ROOT: the list is committed.
    SHOP_CARDS  = os.environ.get("SHOP_CARDS") or photo_dedup.CARDS_FILE

    def emit(tag, obj):
        print(tag + ": " + json.dumps(obj, ensure_ascii=False))

    CANDIDATES_FILE = os.environ.get("CANDIDATES_FILE", "").strip()

    def _mark(status, reason=None):
        """Record this ad's outcome in the work queue, when one was passed.

        Never fatal: a bookkeeping failure must not lose an import that succeeded.
        """
        if not CANDIDATES_FILE:
            return
        try:
            candidates.mark(CANDIDATES_FILE, AD_ID, status, reason)
        except Exception as e:
            emit("WARN", {"ad_id": AD_ID, "msg": "could not mark the queue: %s" % e})

    def skip(reason_code, payload):
        """Emit SKIP:, mark the queue, and stop. One exit, so the two cannot drift."""
        _mark("skipped", reason_code)
        emit("SKIP", dict(payload, ad_id=AD_ID))
        raise SystemExit(0)

    def review_stop(payload):
        """Emit REVIEW: and stop.

        A reason with action=skip ends the watch (§6 decision 5: the agent never
        overrides a gate), so the queue records it and moves on. A review whose
        reasons are ALL action=fix stays pending -- the gate named what to supply
        and the next pass will answer it.
        """
        blocking = [r for r in payload.get("reasons", [])
                    if isinstance(r, dict) and r.get("action") == "skip"]
        if blocking:
            _mark("skipped", blocking[0].get("code"))
        emit("REVIEW", dict(payload, ad_id=AD_ID))
        raise SystemExit(0)

    def die(msg):
        _mark("error", msg)
        emit("ERROR", {"ad_id": AD_ID, "msg": msg})
        raise SystemExit(1)

    def drop_shop_cards(images, numbers):
        """(images, numbers, card files) without the photos that are a shop's cards.

        User directive 2026-10-07: a seller's logo card, storefront or "why buy from
        us" panel is never imported -- it advertises another business and says nothing
        about the watch (photo_dedup.shop_cards). `numbers` keeps each URL's file
        number, so the local copies still match their URLs once some are gone.
        """
        cards = photo_dedup.shop_cards(os.path.dirname(PHOTO_DIR), AD_ID, SHOP_CARDS,
                                       seller=seller["name"])
        if cards:
            emit("CARDS", {"ad_id": AD_ID, "dropped": sorted(cards)})
        drop = {int(f.split(".")[0]) for f in cards}
        kept = [(n, u) for n, u in zip(numbers, images) if n not in drop]
        return [u for _, u in kept], [n for n, _ in kept], sorted(cards)

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

    # A lost admin session is never "not imported" and never "API not deployed".
    LOST = "admin session lost — sign in to 3ceasuri.ro/admin"

    # --- 0. dedup Stage 1: exact listing id ----------------------------------
    try:
        _dup = admin_import.already_imported(A, AD_ID, return_to=OLX_TAB)
    except site_api.SessionLost:
        die(LOST)
    if _dup:
        skip("already_imported", {"reason": "already imported (external_listing_id match)"})

    # --- 1. read the ad ------------------------------------------------------
    switch_tab(OLX_TAB)
    ad = olx_api.offer(bu, AD_ID)
    if not ad:
        die("OLX ad %s did not load — removed, expired, or the bot check is in the way" % AD_ID)
    if ad.get("status") != "active":
        skip("not_active", {"reason": "ad is not active (status=%s)" % ad.get("status")})

    seller = olx_api.seller(ad)
    try:
        _bl = json.load(open(os.path.join(PROJECT_ROOT,
                                          "harness/3ceasuri-import/references/seller-blocklist.json")))
        _block = {str(s["id"]): s.get("name") for s in _bl.get("olx_sellers", [])}
    except Exception:
        _block = {}
    if seller["id"] and seller["id"] in _block:
        skip("blocklisted_seller", {"reason": "blocklisted seller",
                                    "seller_id": seller["id"],
                                    "seller_name": _block.get(seller["id"])})

    title = ad.get("title") or ""
    description = olx_api.clean_description(ad.get("description"))
    text = (title + "\n\n" + description).strip()
    images = olx_api.photo_urls(ad)
    photo_nums = list(range(1, len(images) + 1))    # each URL's NN.jpg, see drop_shop_cards
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
        skip("suspiciously_cheap", {"reason": "suspiciously cheap — %s" % _cheap,
                                    "price": _m.get("price"), "currency": _m.get("currency"),
                                    "title": title[:80]})

    # --- 1d. a days-old account selling an expensive watch = scam ------------
    _young = price_sanity.new_seller_risk(_m.get("price"), _m.get("currency"),
                                          (ad.get("user") or {}).get("created"))
    if _young and os.environ.get("ALLOW_NEW_SELLER", "") != "1":
        skip("new_seller_expensive", {"reason": "new_seller_expensive: " + _young,
                                      "seller_id": seller["id"],
                                      "account_created": (ad.get("user") or {}).get("created"),
                                      "title": title[:80]})

    # --- 1e. two watches, each with its own price ----------------------------
    if olx_api.separately_priced(text):
        skip("bulk_lot", {"reason": "bulk_lot: the ad quotes a separate price per watch",
                          "title": title[:80]})

    # --- 2. what OLX already answers -----------------------------------------
    brand_ids = admin_import.load_brand_ids(HARNESS)
    mapped = olx_api.map_params(ad)

    brand_label = olx_api.brand_param(ad)
    brand = (admin_import.match_brand(brand_label, brand_ids) if brand_label else None) \
            or admin_import.match_brand(title, brand_ids)
    # A known brand in the OLX param or the title is settled. Anything weaker is only
    # a guess the model must confirm: a description match can be a brand the seller
    # says the watch is NOT ("Nu Citizen, Seiko, Breitling..."), and an unknown label
    # would create a new brand row in the DB.
    brand_settled = bool(brand)
    if not brand and conf["brand_from_description"]:
        brand = admin_import.match_brand(olx_api.strip_exchange(description), brand_ids)
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
        # "Condiție impecabilă, atât estetic cât și mecanic" is the watch's condition,
        # not its movement -- it seeded a Tudor 1926 automatic as manual (309992586,
        # 2026-10-07).
        low = _CONDITION_MECANIC.sub(" ", olx_api.strip_exchange(text).lower())
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
        # The two confidence-gate reasons that depend only on the ad, never on the
        # contract. Pass 2 would stop on them anyway -- deciding here saves the photo
        # download, the phone reveal and the model's whole draft edit. Same thresholds
        # as confidence_review(), which still runs in pass 2.
        if len(images) < 2:
            skip("too_few_images", {"reason": "too_few_images: only %d image(s) on the ad"
                                              % len(images)})
        if len(description.strip()) < 40:
            skip("thin_description", {"reason": "thin_description: %d chars"
                                                % len(description.strip())})
        photos, failed = olx_api.download_photos(bu, images, PHOTO_DIR)
        # Shop cards go before anything counts or compares the photos: the model never
        # sees them, and two of a shop's watches never look like one relisted.
        images, photo_nums, cards = drop_shop_cards(images, photo_nums)
        photos = [p for p in photos if os.path.basename(p) not in cards]
        if len(images) < 2:
            skip("too_few_images", {"reason": "too_few_images: only %d image(s) on the ad "
                                              "once %d shop card(s) are dropped"
                                              % (len(images), len(cards))})
        # The same photo files as an ad already imported = the same watch relisted,
        # by the same seller or another account (photo_dedup.py). Decided before the
        # phone reveal and the draft, which it would make wasted work.
        dup = photo_dedup.find_duplicate(os.path.dirname(PHOTO_DIR), AD_ID,
                                         os.path.join(PROJECT_ROOT, "history.jsonl"),
                                         ignore=set(photo_dedup.load_cards(SHOP_CARDS)))
        if dup and os.environ.get("ALLOW_DUPLICATE_PHOTOS", "") != "1":
            skip("duplicate_photos", {"reason": "duplicate_photos: %d photo(s) identical to "
                                                "imported ad %s" % (dup[1], dup[0]),
                                      "duplicate_of": dup[0], "title": title[:80]})
        # The phone is masked in the JSON and only rendered on click, so it costs a
        # page navigation — do it once here and show it with the contract. SOURCE_URL
        # always comes from the API: a hand-built /d/oferta/ slug lands on an
        # unrelated ad.
        phone, phone_status = olx_api.reveal_phone(bu, SOURCE_URL)
        if phone:
            known["phone"] = phone
            data["phone"] = phone      # into the draft, or pass 2 reveals it all over again
        # The brand's models on the site, so `model` reuses one of them: the site refuses
        # a model its brand does not have. Only for a settled brand -- a guessed one
        # would steer the model to the wrong maker's list.
        models = None
        if brand_settled:
            try:
                models = site_api.brand_models(A, brand, return_to=OLX_TAB)
            except site_api.SessionLost:
                die(LOST)
        draft = contract_draft.build(data, profile)
        if not brand_settled and "brand" not in draft["_todo"]:
            draft["_todo"].insert(0, "brand")
        dpath = contract_draft.draft_path(PROJECT_ROOT, AD_ID)
        contract_draft.write(dpath, draft)
        emit("EXTRACT_PROMPT", {
            "ad_id": AD_ID,
            "draft": dpath,
            "todo": draft["_todo"],
            "prompt": infer_fields.build_prompt(text, brand_ids.keys(), profile=profile,
                                                known=known, source_noun="OLX ad",
                                                todo=draft["_todo"], brand=brand,
                                                models=models),
            "models": models,
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
            review_stop({"draft": dpath,
                         "reasons": [{"code": "draft_invalid", "action": "fix",
                                      "message": p, "field": None} for p in problems]})
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
    # User directive 2026-09-22: "Alt brand" is never a stored brand -- an item with no
    # maker is "Fără marcă". Applied to the FINAL answer only: OLX's "Alt brand" label
    # means "a brand OLX does not list", so the real maker is still asked for first.
    if olx_api.norm_label(data.get("brand")) in ("alt brand", "alta marca", "alte branduri",
                                                  "fara brand", "no brand", "noname",
                                                  "no name", "generic"):
        data["brand"] = "Fără marcă"
    # Contact details never reach the public listing, whoever wrote the text.
    if data.get("description"):
        data["description"] = olx_api.strip_phones(data["description"])

    if conf["misroute_check"]:
        # The category facts survive the clearing — a smartwatch stays a smartwatch
        # even when the answer forgets to restate them. An answer that actively
        # disagrees is a routing mistake, not a correction, so it stops instead.
        if data.get("movement") not in (None, "smart"):
            _misroute = {"reasons": [{
                "code": "misrouted_classic", "action": "skip", "field": "movement",
                "message": "movement=%r on the smartwatch importer — if this is a "
                           "mechanical/quartz watch, import it with olx-import-watch.py "
                           "instead" % data.get("movement")}]}
            review_stop(_misroute)
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
    # Neither of these is waived by CONFIRM: every pass 2 sets it, so a CONFIRM guard
    # made both dead code (ad 309588599 imported with is_wristwatch=false, 2026-09-20).
    # A human who disagrees edits the verdict in the contract, not the gate.
    if _not_a_watch:
        skip("not_a_watch", {"reason": conf["not_a_watch_reason"],
                             "notes": filled.get("notes")})
    if filled.get("is_bulk_lot") is True:
        skip("bulk_lot", {"reason": "bulk lot — one price, several watches"})
    # The agent's word that the model is new to the site: added ahead in 7a, never sent.
    new_model = data.pop("new_model", None) is True
    for k in ("is_wristwatch", "is_bulk_lot", "notes"):   # contract-only, not form fields
        data.pop(k, None)
    if data.get("category") is None:                     # same reason as the forced fields
        data["category"] = "wrist"

    # --- 5. provenance -------------------------------------------------------
    # The seller's județ, city and phone are OLX metadata, not claims in the ad text —
    # an answer that omits them is silent, not authoritative, so they are restored
    # rather than cleared. The phone costs a page navigation (it is masked until
    # clicked), so it is only fetched when the contract did not already carry it.
    # No free-text `location`: the site writes the place from county/city itself
    # ("Voluntari, jud. Ilfov"), so it is not sent (2026-10-05).
    data.pop("location", None)
    data["county"] = olx_api.location_county(ad)
    data["city"] = olx_api.location_city(ad)
    if not data.get("phone"):
        data["phone"] = olx_api.reveal_phone(bu, SOURCE_URL)[0] or None
    # Pass 2 read the ad again, so its photo list is whole again: drop the shop cards
    # once more, from the copies pass 1 saved (fetched now if this machine has none).
    if not all(os.path.exists(os.path.join(PHOTO_DIR, "%02d.jpg" % n)) for n in photo_nums):
        switch_tab(OLX_TAB)
        olx_api.download_photos(bu, images, PHOTO_DIR, photo_nums)
    images, photo_nums, _ = drop_shop_cards(images, photo_nums)
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
    review = confidence_review(profile, data, images, brand_ids,
                               seller_text=description if IS_CONTRACT else None,
                               seller_title=title if IS_CONTRACT else None)
    # Not waived by CONFIRM either (§6 decision 5: nobody overrides a gate).
    if review and not DRY_RUN:
        review_stop({"reasons": review, "images": len(images),
                     "inferred": {k: (v if k != "images" else len(v)) for k, v in data.items()},
                     "rerun": RERUN})

    # Hard requirements — CONFIRM cannot wave these through, the form would reject them.
    if not data.get("brand"):
        die('could not infer brand; pass OVERRIDES {"brand":"..."}')
    if not data.get("model"):
        die('could not infer model; pass OVERRIDES {"model":"..."}')
    if data.get("price") is None:
        die('could not infer price; pass OVERRIDES {"price":N,"currency":"RON|EUR"}')

    # --- 7. dedup Stage 2: the same watch relisted under a new ad id ---------
    try:
        repost = admin_import.find_repost(A, data, AD_ID, return_to=ADMIN_TAB)
    except site_api.SessionLost:
        die(LOST)
    if repost:
        detail = dict(repost, ad_id=AD_ID, seller_id=seller["id"], seller_name=seller["name"])
        if repost["strong"]:
            skip("repost", dict(detail, reason="repost (%s match)" % repost["matched_via"]))
        if not CONFIRM:
            review_stop(dict(detail, reasons=[{
                "code": "weak_repost", "action": "skip", "field": None,
                "message": "possible repost: model '%s' is already on the site, but the "
                           "name is generic and the brand could not be confirmed"
                           % data.get("model")}]))

    def report(ok, banners, readback, readback_ok, new_brand):
        """The RESULT: line, one shape for both write paths."""
        state_entry = {"source": "olx", "id": AD_ID, "url": SOURCE_URL,
                       "brand": data["brand"], "model": data["model"],
                       "price": data["price"], "currency": data.get("currency"),
                       "images": len(images)}
        if conf["state_entry_category"]:
            state_entry["category"] = data.get("category")
        state_entry.update({"seller_id": seller["id"], "seller_name": seller["name"],
                            "business": seller["business"]})
        _mark("imported" if ok else "error", None if ok else "import not verified")
        # Saved != correct: the harness once replaced every description with a spec
        # template and nothing noticed for months. Compare the start of what was sent
        # with what the record holds; None when the readback did not load.
        _sent = " ".join((data.get("description") or "").split())[:60]
        desc_ok = (None if not (readback and readback.get("desc") is not None and _sent)
                   else " ".join(readback["desc"].split()).startswith(_sent))
        emit("RESULT", {"ad_id": AD_ID, "ok": bool(ok), "banners": banners,
                        "readback_ok": readback_ok, "expected_images": len(images),
                        "readback": readback, "desc_ok": desc_ok,
                        "new_brand": new_brand, "state_entry": state_entry})

    # --- 7a. import-json, when the admin endpoints are deployed --------------
    # One POST replaces steps 7b-10: the server validates, fetches the photos, creates
    # the brand and answers with what it saved — or exactly why it refused. Once a
    # POST has been sent this never falls back to the DOM path: the server may have
    # saved, or may still be saving, and a second writer is a double import.
    try:
        _api_on = site_api.available(A, return_to=ADMIN_TAB)
    except site_api.SessionLost:
        die(LOST)
    if _api_on:
        # A model the brand does not have is refused by import-json. The contract said
        # it is a new line, so add it first; the site answers with its own spelling.
        if new_model and not DRY_RUN:
            try:
                added = site_api.ensure_model(A, data["brand"], data["model"],
                                              tab=ADMIN_TAB, return_to=ADMIN_TAB)
            except site_api.SessionLost:
                die(LOST)
            if added:
                data["model"] = added["model_name"]
                emit("NEW_MODEL", {"brand": data["brand"], "model": added["model_name"],
                                   "created": bool(added.get("created"))})
        fields = site_api.to_model_fields(data)

        def post(blobs=None):
            try:
                return site_api.import_json(
                    A, fields, data["brand"], image_urls=images, blob_urls=blobs,
                    dry_run=DRY_RUN, tab=ADMIN_TAB, return_to=ADMIN_TAB,
                    allow_duplicate_photos=os.environ.get("ALLOW_DUPLICATE_PHOTOS", "") == "1")
            except Exception as e:          # a CDP error: unknown, like a timeout
                return {"http": 0, "body": "harness: %s" % e}

        def upload():
            """The photos as files: the server could not fetch them (the CDN may refuse
            the production host). Staged and posted from the same admin tab with no
            navigation between — a blob: URL dies with the page that made it."""
            switch_tab(OLX_TAB)
            local = olx_api.photo_data_urls(bu, images, PHOTO_DIR, photo_nums)
            if len(local) < len(images):
                emit("WARN", {"msg": "only %d/%d photos available locally"
                                     % (len(local), len(images))})
            switch_tab(ADMIN_TAB)
            return post(admin_import.stage_images(A, local))

        def imported(readback, pictures, brand=None):
            new_brand = None
            if data["brand"] not in brand_ids:
                # Also when the server did not create it: the brand exists on the
                # site but not in the local map, which olx-step writes it into.
                b = brand
                if not b:
                    try:
                        b = site_api.brand_lookup(A, data["brand"], tab=ADMIN_TAB,
                                                  return_to=ADMIN_TAB)
                    except Exception:       # the watch saved; the map can wait
                        b = None
                b = b or {}
                if b.get("id"):
                    new_brand = {"name": b.get("name") or data["brand"], "id": b["id"]}
                    emit("NEW_BRAND", dict(new_brand, created=bool(b.get("created")), via="api",
                                           action="ADD to BRAND_IDS in import-watch.js AND "
                                                  "references/brand-ids.md, then commit"))
                else:
                    emit("WARN", {"msg": "brand %r is not in BRAND_IDS and its id is unknown "
                                         "- follow the New brand procedure" % data["brand"]})
            report(True, {"images_ok": bool(pictures), "added_ok": True, "via": "api"},
                   readback, True, new_brand)
            raise SystemExit(0)

        force_upload = os.environ.get("FORCE_IMAGE_UPLOAD", "") == "1" and not DRY_RUN
        env, uploaded = (upload(), True) if force_upload else (post(), False)
        while True:
            if site_api.session_lost(env):
                die(LOST)
            http = (env or {}).get("http")
            text = (env or {}).get("body") or ""
            resp = site_api.body_json(env) if site_api.deployed(env) else None
            resp = resp if isinstance(resp, dict) else None
            if DRY_RUN:
                emit("RESULT", {"ad_id": AD_ID, "dry_run": True, "via": "api",
                                "images": len(images),
                                "would_import": {k: (v if k != "images" else len(v))
                                                 for k, v in data.items()},
                                "server": {"http": http,
                                           "answer": resp if resp is not None else text[:300]}})
                raise SystemExit(0)
            if resp is not None and http == 201:
                if resp.get("image_errors"):
                    emit("WARN", {"msg": "%d photo(s) refused by the server"
                                         % len(resp["image_errors"]),
                                  "image_errors": resp["image_errors"][:5]})
                imported(readback_from_saved(resp), resp.get("pictures"), resp.get("brand"))
            if resp is not None and http == 422 and resp.get("error") == "no_images":
                if uploaded:
                    die("import-json saved nothing: no usable photo, also as uploaded "
                        "files: %s" % json.dumps(resp.get("image_errors"))[:300])
                emit("WARN", {"msg": "the server could not fetch the photos; uploading them",
                              "image_errors": (resp.get("image_errors") or [])[:5]})
                env, uploaded = upload(), True
                continue
            if resp is not None and http == 409 and resp.get("error") == "duplicate_photos":
                # The server's photo check: the same files as an ACTIVE listing, from any
                # machine or era -- the pass-1 check only sees this machine's .photos/.
                # Nothing was saved, so this is a skip, never a retry or the DOM path.
                ext = resp.get("external_listing_id")
                skip("duplicate_photos", {
                    "reason": "duplicate_photos: %s photo(s) identical to site listing pk %s "
                              "(%s %s, import-json)" % (resp.get("shared"), resp.get("duplicate_of"),
                                                        resp.get("source"), ext or "-"),
                    "duplicate_of": ext,
                    "existing": {"pk": resp.get("duplicate_of"), "source": resp.get("source"),
                                 "change_url": resp.get("change_url")}})
            if resp is not None and http == 409:
                skip("already_imported", {"reason": "already imported (import-json: duplicate)",
                                          "existing": resp.get("existing")})
            if resp is not None and http == 400 and isinstance(resp.get("errors"), dict):
                _review = {"reasons": server_reasons(resp["errors"], resp.get("models")),
                           "images": len(images), "rerun": RERUN}
                if resp.get("models") is not None:
                    _review["models"] = resp["models"]
                review_stop(_review)
            if http == 400:
                die("import-json answered 400: %s" % text[:300])
            if http == 403:
                # HTML = a CSRF failure; JSON = a staff user without the add permission.
                die("import-json answered 403: %s" % text[:300])
            if http == 413:
                # A proxy refused the body before Django saw it: nothing can have saved.
                die("import-json answered 413 (a proxy in front of Django capped the "
                    "upload): %s" % text[:300])
            # Anything else — a 5xx, a proxy 504, a timeout, a CDP error — is unknown,
            # and Django can still be fetching photos after nginx gave up. Ask lookup/
            # over 45 s before calling it an error; never re-send.
            for wait in (0, 15, 15, 15):
                time.sleep(wait)
                try:
                    found = site_api.lookup_ids(A, [AD_ID], tab=ADMIN_TAB, return_to=ADMIN_TAB)
                except site_api.SessionLost:
                    die(LOST)
                row = ((found or {}).get("existing") or {}).get(AD_ID)
                if row:
                    emit("WARN", {"msg": "import-json answered %s, but the listing is on the "
                                         "site (pk %s)" % (http, row.get("pk"))})
                    imported(readback_from_lookup(row, AD_ID), row.get("pictures"))
            die("import-json answered %s and the listing is not on the site after 45 s: %s"
                % (http, text[:300]))

    # --- 7b. photos as data: URLs (the CDN now refuses the admin's Origin) ---
    if not DRY_RUN:
        switch_tab(OLX_TAB)
        local_photos = olx_api.photo_data_urls(bu, images, PHOTO_DIR, photo_nums)
        if len(local_photos) < len(images):
            emit("WARN", {"msg": "only %d/%d photos available locally"
                                 % (len(local_photos), len(images))})

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

    data["images"] = admin_import.stage_images(A, local_photos)
    ret = admin_import.submit(A, data, len(images))
    if ret:     # importWatch returned instead of navigating: it bailed before submit
        emit("WARN", {"msg": "importWatch returned without navigating", "ret": ret[:3000]})

    # --- 10. verify ----------------------------------------------------------
    ok, banners, readback, readback_ok = admin_import.verify(A, AD_ID)
    report(ok, banners, readback, readback_ok,
           {"name": data["brand"], "id": new_brand_id} if new_brand_id else None)
