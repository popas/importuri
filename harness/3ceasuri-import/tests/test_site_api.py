#!/usr/bin/env python3
"""Offline checks for site_api: the deployed / session-lost detection, the probe, the
tab switch, the lookups and the import-json request shapes — against a fake browser
whose admin endpoints answer by path. No Chrome, no network."""
import json, os, re, sys, time

time.sleep = lambda *a, **k: None      # the polls are instant offline

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, os.path.join(ROOT, "harness/3ceasuri-import/scripts"))
import site_api

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)


SITE = "https://3ceasuri.ro"


def jenv(obj, http=200, path="/admin/watches/watch/lookup/"):
    return {"http": http, "redirected": False, "url": SITE + path,
            "ctype": "application/json", "body": json.dumps(obj, ensure_ascii=False)}


NOT_DEPLOYED = {"http": 200, "redirected": True, "url": SITE + "/admin/",
                "ctype": "text/html; charset=utf-8", "body": "<!doctype html><title>Admin</title>"}
LOGIN = {"http": 200, "redirected": True,
         "url": SITE + "/admin/login/?next=/admin/watches/watch/lookup/%3Fids%3D0",
         "ctype": "text/html; charset=utf-8", "body": "<form id=login-form>"}


def parse_start(e):
    req = json.loads(re.search(r"const REQ = (.*?); const K = ", e, re.S).group(1))
    key = json.loads(re.search(r'const K = ("[^"]+");', e).group(1))
    return req, key


class Page:
    """Tabs, a current tab, and admin endpoints answering by path via `route(req)`."""

    def __init__(self, route=None, tabs=None, current="O", raw=None, poll=None):
        self.tabs = tabs if tabs is not None else [
            {"targetId": "O", "url": "https://www.olx.ro/d/oferta/x.html"},
            {"targetId": "A", "url": SITE + "/admin/watches/watch/add/"}]
        self.cur = current
        self.route = route or (lambda req: jenv({"existing": {}, "missing": ["0"]}))
        self.raw, self.poll = raw, poll          # override the start / poll answers
        self.calls, self.exprs, self.pending, self.switches = [], [], {}, []

    def list_tabs(self):
        return self.tabs

    def current_tab(self):
        return {"targetId": self.cur, "url": ""}

    def switch_tab(self, t):
        self.cur = t
        self.switches.append(t)

    def js(self, e):
        self.exprs.append(e)
        if "/*site_api:start*/" in e:
            if self.raw is not None:
                return self.raw(e) if callable(self.raw) else self.raw
            req, key = parse_start(e)
            self.calls.append((self.cur, req))
            self.pending[key] = self.route(req)
            return key
        if "/*site_api:poll*/" in e:
            if self.poll is not None:
                return self.poll(e) if callable(self.poll) else self.poll
            key = json.loads(re.search(r'b\[("[^"]+")\]', e).group(1))
            env = self.pending.pop(key, None)
            return "" if env is None else json.dumps(env)
        return ""


def fresh():
    site_api.reset()
    os.environ.pop("API", None)


# --- deployed() / session_lost() -------------------------------------------------
check(site_api.deployed(NOT_DEPLOYED) is False,
      "deployed: the admin's catch-all (redirect to /admin/, HTML 200) is NOT deployed")
check(site_api.deployed({"http": 404, "redirected": False, "url": SITE + "/x",
                         "ctype": "text/html", "body": "nope"}) is False,
      "deployed: an HTML 404 is not deployed")
check(site_api.deployed(jenv({"error": "method_not_allowed"}, 405)) is True,
      "deployed: a 405 JSON answer IS deployed (POST-only endpoints answer GET that way)")
check(site_api.deployed(jenv({"existing": {}})) is True, "deployed: a 200 JSON answer")
check(site_api.deployed(None) is False, "deployed: no envelope is not deployed")
check(site_api.session_lost(LOGIN) is True, "session_lost: a redirect to /admin/login/?next=")
check(site_api.session_lost(NOT_DEPLOYED) is False, "session_lost: /admin/ is not the login page")
check(site_api.session_lost(jenv({})) is False, "session_lost: a JSON answer")

# --- available(): one probe, garbage is False, never a crash ----------------------
fresh()
p = Page()
check(site_api.available(p) is True, "available: a 200 JSON probe is on")
check(p.calls and p.calls[0][1]["path"] == "/admin/watches/watch/lookup/?ids=0",
      "available: the probe is GET lookup/?ids=0, got %s" % p.calls[:1])
site_api.available(p)
site_api.available(p)
check(len(p.calls) == 1, "available: one probe per process, got %d" % len(p.calls))

for label, page in (("'OK' from js()", Page(raw="OK")),
                    ("'' from js()", Page(raw="")),
                    ("a non-JSON poll", Page(poll="this is not json")),
                    ("a JSON poll without an envelope", Page(poll='"OK"')),
                    ("a raising js()", Page(raw=lambda e: (_ for _ in ()).throw(RuntimeError("cdp")))),
                    ("a raising poll", Page(poll=lambda e: (_ for _ in ()).throw(RuntimeError("cdp")))),
                    ("a poll that never answers", Page(poll="")),
                    ("not deployed", Page(route=lambda r: NOT_DEPLOYED)),
                    ("an HTML 404", Page(route=lambda r: {"http": 404, "redirected": False,
                                                          "url": SITE + "/x", "ctype": "text/html",
                                                          "body": "x"})),
                    ("no admin tab", Page(tabs=[{"targetId": "O", "url": "https://www.olx.ro/"}]))):
    fresh()
    try:
        got = site_api.available(page)
    except Exception as ex:
        got = "raised %r" % ex
    check(got is False, "available: %s must be False, got %r" % (label, got))

fresh()
try:
    site_api.available(Page(route=lambda r: LOGIN))
    check(False, "available: a lost session must raise SessionLost, not return")
except site_api.SessionLost:
    pass

fresh()
os.environ["API"] = "off"
p = Page()
check(site_api.available(p) is False, "available: API=off is the kill switch")
check(not p.exprs, "available: API=off must not even probe")
check(site_api.lookup_ids(p, ["1"]) is None, "lookup_ids: API=off answers None")
os.environ.pop("API")

# --- the tab: fetched on the admin tab, the caller's tab restored -----------------
fresh()
p = Page(current="O")
site_api.lookup_ids(p, ["308040530"])
check(all(tab == "A" for tab, _ in p.calls), "tab: every fetch must run on the admin tab: %s"
      % [t for t, _ in p.calls])
check(p.cur == "O", "tab: the caller's tab must be restored, ended on %r" % p.cur)
fresh()
p = Page(current="A")
site_api.lookup_ids(p, ["1"])
check(not p.switches, "tab: already on the admin tab, no switching: %s" % p.switches)
fresh()
p = Page(current="O", tabs=[{"targetId": "O", "url": "https://www.olx.ro/"},
                            {"targetId": "A1", "url": SITE + "/admin/watches/watch/1/change/"},
                            {"targetId": "A2", "url": SITE + "/admin/watches/watch/add/"}])
site_api.fetch(p, "/admin/watches/watch/lookup/?ids=1", return_to="A2")
check(p.calls[-1][0] == "A2", "tab: a caller already on an admin tab keeps using it")
# the caller names the admin tab as return_to while the browser still sits on OLX:
# the fetch must still run on the admin tab (from OLX it carries no session cookie)
fresh()
p = Page(current="O")
site_api.fetch(p, "/admin/watches/watch/lookup/?ids=1", return_to="A")
check(p.calls[-1][0] == "A" and p.cur == "A",
      "tab: return_to=<admin tab> while on OLX must still fetch on the admin tab, ran on %r"
      % p.calls[-1][0])
fresh()
p = Page(current="O")
site_api.fetch(p, "/admin/watches/watch/lookup/?ids=1", tab="A", return_to="O")
check(p.calls[-1][0] == "A" and p.cur == "O", "tab: an explicit tab is used, return_to restored")

# --- lookup_ids: batches of 500, no `source` ----------------------------------------
def lookup_route(existing):
    def route(req):
        q = re.search(r"ids=([^&]*)", req["path"]).group(1).split(",")
        ex = {i: existing[i] for i in q if i in existing}
        return jenv({"existing": ex, "missing": [i for i in q if i not in existing and i != "0"]})
    return route

fresh()
ids = [str(300000000 + i) for i in range(1201)]
row = {"pk": 7, "source": "olx", "is_active": False, "status": "expired", "brand": "Casio",
       "model_name": "F-91W", "seller_id": "1", "pictures": 3, "change_url": "/x/"}
p = Page(route=lookup_route({ids[0]: row, ids[1200]: row}))
r = site_api.lookup_ids(p, ids + ["junk", "12a"])
batches = [req for _, req in p.calls if "ids=0" not in req["path"]]
check(len(batches) == 3, "lookup_ids: 1201 ids must go in 3 batches of <=500, got %d" % len(batches))
check(all(len(re.search(r"ids=([^&]*)", b["path"]).group(1).split(",")) <= 500 for b in batches),
      "lookup_ids: a batch over 500 ids")
check(not any("source=" in b["path"] for _, b in p.calls),
      "lookup_ids: dedup is source-agnostic - no source= in the query")
check(set(r["existing"]) == {ids[0], ids[1200]}, "lookup_ids: existing merged across batches")
check(len(r["missing"]) == 1199, "lookup_ids: missing merged, got %d" % len(r["missing"]))
check(not any("junk" in b["path"] for b in batches), "lookup_ids: non-digit ids are not sent")

fresh()
calls = {"n": 0}
def flaky(req):
    calls["n"] += 1
    return jenv({"existing": {}, "missing": []}) if calls["n"] < 3 else NOT_DEPLOYED
check(site_api.lookup_ids(Page(route=flaky), ids) is None,
      "lookup_ids: a batch answering non-JSON makes the whole answer None (the caller falls back)")
fresh()
calls["n"] = 0
def lost_later(req):
    calls["n"] += 1
    return jenv({"existing": {}, "missing": []}) if calls["n"] < 2 else LOGIN
try:
    site_api.lookup_ids(Page(route=lost_later), ["1"])
    check(False, "lookup_ids: a lost session mid-run must raise")
except site_api.SessionLost:
    pass

# --- reposts: the endpoint's rows in find_repost's shape ----------------------------
fresh()
def reposts_route(req):
    if "lookup/" in req["path"]:
        return jenv({"existing": {}, "missing": []})
    return jenv({"by_seller": [{"pk": 1, "external_listing_id": "999", "source": "olx",
                                "is_active": True, "brand": "Garmin",
                                "model_name": "Fenix 7X Solar", "seller_id": "529077689"}],
                 "by_model": [{"pk": 2, "external_listing_id": None, "source": "facebook",
                               "is_active": False, "brand": None,
                               "model_name": "Fenix 7X Solar", "seller_id": None}]})
p = Page(route=reposts_route)
r = site_api.reposts(p, "Fenix 7X Solar", "529077689", "307673714")
q = [req["path"] for _, req in p.calls if "reposts/" in req["path"]][0]
check("model=Fenix+7X+Solar" in q and "seller_id=529077689" in q and "exclude_id=307673714" in q,
      "reposts: query %s" % q)
check(r["by_seller"][0]["model"] == "Fenix 7X Solar" and r["by_seller"][0]["extid"] == "999"
      and r["by_seller"][0]["brand"] == "Garmin" and r["by_seller"][0]["seller"] == "529077689",
      "reposts: row mapping %s" % r["by_seller"][:1])
check(r["by_model"][0]["extid"] == "" and r["by_model"][0]["brand"] == "",
      "reposts: a null id / brand maps to '' like an empty changelist cell: %s" % r["by_model"][:1])
check(site_api.reposts(p, "", "1", "2") is None, "reposts: no model, no request")

# --- brands -----------------------------------------------------------------------
fresh()
def brand_route(req):
    if req["path"].startswith("/admin/watches/brand/all/"):
        return jenv({"brands": [{"id": 2, "name": "Casio", "slug": "casio"},
                                {"id": 54, "name": "Fără marcă", "slug": "fara-marca"},
                                {"id": 266, "name": "Zeppelin", "slug": "zeppelin"}]})
    if req["path"].startswith("/admin/watches/brand/lookup/"):
        return jenv({"found": {"Fara Marca": {"id": 54, "name": "Fără marcă", "slug": "fara-marca"}},
                     "missing": []})
    return jenv({"existing": {}, "missing": []})
p = Page(route=brand_route)
check(site_api.brands_all(p) == {"Casio": 2, "Fără marcă": 54, "Zeppelin": 266},
      "brands_all: {name: id}")
check(site_api.brand_lookup(p, "Fara Marca")["id"] == 54, "brand_lookup: found by the name asked")
rep = site_api.probe_report(p, {"Casio": 2, "Fara marca": 54})
check(rep == {"api": "on", "brands": {"site": 3, "missing": ["Zeppelin"]}},
      "probe_report: missing by id (aliases count as present), got %s" % rep)
fresh()
check(site_api.probe_report(Page(route=lambda r: NOT_DEPLOYED), {}) ==
      {"api": "off", "why": "not deployed"}, "probe_report: not deployed")
fresh()
check(site_api.probe_report(Page(route=lambda r: LOGIN), {})["api"] == "lost",
      "probe_report: a lost session")
fresh()
os.environ["API"] = "off"
check(site_api.probe_report(Page(), {}) == {"api": "off", "why": "forced"}, "probe_report: forced")
os.environ.pop("API")

# --- import_json: JSON body vs multipart ---------------------------------------------
fresh()
p = Page(route=lambda req: jenv({"pk": 1}, 201, "/admin/watches/watch/import-json/"))
long_desc = "Descriere lungă cu diacritice ăîșț. " * 300          # ~11 KB, still one request
fields = site_api.to_model_fields({"model": "G-Shock", "price": 400, "currency": "RON",
                                   "movement": "quartz", "description": long_desc})
urls = ["https://frankfurt.apollo.olxcdn.com:443/v1/files/f%d-RO/image;s=1000x1000" % i
        for i in range(20)]
env = site_api.import_json(p, fields, "Casio", image_urls=urls)
check(env and env["http"] == 201, "import_json: the envelope comes back to the caller")
_, req = p.calls[-1]
check(req["method"] == "POST" and req["path"] == "/admin/watches/watch/import-json/",
      "import_json: POST import-json/, got %s %s" % (req["method"], req["path"]))
check(req["json"]["image_urls"] == urls and "blobs" not in req, "import_json: JSON body with the URLs")
check(req["json"]["brand"] == {"name": "Casio"} and req["json"]["create_brand"] is True
      and req["json"]["dry_run"] is False, "import_json: brand / create_brand / dry_run")
check(req["json"]["watch"]["model_name"] == "G-Shock", "import_json: model fields in `watch`")
e = [x for x in p.exprs if "/*site_api:start*/" in x and "import-json" in x][-1]
check("Content-Type" in e and "X-CSRFToken" in e and "csrftoken" in e,
      "import_json: CSRF from the cookie, sent as X-CSRFToken")
check("csrfmiddlewaretoken" in e, "import_json: the hidden-input CSRF fallback")

blobs = ["blob:%s/%d" % (SITE, i) for i in range(20)]
site_api.import_json(p, fields, "Casio", image_urls=urls, blob_urls=blobs, tab="A")
_, req = p.calls[-1]
check(req.get("blobs") == blobs, "import_json: multipart carries the blob: URLs in order")
check("image_urls" not in req["json"], "import_json: multipart sends no image_urls")
e = [x for x in p.exprs if "/*site_api:start*/" in x][-1]
check("FormData" in e and 'fd.append("payload"' in e and 'fd.append("images"' in e,
      "import_json: multipart = a `payload` field + `images` parts")
check(p.calls[-1][0] == "A", "import_json: multipart posts from the tab the blobs were staged in")
site_api.import_json(p, fields, "Casio", image_urls=urls, dry_run=True)
check(p.calls[-1][1]["json"]["dry_run"] is True, "import_json: dry_run is passed through")

check(all(len(x.encode("utf-8")) < 64 * 1024 for x in p.exprs),
      "import_json: every js() call must stay under 64 KB, max %d"
      % max(len(x.encode("utf-8")) for x in p.exprs))
try:
    site_api.import_json(p, dict(fields, description="x" * 70000), "Casio", image_urls=urls)
    check(False, "import_json: a request over the 64 KB cap must refuse, not be sent")
except ValueError:
    pass

# --- to_model_fields / from_model_field / fixable ------------------------------------
m = site_api.to_model_fields({"model": "Fenix 7", "reference": "", "diameter": 0, "year": None,
                              "description": "  text  \n", "price": 1700.0, "brand": "Garmin",
                              "images": ["u"], "priceNote": "negociabil", "externalId": "307",
                              "sellerName": "Ana", "sourceUrl": "https://www.olx.ro/d/x"})
check(m.get("condition") == "good", "to_model_fields: condition defaults to good (parity with the JS)")
check("movement" not in m, "to_model_fields: NO movement default")
check("reference_number" not in m and "year" not in m, "to_model_fields: None and '' are dropped")
check(m.get("case_diameter_mm") == 0, "to_model_fields: 0 is kept")
check(m.get("description") == "text", "to_model_fields: description stripped, got %r" % m.get("description"))
check("brand" not in m and "images" not in m and "priceNote" not in m,
      "to_model_fields: brand travels separately; harness-only keys are not sent")
check(m.get("external_listing_id") == "307" and m.get("seller_name") == "Ana"
      and m.get("source_url") == "https://www.olx.ro/d/x", "to_model_fields: provenance mapped")
check(site_api.to_model_fields({"condition": "new"})["condition"] == "new",
      "to_model_fields: a given condition wins")
check(site_api.from_model_field("case_material") == "caseMat"
      and site_api.from_model_field("brand") == "brand"
      and site_api.from_model_field("__all__") is None, "from_model_field")
for k in ("movement", "brand", "model", "price", "caseMat", "description", "phone"):
    check(site_api.fixable(k), "fixable: %s is a contract key" % k)
for k in ("sourceUrl", "county", "city", "sellerName", "sellerId", "externalId", "source",
          "videoUrl", None, "", "__all__"):
    check(not site_api.fixable(k), "fixable: %r has no `finish` answer" % k)

print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
