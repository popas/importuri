#!/usr/bin/env python3
"""olx-step.py — the per-watch OLX import loop as a handful of commands.

Run with python3 — this one is NOT a browser-use payload; it runs the payloads:

    S=harness/3ceasuri-import/scripts/olx-step.py
    python3 $S start  <queue> [--target N]           once: preflight + a fresh state.json
    python3 $S next   <queue>                        pass 1 for the next pending ad
    python3 $S finish <queue> <id> [field=value ...] write the answers, pass 2, log it
    python3 $S skip   <queue> <id> <code> ['reason']   your own judgement skip
    python3 $S counts <queue>
    python3 $S stop   <queue>                        end of session: report + status idle

Why it exists. The loop used to be five hand-typed steps per watch, each printing a
few KB of JSON for the model to parse: pass 1, read the draft, edit it, pass 2 piped
through the logger, route every REVIEW by hand. A weaker model at low effort
mis-steps somewhere in that chain, and a strong one spends its tokens reading it.
This driver keeps the payloads' raw output in .runs/ and prints only what the next
decision needs, ending every output with the literal NEXT: command. It decides
nothing the importer does not already decide: every gate lives in olx_import.py.

What it does that a hand-run loop had to remember:
  - routes a candidate flagged looks_smart / looks_classic to the other importer
  - never runs pass 1 on an ad that already has a draft (that run IS pass 2)
  - logs every outcome: RESULT:, SKIP:, and the REVIEW: skips the logger ignores
  - enforces "a fix is tried ONCE": the second fix-REVIEW becomes a skip
  - on a missing/unproven RESULT:, asks the admin before anyone can retry
  - on NEW_BRAND:, writes BRAND_IDS and brand-ids.md and prints the commit
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import candidates        # noqa: E402
import contract_draft    # noqa: E402
import infer_fields      # noqa: E402

ROOT = os.environ.get("PROJECT_ROOT") or os.path.abspath(os.path.join(HERE, "../../.."))
H = os.path.join(ROOT, "harness/3ceasuri-import")
RUNS = os.path.join(H, ".runs")
CDP = os.environ.get("BU_CDP_URL", "http://127.0.0.1:9222")
SELF = "python3 harness/3ceasuri-import/scripts/olx-step.py"
SCRIPTS = {"smart": "olx-import-smartwatch.py", "classic": "olx-import-watch.py"}
PAYLOAD_TIMEOUT = 900

# One line per field the model may be asked. The long form lives in infer_fields'
# RULES_*; this is the part a model needs at the moment it types the answer.
HINTS = {
    "brand": "exact BRAND_IDS spelling when it is one, else the maker on the dial/caseback/box. "
             "No maker mark anywhere -> 'Fără marcă'. Never 'Alt brand'; never a brand the ad "
             "says it is NOT ('Nu Citizen, Seiko...').",
    "model": {"classic": "model NAME only: short, no brand, no filler ('Original', 'Ceas', "
                         "'Dama'). The ad naming none is normal - read it off the dial. Nothing "
                         "identifiable -> the defining trait ('Automatic 21 Jewels').",
              "smart": "model NAME only, no brand/size/condition: 'Watch Series 9', 'Galaxy "
                       "Watch 6 Classic', 'Fenix 7X Solar'. The photo settles the generation, "
                       "not the title."},
    "movement": "judge it from the ad, the dial ('automatic', '21 jewels') or the model. "
                "Nothing states or shows it -> null (the gate then skips it; that is correct).",
    "reference": "only text you can READ in the ad or on a caseback/papers photo. Never from "
                 "the design. Null is normal.",
    "connectivity": "gsm = own SIM/eSIM/LTE/Cellular (Apple: red ring or dot on the crown); "
                    "no_gsm = GPS/Bluetooth only.",
    "compatibility": "Apple Watch -> ios; Galaxy Watch 4 and newer, Google Pixel Watch -> android; Galaxy Watch 3 "
                     "and older, Garmin, Amazfit, Huawei, Xiaomi, Fitbit -> both.",
    "is_wristwatch": {"classic": "false for pocket, mantel, table, alarm and wall clocks. A "
                                 "wristwatch still sealed in its box or wrap is true.",
                      "smart": "false ONLY when the ad SELLS an accessory (strap, charger, case, "
                               "dock, empty box) - the title and text decide it, not one photo. A "
                               "new watch still sealed in its box or wrap is true."},
    "category": "'wrist'; 'wall' for a wall clock (with is_wristwatch=false it IMPORTS: brand "
                "'Fără marcă' if unmarked, caseMat usually wood, diameter in mm - 30 cm = 300); "
                "null for pocket/mantel/table/alarm clocks.",
    "is_bulk_lot": "true when one price covers several watches, or shop stock 'mai multe bucăți'.",
    "notes": "one short sentence ONLY if the operator must know (suspected replica, "
             "iCloud-locked, model read off a photo, movement inferred). Else null.",
    "year": "ONE integer, only when stated. A decade -> null (put it in model). A smartwatch "
            "generation is not a year.",
    "diameter": "case size in mm, a number. Only when stated or legible.",
    "gender": "only when the ad or the watch makes it clear.",
    "condition": "as the ad describes it.",
    "caseMat": "only what the ad or the photo actually shows.",
    "braceletMat": "only what the ad or the photo actually shows (silicone = rubber).",
    "displayColor": "the dial colour, only when the photo shows it.",
}
KEEP_SHOWN = ("brand", "price", "currency", "condition", "category", "movement", "gender")


# --- plumbing ----------------------------------------------------------------
def say(*lines):
    print("\n".join(lines))


def browser_use():
    exe = os.environ.get("BROWSER_USE") or shutil.which("browser-use") \
        or os.path.expanduser("~/.local/bin/browser-use")
    return exe.split() if " " in exe else [exe]


def run_payload(source, env_extra, log_path):
    """Pipe a payload into browser-use; save everything it prints to log_path."""
    env = dict(os.environ, PROJECT_ROOT=ROOT, BU_CDP_URL=CDP, **env_extra)
    try:
        p = subprocess.run(browser_use(), input=source, capture_output=True, text=True,
                           env=env, timeout=PAYLOAD_TIMEOUT)
        out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        out += "\nOLX_STEP: payload timed out after %ds" % PAYLOAD_TIMEOUT
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as f:
        f.write(out)
    return out


def parse_markers(text):
    """{TAG: payload} for every `TAG: {json}` line; the last one of a tag wins."""
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"^([A-Z_]+): ([\[{].*)$", line.strip())
        if m:
            try:
                out[m.group(1)] = json.loads(m.group(2))
            except ValueError:
                pass
    return out


def log_line(tag, payload):
    """Feed one marker line to olx-log-result.py (history.jsonl + state.json)."""
    p = subprocess.run([sys.executable, os.path.join(HERE, "olx-log-result.py"),
                        "--history", os.path.join(ROOT, "history.jsonl"),
                        "--state", os.path.join(ROOT, "state.json")],
                       input="%s: %s\n" % (tag, json.dumps(payload, ensure_ascii=False)),
                       capture_output=True, text=True)
    return (p.stdout or p.stderr).strip()


def run_state_path(ad_id):
    return os.path.join(RUNS, "olx-%s.json" % ad_id)


def load_run(ad_id):
    try:
        with open(run_state_path(ad_id)) as f:
            return json.load(f)
    except Exception:
        return {}


def save_run(ad_id, st):
    os.makedirs(RUNS, exist_ok=True)
    with open(run_state_path(ad_id), "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def settle(queue, ad_id, status, reason):
    """Mark the queue unless the importer already did. A candidate left `pending`
    after a terminal outcome would make `next` hand out the same ad forever."""
    c = find_candidate(queue, ad_id)
    if c is not None and c.get("status", "pending") == "pending":
        candidates.mark(queue, ad_id, status, reason)


def find_candidate(queue, ad_id):
    for c in candidates.load(queue).get("candidates", []):
        if str(c.get("id")) == str(ad_id):
            return c
    return None


def profile_for(queue, cand):
    """Route by kind, not by category (iron rule 7): the discovery flags decide."""
    doc = candidates.load(queue)
    p = doc.get("profile") or ("smart" if "smart" in os.path.basename(queue) else "classic")
    if p == "classic" and (cand or {}).get("looks_smart"):
        return "smart", "looks_smart"
    if p == "smart" and (cand or {}).get("looks_classic"):
        return "classic", "looks_classic"
    return p, None


def next_cmd(queue):
    return "NEXT: %s next %s" % (SELF, os.path.relpath(queue, ROOT))


def parse_pair(pair):
    """'field=value' -> (field, value) typed by the contract. Raises ValueError."""
    if "=" not in pair:
        raise ValueError("%r is not field=value" % pair)
    k, v = pair.split("=", 1)
    k, v = k.strip(), v.strip()
    if v in ("null", "None", ""):
        return k, None
    if k in infer_fields.FLAGS:
        if v.lower() not in ("true", "false"):
            raise ValueError("%s must be true or false, got %r" % (k, v))
        return k, v.lower() == "true"
    if k in infer_fields.NUMERIC:
        try:
            return k, int(float(v)) if infer_fields.NUMERIC[k] is int else float(v)
        except ValueError:
            raise ValueError("%s must be a number, got %r" % (k, v))
    return k, v


def review_outcome(reasons, fix_attempts):
    """('skip', code) or ('fix', reasons). A fix is tried ONCE; a second one skips."""
    reasons = [r for r in (reasons or []) if isinstance(r, dict)]
    blocking = [r for r in reasons if r.get("action") == "skip"]
    if blocking:
        return "skip", blocking[0].get("code") or "review"
    if fix_attempts >= 1:
        return "skip", (reasons[0].get("code") if reasons else "review") + "_unfixed"
    return "fix", reasons


def add_brand(name, brand_id, root=None):
    """Write a NEW_BRAND into BOTH maps. Returns the files changed (maybe none)."""
    h = os.path.join(root or ROOT, "harness/3ceasuri-import")
    js_path = os.path.join(h, "scripts/import-watch.js")
    md_path = os.path.join(h, "references/brand-ids.md")
    changed = []
    with open(js_path) as f:
        src = f.read()
    m = re.search(r"^window\.BRAND_IDS = (\{.*?\});$", src, re.M)
    if not m:
        raise RuntimeError("window.BRAND_IDS line not found in import-watch.js")
    ids = json.loads(m.group(1))
    if name not in ids:
        ids[name] = int(brand_id)
        line = "window.BRAND_IDS = %s;" % json.dumps(ids, ensure_ascii=False,
                                                    separators=(",", ":"))
        with open(js_path, "w") as f:
            f.write(src[:m.start()] + line + src[m.end():])
        changed.append(js_path)
    with open(md_path) as f:
        md = f.read()
    row = "%s:%s" % (name, brand_id)
    if not re.search(r"^%s$" % re.escape(row), md, re.M):
        first = md.find("```")
        close = md.find("\n```", first + 3)
        if first < 0 or close < 0:
            raise RuntimeError("the brand list code block was not found in brand-ids.md")
        md = md[:close] + "\n" + row + md[close:]
        with open(md_path, "w") as f:
            f.write(md)
        changed.append(md_path)
    return changed


# --- the sheet ---------------------------------------------------------------
def hint(field, profile):
    h = HINTS.get(field, "")
    if isinstance(h, dict):
        h = h.get(profile, "")
    if field in infer_fields.ENUMS:
        h = "one of %s. %s" % ("|".join(infer_fields.ENUMS[field]), h)
    elif field in infer_fields.FLAGS:
        h = "true|false. " + h
    return h.strip()


def quote(v):
    return json.dumps(v, ensure_ascii=False)


def sheet(queue, ad_id, profile, draft, extract, photos, note=None):
    todo = draft.get("_todo") or []
    title = (extract or {}).get("title") or ""
    desc = (draft.get("description") or "").strip()
    if len(desc) > 1200:
        desc = desc[:1200] + " […]"
    out = ["AD %s | %s | %s | %s photos | %s %s" % (
        ad_id, profile, quote(title), (extract or {}).get("images", "?"),
        draft.get("price"), draft.get("currency") or "")]
    if note:
        out.append(note)
    out.append("TEXT: " + title)
    out += ["  " + l for l in desc.splitlines() if l.strip()]
    if photos:
        out.append("PHOTO (read exactly this one): %s" % photos[0])
        if len(photos) > 1:
            out.append("  %d more in %s - open one more ONLY for a caseback reference"
                       % (len(photos) - 1, os.path.dirname(photos[0])))
    else:
        out.append("PHOTO: none downloaded - decide from the text; is_wristwatch/model "
                   "doubt -> leave it and let the gate decide")
    out.append("DECIDE (field = current value | rule):")
    w = max([len(f) for f in todo] + [8])
    required = infer_fields.REQUIRED_BY_PROFILE.get(profile, []) + infer_fields.FLAGS
    for f in todo:
        must = "MUST ANSWER - " if f in required and draft.get(f) is None else ""
        out.append("  %-*s = %-18s | %s%s" % (w, f, quote(draft.get(f)), must, hint(f, profile)))
    keep = " ".join("%s=%s" % (k, quote(draft.get(k))) for k in KEEP_SHOWN
                    if k not in todo and draft.get(k) is not None)
    out.append("KEEP (already filled, do not pass them): " + keep)
    out.append("NEXT: %s finish %s %s %s" % (
        SELF, os.path.relpath(queue, ROOT), ad_id,
        " ".join("'%s=...'" % f for f in todo)))
    out.append("  Pass ONLY the fields whose value you change; a field you omit keeps its "
               "current value. true/false/null bare; text as-is inside the quotes.")
    return "\n".join(out)


# --- commands ----------------------------------------------------------------
def cmd_next(queue):
    cand = candidates.next_pending(queue)
    if not cand:
        say("QUEUE_EMPTY: %s" % json.dumps(candidates.counts(queue)),
            "NEXT: %s stop %s" % (SELF, os.path.relpath(queue, ROOT)))
        return 3
    ad_id = str(cand["id"])
    profile, routed = profile_for(queue, cand)
    note = ("ROUTED to the %s importer (%s)" % (profile, routed)) if routed else None

    if isinstance(cand.get("photos"), int) and cand["photos"] < 2:
        candidates.mark(queue, ad_id, "skipped", "too_few_images")
        logged = log_line("SKIP", {"ad_id": ad_id,
                                   "reason": "too_few_images: %d photo(s) at discovery"
                                             % cand["photos"]})
        say("SKIPPED %s: too_few_images (%s)" % (ad_id, logged), next_cmd(queue))
        return 0

    dpath = contract_draft.draft_path(ROOT, ad_id)
    if os.path.exists(dpath):
        # Pass 1 on an ad with a draft IS pass 2 -- never run it. Resume instead.
        st = load_run(ad_id) or {"profile": profile}
        with open(dpath) as f:
            draft = json.load(f)
        pdir = os.path.join(H, ".photos", "olx-%s" % ad_id)
        photos = sorted(os.path.join(pdir, p) for p in os.listdir(pdir)) \
            if os.path.isdir(pdir) else []
        save_run(ad_id, dict(st, queue=queue))
        say(sheet(queue, ad_id, st.get("profile", profile), draft, st.get("extract"), photos,
                  "RESUMED: a draft already exists (pass 1 ran earlier)"))
        return 0

    out = run_payload(open(os.path.join(HERE, SCRIPTS[profile])).read(),
                      {"AD_ID": ad_id, "CANDIDATES_FILE": queue},
                      os.path.join(RUNS, "olx-%s-pass1.log" % ad_id))
    m = parse_markers(out)
    if "SKIP" in m:
        settle(queue, ad_id, "skipped", (m["SKIP"].get("reason") or "skip").split(" ")[0])
        logged = log_line("SKIP", m["SKIP"])
        say("SKIPPED %s: %s (%s)" % (ad_id, m["SKIP"].get("reason"), logged), next_cmd(queue))
        return 0
    if "EXTRACT_PROMPT" in m:
        ep = m["EXTRACT_PROMPT"]
        with open(ep["draft"]) as f:
            draft = json.load(f)
        save_run(ad_id, {"profile": profile, "queue": queue, "fix_attempts": 0,
                         "extract": m.get("EXTRACT"), "photos": ep.get("photos")})
        extra = []
        if ep.get("phone_status") == "login_required":
            extra.append("WARN: olx.ro is not signed in - the phone is missing (not fatal)")
        say(sheet(queue, ad_id, profile, draft, m.get("EXTRACT"), ep.get("photos") or [],
                  note), *extra)
        return 0
    if "ERROR" in m:
        settle(queue, ad_id, "error", m["ERROR"].get("msg"))
        say("ERROR %s: %s (the queue marked it `error`)" % (ad_id, m["ERROR"].get("msg")),
            next_cmd(queue),
            "  Three ERRORs in a row -> stop and invoke olx-troubleshooting.")
        return 0
    return no_marker(queue, ad_id, out, "pass1")


def no_marker(queue, ad_id, out, which):
    tail = "\n".join(("  " + l) for l in (out or "").strip().splitlines()[-12:])
    say("BROWSER_FAILURE %s (%s printed no marker; raw log in .runs/). Last lines:" % (ad_id, which),
        tail,
        "NEXT: invoke the olx-troubleshooting skill. The ad is still pending; do NOT "
        "re-run pass 2 before the admin has been checked.")
    return 2


def admin_has(ad_id):
    """True/False from the admin changelist, or None when the check itself failed."""
    src = ("import os, sys, json\n"
           "sys.path.insert(0, os.path.join(os.environ['PROJECT_ROOT'], "
           "'harness/3ceasuri-import/scripts'))\n"
           "import admin_import\n"
           "A = admin_import.bind(globals())\n"
           "print('FOUND: ' + json.dumps({'found': admin_import.already_imported("
           "A, os.environ['AD_ID'])}))\n")
    m = parse_markers(run_payload(src, {"AD_ID": str(ad_id)},
                                  os.path.join(RUNS, "olx-%s-verify.log" % ad_id)))
    return m.get("FOUND", {}).get("found") if "FOUND" in m else None


def cmd_finish(queue, ad_id, pairs):
    ad_id = str(ad_id)
    dpath = contract_draft.draft_path(ROOT, ad_id)
    if not os.path.exists(dpath):
        say("NO_DRAFT %s: run `next` first - finish only answers a sheet." % ad_id,
            next_cmd(queue))
        return 1
    cand = find_candidate(queue, ad_id)
    st = load_run(ad_id) or {}
    profile = st.get("profile") or profile_for(queue, cand)[0]

    with open(dpath) as f:
        draft = json.load(f)
    answers = {}
    try:
        for p in pairs:
            k, v = parse_pair(p)
            answers[k] = v
    except ValueError as e:
        say("BAD_ANSWER: %s - nothing was run; fix the command and repeat it." % e)
        return 1
    bad = infer_fields.validate(answers)
    if bad:
        say("BAD_ANSWER: %s - nothing was run; fix the command and repeat it."
            % "; ".join(bad))
        return 1
    draft.update(answers)
    contract_draft.write(dpath, draft)

    attempt = int(st.get("fix_attempts", 0))
    out = run_payload(open(os.path.join(HERE, SCRIPTS[profile])).read(),
                      {"AD_ID": ad_id, "CANDIDATES_FILE": queue, "CONFIRM": "1"},
                      os.path.join(RUNS, "olx-%s-pass2-%d.log" % (ad_id, attempt)))
    m = parse_markers(out)

    if "RESULT" in m and m["RESULT"].get("ok"):
        return imported(queue, ad_id, m, cand)
    if "SKIP" in m:
        settle(queue, ad_id, "skipped", (m["SKIP"].get("reason") or "skip").split(" ")[0])
        logged = log_line("SKIP", m["SKIP"])
        say("SKIPPED %s: %s (%s)" % (ad_id, m["SKIP"].get("reason"), logged), next_cmd(queue))
        return 0
    if "REVIEW" in m:
        kind, what = review_outcome(m["REVIEW"].get("reasons"), attempt)
        if kind == "skip":
            msg = "; ".join(r.get("message", "") for r in m["REVIEW"].get("reasons", [])
                            if isinstance(r, dict))
            candidates.mark(queue, ad_id, "skipped", what)
            logged = log_line("SKIP", {"ad_id": ad_id, "reason": "%s: %s" % (what, msg)})
            say("SKIPPED %s: %s - %s (%s)" % (ad_id, what, msg, logged), next_cmd(queue))
            return 0
        save_run(ad_id, dict(st, profile=profile, queue=queue, fix_attempts=attempt + 1))
        lines = ["FIX %s - the gate named what to supply (you get ONE retry):" % ad_id]
        for r in what:
            f = r.get("field")
            lines.append("  %s: %s%s" % (r.get("code"), r.get("message"),
                                         (" | %s" % hint(f, profile)) if f else ""))
        fields = [r.get("field") for r in what if r.get("field")]
        lines.append("NEXT: %s finish %s %s %s" % (
            SELF, os.path.relpath(queue, ROOT), ad_id,
            " ".join("'%s=...'" % f for f in fields) or "'<field>=...'"))
        say(*lines)
        return 0
    if "ERROR" in m:
        settle(queue, ad_id, "error", m["ERROR"].get("msg"))
        say("ERROR %s: %s (the queue marked it `error`)" % (ad_id, m["ERROR"].get("msg")),
            next_cmd(queue))
        return 0

    # No verified RESULT: -- the record may still have saved. "Inspected target
    # navigated or closed" is the SUCCESS path, so ask the admin before anyone retries.
    found = admin_has(ad_id)
    if found:
        entry = dict((m.get("RESULT") or {}).get("state_entry") or {
            "source": "olx", "id": ad_id, "url": (cand or {}).get("url"),
            "brand": draft.get("brand"), "model": draft.get("model"),
            "price": draft.get("price"), "currency": draft.get("currency")})
        m["RESULT"] = dict(m.get("RESULT") or {}, ad_id=ad_id, ok=True, state_entry=entry)
        candidates.mark(queue, ad_id, "imported", None)
        return imported(queue, ad_id, m, cand, verified_by_admin=True)
    if found is False:
        candidates.mark(queue, ad_id, "error", "import not verified")
        say("NOT_SAVED %s: no RESULT: and the admin has no record (raw log in .runs/)."
            % ad_id, next_cmd(queue),
            "  Two NOT_SAVED in a row -> stop and invoke olx-troubleshooting.")
        return 0
    return no_marker(queue, ad_id, out, "pass2 and the admin check")


def imported(queue, ad_id, m, cand, verified_by_admin=False):
    r = m["RESULT"]
    logged = log_line("RESULT", r)
    e = r.get("state_entry") or {}
    rb = r.get("readback") or {}
    lines = ["IMPORTED %s: %s %s, %s %s%s (%s)" % (
        ad_id, e.get("brand"), quote(e.get("model")), e.get("price"), e.get("currency") or "",
        " - verified in the admin, the payload lost its RESULT:" if verified_by_admin else "",
        logged)]
    if not r.get("readback_ok") and not verified_by_admin:
        found = admin_has(ad_id)
        lines.append("  NOTE: the readback did not load; the banners say saved and the admin %s"
                     % {True: "confirms the record", False: "has NO record - check it by hand",
                        None: "check failed - check it by hand"}[found])
    elif rb.get("imgs") is not None and r.get("expected_images") \
            and rb["imgs"] < r["expected_images"]:
        lines.append("  NOTE: %s of %s photos saved - still a success, never re-import"
                     % (rb["imgs"], r["expected_images"]))
    nb = m.get("NEW_BRAND")
    if nb and nb.get("name") and nb.get("id"):
        try:
            changed = add_brand(nb["name"], nb["id"])
        except Exception as ex:
            changed = None
            lines.append("  NEW_BRAND %s (id %s): could not write the maps (%s) - follow the "
                         "New brand procedure in the importer skill" % (nb["name"], nb["id"], ex))
        if changed is not None:
            rel = " ".join(os.path.relpath(c, ROOT) for c in changed)
            lines.append("  NEW_BRAND %s (id %s) written to BRAND_IDS and brand-ids.md." % (
                nb["name"], nb["id"]))
            if changed:
                lines.append("  THEN: git add %s && git commit -m 'harness: add %s as a brand'"
                             % (rel, nb["name"]))
    lines.append(next_cmd(queue))
    say(*lines)
    return 0


def preflight(profile):
    """(ok, facts). Checks Chrome, browser-use, the admin login and the two tabs."""
    try:
        with urllib.request.urlopen(CDP + "/json/version", timeout=4) as r:
            chrome = json.load(r).get("Browser")
    except Exception as e:
        return False, {"chrome": None, "why": "Chrome is not answering on %s (%s). Start it "
                       "with --remote-debugging-port=9222 and sign in to the admin." % (CDP, e)}
    if not shutil.which(browser_use()[0]) and not os.path.exists(browser_use()[0]):
        return False, {"chrome": chrome, "why": "browser-use is not installed / not on PATH"}
    olx_url = ("https://www.olx.ro/electronice-si-electrocasnice/gadgets-wearables-si-camere-"
               "foto-video/smartwatch-uri/" if profile == "smart"
               else "https://www.olx.ro/moda-frumusete/ceasuri/")
    src = ("import json, time\n"
           "tabs = list_tabs()\n"
           "adm = [t for t in tabs if '3ceasuri.ro/admin' in (t.get('url') or '')]\n"
           "olx = [t for t in tabs if 'olx.ro' in (t.get('url') or '')]\n"
           "if not adm:\n"
           "    new_tab('https://3ceasuri.ro/admin/watches/watch/add/'); time.sleep(4)\n"
           "    adm = [t for t in list_tabs() if '3ceasuri.ro/admin' in (t.get('url') or '')]\n"
           "if not olx:\n"
           "    new_tab(%r); time.sleep(5)\n"
           "login = None\n"
           "if adm:\n"
           "    switch_tab(adm[0]['targetId'])\n"
           "    login = js(\"document.querySelector('#id_username') ? 'LOGIN_FORM' : 'OK'\")\n"
           "print('PREFLIGHT: ' + json.dumps({'admin_tab': bool(adm), 'admin': login}))\n"
           % olx_url)
    m = parse_markers(run_payload(src, {}, os.path.join(RUNS, "preflight.log")))
    pf = m.get("PREFLIGHT")
    if not pf:
        return False, {"chrome": chrome, "why": "browser-use could not drive Chrome - see "
                       ".runs/preflight.log"}
    if pf.get("admin") != "OK":
        return False, {"chrome": chrome, "why": "the 3ceasuri.ro admin is not signed in - ask "
                       "the user to log in in that Chrome, then run start again"}
    return True, {"chrome": chrome}


def cmd_start(queue, target):
    doc = candidates.load(queue)
    profile = doc.get("profile") or ("smart" if "smart" in queue else "classic")
    ok, facts = preflight(profile)
    if not ok:
        say("PREFLIGHT_FAILED: " + facts["why"], "NEXT: tell the user; do not continue.")
        return 2
    counts = candidates.counts(queue)
    age = ""
    gen = doc.get("generated")
    if gen:
        try:
            days = (datetime.datetime.now() - datetime.datetime.fromisoformat(
                str(gen)[:19])).days
            if days >= 3:
                age = " WARN: queue is %d days old - ads may be gone (they skip as not_active)" % days
        except ValueError:
            pass
    spath = os.path.join(ROOT, "state.json")
    try:
        with open(spath) as f:
            state = json.load(f)
    except Exception:
        state = {}
    state = {"_truth": state.get("_truth", "Session bookkeeping ONLY. Ground truth is the "
                                           "3ceasuri.ro admin."),
             "session_date": datetime.date.today().isoformat(), "target": target,
             "queue": os.path.relpath(queue, ROOT), "profile": profile,
             "session_imported": 0, "session_skipped": 0, "status": "running", "note": ""}
    with open(spath, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    say("READY: %s | queue %s %s | profile %s | target %s%s" % (
        facts["chrome"], os.path.relpath(queue, ROOT), json.dumps(counts), profile,
        target, age), next_cmd(queue))
    return 0


def cmd_stop(queue):
    spath = os.path.join(ROOT, "state.json")
    with open(spath) as f:
        state = json.load(f)
    state["status"] = "idle"
    with open(spath, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    reasons = {}
    for c in candidates.load(queue).get("candidates", []):
        if c.get("status") == "skipped" and str(c.get("ts", "")).startswith(
                state.get("session_date", "~")):
            reasons[c.get("reason")] = reasons.get(c.get("reason"), 0) + 1
    say("SESSION: imported %s, skipped %s | skip reasons today %s | queue %s | status idle" % (
        state.get("session_imported"), state.get("session_skipped"), json.dumps(reasons),
        json.dumps(candidates.counts(queue))))
    return 0


def cmd_skip(queue, ad_id, code, note):
    """Your own judgement skip (a suspected fake the floors missed, photos of two
    different watches...). Marks the queue and logs it, so nothing is half-done."""
    candidates.mark(queue, ad_id, "skipped", code)
    logged = log_line("SKIP", {"ad_id": str(ad_id),
                               "reason": "%s: %s" % (code, note) if note else code})
    say("SKIPPED %s: %s (%s)" % (ad_id, code, logged), next_cmd(queue))
    return 0


def main(argv):
    if len(argv) < 3 or argv[1] not in ("start", "next", "finish", "skip", "counts", "stop"):
        say(__doc__.split("\n\n")[1])
        return 2
    cmd, queue = argv[1], os.path.abspath(os.path.join(ROOT, argv[2])) \
        if not os.path.isabs(argv[2]) else argv[2]
    if not os.path.exists(queue):
        say("NO_QUEUE: %s does not exist" % queue)
        return 2
    if cmd == "start":
        t = argv[argv.index("--target") + 1] if "--target" in argv else None
        return cmd_start(queue, int(t) if t else None)
    if cmd == "next":
        return cmd_next(queue)
    if cmd == "finish":
        if len(argv) < 4:
            say("usage: finish <queue> <id> [field=value ...]")
            return 2
        return cmd_finish(queue, argv[3], argv[4:])
    if cmd == "skip":
        if len(argv) < 5:
            say("usage: skip <queue> <id> <code> ['a short reason']")
            return 2
        return cmd_skip(queue, argv[3], argv[4], " ".join(argv[5:]))
    if cmd == "counts":
        say(json.dumps(candidates.counts(queue)))
        return 0
    return cmd_stop(queue)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
