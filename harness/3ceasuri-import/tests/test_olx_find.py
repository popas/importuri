#!/usr/bin/env python3
"""Offline harness for the two OLX discovery scripts: stubs browser-use and the
OLX search API so the objective filters can be tested without Chrome.

The filters are the whole contract of these scripts — they are allowed to drop
only what a regex gets right every time, and everything else must survive to be
triaged by hand. Both halves are asserted here."""
import json, os, re, sys, io, contextlib, time, tempfile

time.sleep = lambda *a, **k: None

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
SCRIPTS = os.path.join(ROOT, "harness/3ceasuri-import/scripts")
FIND_SMART = os.path.join(SCRIPTS, "olx-find-smartwatches.py")
FIND_WATCH = os.path.join(SCRIPTS, "olx-find-watches.py")
sys.path.insert(0, SCRIPTS)


def ad(aid, title, price=500, desc="", state_label="Utilizat", status="active",
       business=False, user_id=1000, brand=None, currency="RON", photos=3):
    params = [{"key": "state", "type": "select", "value": {"key": None, "label": state_label}}]
    if brand:
        params.append({"key": "brand", "type": "select", "value": {"key": None, "label": brand}})
    if price is not None:
        params.append({"key": "price", "type": "price",
                       "value": {"value": price, "currency": currency, "negotiable": False}})
    return {"id": aid, "url": "https://www.olx.ro/d/oferta/x-ID%d.html" % aid,
            "title": title, "description": desc, "status": status, "business": business,
            "params": params,
            "photos": [{"link": "https://x/v1/files/%d-RO/image;s={width}x{height}" % i}
                       for i in range(photos)],
            "user": {"id": user_id, "name": "Seller %d" % user_id},
            "location": {"city": {"name": "Cluj-Napoca"}, "region": {"name": "Cluj"}}}


def run(script, offers, env=None, admin_counts=None, lookup=None):
    """Execute a discovery script against a canned API page; return markers.

    `lookup(ids) -> {id: row}` deploys the admin's lookup/ endpoint; without it the
    endpoints are not deployed (the admin's catch-all redirects to /admin/)."""
    state = {"url": "", "site_calls": [], "pending": {}, "q_counts": 0, "paths": []}
    admin_counts = admin_counts or {}
    import site_api
    site_api.reset()

    def site(req):
        if lookup is None or not req["path"].startswith("/admin/watches/watch/lookup/"):
            return {"http": 200, "redirected": True, "url": "https://3ceasuri.ro/admin/",
                    "ctype": "text/html", "body": "<!doctype html>"}
        ids = re.search(r"ids=([^&]*)", req["path"]).group(1).split(",")
        ex = {i: r for i, r in lookup(ids).items() if i in ids}
        return {"http": 200, "redirected": False, "url": "https://3ceasuri.ro" + req["path"],
                "ctype": "application/json",
                "body": json.dumps({"existing": ex, "missing": [i for i in ids if i not in ex]})}

    def js(e):
        if "/*site_api:start*/" in e:
            req = json.loads(re.search(r"const REQ = (.*?); const K = ", e, re.S).group(1))
            key = json.loads(re.search(r'const K = ("[^"]+");', e).group(1))
            state["site_calls"].append(req)
            state["pending"][key] = site(req)
            return key
        if "/*site_api:poll*/" in e:
            key = json.loads(re.search(r'b\[("[^"]+")\]', e).group(1))
            answer = state["pending"].pop(key, None)
            return "" if answer is None else json.dumps(answer)
        if 'Accept:"application/json"' in e:
            path = re.search(r'fetch\("([^"]+)"', e).group(1)
            state["paths"].append(path)
            if "/geo-encoder/regions/" in path:
                return json.dumps({"status": 200, "body": json.dumps({"data": [
                    {"id": 2, "name": "Cluj"}, {"id": 46, "name": "Bucuresti - Ilfov"}]})})
            m = re.search(r"offset=(\d+)", path)
            offset = int(m.group(1)) if m else 0
            page = offers if offset == 0 else []
            return json.dumps({"status": 200, "body": json.dumps(
                {"data": page, "metadata": {"total_elements": len(offers)}})})
        if ".paginator" in e:
            q = re.search(r"[?&]q=([^&\"]+)", state["url"])
            if not q:
                return "83 watchs"
            state["q_counts"] += 1
            return "%d watchs" % admin_counts.get(q.group(1), 0)
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
             {"targetId": "O", "url": "https://www.olx.ro/moda-frumusete/ceasuri/", "title": "olx"}]}

    out_file = os.path.join(tempfile.gettempdir(), "olx-cand-test.json")
    os.environ.clear()
    os.environ.update({"PROJECT_ROOT": ROOT, "PATH": "/usr/bin:/bin", "OUT": out_file,
                       "MAX_PAGES": "1", "DEBUG_DROPS": "1"})
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
    markers["_out_file"] = out_file
    markers["_state"] = state
    return markers


fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)


def ids(markers):
    return [c["id"] for c in markers.get("CANDIDATES", [])]


def why(markers, aid):
    for d in markers.get("DROPPED", []):
        if str(d.get("id")) == str(aid):
            return d["why"]
    return None


# --- smartwatch discovery ---------------------------------------------------
SMART_FEED = [
    ad(1, "Apple Watch Series 9 45mm GPS", price=1200, brand="Apple",
       desc="Stare foarte buna, cu incarcator si cutie originala."),
    ad(2, "Curea Apple Watch 45mm silicon", price=200),                  # accessory
    ad(3, "Husa protectie Apple Watch Ultra", price=180),                # accessory
    ad(4, "Incarcator Samsung Galaxy Watch", price=160),                 # accessory
    ad(5, "Smartwatch replica Apple Watch Ultra AAA+", price=350),       # replica
    ad(6, "Amazfit Bip 5", price=90),                                    # below floor
    ad(7, "Garmin Fenix 7X Solar", price=None),                          # no price
    ad(8, "Samsung Galaxy Watch 6 Classic", price=700, status="removed_by_user"),
    ad(9, "Huawei Watch GT 5 Pro", price=900, business=True,
       desc="Produs resigilat, garantie 2 ani, factura."),               # business: KEPT
    ad(10, "Ceas Poljot automatic vintage", price=600,
       desc="Mecanism automatic rusesc, anii 70."),                      # classic in the smart category
    ad(11, "Apple Watch SE 2 40mm", price=800, user_id=999999),          # blocklist test target
    ad(13, "Apple Watch Ultra 2 49mm sigilat", price=600),               # cheap fake
    ad(12, "Galaxy Watch 5 Pro", price=650, desc="Folosit, stare buna."),  # already imported
]

m = run(FIND_SMART, SMART_FEED, admin_counts={"12": 1})
got = ids(m)
check("1" in got, "smart: a plain Apple Watch must survive")
check("9" in got, "smart: business sellers are KEPT (user directive 2026-08-09)")
check(next(c for c in m["CANDIDATES"] if c["id"] == "9")["business"] is True,
      "smart: a business seller must be FLAGGED so it can be triaged")
check("2" not in got and why(m, 2) == "accessory", "smart: a strap is not a watch (%s)" % why(m, 2))
check("3" not in got and why(m, 3) == "accessory", "smart: a case is not a watch (%s)" % why(m, 3))
check("4" not in got and why(m, 4) == "accessory", "smart: a charger is not a watch (%s)" % why(m, 4))
check("5" not in got and why(m, 5) == "replica", "smart: replica not dropped (%s)" % why(m, 5))
check("6" not in got and why(m, 6) == "price_below_floor", "smart: floor not applied (%s)" % why(m, 6))
check("7" not in got and why(m, 7) == "no_price", "smart: priceless ad kept (%s)" % why(m, 7))
check("8" not in got and why(m, 8) == "not_active", "smart: inactive ad kept (%s)" % why(m, 8))
check("12" not in got and why(m, 12) == "already_imported", "smart: dedup not applied (%s)" % why(m, 12))
check("13" not in got and why(m, 13) == "suspiciously_cheap",
      "smart: a 600 RON Apple Watch Ultra is a fake and must be dropped (%s)" % why(m, 13))
check("10" in got, "smart: a classic watch in this category must be FLAGGED, not dropped")
check(next(c for c in m["CANDIDATES"] if c["id"] == "10")["looks_classic"] is True,
      "smart: looks_classic not flagged")
check(next(c for c in m["CANDIDATES"] if c["id"] == "1")["brand"] == "Apple"
      or next(c for c in m["CANDIDATES"] if c["id"] == "1")["new_brand"] is True,
      "smart: brand hint must be resolved or flagged as new")
check(m["STATS"]["admin_total"] == 83, "smart: admin total not read")

# the candidates file is what a /clear'd context resumes from
saved = json.load(open(m["_out_file"]))
check(saved["profile"] == "smart" and saved["category"] == 1943, "smart: candidates file header wrong")
check(all("text" in c and "url" in c for c in saved["candidates"]),
      "smart: the full record (text + url) must be persisted, not just the snippet")

# blocklist
BL = os.path.join(ROOT, "harness/3ceasuri-import/references/seller-blocklist.json")
blk = json.load(open(BL))
check(any(str(s.get("id")) == "999999" for s in blk.get("olx_sellers", [])) is False,
      "smart: fixture id 999999 should not be in the real blocklist")

# --- classic discovery ------------------------------------------------------
WATCH_FEED = [
    ad(20, "Seiko Prospex SPB077 automatic", price=3500, brand="Seiko",
       desc="Stare impecabila, cutie si acte."),
    ad(21, "Curea de schimb piele 20mm", price=150),                     # accessory
    ad(22, "Mecanism ceas Raketa pentru piese", price=120),              # accessory
    ad(23, "Ceasuri diverse, preturi intre 100 - 900 lei", price=900),   # bulk / price range
    ad(29, "Ceas Rolex Datejust 36, Aur 18K, referinta 1601", price=25000,
       desc="PRET FIX. Accept schimburi cu aur, ceasuri din aur si loturi de "
            "telefoane (sigilate). Ceasul il am de un an."),             # NOT bulk
    ad(30, "Ceas Omega Seamaster referinta 2531 - 3500 lei", price=3500,
       desc="Ceas in stare buna, cu cutie."),                            # NOT bulk
    ad(32, "Ceas Rolex Submariner automatic", price=900,
       desc="Ceas Rolex Submariner, stare buna, functioneaza."),          # cheap fake
    ad(31, "Ceasuri Amanet BKG", price=600, business=True,
       desc="Amanet BKG vinde: Ceas Lee Cooper LC07717 - 200 lei; "
            "Mark Maddox HC3024 - 350 lei; Casio MTP - 180 lei."),       # real stock ad
    ad(24, "Ceas replica Rolex Submariner", price=800),                  # replica
    ad(25, "Ceas dama Casio", price=80),                                 # below floor
    ad(26, "Apple Watch Series 8 45mm", price=1100,
       desc="Smartwatch in stare buna."),                                # smart in this category
    ad(27, "Pendula de perete cu cuc anii 70", price=700,
       desc="Ceas de perete functional, lemn masiv."),                   # wall clock
    ad(28, "Ceas Breitling Avenger Seawolf Amanet BKG", price=9000, business=True,
       desc="Amanet BKG vinde: Ceas Breitling Avenger Seawolf E17370 in stare buna, "
            "mecanism Automatic, 44mm. Garantie 2 ani, factura fiscala."),  # business, ONE watch: KEPT
]

m = run(FIND_WATCH, WATCH_FEED)
got = ids(m)
check("20" in got, "watch: a plain Seiko must survive")
check("28" in got, "watch: a business seller offering ONE watch is KEPT "
      "(only plural-title stock ads drop)")
check("21" not in got and why(m, 21) == "accessory", "watch: strap not dropped (%s)" % why(m, 21))
check("22" not in got and why(m, 22) == "accessory", "watch: parts-only ad not dropped (%s)" % why(m, 22))
check("23" not in got and why(m, 23) == "bulk_or_stock", "watch: price range not dropped (%s)" % why(m, 23))
# Regression, 2026-08-09: the loose bulk rule dropped a real Rolex Datejust because
# the seller accepted "loturi de telefoane" in trade, and a bare numeric range would
# kill any ad whose reference happens to precede its price. Both must survive.
check("29" in got, "watch: 'loturi de telefoane' in a TRADE offer is not a bulk watch lot")
check("30" in got, "watch: 'referinta 2531 - 3500 lei' is a reference + price, not a range")
check("32" not in got and why(m, 32) == "suspiciously_cheap",
      "watch: a 900 RON Rolex is a fake and must be dropped (%s)" % why(m, 32))
check("31" not in got and why(m, 31) == "bulk_or_stock",
      "watch: a plural-titled amanet stock ad must drop (%s)" % why(m, 31))
check("24" not in got and why(m, 24) == "replica", "watch: replica not dropped (%s)" % why(m, 24))
check("25" not in got and why(m, 25) == "price_below_floor", "watch: floor not applied (%s)" % why(m, 25))
check("26" in got and next(c for c in m["CANDIDATES"] if c["id"] == "26")["looks_smart"] is True,
      "watch: a smartwatch here must be FLAGGED and routed, never dropped")
check("27" in got and next(c for c in m["CANDIDATES"] if c["id"] == "27")["looks_wall"] is True,
      "watch: a wall clock must be FLAGGED (the site lists those since 2026-08-09)")
check(next(c for c in m["CANDIDATES"] if c["id"] == "20")["brand"] == "Seiko",
      "watch: known brand not resolved from the OLX brand param")
saved = json.load(open(m["_out_file"]))
check(saved["profile"] == "classic" and saved["category"] == 1677, "watch: candidates file header wrong")

# --- an empty first page is an error, not an empty result ------------------
m = run(FIND_WATCH, [])
check("ERROR" in m and "category 1677" in m["ERROR"]["msg"],
      "empty feed must report an explicit error (bot check / wrong category), got %s" % m.get("ERROR"))

# --- queue: discovery seeds every candidate as pending -----------------------
_doc = json.load(open(m["_out_file"])) if "_out_file" in m else {}
m_q = run(FIND_WATCH, WATCH_FEED)
_doc = json.load(open(m_q["_out_file"]))
check(_doc["candidates"], "queue: discovery wrote no candidates to seed")
check(all(c.get("status") == "pending" for c in _doc["candidates"]),
      "queue: discovery must seed status=pending on every candidate")
# and the work queue can read what discovery wrote, with no adapter in between
sys.path.insert(0, os.path.join(ROOT, "harness/3ceasuri-import/scripts"))
import candidates as _q
check(_q.next_pending(m_q["_out_file"]) is not None,
      "queue: next_pending must understand the file discovery writes")
check(_q.counts(m_q["_out_file"])["pending"] == len(_doc["candidates"]),
      "queue: counts must agree with the file discovery writes")

# --- new drop rules: activation lock and explicit stock ---------------------
# These must be near-zero-false-positive (§6 decision 2): each assertion below that a
# rule does NOT fire is a real historical listing shape that was legitimately imported.
import re as _re
SRC_SMART = open(os.path.join(ROOT, "harness/3ceasuri-import/scripts/olx-find-smartwatches.py")).read()
_ns = {}
exec(_re.search(r"^ACTIVATION_LOCK = .*?\)\n", SRC_SMART, _re.S | _re.M).group(0), {"re": _re}, _ns)
exec(_re.search(r"^EXPLICIT_STOCK = .*?\)\n", SRC_SMART, _re.S | _re.M).group(0), {"re": _re}, _ns)
LOCK, STOCK = _ns["ACTIVATION_LOCK"], _ns["EXPLICIT_STOCK"]

for t in ["Apple Watch blocat icloud, vand pentru piese",
          "are cont apple si nu stiu parola",
          "Activation lock activ, nu il pot debloca"]:
    check(bool(LOCK.search(t)), "lock: should fire on %r" % t)
for t in ["Apple Watch Series 9, resetat din fabrica, fara cont",
          "Se vinde cu contul sters, icloud deconectat",
          "Garmin Fenix, functioneaza impecabil"]:
    check(not LOCK.search(t), "lock: FALSE POSITIVE on %r" % t)

for t in ["Peste 100 bucati disponibile", "lichidari de stocuri, desigilate",
          "avem 20 bucati pe stoc"]:
    check(bool(STOCK.search(t)), "stock: should fire on %r" % t)
for t in ["Vand 1 bucata, stare buna", "ultima bucata ramasa",
          "Ceas Seiko automatic, cutie si acte"]:
    check(not STOCK.search(t), "stock: FALSE POSITIVE on %r" % t)

# the rules are wired into consider(), and report their own drop reason
_LOCK_AD = dict(SMART_FEED[0], id=901,
                title="Apple Watch Series 7 45mm",
                description="Ceasul este blocat icloud, vand pentru piese.")
_STOCK_AD = dict(SMART_FEED[0], id=902,
                 title="Apple Watch Series 7 45mm",
                 description="Peste 30 bucati disponibile, factura si garantie.")
m_d = run(FIND_SMART, SMART_FEED + [_LOCK_AD, _STOCK_AD])
check(why(m_d, 901) == "activation_locked",
      "lock: an activation-locked ad must drop with its own reason (%s)" % why(m_d, 901))
check(why(m_d, 902) == "explicit_stock",
      "stock: a stock ad must drop with its own reason (%s)" % why(m_d, 902))
check("901" not in ids(m_d) and "902" not in ids(m_d), "the new drops must not surface as candidates")

# --- Stage-1 dedup through lookup/ when it is deployed ------------------------
# One request for every candidate id replaces the page-per-id changelist search; it
# must drop exactly the same ids, keep the order and still stop at MAX_CANDIDATES.
m_dom = run(FIND_SMART, SMART_FEED, admin_counts={"12": 1, "9": 1})
m_api = run(FIND_SMART, SMART_FEED, lookup=lambda ids: {"12": {"pk": 1}, "9": {"pk": 2}})
st = m_api["_state"]
batches = [r for r in st["site_calls"] if "ids=0" not in r["path"]]
check(len(batches) == 1, "lookup: one batched request, got %d" % len(batches))
check(st["q_counts"] == 0, "lookup: no per-id changelist search when lookup/ is deployed")
check(ids(m_api) == ids(m_dom), "lookup: the same survivors in the same order: %s vs %s"
      % (ids(m_api), ids(m_dom)))
check(why(m_api, 12) == "already_imported" and why(m_api, 9) == "already_imported",
      "lookup: an id on the site drops as already_imported")
check(m_dom["_state"]["q_counts"] > 0 and not [r for r in m_dom["_state"]["site_calls"]
                                               if "ids=0" not in r["path"]],
      "lookup: not deployed -> the per-id loop, unchanged")
m_cap = run(FIND_SMART, SMART_FEED, env={"MAX_CANDIDATES": "2"},
            lookup=lambda ids: {"1": {"pk": 1}})
m_cap_dom = run(FIND_SMART, SMART_FEED, env={"MAX_CANDIDATES": "2"}, admin_counts={"1": 1})
check(len(ids(m_cap)) == 2 and ids(m_cap) == ids(m_cap_dom) and "1" not in ids(m_cap),
      "lookup: still stops at MAX_CANDIDATES survivors, got %s (per-id loop: %s)"
      % (ids(m_cap), ids(m_cap_dom)))
m_w = run(FIND_WATCH, WATCH_FEED, lookup=lambda ids: {"20": {"pk": 1}})
check("20" not in ids(m_w) and why(m_w, 20) == "already_imported"
      and m_w["_state"]["q_counts"] == 0, "lookup: classic discovery uses it too")

# --- 2026-10-07: two prices, trade offers, the server-side county filter ------
# A dealer's two watches in one ad, one "Pret:" line each, sit below the three-price
# stock rule; a trade offer naming a Garmin made an automatic look like a smartwatch
# and seeded its brand as Tissot.
REGRESS = [
    ad(40, "Ceas Doxa Mecanic", price=580,
       desc="Ceas Doxa Mecanic\nFabricat in Elvetia.\nPret: 580 lei\n"
            "Ceas Doxa Automatic\nFabricat in anii 60.\nPret: 570 lei"),
    ad(41, "Ceas chronograph automatic", price=4499,
       desc="Se vinde ceas automatic bine intretinut. Accept schimb cu Tissot Connect "
            "sau cu Garmin solar. Curea piele."),
    ad(42, "Ceas Seiko 5 automatic", price=900,
       desc="Pret: 900 lei\nPreț nou: 1400 lei"),               # one watch, NOT two
]
m = run(FIND_WATCH, REGRESS)
check("40" not in ids(m) and why(m, 40) == "bulk_or_stock",
      "two labelled prices are two watches (%s)" % why(m, 40))
check("42" in ids(m), "'Pret' + 'Preț nou' is one watch's history, not a second watch")
_c41 = next((c for c in m.get("CANDIDATES", []) if c["id"] == "41"), {})
check(_c41.get("looks_smart") is False, "a trade offer naming Garmin is not a smartwatch")
check(_c41.get("brand") != "Tissot", "a trade offer naming Tissot is not the brand: %s"
      % _c41.get("brand"))
m = run(FIND_SMART, [ad(43, "Apple Watch SE 44mm", price=600,
                        desc="Ceas in stare buna. Accept schimb cu un ceas automatic.")])
check(next(c for c in m["CANDIDATES"] if c["id"] == "43")["looks_classic"] is False,
      "a trade offer for an automatic does not make a smartwatch classic")

# COUNTY filters server-side; the client-side check stays as the net
m = run(FIND_WATCH, WATCH_FEED, env={"COUNTY": "Cluj"})
_s = [p for p in m["_state"]["paths"] if "/api/v1/offers/?" in p]
check(_s and all("region_id=2" in p for p in _s), "COUNTY=Cluj -> region_id=2: %s" % _s)
check(m["STATS"].get("location") == {"region_id": 2}, "STATS reports the filter")
check("20" in ids(m), "a Cluj ad survives COUNTY=Cluj")
m = run(FIND_WATCH, WATCH_FEED, env={"COUNTY": "București"})
_s = [p for p in m["_state"]["paths"] if "/api/v1/offers/?" in p]
check(_s and all("city_id=1" in p for p in _s), "COUNTY=București -> city_id=1: %s" % _s)
check(not ids(m) and why(m, 20) == "wrong_county",
      "the client-side county check still drops what the server let through")
m = run(FIND_WATCH, WATCH_FEED)
check(not any("region_id" in p or "city_id" in p for p in m["_state"]["paths"]),
      "no COUNTY -> no location filter")

print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
