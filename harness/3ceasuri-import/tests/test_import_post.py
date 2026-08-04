#!/usr/bin/env python3
"""Offline harness for import-post.py: stubs browser-use and a canned FB post so
the REVIEW gate and the RO->enum field inference can be tested without Chrome."""
import json, os, re, sys, io, contextlib, time

time.sleep = lambda *a, **k: None      # the script's paced waits are irrelevant offline

ROOT = "/Users/stelian/.hermes/proiecte/3ceasuri"
SRC = os.path.join(ROOT, "harness/3ceasuri-import/scripts/import-post.py")


def run(post_text, n_images=5, env=None, admin_rows_for=None, video=None):
    """Execute import-post.py against a canned post; return (markers, trace)."""
    state = {"url": "", "img": 0, "brand_tab_opened": False, "imported": None}
    admin_rows_for = admin_rows_for or (lambda q: [])

    def js(e):
        # NOTE: order matters. The harness-injection and importWatch payloads embed
        # the whole of import-watch.js / the watch JSON, which contain strings like
        # "imagini salvate" and "naturalWidth" — so match those two FIRST or a later
        # branch will swallow them.
        if "createElement('script')" in e:                                 # harness injection
            return "OK"
        if e.startswith("(async"):                                         # importWatch call
            state["imported"] = e
            return "OK"
        if "td.field-" in e:                                               # dedup rows
            q = re.search(r"[?&]q=([^&\"]+)", state["url"])
            return json.dumps(admin_rows_for(q.group(1) if q else ""))
        if "brand\\/(\\d+)\\/change" in e or "brand/(\\d+)/change" in e:   # new-brand id lookup
            return json.dumps({"id": "99"})
        if "id_name" in e and "id_slug" in e:                             # brand add form
            state["brand_tab_opened"] = True
            return "ok"
        if "hit" in e and "/photo/" in e:
            return json.dumps({"hit": "https://www.facebook.com/photo/?fbid=1&set=pcb.777"})
        if "See more" in e:
            return "ok"
        if "firstIsVideo" in e:
            return json.dumps({"firstIsVideo": bool(video), "videoUrl": video, "txt": post_text,
                               "authorId": "100055", "authorName": "Ion Popescu"})
        if "naturalWidth>400" in e:
            state["img"] += 1
            return ("https://scontent.xx.fbcdn.net/v/t1/%d.jpg?_nc_ohc=abc&oh=1&oe=2" % state["img"]
                    if state["img"] <= n_images else "")
        if "Next photo" in e:
            return "c" if state["img"] < n_images else "x"
        if "same-set" in e:
            return "same-set"
        if "window.BRAND_IDS[" in e:
            return "ok"
        if "imagini salvate" in e:
            return json.dumps({"images_ok": True, "added_ok": True})
        if "/change/" in e and "result_list" in e:
            return json.dumps({"url": "https://3ceasuri.ro/admin/watches/watch/5/change/"})
        if "id_reference_number" in e or "id_case_diameter_mm" in e:
            return json.dumps({"brandId": "1", "price": "1200", "currency": "RON", "ref": None,
                               "diameter": "40", "fbId": "777", "authorId": "100055",
                               "authorName": "Ion Popescu", "imgs": n_images})
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
             {"targetId": "F", "url": "https://www.facebook.com/photo/", "title": "fb"}]}

    os.environ.clear()
    os.environ.update({"PROJECT_ROOT": ROOT, "POST_ID": "777", "PATH": "/usr/bin:/bin"})
    os.environ.update(env or {})

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(open(SRC).read(), SRC, "exec"), g)
    except SystemExit:
        pass
    out = buf.getvalue()
    markers = {}
    for line in out.splitlines():
        m = re.match(r"^([A-Z_]+): (.*)$", line)
        if m:
            markers[m.group(1)] = json.loads(m.group(2))
    return markers, state


fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)

# --- A. confident post: known brand, 5 images, full text -> imports in ONE pass
GOOD = ("Ion Popescu\n2 h\nDoxa Mecanic Vintage\n"
        "Stare excelenta, functioneaza perfect, tinut in cutie.\n"
        "Automatic, 40 mm, curea de piele originala, sticla safir.\n"
        "Pret 1200 lei, negociabil. Tel 0731394148")
m, st = run(GOOD)
check("REVIEW" not in m, "A: confident post must NOT stop for review (got %s)" % m.get("REVIEW"))
check(m.get("RESULT", {}).get("ok") is True, "A: should import and verify ok")
inf = m["INFER"]
check(inf["brand"] == "Doxa", "A: brand %r" % inf.get("brand"))
check(inf["model"] == "Mecanic Vintage", "A: model %r" % inf.get("model"))
check(inf["condition"] == "excellent", "A: condition %r" % inf.get("condition"))
check(inf["movement"] == "automatic", "A: movement %r" % inf.get("movement"))
check(inf["diameter"] == 40.0, "A: diameter %r" % inf.get("diameter"))
check(inf["braceletMat"] == "leather", "A: braceletMat %r" % inf.get("braceletMat"))
check(inf["displayMat"] == "sapphire", "A: displayMat %r" % inf.get("displayMat"))
check(inf["price"] == 1200 and inf["currency"] == "RON", "A: price %r %r" % (inf.get("price"), inf.get("currency")))
check(inf["phone"] == "0731394148", "A: phone %r" % inf.get("phone"))
check(inf["fbAuthorId"] == "100055", "A: author id not captured")
check(not inf["description"].startswith("Ion Popescu"), "A: author/timestamp preamble leaked into description")

# --- B. gold-plating trap: 'placat cu aur' is a coating, case stays steel
PLATED = ("Ion Popescu\n1 h\nSlava AU20 Gold Plated\n"
          "Ceas rusesc vechi placat cu aur, mecanic, stare buna.\n36 mm, curea piele.\nPret 120 euro")
m, _ = run(PLATED, env={"CONFIRM": "1"})
check(m["INFER"]["caseMat"] == "steel", "B: plated case must infer steel, got %r" % m["INFER"].get("caseMat"))
check(m["INFER"]["movement"] == "manual", "B: 'mecanic' -> manual, got %r" % m["INFER"].get("movement"))
check(m["INFER"]["currency"] == "EUR" and m["INFER"]["price"] == 120, "B: EUR price wrong: %s" % m["INFER"])

# --- C. new brand -> REVIEW, and NOTHING is written to the DB
NEWB = ("Ion Popescu\n3 h\nZxcvbnwatch Chronograph\nStare buna, quartz, 42 mm.\nPret 900 lei")
m, st = run(NEWB)
check("REVIEW" in m, "C: unknown brand must stop for review")
check("RESULT" not in m, "C: must not import when review-gated")
check(st["brand_tab_opened"] is False, "C: must NOT create the brand before review")
check(st["imported"] is None, "C: importWatch must not be called")

# --- D. same new brand with CONFIRM=1 -> proceeds, creates brand, imports
m, st = run(NEWB, env={"CONFIRM": "1", "OVERRIDES": json.dumps({"brand": "Zxcvbnwatch"})})
check("REVIEW" not in m, "D: CONFIRM must pass the gate")
check(st["brand_tab_opened"] is True, "D: brand should be created")
check(m.get("NEW_BRAND", {}).get("id") == 99, "D: NEW_BRAND id not reported")
check(m.get("RESULT", {}).get("ok") is True, "D: should import")

# --- E. thin media (1 image) -> REVIEW even though everything else inferred
m, st = run(GOOD, n_images=1)
check("REVIEW" in m and any("image" in r for r in m["REVIEW"]["reasons"]),
      "E: single-image post should stop for review, got %s" % m.get("REVIEW"))
check(st["imported"] is None, "E: must not import")

# --- F. dedup Stage 1 still short-circuits before any FB work
m, _ = run(GOOD, admin_rows_for=lambda q: [{"brand": "Doxa", "model": "X", "fbid": "777"}] if q == "777" else [])
check(m.get("SKIP", {}).get("reason", "").startswith("already imported"), "F: stage-1 dedup broken: %s" % m.get("SKIP"))

# --- G. Stage 2 repost: same author + same brand/model, different post id
def rows(q):
    return [{"brand": "Doxa", "model": "Mecanic Vintage", "fbid": "555"}] if q == "100055" else []
m, st = run(GOOD, admin_rows_for=rows)
check(m.get("SKIP", {}).get("reason", "").startswith("repost"), "G: stage-2 repost dedup broken: %s" % m.get("SKIP"))
check(st["imported"] is None, "G: repost must not import")

# --- H. video-first post imports (user directive 2026-08-04) and carries video_url
VURL = "https://www.facebook.com/reel/123456789"
m, st = run(GOOD, video=VURL)
check("SKIP" not in m, "H: video-first post must no longer be skipped, got %s" % m.get("SKIP"))
check(m.get("VIDEO", {}).get("video_url") == VURL, "H: VIDEO marker missing the url: %s" % m.get("VIDEO"))
check(m["INFER"].get("videoUrl") == VURL, "H: videoUrl not in the inferred payload")
check(VURL in (st["imported"] or ""), "H: videoUrl not passed to importWatch")
check(m.get("RESULT", {}).get("ok") is True, "H: video post should import ok")
check(m["RESULT"]["state_entry"].get("video_url") == VURL, "H: state_entry must carry video_url")

# --- I. a post that never states its movement must be judged, not defaulted to quartz
NOMV = ("Ion Popescu\n2 h\nDoxa Vintage 34 mm\n"
        "Stare buna, functioneaza corect, carcasa de otel.\nPret 300 lei")
m, st = run(NOMV)
check("REVIEW" in m and any("movement" in r for r in m["REVIEW"]["reasons"]),
      "I: unstated movement must stop for review, got %s" % m.get("REVIEW"))
check(st["imported"] is None, "I: must not import a movement-guessed watch")
m, st = run(NOMV, env={"CONFIRM": "1", "OVERRIDES": '{"movement":"manual"}'})
check(m.get("RESULT", {}).get("ok") is True, "I: CONFIRM + movement override should import")

print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
