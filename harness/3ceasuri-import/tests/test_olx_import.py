#!/usr/bin/env python3
"""Offline harness for the two OLX importers: stubs browser-use and the OLX API so
the param map, the contract gates and the provenance fields can be tested without
Chrome (and without touching the live admin)."""
import json, os, re, sys, io, contextlib, time

time.sleep = lambda *a, **k: None      # the scripts' paced waits are irrelevant offline

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
SCRIPTS = os.path.join(ROOT, "harness/3ceasuri-import/scripts")
SMART = os.path.join(SCRIPTS, "olx-import-smartwatch.py")
CLASSIC = os.path.join(SCRIPTS, "olx-import-watch.py")
sys.path.insert(0, SCRIPTS)
import olx_api
import price_sanity


def param(key, name, vkey, label):
    return {"key": key, "name": name, "type": "select", "value": {"key": vkey, "label": label}}


def price_param(value, currency="RON", negotiable=False):
    return {"key": "price", "name": "Pret", "type": "price",
            "value": {"value": value, "currency": currency, "negotiable": negotiable,
                      "label": "%s lei" % value}}


def photos(n):
    return [{"id": i, "filename": "f%d-RO" % i, "width": 750, "height": 1000,
             "link": "https://frankfurt.apollo.olxcdn.com:443/v1/files/f%d-RO/image;s={width}x{height}" % i}
            for i in range(1, n + 1)]


SMART_AD = {
    "id": 307673714,
    "url": "https://www.olx.ro/d/oferta/garmin-fenix-7x-solar-IDkOXZg.html",
    "title": "Garmin Fenix 7x Solar 51mm",
    "description": "Ceas in stare foarte buna, folosit un an.<br />\nVine cu incarcator si cutie.<br />"
                   "<br />Are GPS si harti, autonomie excelenta.&nbsp;Pret usor negociabil.",
    "status": "active",
    "business": False,
    "params": [param("state", "Stare", "used", "Utilizat"),
               param("brand", "Brand", "garmin", "Garmin"),
               param("stil", "Stil", "sport", "Sport"),
               param("pentru", "Pentru", "barbati", "Barbati"),
               price_param(1700)],
    "photos": photos(3),
    "user": {"id": 529077689, "name": "Stanciu Adrian"},
    "location": {"city": {"name": "Bucuresti"}, "region": {"name": "Bucuresti - Ilfov"}},
    "category": {"id": 1943},
}

CLASSIC_AD = {
    "id": 303404526,
    "url": "https://www.olx.ro/d/oferta/seiko-prospex-mm200-spb077-automatic-IDkx3no.html",
    "title": "Seiko Prospex MM200 SPB077 automatic 44mm",
    "description": "Ceas automatic, cumparat in 2019, stare impecabila.<br />"
                   "Vine cu cutie si documente, bratara de otel plus curea de cauciuc.",
    "status": "active",
    "business": False,
    "params": [param("culoare_carcasa", "Culoare carcasa", "alb", "Alb"),
               param("afisaj", "Afisaj", "analogic", "Analogic"),
               param("material_carcasa", "Material carcasa", "otel_inoxidabil", "Otel inoxidabil"),
               param("rezistenta_la_apa", "Rezistenta la apa", "20_atm", "20 ATM"),
               param("brand", "Brand", "seiko", "Seiko"),
               param("state", "Stare", "purtat-o-singura-data", "Purtat o singura data"),
               price_param(3500, negotiable=True)],
    "photos": photos(8),
    "user": {"id": 111222333, "name": "Ana Ionescu"},
    "location": {"city": {"name": "Cluj-Napoca"}, "region": {"name": "Cluj"}},
    "category": {"id": 1677},
}


# The admin's answer to a path that does not exist: its `<path:object_id>/` catch-all
# redirects to /admin/ with an HTML page. That is what "not deployed" looks like.
NOT_DEPLOYED = {"http": 200, "redirected": True, "url": "https://3ceasuri.ro/admin/",
                "ctype": "text/html; charset=utf-8", "body": "<!doctype html>"}


# Pass 1 now writes a contract draft to .contracts/, and pass 2 reads it -- so a
# draft left behind by the PREVIOUS run of this file would make check 4 take the
# pass-2 path. Each fixture ad's draft is cleared the first time it runs. Only the
# fixtures': .contracts/ is the REAL drafts folder (this used to rmtree all of it,
# and running the suite mid-session wiped the live drafts on 2026-10-04).
import glob as _glob
_CLEARED = set()


def _clear_drafts_once(ad_id):
    if ad_id in _CLEARED:
        return
    _CLEARED.add(ad_id)
    for f in _glob.glob(os.path.join(ROOT, "harness/3ceasuri-import/.contracts",
                                     "olx-%s.*" % ad_id)):
        os.remove(f)


# Stub photos go to a scratch folder: the fixture ids are real ads, and the real
# .photos/olx-<id>/ folders hold their photos.
import tempfile as _tempfile
_PHOTO_ROOT = _tempfile.mkdtemp(prefix="olx-test-photos-")
# ...and the shop-cards list is references/shop-cards.json, committed: learning into it
# from stub photos would put test bytes in the real list.
_SHOP_CARDS = os.path.join(_tempfile.mkdtemp(prefix="olx-test-cards-"), "shop-cards.json")


def run(script, ad, env=None, admin_rows_for=None, saved_description=None, site=None,
        photo_b64=None):
    """Execute an OLX importer against a canned ad; return (markers, trace).

    The stub admin saves the description importWatch() was handed, unless
    `saved_description` says what the form ended up holding instead. `site(req)`
    answers the JSON endpoints (an envelope, or "TIMEOUT" for a page that never
    answers); without it they are not deployed."""
    state = {"url": "", "imported": None, "brand_tab_opened": False, "brand_name": "",
             "fetched": [], "site_calls": [], "pending": {}, "injected": 0, "staged": 0,
             "visited": []}
    admin_rows_for = admin_rows_for or (lambda q: [])
    import site_api
    site_api.reset()

    def js(e):
        # Order matters: several payloads are `(async ...)` expressions, so match on
        # a string unique to each before falling through to the generic branches.
        if "/*site_api:start*/" in e:                                   # site_api request
            req = json.loads(re.search(r"const REQ = (.*?); const K = ", e, re.S).group(1))
            key = json.loads(re.search(r'const K = ("[^"]+");', e).group(1))
            state["site_calls"].append(req)
            answer = (site(req) if site else None) or NOT_DEPLOYED
            if answer != "TIMEOUT":
                state["pending"][key] = answer
            return key
        if "/*site_api:poll*/" in e:                                    # site_api answer
            key = json.loads(re.search(r'b\[("[^"]+")\]', e).group(1))
            answer = state["pending"].pop(key, None)
            return "" if answer is None else json.dumps(answer)
        if "__imgParts" in e:                                           # stage_images
            if "createObjectURL" in e:
                state["staged"] += 1
                return "blob:https://3ceasuri.ro/%d" % state["staged"]
            return 1
        if "String(fr.result)" in e:                                    # photo download
            if callable(photo_b64):             # bytes per photo URL
                return photo_b64(json.loads(re.search(r'fetch\(("[^"]*")\)', e).group(1)))
            return photo_b64 or "A" * 800       # 600 bytes: below photo_dedup.MIN_BYTES
        if 'Accept:"application/json"' in e:                            # the OLX API
            path = re.search(r'fetch\("([^"]+)"', e).group(1)
            state["fetched"].append(path)
            if re.search(r"/api/v1/offers/\d+/", path):
                body = json.dumps({"data": ad})
            else:
                body = json.dumps({"data": [], "metadata": {"total_elements": 0}})
            return json.dumps({"status": 200, "body": body})
        if "createElement('script')" in e:                              # harness injection
            state["injected"] += 1
            return "OK"
        if e.startswith("(async"):                                      # importWatch call
            state["imported"] = e
            return "OK"
        if "td.field-" in e:                                            # dedup rows
            q = re.search(r"[?&]q=([^&\"]+)", state["url"])
            import urllib.parse
            return json.dumps(admin_rows_for(urllib.parse.unquote(q.group(1)) if q else ""))
        if "brand\\/(\\d+)\\/change" in e or "brand/(\\d+)/change" in e:  # brand lookup BY NAME
            return json.dumps([{"name": state["brand_name"], "id": "99"}]
                              if state["brand_tab_opened"] else [])
        if "id_name" in e and "id_slug" in e:                            # brand add form
            state["brand_tab_opened"] = True
            m = re.search(r'n\.value=("(?:[^"\\]|\\.)*")', e)
            state["brand_name"] = json.loads(m.group(1)) if m else ""
            return "ok"
        if "window.BRAND_IDS[" in e:
            return "ok"
        if "imagini salvate" in e:
            return json.dumps({"images_ok": True, "added_ok": True})
        if "/change/" in e and "result_list" in e:
            return json.dumps({"url": "https://3ceasuri.ro/admin/watches/watch/5/change/"})
        if "id_reference_number" in e or "id_case_diameter_mm" in e:
            _sent = re.search(r"importWatch\((\{.*\})\); return", state["imported"] or "", re.S)
            _desc = (json.loads(_sent.group(1)).get("description") if _sent else None) or ""
            if saved_description is not None:
                _desc = saved_description
            return json.dumps({"brandId": "1", "price": "1700", "currency": "RON",
                               "ref": None, "diameter": None, "source": "olx",
                               "extId": str(ad["id"]), "sellerId": str(ad["user"]["id"]),
                               "sellerName": ad["user"]["name"], "imgs": len(ad["photos"]),
                               "desc": _desc[:120]})
        if "location.href" in e:
            return state["url"] or "https://www.olx.ro/"
        return ""

    def new_tab(u):
        state["url"] = u
        state["visited"].append(u)
        return {"targetId": "T2"}

    def goto_url(u):
        state["url"] = u
        state["visited"].append(u)

    g = {"__name__": "__main__", "js": js, "new_tab": new_tab, "goto_url": goto_url,
         "close_tab": lambda t: None, "switch_tab": lambda t: None,
         "list_tabs": lambda: [
             {"targetId": "A", "url": "https://3ceasuri.ro/admin/watches/watch/add/", "title": "add"},
             {"targetId": "O", "url": "https://www.olx.ro/moda-frumusete/ceasuri/", "title": "olx"}]}

    _clear_drafts_once(ad["id"])
    os.environ.clear()
    os.environ.update({"PROJECT_ROOT": ROOT, "AD_ID": str(ad["id"]), "PATH": "/usr/bin:/bin",
                       "PHOTO_ROOT": _PHOTO_ROOT, "SHOP_CARDS": _SHOP_CARDS})
    os.environ.update(env or {})

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(open(script).read(), script, "exec"), g)
    except SystemExit:
        pass
    markers = {}
    for line in buf.getvalue().splitlines():
        m = re.match(r"^([A-Z_]+): (.*)$", line)
        if m:
            markers[m.group(1)] = json.loads(m.group(2))
    return markers, state



fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)


# --- 1. the param map is the whole point: it must be exact ------------------
mapped = olx_api.map_params(CLASSIC_AD)
check(mapped["condition"] == "excellent", "1: 'Purtat o singura data' -> excellent, got %r" % mapped.get("condition"))
check(mapped["caseMat"] == "steel", "1: otel inoxidabil -> steel, got %r" % mapped.get("caseMat"))
check(mapped["displayType"] == "analog", "1: analogic -> analog, got %r" % mapped.get("displayType"))
check(mapped["waterRes"] == "water_resistant_yes", "1: 20 ATM -> yes, got %r" % mapped.get("waterRes"))
check(mapped["price"] == 3500 and mapped["currency"] == "RON", "1: price %s" % mapped)
check(mapped["priceNote"] == "negociabil", "1: negotiable -> priceNote, got %r" % mapped.get("priceNote"))
check("displayColor" not in mapped, "1: culoare_carcasa is the CASE colour and must NOT become displayColor")
# OLX hands back padded labels ("Samsung "), which would become a brand row with a
# trailing space and a mangled slug (seen live 2026-08-09).
check(olx_api.brand_param({"params": [param("brand", "Brand", "samsung", "Samsung ")]}) == "Samsung",
      "1: brand label must be stripped, got %r"
      % olx_api.brand_param({"params": [param("brand", "Brand", "samsung", "Samsung ")]}))
smapped = olx_api.map_params(SMART_AD)
check(smapped["condition"] == "good", "1: Utilizat -> good, got %r" % smapped.get("condition"))
check(smapped["gender"] == "men", "1: barbati -> men, got %r" % smapped.get("gender"))
check(smapped["style"] == "sport", "1: sport -> sport, got %r" % smapped.get("style"))
check(olx_api.map_params({"params": [param("state", "Stare", "zzz", "Necunoscut")]}) == {},
      "1: an unknown enum value must be omitted, never guessed")

# --- 2. photo urls are rewritten to full size, not left templated -----------
urls = olx_api.photo_urls(SMART_AD)
check(len(urls) == 3 and all("1000x1000" in u for u in urls), "2: photo urls %r" % urls[:1])
check("{width}" not in "".join(urls), "2: template left unresolved")

# --- 3. description HTML becomes text, keeping the seller's line breaks -----
d = olx_api.clean_description(SMART_AD["description"])
check("<br" not in d and "&nbsp;" not in d, "3: html left in the description: %r" % d[:60])
check(d.startswith("Ceas in stare foarte buna") and "\n" in d, "3: line breaks lost: %r" % d)

# --- 3b. phone numbers never reach the public text (user directive 2026-10-03) ---
for _raw, _want in (
        ("Stare buna.<br />Tel: 0722 123 456", "Stare buna."),
        ("Sunati la 0722-123-456 dupa ora 18", "dupa ora 18"),
        ("+40 722.123.456 / 021 123 4567<br />Cutie si acte", "Cutie si acte"),
        ("Ref T125.617.17.051.03, 1500 lei, 42mm, an 2019",
         "Ref T125.617.17.051.03, 1500 lei, 42mm, an 2019"),
        ("Serie 2345678901 pe capac, IMEI 356789012345678",
         "Serie 2345678901 pe capac, IMEI 356789012345678")):
    _got = olx_api.clean_description(_raw)
    check(_got == _want, "3b: %r -> %r, want %r" % (_raw, _got, _want))

# --- 4. pass 1 hands out the contract and writes NOTHING -------------------
m, st = run(SMART, SMART_AD)
check("EXTRACT_PROMPT" in m, "4: first pass must emit the contract")
check(st["imported"] is None, "4: first pass must not import")
check(len(m["EXTRACT_PROMPT"]["photos"]) == 3, "4: photos must ship with the contract")
check(all(os.path.exists(p) for p in m["EXTRACT_PROMPT"]["photos"]), "4: photos not written to disk")
p = m["EXTRACT_PROMPT"]["prompt"]
check("smartwatch listing" in p, "4: smart profile not used")
check("Known from OLX" in p and "`condition`: \"good\"" in p, "4: known-from-OLX block missing")
check("anything you leave\nout of the answer is cleared" in p, "4: the clearing rule must be stated")
check("Garmin Fenix 7x Solar" in p, "4: ad text missing from the prompt")

# --- 5. the smartwatch importer never lets `movement` fall back to quartz ---
FILLED_SMART = {"brand": "Garmin", "model": "Fenix 7X Solar",
                "connectivity": "no_gsm", "compatibility": "both", "price": 1700,
                "currency": "RON", "condition": "good", "gender": "men",
                "description": "Ceas Garmin Fenix 7X Solar în stare foarte bună, folosit un an.\nVine cu încărcător și cutie.\n\nAre GPS și hărți, autonomie excelentă.",
                "is_wristwatch": True, "is_bulk_lot": False}
m, st = run(SMART, SMART_AD, env={"CONFIRM": "1", "OVERRIDES": json.dumps(FILLED_SMART)})
inf = m["INFER"]
check(inf["movement"] == "smart", "5: movement %r" % inf.get("movement"))
check(inf["style"] == "smart" and inf["displayType"] == "smart", "5: style/displayType %s" % inf)
check(inf["category"] == "wrist", "5: category %r" % inf.get("category"))
check(m.get("RESULT", {}).get("ok") is True, "5: should import")
check(m["RESULT"]["state_entry"]["source"] == "olx", "5: state_entry source")

# --- 6. provenance survives the contract clearing --------------------------
check(inf["source"] == "olx", "6: source not set")
check(inf["externalId"] == "307673714", "6: externalId %r" % inf.get("externalId"))
check(inf["sellerId"] == "529077689", "6: sellerId %r" % inf.get("sellerId"))
check(inf["sellerName"] == "Stanciu Adrian", "6: sellerName %r" % inf.get("sellerName"))
check(inf["sourceUrl"].startswith("https://www.olx.ro/d/oferta/"), "6: sourceUrl %r" % inf.get("sourceUrl"))
# The site writes "București" / "Voluntari, jud. Ilfov" from these two; the old
# free-text "Județul X, localitatea Y" is no longer sent (2026-10-05).
check(inf["county"] == "București" and inf["city"] == "București",
      "6: county/city %r/%r" % (inf.get("county"), inf.get("city")))
check(not inf.get("location"), "6: location must not be filled, got %r" % inf.get("location"))
check("is_wristwatch" not in inf, "6: contract-only flags must not reach the form")
# `style` was answered by OLX but left out of the contract -> it is a forced smart
# field, while `stil`-derived values on other fields must NOT survive silently:
m2, _ = run(SMART, SMART_AD, env={"CONFIRM": "1",
                                  "OVERRIDES": json.dumps(dict(FILLED_SMART, gender=None))})
check(m2["INFER"].get("gender") is None, "6: an omitted/nulled contract field must be cleared")

# --- 7. a smartwatch missing its facets stops for review -------------------
m, st = run(SMART, SMART_AD, env={"OVERRIDES": json.dumps(
    dict(FILLED_SMART, connectivity=None, compatibility=None))})
check("REVIEW" in m, "7: missing smart facets must stop for review")
for f in ("connectivity", "compatibility"):
    check(any(f in r["message"] for r in m["REVIEW"]["reasons"]), "7: %s not flagged" % f)
check(st["imported"] is None, "7: must not import")

# --- 8. an accessory is not a watch ----------------------------------------
m, st = run(SMART, SMART_AD, env={"OVERRIDES": json.dumps(
    dict(FILLED_SMART, is_wristwatch=False, notes="doar curea, nu ceasul"))})
check(m.get("SKIP", {}).get("reason", "").startswith("not a watch"), "8: accessory not skipped: %s" % m.get("SKIP"))
check(st["imported"] is None, "8: must not import an accessory")

# --- 9. a mechanical watch on the smartwatch importer is a routing mistake --
m, st = run(SMART, SMART_AD, env={"OVERRIDES": json.dumps(dict(FILLED_SMART, movement="automatic"))})
check("REVIEW" in m and any("olx-import-watch.py" in r["message"] for r in m["REVIEW"]["reasons"]),
      "9: mis-routed ad must be flagged, got %s" % m.get("REVIEW"))
check(st["imported"] is None, "9: must not import a mis-routed ad")

# --- 10. classic importer: OLX params + contract ---------------------------
FILLED_CLASSIC = {"brand": "Seiko", "model": "Prospex MM200 SPB077", "movement": "automatic",
                  "price": 3500, "currency": "RON", "condition": "excellent",
                  "caseMat": "steel", "diameter": 44, "waterRes": "water_resistant_yes",
                  "description": "Ceas Seiko Prospex automatic, cumpărat în 2019, stare impecabilă.\nVine cu cutie și documente, brățară de oțel plus curea de cauciuc.",
                  "is_wristwatch": True, "is_bulk_lot": False}
m, st = run(CLASSIC, CLASSIC_AD, env={"CONFIRM": "1", "OVERRIDES": json.dumps(FILLED_CLASSIC)})
inf = m["INFER"]
check(inf["movement"] == "automatic", "10: movement %r" % inf.get("movement"))
check(inf["category"] == "wrist", "10: category %r" % inf.get("category"))
check(inf["source"] == "olx" and inf["externalId"] == "303404526", "10: provenance %s" % inf)
check(m.get("RESULT", {}).get("ok") is True, "10: should import")

# --- 11. classic: an unstated movement is judged, never defaulted ----------
NO_MOVEMENT = dict(CLASSIC_AD, description="Ceas de dama, stare buna, cu cutie si garantie.",
                   title="Ceas dama elegant", params=[p for p in CLASSIC_AD["params"]])
m, st = run(CLASSIC, NO_MOVEMENT)
check("EXTRACT_PROMPT" in m, "11: first pass emits the contract")
m, st = run(CLASSIC, NO_MOVEMENT, env={"OVERRIDES": json.dumps(
    dict(FILLED_CLASSIC, movement=None))})
check("REVIEW" in m and any("movement" in r["message"] for r in m["REVIEW"]["reasons"]),
      "11: unstated movement must stop for review, got %s" % m.get("REVIEW"))
check(st["imported"] is None, "11: must not import a movement-guessed watch")

# --- 12. classic: a wall clock imports, a mantel clock skips ---------------
m, st = run(CLASSIC, CLASSIC_AD, env={"CONFIRM": "1", "OVERRIDES": json.dumps(
    dict(FILLED_CLASSIC, is_wristwatch=False, category="wall", caseMat="wood",
         brand="Fără marcă", model="Pendulă cu cuc anii '70"))})
check("SKIP" not in m, "12: a wall clock must import, got %s" % m.get("SKIP"))
check(m["INFER"]["category"] == "wall", "12: category not wall")
m, st = run(CLASSIC, CLASSIC_AD, env={"OVERRIDES": json.dumps(
    dict(FILLED_CLASSIC, is_wristwatch=False))})
check(m.get("SKIP", {}).get("reason", "").startswith("not a wristwatch"),
      "12: a non-wall non-wristwatch must skip, got %s" % m.get("SKIP"))

# --- 13. dedup Stage 1 short-circuits before any OLX work ------------------
m, st = run(SMART, SMART_AD,
            admin_rows_for=lambda q: [{"brand": "Garmin", "model": "X", "extid": "307673714"}]
            if q == "307673714" else [])
check(m.get("SKIP", {}).get("reason", "").startswith("already imported"), "13: stage-1 dedup broken: %s" % m.get("SKIP"))
check(not st["fetched"], "13: must not touch the OLX API for an ad already imported")

# --- 14. dedup Stage 2: the same watch relisted under a new ad id ----------
def rows(q):
    return [{"brand": "Garmin", "model": "Fenix 7X Solar", "extid": "999"}] if q == "529077689" else []
m, st = run(SMART, SMART_AD, env={"CONFIRM": "1", "OVERRIDES": json.dumps(FILLED_SMART)},
            admin_rows_for=rows)
check(m.get("SKIP", {}).get("reason", "").startswith("repost"), "14: stage-2 repost dedup broken: %s" % m.get("SKIP"))
check(st["imported"] is None, "14: repost must not import")

# --- 15. an illegal DB value dies loudly instead of being dropped ----------
m, _ = run(SMART, SMART_AD, env={"CONFIRM": "1",
                                 "OVERRIDES": json.dumps(dict(FILLED_SMART, connectivity="LTE"))})
check("ERROR" in m and "not one of" in json.dumps(m["ERROR"]), "15: bad enum not rejected: %s" % m.get("ERROR"))

# --- 15b. Romanian "referință" must not yield a mid-word capture ----------
# Regression 2026-08-09: `erin[țt]a` never matched "referință" (it ends ț+ă), so the
# capture started mid-word and a Rolex ad proposed reference "erin".
# Priced like the real one (21000 RON): at CLASSIC_AD's 3500 the cheap-fake rule
# would skip it before the contract is ever built — which is the rule working.
ROLEX_AD = dict(CLASSIC_AD, id=307626402,
                title="Ceas Rolex Datejust 36, Aur 18K+Otel, referință 1601",
                description="Ceas Rolex Datejust 36, referință 1601, automat (calibru 1570).",
                params=[param("state", "Stare", "used", "Utilizat"),
                        param("brand", "Brand", "rolex", "Rolex"),
                        price_param(21000)])
m, _ = run(CLASSIC, ROLEX_AD)
known = m["EXTRACT_PROMPT"]["prompt"]
check("`reference`: \"erin\"" not in known, "15b: mid-word reference capture is back")
check('`reference`: "1601"' in known, "15b: 'referință 1601' must yield 1601, prompt said: %s"
      % [l for l in known.splitlines() if "reference" in l][:2])

# --- 15c. the login redirect must never poison the OLX tab ----------------
# Regression 2026-08-09: logged out, clicking the phone button navigates the tab to
# login.olx.ro — a different origin — and every later /api/v1/ fetch from that tab
# 404s. Three ads in a row failed to load before the tab was steered back.
check(olx_api._is_api_origin("https://www.olx.ro/d/oferta/x.html") is True,
      "15c: www.olx.ro must count as the API origin")
check(olx_api._is_api_origin("https://login.olx.ro/?cc=abc") is False,
      "15c: login.olx.ro must NOT count as the API origin")

class _Bu:
    """A tab parked on login.olx.ro, as a poisoned session leaves it."""
    def __init__(self):
        self.url = "https://login.olx.ro/?cc=abc"
        self.went = []
    def list_tabs(self):
        return [{"targetId": "T", "url": self.url}]
    def switch_tab(self, t): pass
    def goto_url(self, u):
        self.url = u; self.went.append(u)
    def new_tab(self, u):
        self.went.append("NEW:" + u); return {"targetId": "NEW"}

_b = _Bu()
_tab = olx_api.ensure_tab(_b, "https://www.olx.ro/moda-frumusete/ceasuri/")
check(_tab == "T", "15c: the existing tab must be reused, not abandoned")
check(any("www.olx.ro" in u for u in _b.went),
      "15c: a tab parked on login.olx.ro must be steered back to www.olx.ro, got %r" % _b.went)
check(not any(u.startswith("NEW:") for u in _b.went),
      "15c: must not leak a new tab when one is merely on the wrong olx host")

# --- 15d. the phone reveal: visible button, native click, wall gate -------
# Measured live 2026-08-09 on the ad the user pointed at: OLX renders the reveal
# control TWICE (sidebar + sticky bar) and the first in DOM order has width 0, so
# clicking `querySelector(...)` clicked the hidden one and the number never
# appeared. A synthetic MouseEvent did not trigger the handler either.
class _PhoneBu:
    """Records the JS the reveal runs, and plays back a page that reveals on click."""
    def __init__(self, wall=False, reveal=True):
        self.wall, self.reveal, self.clicked = wall, reveal, False
        self.url, self.went, self.scripts = "https://www.olx.ro/d/oferta/x.html", [], []
    def goto_url(self, u):
        self.url = u; self.went.append(u)
    def js(self, e):
        self.scripts.append(e)
        # The reveal confirms it has landed on the ad before reading anything.
        if "location.pathname" in e:
            import urllib.parse
            return urllib.parse.urlparse(self.url).path
        # Order matters: the reader script ALSO contains the wall wording (it reports
        # `login:`), so match its unique marker first or the wall branch swallows it.
        if "href:location.href" in e:
            tel = ["+40742866198"] if (self.clicked and self.reveal) else []
            return json.dumps({"tel": tel, "txt": [], "href": self.url,
                               "login": False, "masked": not tel})
        if "contul t" in e:
            return "wall" if self.wall else ""
        if "show-phone" in e:
            self.clicked = True
            return "clicked"
        return ""
    def list_tabs(self): return [{"targetId": "T", "url": self.url}]
    def switch_tab(self, t): pass
    def new_tab(self, u): return {"targetId": "N"}
    def close_tab(self, t): pass

_ok = _PhoneBu()
check(olx_api.reveal_phone(_ok, "https://www.olx.ro/d/oferta/x.html") == ("+40742866198", "ok"),
      "15d: a revealable phone must be read")
_click = [e for e in _ok.scripts if "show-phone" in e]
check(_click and "getBoundingClientRect().width > 0" in _click[0],
      "15d: must click only VISIBLE controls — the first show-phone button has width 0")
check(_click and ".click()" in _click[0] and "new MouseEvent" not in _click[0],
      "15d: must use the native .click(); a synthetic MouseEvent does not fire the handler")

# The wall gate has to fire BEFORE any click: on a private ad the click navigates to
# login.olx.ro and poisons the tab for every later API call.
_wall = _PhoneBu(wall=True)
check(olx_api.reveal_phone(_wall, "https://www.olx.ro/d/oferta/x.html") == (None, "login_required"),
      "15d: a walled ad must report login_required")
check(_wall.clicked is False, "15d: must NOT click through the login wall")

# --- 15e. never read a phone off a page that has not navigated yet --------
# Caught live 2026-08-09: goto_url returns before the navigation settles and the
# PREVIOUS ad is still in the DOM with its number already revealed, so a private
# seller in Berceni was about to be saved with an amanet's number from the ad
# imported moments earlier. The reveal must confirm the path first.
class _SlowBu(_PhoneBu):
    """Navigation that never lands on the requested ad."""
    def js(self, e):
        if "location.pathname" in e:
            return "/d/oferta/some-other-ad-IDxxx.html"      # still the old page
        return super().js(e)

_slow = _SlowBu()
check(olx_api.reveal_phone(_slow, "https://www.olx.ro/d/oferta/wanted-IDaaa.html")
      == (None, "wrong_page"),
      "15e: a page that never navigated must report wrong_page, not a stale phone")
check(_slow.clicked is False, "15e: must not click a page that is not the target ad")

class _LandedBu(_PhoneBu):
    def js(self, e):
        if "location.pathname" in e:
            return "/d/oferta/wanted-IDaaa.html"
        return super().js(e)

check(olx_api.reveal_phone(_LandedBu(), "https://www.olx.ro/d/oferta/wanted-IDaaa.html")
      == ("+40742866198", "ok"),
      "15e: the matching path must still read normally")

# --- 15f. suspiciously cheap is NEVER imported (user directive 2026-08-09) -
# A replica seldom says "replica"; the price is what gives it away. This is a hard
# skip, before the photos are fetched, and CONFIRM must not wave it through.
check(price_sanity.implausible_price(900, "RON", "Rolex", "Ceas Rolex Datejust 36"),
      "15f: a 900 RON Rolex must be rejected")
check(price_sanity.implausible_price(160, "RON", "Apple", "apple watch series 11"),
      "15f: a 160 RON Series 11 must be rejected")
check(price_sanity.implausible_price(700, "RON", "Apple", "Apple Watch Ultra 2"),
      "15f: a 700 RON Ultra must be rejected")
check(price_sanity.implausible_price(200, "RON", "Omega", "Omega Seamaster"),
      "15f: a 200 RON Omega must be rejected")
# ...and everything genuinely imported on 2026-08-09 must still pass
for _p, _c, _b, _t in ((21000, "RON", "Rolex", "Rolex Datejust 36 aur 18k"),
                       (2000, "RON", "Apple", "Apple Watch Ultra 2 baterie 100%"),
                       (1100, "RON", "Apple", "Apple watch 9, 45 mm"),
                       (999, "RON", "Apple", "Apple watch stainless steel 45mm seria 7"),
                       (9000, "RON", "Breitling", "Ceas Breitling Avenger Seawolf"),
                       (950, "RON", "Christophe Duchamp", "Christophe Duchamp L'envie"),
                       (300, "RON", "Police", "Ceas Police Timepieces"),
                       (400, "EUR", "Omega", "Omega Seamaster vintage")):
    check(price_sanity.implausible_price(_p, _c, _b, _t) is None,
          "15f: %s at %s %s must NOT be rejected" % (_b, _p, _c))

CHEAP_AD = dict(SMART_AD, id=999111222, title="Apple Watch Ultra 2 49mm sigilat",
                params=[param("state", "Stare", "new", "Nou"),
                        param("brand", "Brand", "apple", "Apple"),
                        price_param(600)])
m, st = run(SMART, CHEAP_AD)
check(m.get("SKIP", {}).get("reason", "").startswith("suspiciously cheap"),
      "15f: pass 1 must skip a cheap fake, got %s" % (m.get("SKIP") or m.keys()))
check("EXTRACT_PROMPT" not in m, "15f: must not even build the contract for a fake")
check(st["imported"] is None, "15f: nothing may be written")

m, st = run(SMART, CHEAP_AD, env={"CONFIRM": "1", "OVERRIDES": json.dumps(FILLED_SMART)})
check(m.get("SKIP", {}).get("reason", "").startswith("suspiciously cheap"),
      "15f: CONFIRM must NOT wave a cheap fake through")
check(st["imported"] is None, "15f: CONFIRM must still write nothing")

# --- 16. an inactive ad is skipped, not imported --------------------------
m, _ = run(SMART, dict(SMART_AD, status="removed_by_user"))
check(m.get("SKIP", {}).get("reason", "").startswith("ad is not active"), "16: inactive ad: %s" % m.get("SKIP"))

# --- 16b. the two profiles stay distinct after the collapse -----------------
# A characterisation test: it pins the SIX ways the classic and smart paths differ,
# side by side, so collapsing them onto one shared flow cannot quietly lose one.
# It passed before the refactor and must pass after — that is the whole contract.
_ov_c = {"brand": "Seiko", "model": "Prospex MM200", "price": 3500, "currency": "RON",
         "movement": "automatic", "is_wristwatch": True, "is_bulk_lot": False}
_ov_s = {"brand": "Garmin", "model": "Fenix 7X Solar", "price": 1700, "currency": "RON",
         "connectivity": "no_gsm", "compatibility": "both",
         "description": FILLED_SMART["description"],
         "is_wristwatch": True, "is_bulk_lot": False}
m_c, _ = run(CLASSIC, CLASSIC_AD, {"CONFIRM": "1", "OVERRIDES": json.dumps(_ov_c)})
m_s, _ = run(SMART, SMART_AD, {"CONFIRM": "1", "OVERRIDES": json.dumps(_ov_s)})
check(m_c["INFER"]["movement"] == "automatic", "16b: classic movement %r" % m_c["INFER"].get("movement"))
check(m_s["INFER"]["movement"] == "smart", "16b: smart profile must force movement=smart")
check(m_s["INFER"]["style"] == "smart" and m_s["INFER"]["displayType"] == "smart",
      "16b: smart profile must force style/displayType")
check(m_c["INFER"].get("connectivity") is None, "16b: classic must not invent connectivity")
check(m_c["RESULT"]["state_entry"]["category"] == "wrist", "16b: classic state_entry carries category")
check("category" not in m_s["RESULT"]["state_entry"], "16b: smart state_entry omits category")

# --- 17. pass 1 writes a seeded draft; pass 2 reads it -----------------------
import contract_draft
_dp = contract_draft.draft_path(ROOT, SMART_AD["id"])
if os.path.exists(_dp):
    os.remove(_dp)
m, st = run(SMART, SMART_AD)
check("EXTRACT_PROMPT" in m, "17: pass 1 must still emit the contract")
check(m["EXTRACT_PROMPT"]["draft"] == _dp, "17: pass 1 must report the draft path")
check(os.path.exists(_dp), "17: pass 1 must write the draft to disk")
_d = json.load(open(_dp))
check(_d["description"].startswith("Ceas in stare foarte buna"),
      "17: the draft must carry the cleaned description, so it is never retyped")
check(_d["brand"] == "Garmin" and _d["price"] == 1700, "17: draft missing mapped params")
check("model" in _d["_todo"] and "connectivity" in _d["_todo"], "17: _todo wrong: %s" % _d["_todo"])
check(st["imported"] is None, "17: pass 1 must still write nothing")
# the prompt now asks only about the open fields -- that is what a continuous
# session stops paying per watch
_p17 = m["EXTRACT_PROMPT"]["prompt"]
check("- `connectivity`:" in _p17, "17: an open field must still be described")
check("- `waterRes`:" not in _p17, "17: a field the baseline settled must not be asked again")

# the model edits the draft, then pass 2 runs with no OVERRIDES at all
_d.update({"model": "Fenix 7X Solar", "connectivity": "no_gsm", "compatibility": "both",
           "is_wristwatch": True, "is_bulk_lot": False, "notes": None,
           "description": FILLED_SMART["description"]})
json.dump(_d, open(_dp, "w"))
m2, st2 = run(SMART, SMART_AD, {"CONFIRM": "1"})
check(m2.get("RESULT", {}).get("ok") is True, "17: pass 2 must import from the draft: %s" % m2.get("REVIEW"))
check(m2["INFER"]["model"] == "Fenix 7X Solar", "17: the edit did not reach the form")
check(m2["INFER"]["description"] == FILLED_SMART["description"],
      "17: description lost between draft and form")
check(m2["RESULT"].get("desc_ok") is True,
      "17: the readback must confirm the description saved: %s" % m2["RESULT"].get("desc_ok"))
# the v7 harness bug: the form held a spec template instead of the text sent
m2t, _ = run(SMART, SMART_AD, {"CONFIRM": "1"},
             saved_description="Garmin Fenix 7X Solar\n\nSpecificații:\n- Mecanism: smart")
check(m2t["RESULT"].get("desc_ok") is False,
      "17: a description the form did not keep must read back desc_ok=False")

# --- 17b. the seller's text handed back unchanged is a fix, not an import ------
check("description" in _d["_todo"], "17b: description must always be asked")
_d["description"] = olx_api.clean_description(SMART_AD["description"])
json.dump(_d, open(_dp, "w"))
m2b, st2b = run(SMART, SMART_AD, {"CONFIRM": "1"})
check(any(r.get("code") == "description_unedited" and r.get("action") == "fix"
          for r in (m2b.get("REVIEW") or {}).get("reasons", [])),
      "17b: an unedited description must stop as a fix, got %s" % m2b.get("REVIEW"))
check(st2b["imported"] is None, "17b: an unedited description must not import")

# --- 17c. the description stays in the seller's voice (user directive 2026-10-04) ---
def _desc_codes(desc):
    _d["description"] = desc
    json.dump(_d, open(_dp, "w"))
    m, st = run(SMART, SMART_AD, {"CONFIRM": "1"})
    return [r.get("code") for r in (m.get("REVIEW") or {}).get("reasons", [])], st
# the 2026-10-04 listings: a third voice narrating the seller and the photos
codes, st = _desc_codes(FILLED_SMART["description"] + " Vânzătorul precizează că "
                        "funcționează. Fotografiile prezintă ceasul, iar în anunț sunt "
                        "disponibile și alte imagini.")
check("description_meta" in codes, "17c: a text about the seller/ad/photos must stop: %s" % codes)
check(st["imported"] is None, "17c: a text about the seller/ad/photos must not import")
# a wholesale rewrite: hardly a word of it is the seller's
codes, _ = _desc_codes("Garmin Fenix 7X Solar este un ceas smart outdoor robust, cu carcasă "
                       "rezistentă, ecran transflectiv mare, lanternă integrată și încărcare "
                       "solară prin geamul Power Glass, potrivit pentru drumeții lungi.")
check("description_drifted" in codes, "17c: a rewrite must stop as drifted: %s" % codes)
# a light edit plus a short clause of ours still passes
codes, _ = _desc_codes("Ceas Garmin Fenix 7X Solar de 51 mm, negru, în stare foarte bună, "
                       "folosit un an.\nVine cu încărcător și cutie.\n\nAre GPS și hărți, "
                       "autonomie excelentă.")
check(not [c for c in codes if c.startswith("description")],
      "17c: a light edit must pass: %s" % codes)
_d["description"] = FILLED_SMART["description"] + " Contact: 0745 123 456"
json.dump(_d, open(_dp, "w"))
m2c, _ = run(SMART, SMART_AD, {"CONFIRM": "1"})
check(m2c["INFER"]["description"] == FILLED_SMART["description"],
      "17b: a phone in OUR text must be stripped too: %r" % m2c["INFER"]["description"])
_d["description"] = FILLED_SMART["description"]
json.dump(_d, open(_dp, "w"))

# --- 18. blanking a field in the draft still clears it -----------------------
_d["gender"] = None
json.dump(_d, open(_dp, "w"))
m3, _ = run(SMART, SMART_AD, {"CONFIRM": "1"})
check(m3["INFER"].get("gender") is None,
      "18: a field blanked in the draft must be CLEARED, not restored from the params")

# --- 18b. an unanswered _todo is a REVIEW, never a silent null ---------------
_d["model"] = None
json.dump(_d, open(_dp, "w"))
m3b, st3b = run(SMART, SMART_AD, {"CONFIRM": "1"})
check("REVIEW" in m3b, "18b: a draft with a null required field must stop")
check(any(r.get("code") == "draft_invalid" for r in m3b["REVIEW"]["reasons"]),
      "18b: the stop must carry the draft_invalid code, got %s" % m3b.get("REVIEW"))
check(st3b["imported"] is None, "18b: an unanswered _todo must not import")
_d["model"] = "Fenix 7X Solar"
json.dump(_d, open(_dp, "w"))

# --- 19. OVERRIDES still wins, for a human one-off fix -----------------------
m4, _ = run(SMART, SMART_AD, {"CONFIRM": "1", "OVERRIDES": json.dumps({"model": "Fenix 7"})})
check(m4["INFER"]["model"] == "Fenix 7", "19: OVERRIDES must override the draft")
check(m4["INFER"]["description"] == FILLED_SMART["description"],
      "19: a one-field OVERRIDES on top of a draft must keep the rest of the draft")

# --- 21. every REVIEW reason is machine-readable ----------------------------
# The runbook routes on `action` alone, so a reason without one is a judgement
# call handed back to the model -- which is the thing this work removes.
for _label, _mk in (("smart facets", lambda: run(SMART, SMART_AD, {"OVERRIDES": json.dumps(
                         dict(FILLED_SMART, connectivity=None, compatibility=None))})),
                    ("misroute", lambda: run(SMART, SMART_AD, {"OVERRIDES": json.dumps(
                         dict(FILLED_SMART, movement="automatic"))})),
                    ("movement", lambda: run(CLASSIC, NO_MOVEMENT, {"OVERRIDES": json.dumps(
                         dict(FILLED_CLASSIC, movement=None))}))):
    _m, _ = _mk()
    _rs = _m.get("REVIEW", {}).get("reasons", [])
    check(_rs and all(isinstance(r, dict) for r in _rs), "21: %s: reasons must be objects" % _label)
    check(all(r.get("code") and r.get("action") in ("fix", "skip") for r in _rs),
          "21: %s: every reason needs a code and a fix/skip action: %s" % (_label, _rs))

# --- 20. the importer marks the queue on every terminal path -----------------
import tempfile
import candidates as _q

def _queue(ad_id):
    _qp = os.path.join(tempfile.mkdtemp(), "q.json")
    json.dump({"source": "olx", "profile": "smart",
               "candidates": [{"id": str(ad_id), "status": "pending"}]}, open(_qp, "w"))
    return _qp

def _fill_smart_draft(**over):
    _p = contract_draft.draft_path(ROOT, SMART_AD["id"])
    _d = json.load(open(_p))
    _d.update({"model": "Fenix 7X Solar", "connectivity": "no_gsm", "compatibility": "both",
               "is_wristwatch": True, "is_bulk_lot": False})
    _d.update(over)
    json.dump(_d, open(_p, "w"))

_fill_smart_draft()
_qp = _queue(SMART_AD["id"])
m, _ = run(SMART, SMART_AD, {"CONFIRM": "1", "CANDIDATES_FILE": _qp})
check(m.get("RESULT", {}).get("ok") is True, "20: should import")
check(_q.load(_qp)["candidates"][0]["status"] == "imported",
      "20: a successful import must mark the queue")

# a SKIP marks the queue with the reason code
_qp = _queue(SMART_AD["id"])
m, _ = run(SMART, dict(SMART_AD, status="removed_by_user"), {"CANDIDATES_FILE": _qp})
_c = _q.load(_qp)["candidates"][0]
check(_c["status"] == "skipped" and _c["reason"] == "not_active",
      "20: a skip must mark the queue with its reason code, got %s" % _c)

# a REVIEW whose reasons are all action=skip ends the watch, so the queue records it
_fill_smart_draft(movement="automatic")
_qp = _queue(SMART_AD["id"])
m, _ = run(SMART, SMART_AD, {"CANDIDATES_FILE": _qp})
_c = _q.load(_qp)["candidates"][0]
check(_c["status"] == "skipped" and _c["reason"] == "misrouted_classic",
      "20: an action=skip REVIEW must mark the queue with the gate's code, got %s" % _c)

# ...but a REVIEW that is purely action=fix leaves the candidate PENDING: the gate
# named what to supply, so the queue must still point at it.
_fill_smart_draft(movement=None, connectivity=None)
_qp = _queue(SMART_AD["id"])
m, _ = run(SMART, SMART_AD, {"CANDIDATES_FILE": _qp})
check("REVIEW" in m, "20: a missing facet must stop for review")
check(all(r["action"] == "fix" for r in m["REVIEW"]["reasons"]),
      "20: connectivity/draft reasons are fixable: %s" % m["REVIEW"]["reasons"])
check(_q.load(_qp)["candidates"][0]["status"] == "pending",
      "20: a fixable REVIEW must leave the candidate pending")
_fill_smart_draft()

# bookkeeping must never be fatal: a broken queue path warns and imports anyway
m, _ = run(SMART, SMART_AD, {"CONFIRM": "1", "CANDIDATES_FILE": "/nonexistent/dir/q.json"})
check(m.get("RESULT", {}).get("ok") is True,
      "20: a queue-marking failure must not lose an import that succeeded")
check("WARN" in m, "20: a queue-marking failure must be reported")

# --- 22. the gates fire under CONFIRM=1, which every documented pass 2 sets ---
# Every check above ran its gate WITHOUT CONFIRM, so none of them noticed that
# `and not CONFIRM` made the gates dead in real use: ad 309588599 imported on
# 2026-09-20 with is_wristwatch=false and one photo.
for _label, _script, _ad, _ov, _want in (
        ("not_a_watch smart",   SMART,   SMART_AD,   dict(FILLED_SMART, is_wristwatch=False), "SKIP"),
        ("not_a_watch classic", CLASSIC, CLASSIC_AD, dict(FILLED_CLASSIC, is_wristwatch=False), "SKIP"),
        ("bulk_lot",            SMART,   SMART_AD,   dict(FILLED_SMART, is_bulk_lot=True), "SKIP"),
        ("misrouted_classic",   SMART,   SMART_AD,   dict(FILLED_SMART, movement="automatic"), "REVIEW"),
        ("movement_missing",    CLASSIC, CLASSIC_AD, dict(FILLED_CLASSIC, movement=None), "REVIEW"),
        ("misrouted_smart",     CLASSIC, CLASSIC_AD, dict(FILLED_CLASSIC, movement="smart"), "REVIEW"),
        ("connectivity",        SMART,   SMART_AD,   dict(FILLED_SMART, connectivity=None), "REVIEW"),
        ("thin_description",    SMART,   SMART_AD,   dict(FILLED_SMART, description="ok"), "REVIEW")):
    _m, _st = run(_script, _ad, {"CONFIRM": "1", "OVERRIDES": json.dumps(_ov)})
    check(_want in _m, "22: %s must %s under CONFIRM=1, got %s" % (_label, _want, sorted(_m)))
    check(_st["imported"] is None, "22: %s must not import under CONFIRM=1" % _label)
    check("RESULT" not in _m, "22: %s must not reach RESULT: under CONFIRM=1" % _label)

# the real pass 2 reads the draft from disk, with no OVERRIDES
for _label, _over, _want in (("not_a_watch", {"is_wristwatch": False}, "SKIP"),
                             ("bulk_lot", {"is_bulk_lot": True}, "SKIP"),
                             ("misrouted_classic", {"movement": "automatic"}, "REVIEW")):
    _fill_smart_draft(**_over)
    _m, _st = run(SMART, SMART_AD, {"CONFIRM": "1"})
    check(_want in _m and _st["imported"] is None,
          "22: %s from the draft must %s under CONFIRM=1, got %s" % (_label, _want, sorted(_m)))
_fill_smart_draft(movement=None)       # the base fill does not reset movement

# too few photos: the exact shape of 309588599
_m, _st = run(SMART, dict(SMART_AD, photos=SMART_AD["photos"][:1]),
              {"CONFIRM": "1", "OVERRIDES": json.dumps(FILLED_SMART)})
check(any(r["code"] == "too_few_images" for r in _m.get("REVIEW", {}).get("reasons", [])),
      "22: one photo must stop for too_few_images under CONFIRM=1, got %s" % sorted(_m))
check(_st["imported"] is None, "22: a one-photo ad must not import")

# a new brand is not a gate: it imports and hands off through NEW_BRAND:
_m, _st = run(SMART, SMART_AD, {"CONFIRM": "1",
                                "OVERRIDES": json.dumps(dict(FILLED_SMART, brand="Zxcvbnwatch"))})
check("REVIEW" not in _m, "22: a new brand must not stop for review: %s" % _m.get("REVIEW"))
check(_m.get("RESULT", {}).get("ok") is True and "NEW_BRAND" in _m,
      "22: a new brand must import and emit NEW_BRAND:, got %s" % sorted(_m))

# --- 23. the admin's JSON endpoints, when they are deployed -------------------
# The same pass 2, written through import-json instead of the DOM. Everything the
# agent and olx-step read — the marker lines, the RESULT: keys, the routing — must be
# what the DOM path produces.
import site_api

def jenv(obj, http=200):
    return {"http": http, "redirected": False, "url": "https://3ceasuri.ro/admin/x/",
            "ctype": "application/json", "body": json.dumps(obj, ensure_ascii=False)}

LOGIN = {"http": 200, "redirected": True,
         "url": "https://3ceasuri.ro/admin/login/?next=/admin/watches/watch/import-json/",
         "ctype": "text/html; charset=utf-8", "body": "<form id=login-form>"}

def created(pictures=3, brand=None, image_errors=()):
    """A 201 built from what was posted, stored the way the server stores it."""
    def answer(req):
        w = req["json"]["watch"]
        saved = {f: w.get(f) for f in site_api.CONTRACT_TO_MODEL.values()}
        saved["price"] = "%.2f" % float(w["price"])
        return jenv({"pk": 1454, "change_url": "/admin/watches/watch/1454/change/",
                     "public_url": "/ceas/garmin-fenix-7x-solar-ab12cd/", "pictures": pictures,
                     "image_errors": list(image_errors),
                     "brand": brand or {"id": 58, "name": "Garmin", "created": False},
                     "saved": saved}, 201)
    return answer

def deployed_site(imports=(), existing=None, reposts=None, appears=None, brand_found=None):
    """A deployed admin. `imports`: the import-json answers in order. `appears`: the
    lookup (counted after the first POST) from which the ad id is on the site."""
    answers, seen = list(imports), {"posted": False, "after": 0}
    def route(req):
        path = req["path"]
        if path.startswith("/admin/watches/watch/lookup/"):
            ids = re.search(r"ids=([^&]*)", path).group(1).split(",")
            ex = {i: existing[i] for i in ids if existing and i in existing}
            if seen["posted"] and ids != ["0"]:
                seen["after"] += 1
                if appears and seen["after"] >= appears:
                    ex.update({i: {"pk": 1454, "source": "olx", "is_active": True,
                                   "status": "active", "brand": "Garmin",
                                   "model_name": "Fenix 7X Solar", "seller_id": "529077689",
                                   "pictures": 3, "change_url": "/x/"} for i in ids})
            return jenv({"existing": ex, "missing": [i for i in ids if i not in ex]})
        if path.startswith("/admin/watches/watch/reposts/"):
            return jenv(reposts or {"by_seller": [], "by_model": []})
        if path.startswith("/admin/watches/brand/lookup/"):
            return jenv({"found": brand_found or {}, "missing": []})
        if path.startswith("/admin/watches/watch/import-json/"):
            seen["posted"] = True
            a = answers.pop(0)
            return a(req) if callable(a) else a
        return None
    return route

def posts(st):
    return [r for r in st["site_calls"] if r["path"].startswith("/admin/watches/watch/import-json/")]

def dom_used(st):
    return (st["imported"] is not None or st["injected"] > 0
            or any("3ceasuri.ro/admin/watches/" in u for u in st["visited"]))

_env = {"CONFIRM": "1", "OVERRIDES": json.dumps(FILLED_SMART)}
_dom, _ = run(SMART, SMART_AD, _env)                     # the DOM path, for the shapes

_qp = _queue(SMART_AD["id"])
m, st = run(SMART, SMART_AD, dict(_env, CANDIDATES_FILE=_qp), site=deployed_site([created()]))
r = m.get("RESULT") or {}
check(r.get("ok") is True, "23: import-json must import: %s" % sorted(m))
check(not dom_used(st), "23: with the API on, no inject / importWatch / admin page loads")
check(set(r) == set(_dom["RESULT"]), "23: RESULT keys must equal the DOM path's: %s vs %s"
      % (sorted(r), sorted(_dom["RESULT"])))
import admin_import
_rb_keys = set(re.findall(r"(\w+):", re.search(r"JSON\.stringify\(\{(.*)\}\)",
                                                admin_import._READBACK_JS).group(1))) - {"id", "i"}
if ",imgs}" in admin_import._READBACK_JS:               # ES shorthand, no colon
    _rb_keys.add("imgs")
check(set(r.get("readback") or {}) == _rb_keys,
      "23: readback keys must equal the DOM readback's (_READBACK_JS): %s vs %s"
      % (sorted(r.get("readback") or {}), sorted(_rb_keys)))
check(r.get("banners") == {"images_ok": True, "added_ok": True, "via": "api"},
      "23: banners %s" % r.get("banners"))
check(r.get("readback_ok") is True and r.get("desc_ok") is True, "23: readback_ok / desc_ok")
check(len(r["readback"]["desc"]) <= 120, "23: history.jsonl gets 120 chars of the description")
check(r["readback"]["price"] == "1700.00" and r["readback"]["brandId"] == "58"
      and r["readback"]["imgs"] == 3 and r["readback"]["extId"] == "307673714",
      "23: readback from `saved`: %s" % r.get("readback"))
check("NEW_BRAND" not in m, "23: a brand in BRAND_IDS is not a NEW_BRAND")
check(_q.load(_qp)["candidates"][0]["status"] == "imported", "23: the queue is marked imported")
_p = posts(st)[0]["json"]
check(_p["brand"] == {"name": "Garmin"} and _p["create_brand"] is True and _p["dry_run"] is False,
      "23: brand / create_brand / dry_run: %s" % {k: _p[k] for k in ("brand", "create_brand", "dry_run")})
check(_p["image_urls"] == olx_api.photo_urls(SMART_AD), "23: the server fetches the OLX photo URLs")
_w = _p["watch"]
check(_w["model_name"] == "Fenix 7X Solar" and _w["movement"] == "smart"
      and _w["external_listing_id"] == "307673714" and _w["source"] == "olx"
      and _w["seller_id"] == "529077689" and _w["description"] == FILLED_SMART["description"],
      "23: the watch fields: %s" % _w)
check("is_wristwatch" not in _w and "brand" not in _w and "images" not in _w,
      "23: only model fields are sent")
check("location" not in _w and _w.get("county") == "București",
      "23: county/city are sent, the free-text location is not: %s" % _w)

# NEW_BRAND: whenever the contract's brand is not in BRAND_IDS, with the server's name/id
for _created in (True, False):
    m, st = run(SMART, SMART_AD, {"CONFIRM": "1", "OVERRIDES": json.dumps(
        dict(FILLED_SMART, brand="Zxcvbnwatch"))}, site=deployed_site([created(
            brand={"id": 266, "name": "ZXCVBN Watch", "created": _created})]))
    nb = m.get("NEW_BRAND") or {}
    check(m.get("RESULT", {}).get("ok") is True, "23: new brand (created=%s) imports" % _created)
    check(nb.get("name") == "ZXCVBN Watch" and nb.get("id") == 266 and nb.get("created") is _created
          and nb.get("via") == "api", "23: NEW_BRAND (created=%s) carries the server's brand: %s"
          % (_created, nb))
    check(m["RESULT"].get("new_brand") == {"name": "ZXCVBN Watch", "id": 266},
          "23: RESULT new_brand %s" % m["RESULT"].get("new_brand"))

# 422 no_images -> the photos are uploaded from the admin tab, then imported
_no_images = jenv({"error": "no_images", "image_errors": [{"url": "u", "error": "403"}]}, 422)
m, st = run(SMART, SMART_AD, _env, site=deployed_site([_no_images, created()]))
check(m.get("RESULT", {}).get("ok") is True, "23: 422 then multipart must import: %s" % sorted(m))
_ps = posts(st)
check(len(_ps) == 2 and "blobs" not in _ps[0] and len(_ps[1].get("blobs") or []) == 3,
      "23: the retry is multipart with the 3 staged photos: %s" % [sorted(p) for p in _ps])
check(st["staged"] == 3 and not dom_used(st), "23: staged, never the DOM path")
m, st = run(SMART, SMART_AD, _env, site=deployed_site([_no_images, _no_images]))
check("ERROR" in m and "RESULT" not in m and not dom_used(st),
      "23: a second 422 is an ERROR, got %s" % sorted(m))
m, st = run(SMART, SMART_AD, dict(_env, FORCE_IMAGE_UPLOAD="1"), site=deployed_site([created()]))
check(m.get("RESULT", {}).get("ok") is True and posts(st)[0].get("blobs"),
      "23: FORCE_IMAGE_UPLOAD=1 goes straight to the multipart upload")

# 409 -> already imported
m, st = run(SMART, SMART_AD, _env, site=deployed_site([jenv(
    {"error": "duplicate", "existing": {"pk": 9, "change_url": "/x/", "is_active": False}}, 409)]))
check(m.get("SKIP", {}).get("reason", "").startswith("already imported"),
      "23: 409 is SKIP already_imported, got %s" % sorted(m))

# 409 duplicate_photos -> the server's photo check: a skip, never a retry or the DOM path
_dup_photos = jenv({"error": "duplicate_photos", "duplicate_of": 741,
                    "external_listing_id": "299454774", "source": "olx", "shared": 3,
                    "change_url": "/admin/watches/watch/741/change/"}, 409)
_qp = _queue(SMART_AD["id"])
m, st = run(SMART, SMART_AD, dict(_env, CANDIDATES_FILE=_qp), site=deployed_site([_dup_photos]))
_s = m.get("SKIP") or {}
check(_s.get("reason", "").startswith("duplicate_photos") and "pk 741" in _s["reason"]
      and _s.get("duplicate_of") == "299454774" and (_s.get("existing") or {}).get("pk") == 741,
      "23: 409 duplicate_photos is SKIP duplicate_photos carrying the listing: %s"
      % (_s or sorted(m)))
check(len(posts(st)) == 1 and not dom_used(st), "23: duplicate_photos is never re-posted")
_c = _q.load(_qp)["candidates"][0]
check(_c["status"] == "skipped" and _c.get("reason") == "duplicate_photos",
      "23: the queue records duplicate_photos: %s" % _c)
check("allow_duplicate_photos" not in posts(st)[0]["json"],
      "23: the override is not sent unless a human set it")
m, st = run(SMART, SMART_AD, dict(_env, ALLOW_DUPLICATE_PHOTOS="1"), site=deployed_site([created()]))
check(m.get("RESULT", {}).get("ok") is True
      and posts(st)[0]["json"].get("allow_duplicate_photos") is True,
      "23: ALLOW_DUPLICATE_PHOTOS=1 waves the server's check through too")

# 400 -> REVIEW server_invalid: fix only what `finish` can answer
for _field, _key, _action in (("movement", "movement", "fix"), ("source_url", "sourceUrl", "skip"),
                              ("__all__", None, "skip"), ("brand", "brand", "fix")):
    m, st = run(SMART, SMART_AD, _env, site=deployed_site([jenv(
        {"errors": {_field: ["Select a valid choice."]}}, 400)]))
    rs = (m.get("REVIEW") or {}).get("reasons") or [{}]
    check(rs[0].get("code") == "server_invalid" and rs[0].get("field") == _key
          and rs[0].get("action") == _action and "Select a valid choice." in rs[0].get("message", ""),
          "23: 400 on %s -> server_invalid field=%r action=%s, got %s" % (_field, _key, _action, rs))
    check(not dom_used(st), "23: a 400 never falls back to the DOM path")

# a lost session and a 403 are errors, never a fallback
m, st = run(SMART, SMART_AD, _env, site=deployed_site([LOGIN]))
check("session lost" in (m.get("ERROR") or {}).get("msg", "") and not dom_used(st),
      "23: a login redirect is ERROR 'session lost', got %s" % m.get("ERROR"))
m, st = run(SMART, SMART_AD, _env, site=deployed_site([jenv({"detail": "no add permission"}, 403)]))
check("403" in (m.get("ERROR") or {}).get("msg", "") and not dom_used(st),
      "23: a 403 is an ERROR, got %s" % m.get("ERROR"))
m, st = run(SMART, SMART_AD, _env, site=deployed_site([{
    "http": 413, "redirected": False, "url": "https://3ceasuri.ro/admin/watches/watch/import-json/",
    "ctype": "text/html", "body": "<h1>413 Request Entity Too Large</h1>"}]))
_lk = [r for r in st["site_calls"] if "lookup/?ids=%s" % SMART_AD["id"] in r["path"]]
check("413" in (m.get("ERROR") or {}).get("msg", "") and len(_lk) == 1 and not dom_used(st),
      "23: a 413 is an immediate ERROR (the proxy refused it; no lookup wait): %s" % m.get("ERROR"))
def _lost_probe(req):
    return LOGIN
m, st = run(SMART, SMART_AD, _env, site=_lost_probe)
check("session lost" in (m.get("ERROR") or {}).get("msg", "") and not dom_used(st),
      "23: a lost session at the probe is ERROR, not 'not deployed': %s" % sorted(m))

# anything else: ask lookup/ over 45 s, never re-send, never the DOM path
_500 = {"http": 500, "redirected": False, "url": "https://3ceasuri.ro/admin/watches/watch/import-json/",
        "ctype": "text/html", "body": "<h1>Server Error (500)</h1>"}
m, st = run(SMART, SMART_AD, _env, site=deployed_site([_500], appears=2))
check(m.get("RESULT", {}).get("ok") is True, "23: a 500, then lookup finds it: RESULT ok, got %s"
      % sorted(m))
check(m["RESULT"]["readback"]["imgs"] == 3 and m["RESULT"]["readback_ok"] is True,
      "23: the readback comes from the lookup row: %s" % m["RESULT"].get("readback"))
check(len(posts(st)) == 1 and not dom_used(st), "23: never re-sent, never the DOM path")
m, st = run(SMART, SMART_AD, _env, site=deployed_site([_500]))
_lk = [r for r in st["site_calls"] if "lookup/?ids=%s" % SMART_AD["id"] in r["path"]]
check("ERROR" in m and "500" in m["ERROR"]["msg"] and "RESULT" not in m,
      "23: never found -> ERROR with the status, got %s" % sorted(m))
check(len(_lk) == 1 + 4, "23: lookup is asked 4 times after the POST (0/15/30/45 s), got %d"
      % (len(_lk) - 1))
check(len(posts(st)) == 1 and not dom_used(st), "23: never re-sent, never the DOM path")
m, st = run(SMART, SMART_AD, _env, site=deployed_site(["TIMEOUT"], appears=1))
check(m.get("RESULT", {}).get("ok") is True and not dom_used(st),
      "23: a page that never answers is checked with lookup too, got %s" % sorted(m))

# DRY_RUN=1 asks the server for its verdict and writes nothing
m, st = run(SMART, SMART_AD, dict(_env, DRY_RUN="1"),
            site=deployed_site([jenv({"valid": True, "would_create_brand": False})]))
r = m.get("RESULT") or {}
check(r.get("dry_run") is True and r.get("server", {}).get("answer", {}).get("valid") is True,
      "23: DRY_RUN prints the server's verdict: %s" % r)
check(posts(st)[0]["json"]["dry_run"] is True and not dom_used(st), "23: DRY_RUN sends dry_run")

# the lookups replace the changelist searches
m, st = run(SMART, SMART_AD, _env, site=deployed_site(existing={str(SMART_AD["id"]): {"pk": 5}}))
check(m.get("SKIP", {}).get("reason", "").startswith("already imported") and not st["fetched"],
      "23: stage-1 dedup through lookup/, before any OLX read: %s" % sorted(m))
check(not dom_used(st), "23: no changelist search for the stage-1 dedup")
m, st = run(SMART, SMART_AD, _env, site=deployed_site(reposts={"by_seller": [
    {"pk": 3, "external_listing_id": "999", "source": "olx", "is_active": True,
     "brand": "Garmin", "model_name": "Fenix 7X Solar", "seller_id": "529077689"}], "by_model": []}))
check(m.get("SKIP", {}).get("reason", "").startswith("repost") and not posts(st),
      "23: a same-seller row from reposts/ is a strong repost: %s" % sorted(m))
_rq = [r["path"] for r in st["site_calls"] if r["path"].startswith("/admin/watches/watch/reposts/")]
check(_rq and "exclude_id=%s" % SMART_AD["id"] in _rq[0] and "seller_id=529077689" in _rq[0],
      "23: reposts/ is asked with the seller and this ad excluded: %s" % _rq)

# API=off keeps the DOM path even with the endpoints deployed
m, st = run(SMART, SMART_AD, dict(_env, API="off"), site=deployed_site([created()]))
check(m.get("RESULT", {}).get("ok") is True and st["imported"] is not None and not st["site_calls"],
      "23: API=off is the kill switch back to the DOM path")

# --- 24. pass-1 regressions of 2026-10-07 -----------------------------------
import contract_draft as _cd


def _draft_of(ad_id):
    p = _cd.draft_path(ROOT, ad_id)
    d = json.load(open(p)) if os.path.exists(p) else {}
    for f in _glob.glob(os.path.join(ROOT, "harness/3ceasuri-import/.contracts",
                                     "olx-%s.*" % ad_id)):
        os.remove(f)                     # a fake id never stays in the real drafts folder
    return d


# two watches, each with its own "Pret:" line -> bulk_lot, before any photo is fetched
_two = dict(CLASSIC_AD, id=900000001, title="Ceas Doxa Mecanic",
            description="Ceas Doxa Mecanic, anii 60.<br />Pret: 580 lei<br /><br />"
                        "Ceas Doxa Automatic, anii 60.<br />Pret: 570 lei")
m, st = run(CLASSIC, _two)
check(m.get("SKIP", {}).get("reason", "").startswith("bulk_lot")
      and "EXTRACT_PROMPT" not in m, "24: two labelled prices must skip as bulk_lot: %s"
      % (m.get("SKIP") or sorted(m)))
_draft_of(900000001)

# "atât estetic cât și mecanic" is condition, not a hand-wound movement (Tudor 1926)
_cond = dict(CLASSIC_AD, id=900000002, title="Ceas Tudor 1926 36mm",
             description="Purtat de doar 3 ori.<br />Condiție impecabilă, atât estetic cât "
                         "și mecanic.<br />Full set, cutie și acte.")
m, st = run(CLASSIC, _cond)
_d = _draft_of(900000002)
check("EXTRACT_PROMPT" in m and not _d.get("movement") and "movement" in _d.get("_todo", []),
      "24: a condition phrase must not seed movement=manual: %r" % _d.get("movement"))

# a trade offer names watches the seller would TAKE: never the brand
_trade = dict(CLASSIC_AD, id=900000003, title="Ceas chronograph automatic",
              params=[p for p in CLASSIC_AD["params"] if p.get("key") != "brand"],
              description="Se vinde ceas automatic, bine întreținut.<br />Accept schimb cu "
                          "Tissot Connect sau cu Garmin solar.<br />Curea piele.")
m, st = run(CLASSIC, _trade)
_d = _draft_of(900000003)
check(_d.get("brand") != "Tissot" and "brand" in _d.get("_todo", []),
      "24: a trade offer must not seed the brand: %r" % _d.get("brand"))
check(_d.get("movement") == "automatic", "24: the real movement still seeds: %r" % _d.get("movement"))

# the same photo files as an IMPORTED ad (history.jsonl) -> duplicate_photos
import tempfile as _tf
_root = _tf.mkdtemp(prefix="olx-test-dup-")
_imported = "303404526"            # CLASSIC_AD, imported for real on 2026-08-12
os.makedirs(os.path.join(_root, "olx-" + _imported))
_b64 = "QUJD" * 3000               # 9000 bytes decoded: a real-sized photo
import base64 as _b
for _n in ("01.jpg", "02.jpg"):
    open(os.path.join(_root, "olx-" + _imported, _n), "wb").write(_b.b64decode(_b64))
_dup = dict(CLASSIC_AD, id=900000004)
m, st = run(CLASSIC, _dup, env={"PHOTO_ROOT": _root}, photo_b64=_b64)
check(m.get("SKIP", {}).get("reason", "").startswith("duplicate_photos")
      and m["SKIP"].get("duplicate_of") == _imported and "EXTRACT_PROMPT" not in m,
      "24: photos identical to an imported ad must skip: %s" % (m.get("SKIP") or sorted(m)))
m, st = run(CLASSIC, _dup, env={"PHOTO_ROOT": _root, "ALLOW_DUPLICATE_PHOTOS": "1"},
            photo_b64=_b64)
check("EXTRACT_PROMPT" in m, "24: ALLOW_DUPLICATE_PHOTOS=1 lets a human wave it through")
_draft_of(900000004)

# --- 25. shop cards are never imported ---------------------------------------
# The shape of TotalConvert's 304459760 / 304460733 (2026-10-07): two different watches,
# each beside the same three shop cards. The cards sit BETWEEN the watch photos here, so
# a URL dropped without its file number would upload the wrong local copies.
_croot = _tf.mkdtemp(prefix="olx-test-cards-")
def _pic(tag):
    return _b.b64encode(((tag + "|") * 2000).encode()[:9000]).decode()
_card_tags = {2: "LOGO", 4: "STOREFRONT", 6: "INSIDE"}       # photo number -> card
os.makedirs(os.path.join(_croot, "olx-900000010"))           # the shop's earlier watch
for _i, _tag in enumerate(["blue1", "LOGO", "blue2", "STOREFRONT", "INSIDE"], 1):
    open(os.path.join(_croot, "olx-900000010", "%02d.jpg" % _i), "wb").write(
        _b.b64decode(_pic(_tag)))
_shop_ad = dict(SMART_AD, id=900000011, photos=photos(6))
_urls = olx_api.photo_urls(_shop_ad)
def _shop_photo(url):
    n = _urls.index(url) + 1
    return _pic(_card_tags.get(n, "orange%d" % n))
_cenv = {"PHOTO_ROOT": _croot}
m, st = run(SMART, _shop_ad, env=_cenv, photo_b64=_shop_photo)
check((m.get("CARDS") or {}).get("dropped") == ["02.jpg", "04.jpg", "06.jpg"],
      "25: pass 1 drops the three cards: %s" % m.get("CARDS"))
check("EXTRACT_PROMPT" in m and "SKIP" not in m,
      "25: the shop's second watch is not a relist: %s" % (m.get("SKIP") or sorted(m)))
check([os.path.basename(p) for p in (m.get("EXTRACT_PROMPT") or {}).get("photos", [])]
      == ["01.jpg", "03.jpg", "05.jpg"], "25: the model is shown only the watch's own photos")
import photo_dedup as _pd
check(len(_pd.load_cards(_SHOP_CARDS)) == 3, "25: the cards are learned into the list")
m, st = run(SMART, _shop_ad, dict(_cenv, CONFIRM="1", OVERRIDES=json.dumps(FILLED_SMART)),
            site=deployed_site([created()]), photo_b64=_shop_photo)
check(m.get("RESULT", {}).get("ok") is True, "25: it imports: %s" % sorted(m))
check(posts(st) and posts(st)[0]["json"]["image_urls"] == [_urls[0], _urls[2], _urls[4]],
      "25: import-json gets only the watch's photo URLs: %s"
      % (posts(st)[0]["json"]["image_urls"] if posts(st) else None))
check(m["RESULT"]["state_entry"]["images"] == 3, "25: history counts the photos imported")
# the uploaded copies are the files those URLs were saved to, not 01-03.jpg
_local = olx_api.photo_data_urls(None, [_urls[0], _urls[2], _urls[4]],
                                 os.path.join(_croot, "olx-900000011"), [1, 3, 5])
check([_b.b64decode(u.split(",", 1)[1])[:7] for u in _local]
      == [b"orange1", b"orange3", b"orange5"], "25: photo_data_urls reads files by number")
# an ad that is nothing but one photo and the cards is too thin to import
_thin = dict(SMART_AD, id=900000012, photos=photos(4))
_turls = olx_api.photo_urls(_thin)
m, st = run(SMART, _thin, env=_cenv, photo_b64=lambda u: _pic(
    ["solo", "LOGO", "STOREFRONT", "INSIDE"][_turls.index(u)]))
check(m.get("SKIP", {}).get("reason", "").startswith("too_few_images")
      and "shop card" in m["SKIP"]["reason"],
      "25: one photo beside the cards is too_few_images: %s" % (m.get("SKIP") or sorted(m)))
for _i in (900000011, 900000012):
    _draft_of(_i)

# --- 26. the model is one the brand already has, or added on purpose --------
# The site refuses a model its brand does not have (2026-10-08): "Watch SE (Gen 2)",
# "SE 2nd generation" and "SE 2022" had become three models of one watch. Pass 1 shows
# the brand's models; pass 2 adds a new one first (watchmodel/ensure/) only when the
# contract says new_model=true, and turns the server's refusal into a `fix`.
_GARMIN_MODELS = {"brand": {"id": 58, "name": "Garmin", "slug": "garmin"},
                  "models": [{"name": "Fenix 7X", "listings": 5},
                             {"name": "Fenix 8 Pro", "listings": 6}]}


def models_site(imports=(), ensured=None):
    """deployed_site() plus the model endpoints; `ensured` is ensure's answer."""
    base = deployed_site(imports)

    def route(req):
        if req["path"].startswith("/admin/watches/watchmodel/list/"):
            return jenv(_GARMIN_MODELS)
        if req["path"] == "/admin/watches/watchmodel/ensure/":
            return ensured or jenv({"model_name": req["json"]["model_name"], "created": True})
        return base(req)
    return route


def ensures(st):
    return [r for r in st["site_calls"] if r["path"] == "/admin/watches/watchmodel/ensure/"]


_mad = dict(SMART_AD, id=900000020)
m, st = run(SMART, _mad, site=models_site())
_ep = m.get("EXTRACT_PROMPT") or {}
check("Fenix 7X" in _ep.get("prompt", "") and "Fenix 8 Pro" in _ep.get("prompt", "")
      and "Garmin already has" in _ep.get("prompt", ""),
      "26: pass 1 shows the brand's models on the site: %s" % sorted(m))
check(_ep.get("models") == ["Fenix 7X", "Fenix 8 Pro"], "26: EXTRACT_PROMPT carries the models")
check("variant" in _ep.get("todo", []), "26: the variant is decided with the model")
_draft_of(900000020)

_refused = jenv({"errors": {"model_name": ["unknown model 'Fenix 7X Solar' for Garmin; send "
                                           "create_model: true to add it"]},
                 "models": ["Fenix 7X", "Fenix 8 Pro"]}, 400)
m, st = run(SMART, SMART_AD, _env, site=models_site([_refused]))
rs = (m.get("REVIEW") or {}).get("reasons") or [{}]
check(rs[0].get("code") == "unknown_model" and rs[0].get("action") == "fix"
      and rs[0].get("field") == "model", "26: a refused model is a fix on `model`: %s" % rs)
check("Fenix 7X, Fenix 8 Pro" in rs[0].get("message", "") and "new_model=true" in rs[0]["message"]
      and "variant" in rs[0]["message"],
      "26: the fix lists the brand's models and both ways out: %s" % rs[0].get("message"))
check((m.get("REVIEW") or {}).get("models") == ["Fenix 7X", "Fenix 8 Pro"],
      "26: the REVIEW carries the models")
check(not ensures(st) and not dom_used(st), "26: no model is added without new_model=true")

_ov = dict(FILLED_SMART, model="Fenix 7X", variant="Solar")
m, st = run(SMART, SMART_AD, {"CONFIRM": "1", "OVERRIDES": json.dumps(_ov)},
            site=models_site([created()]))
check(m.get("RESULT", {}).get("ok") is True, "26: an existing model imports: %s" % sorted(m))
_w = posts(st)[0]["json"]["watch"]
check(_w.get("model_name") == "Fenix 7X" and _w.get("variant") == "Solar",
      "26: model and variant are both sent: %s" % {k: _w.get(k) for k in ("model_name", "variant")})
check(not ensures(st), "26: an existing model is not ensured")

_ov = dict(FILLED_SMART, model="Fenix 9 pro", new_model=True)
m, st = run(SMART, SMART_AD, {"CONFIRM": "1", "OVERRIDES": json.dumps(_ov)},
            site=models_site([created()], ensured=jenv({"model_name": "Fenix 9 Pro",
                                                        "created": True})))
check(m.get("RESULT", {}).get("ok") is True, "26: a new model imports: %s" % sorted(m))
check(len(ensures(st)) == 1 and ensures(st)[0]["json"] == {"brand": "Garmin",
                                                           "model_name": "Fenix 9 pro"},
      "26: new_model=true adds the model first: %s" % ensures(st))
_calls = [r["path"] for r in st["site_calls"]]
check(_calls.index("/admin/watches/watchmodel/ensure/")
      < _calls.index("/admin/watches/watch/import-json/"), "26: ensure runs before the import")
_w = posts(st)[0]["json"]["watch"]
check(_w.get("model_name") == "Fenix 9 Pro" and "new_model" not in _w,
      "26: the import uses the site's spelling, and new_model stays the harness's: %s" % _w)
check((m.get("NEW_MODEL") or {}).get("created") is True, "26: NEW_MODEL: says it was added")

# a brand the site does not have yet: ensure 404s, the import creates both
m, st = run(SMART, SMART_AD, {"CONFIRM": "1", "OVERRIDES": json.dumps(
    dict(FILLED_SMART, brand="Zxcvbnwatch", new_model=True))},
    site=models_site([created(brand={"id": 266, "name": "ZXCVBN Watch", "created": True})],
                     ensured=jenv({"error": "unknown_brand"}, 404)))
check(m.get("RESULT", {}).get("ok") is True, "26: a new brand with its first model imports: %s"
      % sorted(m))

print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
