#!/usr/bin/env python3
"""Offline harness for the two OLX importers: stubs browser-use and the OLX API so
the param map, the contract gates and the provenance fields can be tested without
Chrome (and without touching the live admin)."""
import json, os, re, sys, io, contextlib, time

time.sleep = lambda *a, **k: None      # the scripts' paced waits are irrelevant offline

ROOT = "/Users/stelian/.hermes/proiecte/3ceasuri"
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


def run(script, ad, env=None, admin_rows_for=None):
    """Execute an OLX importer against a canned ad; return (markers, trace)."""
    state = {"url": "", "imported": None, "brand_tab_opened": False, "brand_name": "",
             "fetched": []}
    admin_rows_for = admin_rows_for or (lambda q: [])

    def js(e):
        # Order matters: several payloads are `(async ...)` expressions, so match on
        # a string unique to each before falling through to the generic branches.
        if "String(fr.result)" in e:                                    # photo download
            return "A" * 800
        if 'Accept:"application/json"' in e:                            # the OLX API
            path = re.search(r'fetch\("([^"]+)"', e).group(1)
            state["fetched"].append(path)
            if re.search(r"/api/v1/offers/\d+/", path):
                body = json.dumps({"data": ad})
            else:
                body = json.dumps({"data": [], "metadata": {"total_elements": 0}})
            return json.dumps({"status": 200, "body": body})
        if "createElement('script')" in e:                              # harness injection
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
            return json.dumps({"brandId": "1", "price": "1700", "currency": "RON",
                               "ref": None, "diameter": None, "source": "olx",
                               "extId": str(ad["id"]), "sellerId": str(ad["user"]["id"]),
                               "sellerName": ad["user"]["name"], "imgs": len(ad["photos"])})
        if "location.href" in e:
            return state["url"] or "https://www.olx.ro/"
        return ""

    def new_tab(u):
        state["url"] = u
        return {"targetId": "T2"}

    def goto_url(u):
        state["url"] = u

    g = {"__name__": "__main__", "js": js, "new_tab": new_tab, "goto_url": goto_url,
         "close_tab": lambda t: None, "switch_tab": lambda t: None,
         "list_tabs": lambda: [
             {"targetId": "A", "url": "https://3ceasuri.ro/admin/watches/watch/add/", "title": "add"},
             {"targetId": "O", "url": "https://www.olx.ro/moda-frumusete/ceasuri/", "title": "olx"}]}

    os.environ.clear()
    os.environ.update({"PROJECT_ROOT": ROOT, "AD_ID": str(ad["id"]), "PATH": "/usr/bin:/bin"})
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


# Pass 1 now writes a contract draft to .contracts/, and pass 2 reads it -- so a
# draft left behind by the PREVIOUS run of this file would make check 4 take the
# pass-2 path. Clear them once, at the start, to keep the suite hermetic.
import glob as _glob, shutil as _shutil
_shutil.rmtree(os.path.join(ROOT, "harness/3ceasuri-import/.contracts"), ignore_errors=True)

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
                "description": "Ceas in stare foarte buna, folosit un an. Vine cu incarcator si cutie.",
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
                  "description": "Ceas automatic, cumparat in 2019, stare impecabila. Vine cu cutie si documente.",
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
           "is_wristwatch": True, "is_bulk_lot": False, "notes": None})
json.dump(_d, open(_dp, "w"))
m2, st2 = run(SMART, SMART_AD, {"CONFIRM": "1"})
check(m2.get("RESULT", {}).get("ok") is True, "17: pass 2 must import from the draft: %s" % m2.get("REVIEW"))
check(m2["INFER"]["model"] == "Fenix 7X Solar", "17: the edit did not reach the form")
check(m2["INFER"]["description"].startswith("Ceas in stare foarte buna"),
      "17: description lost between draft and form")

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
check(m4["INFER"]["description"].startswith("Ceas in stare foarte buna"),
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

print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
