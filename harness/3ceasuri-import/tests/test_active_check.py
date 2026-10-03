#!/usr/bin/env python3
"""Offline tests for olx-check-active.py / active_check.py: stubs the admin, the
Django endpoints and the OLX API, so nothing touches the live site."""
import contextlib, io, json, os, re, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
SCRIPTS = os.path.join(ROOT, "harness/3ceasuri-import/scripts")
PAYLOAD = os.path.join(SCRIPTS, "olx-check-active.py")
sys.path.insert(0, SCRIPTS)
import active_check

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)


# --- 1. classify: only clean answers decide anything --------------------------
for (http, st), want in {(200, "active"): ("active", None),
                         (410, None): ("gone", "withdrawn"),
                         (404, None): ("gone", "withdrawn"),
                         (200, "outdated"): ("gone", "expired"),
                         (200, "removed_by_user"): ("gone", "withdrawn"),
                         (200, "moderated"): ("unknown", None),
                         (200, None): ("unknown", None),      # a bot-check page, not JSON
                         (403, None): ("unknown", None),
                         (429, None): ("unknown", None),
                         (0, None): ("unknown", None),
                         (500, None): ("unknown", None)}.items():
    got = active_check.classify(http, st)
    check(got[:2] == want, "1: classify(%s, %r) = %s, want %s" % (http, st, got, want))


# --- the stub browser ------------------------------------------------------------
# What the live admin answers for an endpoint that is not deployed: its object-id
# catch-all redirects to /admin/ with HTML (checked 2026-10-04), not a 404.
NOT_DEPLOYED = {"http": 200, "redirected": True, "ctype": "text/html; charset=utf-8",
                "body": "<!DOCTYPE html><title>Administrare site</title>"}
JSON = {"redirected": False, "ctype": "application/json"}


def make_env(site_ids, olx, endpoints=False, deactivate_status=200, missing=NOT_DEPLOYED):
    """site_ids: active OLX ids on the site; olx: id -> (http, status)."""
    st = {"tab": None, "posts": [], "olx_calls": 0}
    pages = [site_ids[i:i + 3] for i in range(0, len(site_ids), 3)]     # 3 rows a page

    def js(e):
        if active_check.ACTIVE_IDS_PATH in e:
            if not endpoints:
                return json.dumps(missing)
            after = int(re.search(r"after_pk=(\d+)", e).group(1))
            rows = [{"pk": i + 1, "external_listing_id": int(x), "created_at": "2026-10-01"}
                    for i, x in enumerate(site_ids) if i + 1 > after][:2]          # 2 a page
            nxt = rows[-1]["pk"] if rows and rows[-1]["pk"] < len(site_ids) else None
            return json.dumps(dict(JSON, http=200, body=json.dumps(
                {"count": len(site_ids), "results": rows, "next_after_pk": nxt})))
        if "is_active__exact=1&p=" in e:
            p = int(re.search(r"&p=(\d+)", e).group(1))
            rows = pages[p - 1] if p <= len(pages) else (pages[-1] if pages else [])
            return json.dumps({"http": 200, "rows": [{"id": x, "pk": site_ids.index(x) + 1,
                                                      "created": "1 Octombrie 2026"} for x in rows]})
        if "/api/v1/offers/" in e:
            st["olx_calls"] += 1
            ad = re.search(r"/api/v1/offers/(\d+)/", e).group(1)
            http, status = olx.get(ad, (200, "active"))
            return json.dumps({"http": http, "status": status})
        if "csrftoken=" in e:
            return "tok123"
        if active_check.DEACTIVATE_PATH in e:
            body = json.loads(json.loads(re.search(r"body: (\".*\")\}\);", e).group(1)))
            st["posts"].append(body)
            if not endpoints:
                return json.dumps(missing)
            ids = [i["external_listing_id"] for i in body["items"]]
            return json.dumps(dict(JSON, http=deactivate_status, body=json.dumps(
                {"dry_run": body["dry_run"], "deactivated": [] if body["dry_run"] else ids,
                 "already_inactive": [], "not_found": [], "rejected": {}})))
        return ""

    g = {"__name__": "__main__", "js": js,
         "new_tab": lambda u: {"targetId": "T9"}, "close_tab": lambda t: None,
         "switch_tab": lambda t: st.__setitem__("tab", t), "goto_url": lambda u: None,
         "list_tabs": lambda: [{"targetId": "A", "url": "https://3ceasuri.ro/admin/watches/watch/"},
                               {"targetId": "O", "url": "https://www.olx.ro/ceasuri/"}]}
    return g, st


def run(g, env):
    """Execute the real payload against the stub; return (markers, report)."""
    out = os.path.join(tempfile.mkdtemp(), "report.json")
    saved = dict(os.environ)
    os.environ.update({"PROJECT_ROOT": ROOT, "PACE": "0", "OUT": out}, **env)
    for k in ("SAMPLE", "LIMIT", "IDS", "APPLY", "SEED"):
        if k not in env:
            os.environ.pop(k, None)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            try:
                exec(compile(open(PAYLOAD).read(), PAYLOAD, "exec"), g)
            except SystemExit:
                pass
    finally:
        os.environ.clear()
        os.environ.update(saved)
    markers = {}
    for line in buf.getvalue().splitlines():
        m = re.match(r"^([A-Z_]+): (.*)$", line)
        if m:
            markers[m.group(1)] = json.loads(m.group(2))
    report = json.load(open(out)) if os.path.exists(out) else None
    return markers, report


SITE = ["301", "302", "303", "304", "305", "306", "307"]
OLX = {"302": (410, None), "304": (404, None), "305": (200, "outdated"), "306": (403, None)}

# --- 2. without endpoints: lists via the changelist, reports, writes nothing ----
g, st = make_env(SITE, OLX)
m, rep = run(g, {})
check(m.get("ACTIVE_IDS") == {"count": 7, "via": "changelist"}, "2: listing: %s" % m.get("ACTIVE_IDS"))
check(m["STATS"]["gone"] == 3 and m["STATS"]["active"] == 3 and m["STATS"]["unknown"] == 1,
      "2: stats wrong: %s" % m.get("STATS"))
check(m["STATS"]["gone_pct"] == 50.0, "2: gone_pct is over decided answers only: %s" % m["STATS"])
check(sorted(m["GONE"]) == ["302", "304", "305"], "2: gone ids: %s" % m.get("GONE"))
check(m.get("UNKNOWN") == [{"id": "306", "reason": "olx_http_403"}], "2: unknown: %s" % m.get("UNKNOWN"))
check(not st["posts"], "2: without APPLY nothing may be posted")
check(rep and len(rep["results"]) == 7 and rep["stats"] == m["STATS"], "2: report not written")
_by = {r["id"]: r for r in rep["results"]}
check(_by["305"]["listing_status"] == "expired" and _by["302"]["listing_status"] == "withdrawn",
      "2: status mapping in the report: %s" % _by)

# --- 3. APPLY=1 while the endpoint is missing: one probe, no fallback writes ------
g, st = make_env(SITE, OLX)
m, rep = run(g, {"APPLY": "1"})
check("APPLY_UNAVAILABLE" in m and "APPLY" not in m, "3: a 404 endpoint must say so: %s" % list(m))
check(len(st["posts"]) == 1, "3: exactly one probe POST, got %d" % len(st["posts"]))
# a plain 404 (another server in front, or a future Django) is "not deployed" too
g, st = make_env(SITE, OLX, missing={"http": 404, "redirected": False, "ctype": "text/html", "body": ""})
m, rep = run(g, {"APPLY": "1"})
check(m.get("ACTIVE_IDS", {}).get("via") == "changelist" and "APPLY_UNAVAILABLE" in m,
      "3: a 404 must fall back too: %s" % list(m))

# --- 4. with endpoints: keyset paging, and only the gone ones are sent ------------
g, st = make_env(SITE, OLX, endpoints=True)
m, rep = run(g, {"APPLY": "1"})
check(m.get("ACTIVE_IDS") == {"count": 7, "via": "endpoint"}, "4: listing: %s" % m.get("ACTIVE_IDS"))
sent = [i for p in st["posts"] for i in p["items"]]
check(sorted(i["external_listing_id"] for i in sent) == ["302", "304", "305"],
      "4: sent the wrong ids: %s" % sent)
check(all(p["source"] == "olx" and p["dry_run"] is False for p in st["posts"]), "4: body: %s" % st["posts"])
check({i["external_listing_id"]: (i["status"], i["reason"]) for i in sent}["305"] == ("expired", "olx_outdated"),
      "4: outdated must go as expired: %s" % sent)
check(m.get("APPLY", {}).get("deactivated") == 3, "4: APPLY summary: %s" % m.get("APPLY"))
check(rep["applied"]["deactivated"] == ["302", "304", "305"], "4: the report must keep the server answer")

# --- 5. APPLY=dry sends dry_run=true ---------------------------------------------
g, st = make_env(SITE, OLX, endpoints=True)
m, _ = run(g, {"APPLY": "dry"})
check(st["posts"] and all(p["dry_run"] is True for p in st["posts"]), "5: dry run flag: %s" % st["posts"])

# --- 6. batches of APPLY_BATCH ------------------------------------------------------
many = [str(400000 + i) for i in range(active_check.APPLY_BATCH + 5)]
g, st = make_env(many, {x: (410, None) for x in many}, endpoints=True)
m, _ = run(g, {"APPLY": "1"})
check([len(p["items"]) for p in st["posts"]] == [active_check.APPLY_BATCH, 5],
      "6: batching: %s" % [len(p["items"]) for p in st["posts"]])

# --- 7. a run of blocked answers stops the sweep, and then nothing is applied -------
blocked = {x: (429, None) for x in SITE[1:]}
g, st = make_env(SITE, blocked, endpoints=True)
m, _ = run(g, {"APPLY": "1"})
check(m["STATS"]["stopped"] and "blocked" in m["STATS"]["stopped"], "7: must stop: %s" % m["STATS"])
check(st["olx_calls"] == 1 + active_check.BLOCKED_STREAK, "7: kept hammering: %d calls" % st["olx_calls"])
check(not st["posts"], "7: a stopped sweep must not apply anything")

# --- 8. SAMPLE / LIMIT / IDS pick the rows -------------------------------------------
g, st = make_env(SITE, OLX)
m, rep = run(g, {"SAMPLE": "3", "SEED": "7"})
check(m["STATS"]["checked"] == 3 and m["STATS"]["site_active_olx"] == 7, "8: sample: %s" % m["STATS"])
g, st = make_env(SITE, OLX)
m, rep = run(g, {"LIMIT": "2"})
check([r["id"] for r in rep["results"]] == ["301", "302"], "8: limit: %s" % [r["id"] for r in rep["results"]])
g, st = make_env(SITE, OLX)
m, rep = run(g, {"IDS": "302, 307"})
check(m["ACTIVE_IDS"]["via"] == "ids" and [r["id"] for r in rep["results"]] == ["302", "307"],
      "8: ids: %s" % m)

print("\n".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
