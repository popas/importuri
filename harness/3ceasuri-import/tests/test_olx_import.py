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
FILLED_SMART = {"brand": "Garmin", "model": "Fenix 7X Solar", "series": "Fenix 7",
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

# --- 7. a smartwatch missing its three facets stops for review -------------
m, st = run(SMART, SMART_AD, env={"OVERRIDES": json.dumps(
    dict(FILLED_SMART, series=None, connectivity=None, compatibility=None))})
check("REVIEW" in m, "7: missing smart facets must stop for review")
for f in ("series", "connectivity", "compatibility"):
    check(any(f in r for r in m["REVIEW"]["reasons"]), "7: %s not flagged" % f)
check(st["imported"] is None, "7: must not import")

# --- 8. an accessory is not a watch ----------------------------------------
m, st = run(SMART, SMART_AD, env={"OVERRIDES": json.dumps(
    dict(FILLED_SMART, is_wristwatch=False, notes="doar curea, nu ceasul"))})
check(m.get("SKIP", {}).get("reason", "").startswith("not a watch"), "8: accessory not skipped: %s" % m.get("SKIP"))
check(st["imported"] is None, "8: must not import an accessory")

# --- 9. a mechanical watch on the smartwatch importer is a routing mistake --
m, st = run(SMART, SMART_AD, env={"OVERRIDES": json.dumps(dict(FILLED_SMART, movement="automatic"))})
check("REVIEW" in m and any("olx-import-watch.py" in r for r in m["REVIEW"]["reasons"]),
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
check("REVIEW" in m and any("movement" in r for r in m["REVIEW"]["reasons"]),
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
ROLEX_AD = dict(CLASSIC_AD, id=307626402,
                title="Ceas Rolex Datejust 36, Aur 18K+Otel, referință 1601",
                description="Ceas Rolex Datejust 36, referință 1601, automat (calibru 1570).")
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

# --- 16. an inactive ad is skipped, not imported --------------------------
m, _ = run(SMART, dict(SMART_AD, status="removed_by_user"))
check(m.get("SKIP", {}).get("reason", "").startswith("ad is not active"), "16: inactive ad: %s" % m.get("SKIP"))

print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
