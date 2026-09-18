#!/usr/bin/env python3
"""Offline harness for import-post.py: stubs browser-use and a canned FB post so
the REVIEW gate and the RO->enum field inference can be tested without Chrome."""
import json, os, re, sys, io, contextlib, time

time.sleep = lambda *a, **k: None      # the script's paced waits are irrelevant offline

ROOT = "/Users/stelian/.hermes/proiecte/3ceasuri"
SRC = os.path.join(ROOT, "archive/facebook/scripts/import-post.py")


def run(post_text, n_images=5, env=None, admin_rows_for=None, video=None, brand_on_site=None):
    """Execute import-post.py against a canned post; return (markers, trace).

    `brand_on_site` names a brand the admin already holds (id 77) even though it is
    absent from BRAND_IDS — the case that used to create a duplicate row."""
    state = {"url": "", "img": 0, "brand_tab_opened": False, "imported": None, "brand_name": ""}
    admin_rows_for = admin_rows_for or (lambda q: [])

    def js(e):
        # NOTE: order matters. The harness-injection and importWatch payloads embed
        # the whole of import-watch.js / the watch JSON, which contain strings like
        # "imagini salvate" and "naturalWidth" — so match those two FIRST or a later
        # branch will swallow them.
        # The photo fetch is an (async ...) expression AND uses FileReader, both of
        # which collide with earlier branches (importWatch / the injected harness).
        # Match on a string unique to it.
        if "String(fr.result)" in e:                                       # photo fetch -> base64
            return "A" * 800
        if "createElement('script')" in e:                                 # harness injection
            return "OK"
        if e.startswith("(async"):                                         # importWatch call
            state["imported"] = e
            return "OK"
        if "td.field-" in e:                                               # dedup rows
            q = re.search(r"[?&]q=([^&\"]+)", state["url"])
            return json.dumps(admin_rows_for(q.group(1) if q else ""))
        if "brand\\/(\\d+)\\/change" in e or "brand/(\\d+)/change" in e:   # brand lookup BY NAME
            if brand_on_site:
                return json.dumps([{"name": brand_on_site, "id": "77"}])
            # nothing matches until the add form has actually been submitted
            return json.dumps([{"name": state["brand_name"], "id": "99"}]
                              if state["brand_tab_opened"] else [])
        if "id_name" in e and "id_slug" in e:                             # brand add form
            state["brand_tab_opened"] = True
            m = re.search(r'n\.value=("(?:[^"\\]|\\.)*")', e)
            state["brand_name"] = json.loads(m.group(1)) if m else ""
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
                               "diameter": "40", "extId": "777", "sellerId": "100055",
                               "sellerName": "Ion Popescu", "source": "facebook", "imgs": n_images})
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
    os.environ.update({"PROJECT_ROOT": ROOT, "POST_ID": "777", "PATH": "/usr/bin:/bin",
                       "SKIP_PROMPT": "1"})
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
check(inf["sellerId"] == "100055", "A: seller id not captured")
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

# --- D2. brand already on the site but missing from BRAND_IDS -> REUSE, never re-create
#         (creating it again produced a duplicate 'Fără marcă' with a mangled slug)
m, st = run(NEWB, env={"CONFIRM": "1", "OVERRIDES": json.dumps({"brand": "Zxcvbnwatch"})},
            brand_on_site="Zxcvbnwatch")
check(st["brand_tab_opened"] is False, "D2: must NOT open the add form for an existing brand")
check(m.get("NEW_BRAND", {}).get("id") == 77, "D2: should reuse the existing brand id")
check(m.get("NEW_BRAND", {}).get("created") is False, "D2: NEW_BRAND must say created:false")
check(m.get("RESULT", {}).get("ok") is True, "D2: should import")

# --- E. thin media (1 image) -> REVIEW even though everything else inferred
m, st = run(GOOD, n_images=1)
check("REVIEW" in m and any("image" in r for r in m["REVIEW"]["reasons"]),
      "E: single-image post should stop for review, got %s" % m.get("REVIEW"))
check(st["imported"] is None, "E: must not import")

# --- F. dedup Stage 1 still short-circuits before any FB work
m, _ = run(GOOD, admin_rows_for=lambda q: [{"brand": "Doxa", "model": "X", "extid": "777"}] if q == "777" else [])
check(m.get("SKIP", {}).get("reason", "").startswith("already imported"), "F: stage-1 dedup broken: %s" % m.get("SKIP"))

# --- G. Stage 2 repost: same author + same brand/model, different post id
def rows(q):
    return [{"brand": "Doxa", "model": "Mecanic Vintage", "extid": "555"}] if q == "100055" else []
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

# --- J. first pass hands out the contract and writes nothing
m, st = run(GOOD, env={"SKIP_PROMPT": ""})
check("EXTRACT_PROMPT" in m, "J: first pass must emit the contract")
check(st["imported"] is None, "J: first pass must not import")
prompt = m["EXTRACT_PROMPT"]["prompt"]
check("Doxa Mecanic Vintage" in prompt, "J: post text missing from the prompt")
check("`reference`" in prompt and "T125.617.17.051.03" in prompt, "J: reference rule missing")
check("one of automatic | manual | quartz | smart" in prompt, "J: movement enum missing from the contract")
check("LOOK AT THE PHOTOS" in prompt, "J: photo-identification rule missing")
check("Never a filler noun" in prompt, "J: filler-model ban missing")
check("Never derive a reference from the design" in prompt, "J: reference guard missing")
saved = m["EXTRACT_PROMPT"]["photos"]
check(len(saved) == 5, "J: photos must ship with the contract, got %r" % len(saved))
check(m["EXTRACT_PROMPT"]["photos_failed"] == 0, "J: photo saving reported failures")
check(all(not p.startswith("http") for p in saved), "J: contract must hand over local paths, not URLs")
check(all(os.path.exists(p) and os.path.getsize(p) > 0 for p in saved), "J: photos not actually written to disk")

# --- K. filled contract imports in the second pass; OVERRIDES are the values used
# A contract answer is complete: authoritative-about-silence means anything left
# out is cleared, so price/description must be in it or the import dies on the
# hard requirements — which is the point.
FILLED = {"brand": "Doxa", "model": "Sub 300T", "reference": "T125.617.17.051.03",
          "movement": "automatic", "price": 1200, "currency": "RON",
          "description": "Doxa Sub 300T, stare excelenta, functioneaza perfect, tinut in cutie.\nCurea de piele originala, sticla safir.",
          "is_wristwatch": True, "is_bulk_lot": False}
m, st = run(GOOD, env={"CONFIRM": "1", "OVERRIDES": json.dumps(FILLED)})
check(m["INFER"]["model"] == "Sub 300T", "K: model %r" % m["INFER"].get("model"))
check(m["INFER"]["reference"] == "T125.617.17.051.03", "K: reference %r" % m["INFER"].get("reference"))
check("is_wristwatch" not in m["INFER"], "K: contract-only flags must not reach the form")
check(m.get("RESULT", {}).get("ok") is True, "K: should import")

# --- L. the two judgement calls, and CONFIRM overriding them
m, st = run(GOOD, env={"OVERRIDES": json.dumps(dict(FILLED, is_wristwatch=False))})
check(m.get("SKIP", {}).get("reason", "").startswith("not a wristwatch"), "L: wall clock not skipped: %s" % m.get("SKIP"))
check(st["imported"] is None, "L: must not import a non-wristwatch")
m, _ = run(GOOD, env={"OVERRIDES": json.dumps(dict(FILLED, is_bulk_lot=True))})
check(m.get("SKIP", {}).get("reason", "").startswith("bulk lot"), "L: bulk lot not skipped: %s" % m.get("SKIP"))
m, _ = run(GOOD, env={"CONFIRM": "1", "OVERRIDES": json.dumps(dict(FILLED, is_wristwatch=False))})
check("SKIP" not in m, "L: CONFIRM=1 must override the verdict, got %s" % m.get("SKIP"))

# --- M. an illegal DB value dies loudly instead of being dropped by the form
m, _ = run(GOOD, env={"CONFIRM": "1", "OVERRIDES": json.dumps(dict(FILLED, movement="mecanic"))})
check("ERROR" in m and "not one of" in json.dumps(m["ERROR"]), "M: bad enum not rejected: %s" % m.get("ERROR"))
m, _ = run(GOOD, env={"CONFIRM": "1", "OVERRIDES": json.dumps(dict(FILLED, year="1970-1980"))})
check("ERROR" in m, "M: a decade range in `year` must be rejected, not silently dropped")

# --- N. a filled contract is authoritative about silence too
# caseMat is omitted from the answer, and the post never states one -> the regex
# guess ("steel") must NOT survive.
m, st = run(GOOD, env={"CONFIRM": "1", "OVERRIDES": json.dumps(FILLED)})
check(m["INFER"].get("caseMat") is None, "N: omitted contract field kept the regex guess: %r" % m["INFER"].get("caseMat"))
check(m["INFER"].get("phone") is None, "N: omitted phone kept the regex guess: %r" % m["INFER"].get("phone"))
check(m["INFER"]["model"] == "Sub 300T", "N: supplied fields must survive the clear")
check(m["INFER"]["sourceUrl"].endswith("/777/"), "N: non-contract fields must NOT be cleared")
check(m["INFER"]["externalId"] == "777", "N: externalId must survive")
check(m["INFER"]["source"] == "facebook", "N: source must survive")
check(m["INFER"]["sellerId"] == "100055", "N: seller capture must survive")
check(m.get("RESULT", {}).get("ok") is True, "N: should still import")

# --- O. a targeted OVERRIDES fix (no is_wristwatch) still merges, as before
m, _ = run(GOOD, env={"CONFIRM": "1", "OVERRIDES": json.dumps({"model": "Just This"})})
check(m["INFER"]["model"] == "Just This", "O: targeted override not applied")
check(m["INFER"].get("caseMat") == "steel", "O: targeted override must not clear the rest")

print("FAILURES:" if fails else "ALL CHECKS PASSED")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
